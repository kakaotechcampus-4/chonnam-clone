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
        self.assertEqual(second["selected_agent"], "nana_agent")

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

        self.assertIs(first, supervisor)
        self.assertIs(second, supervisor)
        create_agent.assert_called_once_with(
            model="model",
            tools=["nana", "kana"],
            system_prompt="supervisor prompt",
        )


if __name__ == "__main__":
    unittest.main()
