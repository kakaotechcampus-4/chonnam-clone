from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from student_parts.week04_retrieve_nanas_memory import week04_prompt_parts, week04_tools
from student_parts.week05_load_kanas_past_conversations import week05_prompt_parts
from student_parts.week06_kanamate_decides_schedule import (
    AgentQueryInput,
    DECIDE_FINAL_SLOT_DESCRIPTION,
    FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION,
    FindCommonAvailableSlotsInput,
    ProposeGroupScheduleInput,
    _tool_call_names,
    agent_tool_names,
    kana_prompt_parts,
    kana_system_prompt,
    kana_tools,
    nana_prompt_parts,
    propose_group_schedule,
    supervisor_system_prompt,
    supervisor_tools,
    tool_name,
    week06_prompt_parts,
    week06_system_prompt,
)


class Week06PromptTest(unittest.TestCase):
    def test_supervisor_prompt_accumulates_week05_and_defines_delegation(self):
        previous_parts = week05_prompt_parts()
        parts = week06_prompt_parts()
        prompt = supervisor_system_prompt()

        self.assertEqual(parts[: len(previous_parts)], previous_parts)
        self.assertIn("현재 실행 범위는 Week 6", prompt)
        self.assertIn("nana_agent", prompt)
        self.assertIn("kana_agent", prompt)
        self.assertIn("담당 하나를 정확히 한 번 호출", prompt)
        self.assertIn("직접 완료 답변을 만들지 않는다", prompt)
        self.assertEqual(week06_system_prompt(), prompt)

    def test_nana_prompt_accumulates_week04_and_rejects_group_work(self):
        previous_parts = week04_prompt_parts()
        parts = nana_prompt_parts()
        prompt = "\n".join(parts)

        self.assertEqual(parts[: len(previous_parts)], previous_parts)
        self.assertIn("개인 일정 생성·조회·수정·삭제", prompt)
        self.assertIn("외부 멤버의 일정 조회와 그룹 공통 시간 결정은 담당하지 않는다", prompt)
        self.assertIn("Kana 담당", prompt)
        self.assertIn("mutation tool의 결과를 받기 전", prompt)
        self.assertIn("workflow를 끝내지 않는다", prompt)

    def test_kana_prompt_is_self_contained_and_requires_full_decision_flow(self):
        prompt = kana_system_prompt()

        self.assertTrue(kana_prompt_parts())
        self.assertIn("현재 앱 기준 날짜", prompt)
        self.assertIn("search_previous_conversations", prompt)
        self.assertIn("collect_member_schedules", prompt)
        self.assertIn("find_common_available_slots", prompt)
        self.assertIn("decide_final_slot", prompt)
        self.assertIn("final_slot=null", prompt)
        self.assertIn("실제 저장은 Nana 담당", prompt)


class Week06ToolBoundaryTest(unittest.TestCase):
    def test_supervisor_exposes_only_two_wrapper_tools(self):
        self.assertEqual(
            [tool_name(item) for item in supervisor_tools()],
            ["nana_agent", "kana_agent"],
        )
        self.assertEqual(agent_tool_names("supervisor"), ["nana_agent", "kana_agent"])

    def test_nana_tools_are_exactly_week04_tools(self):
        self.assertEqual(
            agent_tool_names("nana_agent"),
            [tool_name(item) for item in week04_tools()],
        )
        self.assertNotIn("find_common_available_slots", agent_tool_names("nana_agent"))

    def test_nana_mutation_tool_descriptions_define_workflow_boundaries(self):
        tools = {tool_name(item): item for item in week04_tools()}

        self.assertIn("mutation workflow의 첫 단계", tools["extract_schedule_request"].description)
        self.assertIn("최종 mutation tool", tools["personal_create_schedule"].description)
        self.assertIn("최종 mutation tool", tools["save_structured_request"].description)
        self.assertIn("선행 tool", tools["personal_list_saved_schedules"].description)
        self.assertIn("결과를 받기 전", tools["personal_update_saved_schedule"].description)
        self.assertIn("결과를 받기 전", tools["personal_delete_saved_schedules"].description)

    def test_kana_has_required_tools_but_not_personal_mutations_or_compat_tool(self):
        names = [tool_name(item) for item in kana_tools()]

        for required in (
            "extract_schedule_request",
            "search_previous_conversations",
            "load_conversation_messages",
            "extract_schedules_from_history",
            "list_shared_schedules",
            "collect_member_schedules",
            "find_common_available_slots",
            "decide_final_slot",
        ):
            self.assertIn(required, names)
        for forbidden in (
            "personal_create_schedule",
            "personal_update_saved_schedule",
            "personal_delete_saved_schedules",
            "propose_group_schedule",
        ):
            self.assertNotIn(forbidden, names)
        self.assertEqual(agent_tool_names("unknown"), [])

    def test_tool_call_names_keeps_only_named_calls_in_order_with_duplicates(self):
        events = [
            {"event": "tool_call", "tool_name": "first"},
            {"event": "tool_result", "tool_name": "first"},
            {"event": "tool_call", "tool_name": None},
            {"event": "tool_call", "tool_name": "first"},
            {"event": "tool_call", "tool_name": "second"},
        ]

        self.assertEqual(_tool_call_names(events), ["first", "first", "second"])


