from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, ToolMessage

import student_parts.week06_kanamate_decides_schedule as week06


class CommonAvailableSlotTests(unittest.TestCase):
    def test_description_makes_kana_choose_candidates_before_validation(self) -> None:
        description = week06.FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION

        self.assertIn("대신 계산하는 도구가 아니라", description)
        self.assertIn("collect_member_schedules", description)
        self.assertIn("date(YYYY-MM-DD)", description)
        self.assertIn("busy_rows", description)
        self.assertIn("decide_final_slot", description)

    def test_helper_collects_normalized_busy_rows_and_filters_invalid_candidates(self) -> None:
        collected = {
            "ok": True,
            "tool_name": "collect_member_schedules",
            "members": ["나", "철수"],
            "rows": [
                {
                    "member_name": "나",
                    "title": "기존 회의",
                    "date": "2026-08-06",
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "notes": "Nana 개인 일정",
                }
            ],
            "schedule_summary": "기존 회의 1건",
        }
        candidates = [
            {
                "date": "2026-08-06",
                "start_time": "11:00",
                "end_time": "12:00",
                "duration_minutes": 60,
                "reason": "기존 회의 직후",
            },
            {
                "date": "2026-08-06",
                "start_time": "10:30",
                "end_time": "11:30",
                "duration_minutes": 60,
                "reason": "기존 회의와 겹침",
            },
            {
                "date": "2026-08-07",
                "start_time": "11:00",
                "end_time": "12:00",
                "duration_minutes": 60,
                "reason": "날짜 범위 밖",
            },
            {
                "date": "2026-08-06",
                "start_time": "08:00",
                "end_time": "09:00",
                "duration_minutes": 60,
                "reason": "업무 시간 밖",
            },
        ]

        collect = Mock()
        collect.invoke.return_value = json.dumps(collected, ensure_ascii=False)
        with patch.object(week06, "collect_member_schedules", collect):
            result = week06.find_common_available_slots_dict(
                member_names=[" 철수 ", ""],
                date_from="2026-08-06T00:00:00+09:00",
                date_to="2026-08-06T23:59:59+09:00",
                busy_rows=None,
                candidate_slots=candidates,
                llm_reason="busy rows를 비교함",
            )

        collect.invoke.assert_called_once_with(
            {
                "member_names": ["철수"],
                "date_from": "2026-08-06",
                "date_to": "2026-08-06",
            }
        )
        self.assertEqual(result["members"], ["나", "철수"])
        self.assertEqual(result["busy_rows"], collected["rows"])
        self.assertEqual(len(result["candidate_slots"]), 1)
        self.assertEqual(result["candidate_slots"][0]["start_time"], "11:00")
        self.assertEqual(result["slot_source"], "llm")
        self.assertEqual(result["llm_reason"], "busy rows를 비교함")

    def test_explicit_busy_rows_skip_collection_and_include_me_once(self) -> None:
        collect = Mock()
        with patch.object(week06, "collect_member_schedules", collect):
            result = week06.find_common_available_slots_dict(
                member_names=["나", "민준"],
                date_from="2026-08-06",
                date_to="2026-08-06",
                busy_rows=[],
                candidate_slots=[],
            )

        collect.invoke.assert_not_called()
        self.assertEqual(result["members"], ["나", "민준"])
        self.assertEqual(result["busy_rows"], [])

    def test_unspecified_busy_time_blocks_the_whole_day(self) -> None:
        result = week06.find_common_available_slots_dict(
            member_names=["민준"],
            date_from="2026-08-06",
            date_to="2026-08-06",
            busy_rows=[
                {
                    "member_name": "나",
                    "date": "2026-08-06",
                    "start_time": None,
                    "end_time": None,
                }
            ],
            candidate_slots=[
                {
                    "date": "2026-08-06",
                    "start_time": "14:00",
                    "end_time": "15:00",
                    "duration_minutes": 60,
                    "reason": "오후 후보",
                }
            ],
        )

        self.assertEqual(result["candidate_slots"], [])

    def test_malformed_collection_payloads_fail_instead_of_looking_empty(self) -> None:
        malformed_payloads = [
            ("not JSON", "invalid JSON"),
            ("[]", "non-object payload"),
            ('{"ok": false, "rows": []}', "failed collection"),
            ('{"ok": true}', "non-list rows field"),
            ('{"ok": true, "rows": {}}', "non-list rows field"),
            ('{"ok": true, "rows": [1]}', "non-object row"),
        ]

        for payload, expected_error in malformed_payloads:
            with self.subTest(payload=payload):
                collect = Mock()
                collect.invoke.return_value = payload
                with patch.object(week06, "collect_member_schedules", collect):
                    with self.assertRaisesRegex(RuntimeError, expected_error):
                        week06.find_common_available_slots_dict(
                            member_names=["철수"],
                            date_from="2026-08-06",
                            date_to="2026-08-06",
                        )

    def test_public_tool_returns_unescaped_korean_json(self) -> None:
        raw_result = week06.find_common_available_slots.invoke(
            {
                "member_names": ["철수"],
                "date_from": "2026-08-06",
                "date_to": "2026-08-06",
                "busy_rows": [],
                "candidate_slots": [
                    {
                        "date": "2026-08-06",
                        "start_time": "14:00",
                        "end_time": "15:00",
                        "duration_minutes": 60,
                        "reason": "모두 가능한 시간",
                    }
                ],
                "llm_reason": "일정을 비교함",
            }
        )

        self.assertNotIn("\\u", raw_result)
        payload = json.loads(raw_result)
        self.assertEqual(payload["tool_name"], "find_common_available_slots")
        self.assertEqual(payload["candidate_slots"][0]["reason"], "모두 가능한 시간")


class FinalSlotDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = [
            {
                "date": "2026-08-06",
                "start_time": "11:00",
                "end_time": "12:00",
                "duration_minutes": 60,
                "reason": "오전 후보",
            },
            {
                "date": "2026-08-06",
                "start_time": "14:00",
                "end_time": "15:00",
                "duration_minutes": 60,
                "reason": "오후 후보",
            },
        ]

    def test_description_requires_kana_to_make_the_final_choice(self) -> None:
        description = week06.DECIDE_FINAL_SLOT_DESCRIPTION

        self.assertIn("대신 고르는 도구가 아니라", description)
        self.assertIn("selected_index", description)
        self.assertIn("YYYY-MM-DD HH:MM-HH:MM", description)
        self.assertIn("final_slot=null", description)
        self.assertIn("busy_rows", description)
        self.assertIn("'나'가 포함", description)

    def test_selected_index_records_the_exact_final_slot_and_evidence(self) -> None:
        busy_rows = [
            {
                "member_name": "철수",
                "title": "기존 일정",
                "date": "2026-08-06",
                "start_time": "10:00",
                "end_time": "11:00",
            }
        ]
        raw_result = week06.decide_final_slot.invoke(
            {
                "candidate_slots": self.candidates,
                "selected_index": 1,
                "final_slot": "2026-08-06 14:00-15:00",
                "needs_agent_selection": False,
                "member_names": ["나", "철수"],
                "date_from": "2026-08-06T00:00:00+09:00",
                "date_to": "2026-08-06T23:59:59+09:00",
                "duration_minutes": 60,
                "reason": "오후가 모두에게 가능함",
                "busy_rows": busy_rows,
            }
        )

        self.assertNotIn("\\u", raw_result)
        payload = json.loads(raw_result)
        self.assertEqual(payload["final_slot"], "2026-08-06 14:00-15:00")
        self.assertEqual(payload["selected_index"], 1)
        self.assertEqual(payload["selected_slot"], self.candidates[1])
        self.assertFalse(payload["needs_agent_selection"])
        self.assertEqual(payload["reason"], "오후가 모두에게 가능함")
        self.assertEqual(payload["members"], ["나", "철수"])
        self.assertEqual(payload["date_from"], "2026-08-06")
        self.assertEqual(payload["busy_rows"], busy_rows)

    def test_missing_selection_keeps_the_decision_open(self) -> None:
        payload = json.loads(
            week06.decide_final_slot.invoke(
                {
                    "candidate_slots": self.candidates,
                    "selected_index": None,
                    "selected_slot": None,
                    "final_slot": None,
                    "needs_agent_selection": None,
                }
            )
        )

        self.assertIsNone(payload["final_slot"])
        self.assertTrue(payload["needs_agent_selection"])
        self.assertIn("최종 확정하지 않았습니다", payload["reason"])
        self.assertEqual(payload["candidates"], [
            "2026-08-06 11:00-12:00",
            "2026-08-06 14:00-15:00",
        ])

    def test_invalid_index_does_not_fall_back_to_another_candidate(self) -> None:
        payload = json.loads(
            week06.decide_final_slot.invoke(
                {
                    "candidate_slots": self.candidates,
                    "selected_index": 9,
                    "final_slot": None,
                    "needs_agent_selection": None,
                }
            )
        )

        self.assertIsNone(payload["final_slot"])
        self.assertTrue(payload["needs_agent_selection"])
        self.assertIn("범위를 벗어났습니다", payload["reason"])

    def test_no_candidates_remains_unconfirmed(self) -> None:
        payload = json.loads(week06.decide_final_slot.invoke({"candidate_slots": []}))

        self.assertIsNone(payload["final_slot"])
        self.assertTrue(payload["needs_agent_selection"])
        self.assertEqual(payload["candidates"], [])
        self.assertIn("찾지 못했습니다", payload["reason"])


