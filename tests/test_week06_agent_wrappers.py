from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

import student_parts.week06_kanamate_decides_schedule as week06


class Week06AgentWrapperTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_nana = week06._NANA_SUBAGENT
        self.original_kana = week06._KANA_SUBAGENT
        self.original_supervisor = week06._SUPERVISOR_AGENT
        week06._NANA_SUBAGENT = None
        week06._KANA_SUBAGENT = None
        week06._SUPERVISOR_AGENT = None

    def tearDown(self) -> None:
        week06._NANA_SUBAGENT = self.original_nana
        week06._KANA_SUBAGENT = self.original_kana
        week06._SUPERVISOR_AGENT = self.original_supervisor

    @patch.object(week06, "extract_final_text", return_value="내 일정을 확인했습니다.")
    @patch.object(week06, "extract_agent_events")
    @patch.object(week06, "chat_model", return_value="model")
    @patch.object(week06, "create_agent")
    def test_nana_agent_creates_once_reuses_and_returns_trace(
        self,
        create_agent,
        _chat_model,
        extract_events,
        _extract_text,
    ):
        subagent = Mock()
        subagent.invoke.return_value = {"result": "nana"}
        create_agent.return_value = subagent
        extract_events.return_value = [
            {
                "event": "tool_call",
                "tool_name": "personal_list_saved_schedules",
            },
            {
                "event": "tool_result",
                "tool_name": "personal_list_saved_schedules",
                "content": {"ok": True},
            },
        ]

        first = json.loads(week06.nana_agent.invoke({"query": "내 일정 보여줘"}))
        second = json.loads(week06.nana_agent.invoke({"query": "내 할 일 보여줘"}))

        create_agent.assert_called_once()
        self.assertEqual(create_agent.call_args.kwargs["model"], "model")
        self.assertEqual(
            [week06.tool_name(item) for item in create_agent.call_args.kwargs["tools"]],
            [week06.tool_name(item) for item in week06.week04_tools()],
        )
        self.assertEqual(
            create_agent.call_args.kwargs["system_prompt"],
            week06.nana_system_prompt(),
        )
        self.assertEqual(
            subagent.invoke.call_args_list[0].args[0],
            {"messages": [{"role": "user", "content": "내 일정 보여줘"}]},
        )
        self.assertEqual(
            subagent.invoke.call_args_list[1].args[0],
            {"messages": [{"role": "user", "content": "내 할 일 보여줘"}]},
        )
        self.assertEqual(first["selected_agent"], "nana_agent")
        self.assertEqual(first["answer"], "내 일정을 확인했습니다.")
        self.assertEqual(first["inner_tool_names"], ["personal_list_saved_schedules"])
        self.assertEqual(first["retry_count"], 0)
        self.assertEqual(second["selected_agent"], "nana_agent")

    @patch.object(week06, "extract_final_text", return_value="일정을 저장했습니다.")
    @patch.object(week06, "extract_agent_events")
    @patch.object(week06, "chat_model", return_value="model")
    @patch.object(week06, "create_agent")
    def test_nana_agent_retries_missing_mutation_once_and_merges_trace(
        self,
        create_agent,
        _chat_model,
        extract_events,
        _extract_text,
    ):
        subagent = Mock()
        first_result = {"attempt": 1}
        retry_result = {"attempt": 2}
        subagent.invoke.side_effect = [first_result, retry_result]
        create_agent.return_value = subagent
        retry_events = [
            {"event": "tool_call", "tool_name": "extract_schedule_request"},
            {"event": "tool_result", "tool_name": "extract_schedule_request", "content": {"ok": True}},
            {"event": "tool_call", "tool_name": "personal_create_schedule"},
            {"event": "tool_result", "tool_name": "personal_create_schedule", "content": {"ok": True}},
        ]
        extract_events.side_effect = [[], retry_events]

        payload = json.loads(
            week06.nana_agent.invoke(
                {
                    "query": (
                        "2026년 8월 10일 15시부터 16시까지 테스트 회의를 "
                        "내 일정에 등록해줘."
                    )
                }
            )
        )

        self.assertEqual(subagent.invoke.call_count, 2)
        retry_query = subagent.invoke.call_args_list[1].args[0]["messages"][0]["content"]
        self.assertIn("원래 사용자 요청", retry_query)
        self.assertIn(
            "extract_schedule_request -> personal_create_schedule",
            retry_query,
        )
        self.assertEqual(payload["retry_count"], 1)
        self.assertEqual(
            payload["inner_tool_names"],
            ["extract_schedule_request", "personal_create_schedule"],
        )

    @patch.object(week06, "extract_final_text", return_value="완료")
    @patch.object(week06, "extract_agent_events")
    @patch.object(week06, "chat_model", return_value="model")
    @patch.object(week06, "create_agent")
    def test_nana_agent_does_not_retry_after_mutation_or_known_empty_lookup(
        self,
        create_agent,
        _chat_model,
        extract_events,
        _extract_text,
    ):
        subagent = Mock()
        subagent.invoke.return_value = {"result": "nana"}
        create_agent.return_value = subagent
        extract_events.side_effect = [
            [
                {
                    "event": "tool_result",
                    "tool_name": "personal_create_schedule",
                    "content": {"ok": True},
                },
            ],
            [
                {"event": "tool_call", "tool_name": "personal_list_saved_schedules"},
                {
                    "event": "tool_result",
                    "tool_name": "personal_list_saved_schedules",
                    "content": {"ok": True, "schedules": []},
                },
            ],
        ]

        created = json.loads(
            week06.nana_agent.invoke(
                {
                    "query": (
                        "2026년 8월 10일 15시부터 16시까지 테스트 회의를 "
                        "내 일정에 등록해줘."
                    )
                }
            )
        )
        deleted = json.loads(
            week06.nana_agent.invoke(
                {"query": "2026년 8월 10일 테스트 회의를 삭제해줘."}
            )
        )

        self.assertEqual(subagent.invoke.call_count, 2)
        self.assertEqual(created["retry_count"], 0)
        self.assertEqual(deleted["retry_count"], 0)

    @patch.object(week06, "extract_final_text", return_value="도구 없이 종료")
    @patch.object(week06, "extract_agent_events", side_effect=[[], []])
    @patch.object(week06, "chat_model", return_value="model")
    @patch.object(week06, "create_agent")
    def test_nana_agent_stops_after_one_failed_retry(
        self,
        create_agent,
        _chat_model,
        _extract_events,
        _extract_text,
    ):
        subagent = Mock()
        subagent.invoke.side_effect = [{"attempt": 1}, {"attempt": 2}]
        create_agent.return_value = subagent

        payload = json.loads(
            week06.nana_agent.invoke(
                {"query": "2026년 8월 10일까지 Week 6 과제 제출을 할 일로 저장해줘."}
            )
        )

        self.assertEqual(subagent.invoke.call_count, 2)
        self.assertEqual(payload["retry_count"], 1)
        self.assertEqual(payload["inner_tool_names"], [])

    def test_nana_retry_plan_requires_explicit_complete_mutation_input(self):
        self.assertEqual(
            week06._nana_mutation_retry_plan(
                "2026년 8월 10일 15시부터 16시까지 테스트 회의를 내 일정에 등록해줘."
            ),
            (
                "personal_create_schedule",
                ("extract_schedule_request", "personal_create_schedule"),
            ),
        )
        self.assertEqual(
            week06._nana_mutation_retry_plan(
                "2026년 8월 10일 테스트 회의를 17시부터 18시까지로 수정해줘."
            )[0],
            "personal_update_saved_schedule",
        )
        self.assertIsNone(
            week06._nana_mutation_retry_plan("내일 3시에 회의 등록해줘.")
        )

    def test_nana_read_retry_does_not_replace_reference_save(self):
        self.assertIsNone(
            week06._nana_read_retry_tool(
                "식별 코드는 W6-0640이라고 개인 참고자료에 기억해줘."
            )
        )
        self.assertEqual(
            week06._nana_read_retry_tool("개인 참고자료에서 식별 코드를 찾아줘."),
            "search_personal_references",
        )

    @patch.object(week06, "extract_final_text", return_value="파랑새-726")
    @patch.object(week06, "extract_agent_events")
    @patch.object(week06, "chat_model", return_value="model")
    @patch.object(week06, "create_agent")
    def test_nana_agent_corrects_wrong_read_source_once(
        self,
        create_agent,
        _chat_model,
        extract_events,
        _extract_text,
    ):
        subagent = Mock()
        subagent.invoke.side_effect = [{"attempt": 1}, {"attempt": 2}]
        create_agent.return_value = subagent
        extract_events.side_effect = [
            [{"event": "tool_call", "tool_name": "search_personal_references"}],
            [{"event": "tool_call", "tool_name": "search_conversation_messages"}],
        ]

        payload = json.loads(
            week06.nana_agent.invoke(
                {"query": "앱의 이전 일반 대화에서 프로젝트 대화 전용 암호를 찾아줘."}
            )
        )

        self.assertEqual(payload["retry_count"], 1)
        self.assertEqual(payload["inner_tool_names"], ["search_conversation_messages"])
        self.assertEqual(
            payload["attempted_inner_tool_names"],
            ["search_personal_references", "search_conversation_messages"],
        )
        self.assertIn(
            "search_conversation_messages을 정확히 한 번",
            subagent.invoke.call_args_list[1].args[0]["messages"][0]["content"],
        )

    def test_retry_instructions_preserve_remaining_step_evidence_and_time_window(self):
        events = [
            {"event": "tool_call", "tool_name": "extract_schedule_request"},
            {
                "event": "tool_result",
                "tool_name": "extract_schedule_request",
                "content": {"ok": True, "structured_request": {"title": "회의"}},
            },
        ]
        remaining = week06._remaining_sequence(
            ("extract_schedule_request", "personal_create_schedule"), events
        )
        nana_instruction = week06._nana_retry_instruction("원문", remaining, events)
        kana_instruction = week06._kana_retry_instruction(
            "나와 철수가 2026년 7월 7일 10시부터 11시 사이에 회의할 최종 시간을 정해줘.",
            "decide_final_slot",
            events,
        )

        self.assertEqual(remaining, ("personal_create_schedule",))
        self.assertIn('"title": "회의"', nana_instruction)
        self.assertIn("남은 필수 단계는 personal_create_schedule", nana_instruction)
        self.assertIn("workday_start=10:00", kana_instruction)
        self.assertIn("workday_end=11:00", kana_instruction)
        self.assertIsNone(
            week06._explicit_time_window(
                "2026-07-07T09:00:00+09:00부터 2026-07-17T18:00:00+09:00까지"
            )
        )

    def test_kana_decision_retry_reason_checks_evidence_and_explicit_window(self):
        rows = [{"member_name": "철수", "date": "2026-07-07"}]
        candidates = [
            {
                "date": "2026-07-07",
                "start_time": "10:00",
                "end_time": "11:00",
                "duration_minutes": 60,
                "reason": "가능",
            }
        ]
        find_result = {
            "members": ["나", "철수"],
            "busy_rows": rows,
            "candidate_slots": candidates,
        }
        base_events = [
            {
                "event": "tool_call",
                "tool_name": "find_common_available_slots",
                "arguments": {"workday_start": "10:00", "workday_end": "11:00"},
            },
            {
                "event": "tool_result",
                "tool_name": "find_common_available_slots",
                "content": find_result,
            },
        ]
        query = "나와 철수가 2026년 7월 7일 10시부터 11시 사이에 회의할 최종 시간을 정해줘."
        missing_evidence = [
            *base_events,
            {
                "event": "tool_result",
                "tool_name": "decide_final_slot",
                "content": {"members": ["철수"], "candidate_slots": candidates},
            },
        ]
        valid = [
            *base_events,
            {
                "event": "tool_result",
                "tool_name": "decide_final_slot",
                "content": find_result,
            },
        ]
        wrong_window = [
            {
                **base_events[0],
                "arguments": {"workday_start": "09:00", "workday_end": "18:00"},
            },
            *base_events[1:],
            valid[-1],
        ]

        self.assertIn(
            "members",
            week06._kana_decision_retry_reason(query, missing_evidence),
        )
        self.assertIsNone(week06._kana_decision_retry_reason(query, valid))
        self.assertEqual(
            week06._kana_decision_retry_reason(query, wrong_window),
            "사용자 명시 허용 시간 범위 불일치",
        )

    @patch.object(week06, "extract_final_text", return_value="최종 시간을 정했습니다.")
    @patch.object(week06, "extract_agent_events")
    @patch.object(week06, "chat_model", return_value="model")
    @patch.object(week06, "create_agent")
    def test_kana_agent_reuses_and_extracts_only_decision_tool_final_slot(
        self,
        create_agent,
        _chat_model,
        extract_events,
        _extract_text,
    ):
        subagent = Mock()
        subagent.invoke.return_value = {"result": "kana"}
        create_agent.return_value = subagent
        expected_final = {
            "final_slot": "2026-08-11 15:00-16:00",
            "reason": "선택",
            "candidates": ["2026-08-11 15:00-16:00"],
            "needs_agent_selection": False,
        }
        extract_events.return_value = [
            {"event": "tool_call", "tool_name": "find_common_available_slots"},
            {
                "event": "tool_result",
                "tool_name": "find_common_available_slots",
                "content": {"final_slot": "잘못된 동명 필드"},
            },
            {"event": "tool_call", "tool_name": "decide_final_slot"},
            {
                "event": "tool_result",
                "tool_name": "decide_final_slot",
                "content": expected_final,
            },
            {
                "event": "tool_result",
                "tool_name": "legacy",
                "content": {"final_decision": {"status": "confirmed"}},
            },
        ]

        first = json.loads(week06.kana_agent.invoke({"query": "회의 시간 정해줘"}))
        second = json.loads(week06.kana_agent.invoke({"query": "다시 확인해줘"}))

        create_agent.assert_called_once()
        self.assertEqual(
            [week06.tool_name(item) for item in create_agent.call_args.kwargs["tools"]],
            [week06.tool_name(item) for item in week06.kana_tools()],
        )
        self.assertEqual(
            create_agent.call_args.kwargs["system_prompt"],
            week06.kana_system_prompt(),
        )
        self.assertEqual(first["selected_agent"], "kana_agent")
        self.assertEqual(first["final_slot_payload"], expected_final)
        self.assertEqual(first["final_decision_payload"], {"status": "confirmed"})
        self.assertEqual(
            first["inner_tool_names"],
            ["find_common_available_slots", "decide_final_slot"],
        )
        self.assertEqual(second["answer"], "최종 시간을 정했습니다.")

    @patch.object(week06, "extract_final_text", return_value="최종 시간을 정했습니다.")
    @patch.object(week06, "extract_agent_events")
    @patch.object(week06, "chat_model", return_value="model")
    @patch.object(week06, "create_agent")
    def test_kana_agent_retries_missing_terminal_tool_once(
        self,
        create_agent,
        _chat_model,
        extract_events,
        _extract_text,
    ):
        subagent = Mock()
        subagent.invoke.side_effect = [{"attempt": 1}, {"attempt": 2}]
        create_agent.return_value = subagent
        extract_events.side_effect = [
            [{"event": "tool_call", "tool_name": "find_common_available_slots"}],
            [{"event": "tool_call", "tool_name": "decide_final_slot"}],
        ]

        payload = json.loads(
            week06.kana_agent.invoke(
                {
                    "query": (
                        "나와 철수가 2026년 7월 7일부터 17일까지 60분 회의할 "
                        "최종 시간을 정해줘."
                    )
                }
            )
        )

        self.assertEqual(subagent.invoke.call_count, 2)
        self.assertEqual(payload["retry_count"], 1)
        self.assertEqual(
            payload["inner_tool_names"],
            ["find_common_available_slots", "decide_final_slot"],
        )
        self.assertIn(
            "find_common_available_slots -> decide_final_slot",
            subagent.invoke.call_args_list[1].args[0]["messages"][0]["content"],
        )

    def test_kana_retry_plan_requires_date_and_named_participants(self):
        self.assertEqual(
            week06._kana_required_terminal_tool(
                "나와 철수가 2026년 7월 7일부터 17일까지 회의할 최종 시간을 정해줘."
            ),
            "decide_final_slot",
        )
        self.assertEqual(
            week06._kana_required_terminal_tool(
                "나와 철수의 2026년 7월 7일부터 17일까지 일정을 비교해줘. 시간 결정은 하지 마."
            ),
            "collect_member_schedules",
        )
        self.assertIsNone(
            week06._kana_required_terminal_tool("나와 철수가 60분 회의할 시간을 정해줘.")
        )

    @patch.object(week06, "extract_agent_events")
    def test_supervisor_trace_lifts_wrapper_metadata(self, extract_events):
        final_slot = {
            "final_slot": "2026-08-11 15:00-16:00",
            "reason": "선택",
            "candidates": [],
        }
        extract_events.return_value = [
            {"event": "tool_call", "tool_name": "kana_agent"},
            {
                "event": "tool_result",
                "tool_name": "kana_agent",
                "content": {
                    "inner_tool_names": [
                        "collect_member_schedules",
                        "find_common_available_slots",
                        "decide_final_slot",
                    ],
                    "final_slot_payload": final_slot,
                    "final_decision_payload": {"status": "confirmed"},
                },
            },
        ]

        trace = week06.extract_langchain_trace({"messages": []})

        extract_events.assert_called_once_with({"messages": []})
        self.assertEqual(trace["supervisor_selected_agent"], "kana_agent")
        self.assertEqual(
            trace["inner_tool_names"],
            [
                "collect_member_schedules",
                "find_common_available_slots",
                "decide_final_slot",
            ],
        )
        self.assertEqual(trace["final_slot_payload"], final_slot)
        self.assertEqual(trace["final_decision_payload"], {"status": "confirmed"})

    @patch.object(week06, "extract_agent_events", return_value=[])
    def test_supervisor_retries_in_scope_request_without_wrapper_once(self, _extract_events):
        underlying = Mock()
        underlying.invoke.side_effect = [
            {"messages": ["직접 답변"]},
            {"messages": ["wrapper 재시도 결과"]},
        ]
        agent = week06.Week06SupervisorRetryAgent(underlying)
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": "2026년 8월 10일 테스트 회의를 내 일정에 등록해줘.",
                }
            ]
        }

        result = agent.invoke(payload)

        self.assertEqual(underlying.invoke.call_count, 2)
        retry_messages = underlying.invoke.call_args_list[1].args[0]["messages"]
        self.assertEqual(retry_messages[0], payload["messages"][0])
        self.assertIn("wrapper 하나를 정확히 한 번", retry_messages[-1]["content"])
        self.assertEqual(result["supervisor_retry_count"], 1)

    @patch.object(week06, "extract_agent_events")
    def test_supervisor_does_not_retry_observed_wrapper_or_out_of_scope_chat(
        self,
        extract_events,
    ):
        underlying = Mock()
        underlying.invoke.side_effect = [
            {"messages": ["위임 결과"]},
            {"messages": ["일반 답변"]},
        ]
        agent = week06.Week06SupervisorRetryAgent(underlying)
        extract_events.side_effect = [
            [{"event": "tool_result", "tool_name": "nana_agent"}],
            [],
        ]

        delegated = agent.invoke(
            {"messages": [{"role": "user", "content": "내 일정 보여줘"}]}
        )
        ordinary = agent.invoke(
            {"messages": [{"role": "user", "content": "안녕"}]}
        )

        self.assertEqual(underlying.invoke.call_count, 2)
        self.assertEqual(delegated["supervisor_retry_count"], 0)
        self.assertEqual(ordinary["supervisor_retry_count"], 0)

    @patch.object(week06, "extract_agent_events", return_value=[])
    def test_supervisor_stops_after_one_retry_even_without_wrapper(self, _extract_events):
        underlying = Mock()
        underlying.invoke.side_effect = [
            {"messages": ["첫 직접 답변"]},
            {"messages": ["두 번째 직접 답변"]},
        ]
        agent = week06.Week06SupervisorRetryAgent(underlying)

        result = agent.invoke(
            {"messages": [{"role": "user", "content": "회의 일정 정해줘"}]}
        )

        self.assertEqual(underlying.invoke.call_count, 2)
        self.assertEqual(result["supervisor_retry_count"], 1)

    @patch.object(week06, "_supervisor_wrapper_observed", return_value=False)
    def test_supervisor_stream_retries_in_scope_request_once(self, _observed):
        underlying = Mock()
        underlying.stream.side_effect = [
            iter([{"model": {"messages": ["첫 응답"]}}]),
            iter([{"tools": {"messages": ["wrapper 응답"]}}]),
        ]
        agent = week06.Week06SupervisorRetryAgent(underlying)
        payload = {
            "messages": [
                {"role": "user", "content": "2026년 8월 10일 회의 일정 등록해줘"}
            ]
        }

        chunks = list(agent.stream(payload, stream_mode="updates"))

        self.assertEqual(underlying.stream.call_count, 2)
        self.assertEqual(len(chunks), 2)
        retry_messages = underlying.stream.call_args_list[1].args[0]["messages"]
        self.assertIn("self-contained", retry_messages[-1]["content"])

    @patch.object(week06, "supervisor_system_prompt", return_value="supervisor prompt")
    @patch.object(week06, "supervisor_tools", return_value=["nana", "kana"])
    @patch.object(week06, "chat_model", return_value="model")
    @patch.object(week06, "create_agent")
    def test_supervisor_builder_creates_once_and_build_week_reuses(
        self,
        create_agent,
        _chat_model,
        _tools,
        _prompt,
    ):
        supervisor = object()
        create_agent.return_value = supervisor

        first = week06.build_langchain_supervisor_agent()
        second = week06.build_week_agent()

        self.assertIsInstance(first, week06.Week06SupervisorRetryAgent)
        self.assertIs(first._agent, supervisor)
        self.assertIs(second, first)
        create_agent.assert_called_once_with(
            model="model",
            tools=["nana", "kana"],
            system_prompt="supervisor prompt",
        )


if __name__ == "__main__":
    unittest.main()