class Week06SchemaAndDescriptionTest(unittest.TestCase):
    def test_find_schema_defaults_and_numeric_boundaries(self):
        value = FindCommonAvailableSlotsInput(
            member_names=["철수"],
            date_from="2026-08-10",
            date_to="2026-08-12",
        )
        self.assertEqual(value.duration_minutes, 60)
        self.assertEqual(value.workday_start, "09:00")
        self.assertEqual(value.workday_end, "18:00")
        self.assertEqual(value.limit, 5)

        for duration in (30, 480):
            self.assertEqual(
                FindCommonAvailableSlotsInput(
                    member_names=["철수"],
                    date_from="2026-08-10",
                    date_to="2026-08-12",
                    duration_minutes=duration,
                ).duration_minutes,
                duration,
            )
        for duration in (29, 481):
            with self.assertRaises(ValidationError):
                FindCommonAvailableSlotsInput(
                    member_names=["철수"],
                    date_from="2026-08-10",
                    date_to="2026-08-12",
                    duration_minutes=duration,
                )

    def test_wrapper_input_schemas_keep_required_contracts(self):
        with self.assertRaises(ValidationError):
            AgentQueryInput()
        self.assertEqual(AgentQueryInput(query="내 일정").query, "내 일정")
        self.assertIn(
            "완결된 요청",
            AgentQueryInput.model_fields["query"].description,
        )
        with self.assertRaises(ValidationError):
            ProposeGroupScheduleInput(member_names=["철수"])

    def test_tool_descriptions_tell_agent_to_select_instead_of_python(self):
        self.assertIn("후보를 대신", FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION)
        self.assertIn("busy_rows", FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION)
        self.assertIn("date(YYYY-MM-DD)", FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION)
        self.assertIn("duration_minutes", FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION)
        self.assertIn("decide_final_slot", FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION)

        self.assertIn("자동 선택하지 않습니다", DECIDE_FINAL_SLOT_DESCRIPTION)
        self.assertIn("selected_index", DECIDE_FINAL_SLOT_DESCRIPTION)
        self.assertIn("YYYY-MM-DD HH:MM-HH:MM", DECIDE_FINAL_SLOT_DESCRIPTION)
        self.assertIn("needs_agent_selection=false", DECIDE_FINAL_SLOT_DESCRIPTION)
        self.assertIn("final_slot=null", DECIDE_FINAL_SLOT_DESCRIPTION)

    def test_compatibility_tool_keeps_confirmed_and_manual_review_statuses(self):
        candidate = {
            "date": "2026-08-10",
            "start_time": "11:00",
            "end_time": "12:00",
            "duration_minutes": 60,
            "reason": "가능",
        }
        confirmed = json.loads(
            propose_group_schedule.invoke(
                {
                    "title": "회의",
                    "member_names": [" 철수 "],
                    "candidate_slots": [candidate],
                    "selected_slot": candidate,
                    "reason": "선택",
                }
            )
        )
        manual = json.loads(
            propose_group_schedule.invoke(
                {"title": "회의", "member_names": ["철수"]}
            )
        )

        self.assertEqual(confirmed["final_decision"]["status"], "confirmed")
        self.assertEqual(confirmed["final_decision"]["members"], ["철수"])
        self.assertEqual(manual["final_decision"]["status"], "needs_manual_review")


if __name__ == "__main__":
    unittest.main()