class AgentFake:
    def __init__(self, result: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self.result = result or {"messages": [AIMessage(content="완료했습니다.")]}
        self.error = error
        self.invoke_calls: list[dict[str, object]] = []

    def invoke(self, arguments: dict[str, object]) -> dict[str, object]:
        self.invoke_calls.append(arguments)
        if self.error is not None:
            raise self.error
        return self.result


class SubAgentTests(unittest.TestCase):
    def test_prompts_define_distinct_roles_and_intent_based_routing(self) -> None:
        nana_prompt = week06.nana_system_prompt()
        kana_prompt = week06.kana_system_prompt()

        self.assertIn("개인 일정의 생성·조회·수정·삭제", nana_prompt)
        self.assertIn("참석자가 있어도 날짜와 시간이 이미 정해져", nana_prompt)
        self.assertIn("여러 사람의 가능 시간 탐색", nana_prompt)
        self.assertIn("외부 구성원의 과거 대화와 일정", kana_prompt)
        self.assertIn("이미 받은 정보를 다시 묻지 않는다", kana_prompt)
        self.assertIn("extract_schedule_request를 호출하지 않고 바로", kana_prompt)
        self.assertIn("member_names=['철수', '영희']", kana_prompt)
        self.assertIn("collect_member_schedules를 한 번 호출", kana_prompt)
        self.assertIn("find_common_available_slots", kana_prompt)
        self.assertIn("decide_final_slot", kana_prompt)
        self.assertIn("'나' 포함 members 전체", kana_prompt)
        self.assertIn(week06.current_app_date_iso(), kana_prompt)

    def test_role_tool_lists_do_not_leak_between_nana_and_kana(self) -> None:
        nana_names = set(week06.agent_tool_names("nana_agent"))
        kana_names = set(week06.agent_tool_names("kana_agent"))

        self.assertIn("personal_list_saved_schedules", nana_names)
        self.assertIn("search_conversation_messages", nana_names)
        self.assertNotIn("collect_member_schedules", nana_names)
        self.assertIn("collect_member_schedules", kana_names)
        self.assertIn("find_common_available_slots", kana_names)
        self.assertIn("decide_final_slot", kana_names)
        self.assertNotIn("personal_list_saved_schedules", kana_names)
        self.assertNotIn("propose_group_schedule", kana_names)

    def test_nana_agent_is_cached_and_returns_inner_trace(self) -> None:
        result = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "personal_list_saved_schedules",
                            "args": {"date_from": "2026-08-06"},
                            "id": "nana-call-1",
                        }
                    ],
                ),
                ToolMessage(
                    content=json.dumps({"ok": True, "schedules": []}, ensure_ascii=False),
                    tool_call_id="nana-call-1",
                    name="personal_list_saved_schedules",
                ),
                AIMessage(content="저장된 일정이 없습니다."),
            ]
        }
        fake_agent = AgentFake(result)
        fake_model = object()
        previous_agent = week06._NANA_SUBAGENT
        week06._NANA_SUBAGENT = None
        try:
            with (
                patch.object(week06, "chat_model", return_value=fake_model) as model,
                patch.object(week06, "create_agent", return_value=fake_agent) as create,
            ):
                first = json.loads(week06.nana_agent.invoke({"query": "내 일정 보여줘"}))
                second = json.loads(week06.nana_agent.invoke({"query": "다시 보여줘"}))
        finally:
            week06._NANA_SUBAGENT = previous_agent

        model.assert_called_once_with()
        create.assert_called_once()
        self.assertIs(create.call_args.kwargs["model"], fake_model)
        self.assertEqual(
            [tool.name for tool in create.call_args.kwargs["tools"]],
            [tool.name for tool in week06.week04_tools()],
        )
        self.assertIn("개인 일정의 생성·조회·수정·삭제", create.call_args.kwargs["system_prompt"])
        self.assertEqual(first["selected_agent"], "nana_agent")
        self.assertEqual(first["inner_tool_names"], ["personal_list_saved_schedules"])
        self.assertEqual(first["answer"], "저장된 일정이 없습니다.")
        self.assertEqual(first["trace"][1]["content"], {"ok": True, "schedules": []})
        self.assertEqual(second["selected_agent"], "nana_agent")
        self.assertEqual(len(fake_agent.invoke_calls), 2)

    def test_kana_agent_lifts_final_payload_and_is_cached(self) -> None:
        final_payload = {
            "final_slot": "2026-08-06 14:00-15:00",
            "reason": "모두 가능함",
            "candidates": ["2026-08-06 14:00-15:00"],
            "needs_agent_selection": False,
        }
        result = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "collect_member_schedules",
                            "args": {
                                "member_names": ["철수"],
                                "date_from": "2026-08-06",
                                "date_to": "2026-08-06",
                            },
                            "id": "kana-call-1",
                        }
                    ],
                ),
                ToolMessage(
                    content='{"ok": true, "rows": []}',
                    tool_call_id="kana-call-1",
                    name="collect_member_schedules",
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "decide_final_slot",
                            "args": {"selected_index": 0},
                            "id": "kana-call-2",
                        }
                    ],
                ),
                ToolMessage(
                    content=json.dumps(final_payload, ensure_ascii=False),
                    tool_call_id="kana-call-2",
                    name="decide_final_slot",
                ),
                AIMessage(content="8월 6일 오후 2시로 결정했습니다."),
            ]
        }
        fake_agent = AgentFake(result)
        previous_agent = week06._KANA_SUBAGENT
        week06._KANA_SUBAGENT = None
        try:
            with patch.object(week06, "create_agent", return_value=fake_agent) as create:
                first = json.loads(week06.kana_agent.invoke({"query": "철수와 시간 맞춰줘"}))
                second = json.loads(week06.kana_agent.invoke({"query": "결과 다시 알려줘"}))
        finally:
            week06._KANA_SUBAGENT = previous_agent

        create.assert_called_once()
        self.assertEqual(first["selected_agent"], "kana_agent")
        self.assertEqual(
            first["inner_tool_names"],
            ["collect_member_schedules", "decide_final_slot"],
        )
        self.assertEqual(first["final_slot_payload"], final_payload)
        self.assertIsNone(first["final_decision_payload"])
        self.assertEqual(first["answer"], "8월 6일 오후 2시로 결정했습니다.")
        self.assertEqual(second["selected_agent"], "kana_agent")
        self.assertEqual(len(fake_agent.invoke_calls), 2)

    def test_subagent_runtime_errors_are_not_converted_to_success_json(self) -> None:
        previous_agent = week06._KANA_SUBAGENT
        week06._KANA_SUBAGENT = AgentFake(error=RuntimeError("MCP unavailable"))
        try:
            with self.assertRaisesRegex(RuntimeError, "MCP unavailable"):
                week06.kana_agent.invoke({"query": "철수 일정 찾아줘"})
        finally:
            week06._KANA_SUBAGENT = previous_agent


class SupervisorTests(unittest.TestCase):
    def test_supervisor_prompt_routes_by_intent_and_data_source(self) -> None:
        prompt = week06.supervisor_system_prompt()

        self.assertIn("업무를 직접 수행하지 않고", prompt)
        self.assertIn("요청의 의도와 데이터 출처", prompt)
        self.assertIn("내일 3시에 철수와 회의를 내 일정에 등록해줘", prompt)
        self.assertIn("nana_agent", prompt)
        self.assertIn("철수와 다음 주 가능한 시간을 찾아 회의 시간을 정해줘", prompt)
        self.assertIn("kana_agent", prompt)
        self.assertIn("collect_member_schedules가 함께 수집", prompt)
        self.assertIn("needs_agent_selection이 false", prompt)
        self.assertIn("저장 의도가 명시되지 않았거나", prompt)
        self.assertIn("적어도 하나를 호출", prompt)
        self.assertIn("가용 시간 비교를 뜻하는 표현이 하나라도 있으면 반드시 kana_agent", prompt)
        self.assertIn("저장하지 마", prompt)
        self.assertIn("kana_agent 하나만 호출", prompt)
        self.assertIn("사용자 원문과 제약을 그대로 전달", prompt)

    def test_supervisor_exposes_only_two_delegate_tools(self) -> None:
        self.assertEqual(
            [tool.name for tool in week06.supervisor_tools()],
            ["nana_agent", "kana_agent"],
        )
        self.assertEqual(
            week06.agent_tool_names("supervisor"),
            ["nana_agent", "kana_agent"],
        )

    def test_supervisor_agent_is_built_once_with_delegate_tools(self) -> None:
        previous_agent = week06._SUPERVISOR_AGENT
        fake_agent = object()
        fake_model = object()
        week06._SUPERVISOR_AGENT = None
        try:
            with (
                patch.object(week06, "chat_model", return_value=fake_model) as model,
                patch.object(week06, "create_agent", return_value=fake_agent) as create,
            ):
                first = week06.build_langchain_supervisor_agent()
                second = week06.build_week_agent()
        finally:
            week06._SUPERVISOR_AGENT = previous_agent

        self.assertIs(first, fake_agent)
        self.assertIs(second, fake_agent)
        model.assert_called_once_with()
        create.assert_called_once()
        self.assertIs(create.call_args.kwargs["model"], fake_model)
        self.assertEqual(
            [tool.name for tool in create.call_args.kwargs["tools"]],
            ["nana_agent", "kana_agent"],
        )
        self.assertIn("적어도 하나를 호출", create.call_args.kwargs["system_prompt"])

    def test_supervisor_trace_lifts_kana_evidence(self) -> None:
        final_payload = {
            "final_slot": "2026-08-06 14:00-15:00",
            "reason": "모두 가능한 시간",
            "candidates": ["2026-08-06 14:00-15:00"],
            "needs_agent_selection": False,
        }
        wrapper_payload = {
            "selected_agent": "kana_agent",
            "answer": "8월 6일 오후 2시가 가능합니다.",
            "trace": [],
            "inner_tool_names": [
                "collect_member_schedules",
                "find_common_available_slots",
                "decide_final_slot",
            ],
            "final_slot_payload": final_payload,
            "final_decision_payload": None,
        }
        result = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "kana_agent",
                            "args": {"query": "철수와 일정 맞춰줘"},
                            "id": "supervisor-call-1",
                        }
                    ],
                ),
                ToolMessage(
                    content=json.dumps(wrapper_payload, ensure_ascii=False),
                    tool_call_id="supervisor-call-1",
                    name="kana_agent",
                ),
                AIMessage(content="8월 6일 오후 2시가 모두에게 가능합니다."),
            ]
        }

        trace = week06.extract_langchain_trace(result)

        self.assertEqual(trace["supervisor_selected_agent"], "kana_agent")
        self.assertEqual(trace["inner_tool_names"], wrapper_payload["inner_tool_names"])
        self.assertEqual(trace["final_slot_payload"], final_payload)
        self.assertIsNone(trace["final_decision_payload"])
        self.assertEqual(trace["events"][1]["content"], wrapper_payload)


if __name__ == "__main__":
    unittest.main()
