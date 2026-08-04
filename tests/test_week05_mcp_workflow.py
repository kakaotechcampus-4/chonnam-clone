from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from fixed.langchain_trace import extract_langchain_trace
from fixed.session_scope import conversation_session_scope
from student_parts.prompts.week05 import (
    WEEK05_HISTORY_WORKFLOW_PROMPT,
    WEEK05_MCP_BOUNDARY_PROMPT,
    WEEK05_SCHEDULE_COLLECTION_PROMPT,
    WEEK05_SCOPE_PROMPT,
    WEEK05_TRACEABILITY_PROMPT,
)
from student_parts.week01_wake_up_nana import PERSONAL_SCHEDULES
from student_parts.week04_retrieve_nanas_memory import week04_prompt_parts
from student_parts.week05_load_kanas_past_conversations import (
    _collect_member_schedules,
    _personal_schedules_for_current_scope,
    create_shared_schedule,
    delete_shared_schedule,
    extract_schedules_from_history,
    list_shared_schedules,
    load_conversation_messages,
    search_previous_conversations,
    week05_prompt_parts,
    week05_system_prompt,
)


class ToolCallingFakeChatModel(FakeMessagesListChatModel):
    """미리 정한 tool call을 실제 LangChain agent loop에서 순서대로 반환합니다."""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        """테스트 응답에 tool call이 이미 있으므로 전달받은 tool 목록만 수용합니다."""

        return self


class Week05McpWrapperTest(unittest.TestCase):
    @patch(
        "student_parts.week05_load_kanas_past_conversations.call_mcp_tool_sync",
        return_value='{"ok": true, "rows": []}',
    )
    def test_search_previous_conversations_delegates_to_mcp(self, call_mcp):
        result = search_previous_conversations.invoke(
            {
                "query": "고객 인터뷰",
                "member_names": ["철수"],
                "limit": 3,
            }
        )

        self.assertEqual(result, '{"ok": true, "rows": []}')
        call_mcp.assert_called_once_with(
            "search_previous_conversations",
            {
                "query": "고객 인터뷰",
                "member_names": ["철수"],
                "limit": 3,
            },
        )

    @patch(
        "student_parts.week05_load_kanas_past_conversations.call_external_tool_payload",
        return_value={
            "ok": True,
            "rows": [
                {
                    "sender": "철수",
                    "content": "7월 9일 14시는 고객 인터뷰가 있어요.",
                    "created_at": "2026-07-01T10:00:00+09:00",
                }
            ],
        },
    )
    def test_load_conversation_messages_keeps_payload_and_korean(self, call_external):
        result = json.loads(
            load_conversation_messages.invoke({"conversation_id": "ext_cs"})
        )

        call_external.assert_called_once_with(
            "load_conversation_messages",
            {"conversation_id": "ext_cs"},
        )
        self.assertEqual(result["rows"][0]["sender"], "철수")
        self.assertIn("고객 인터뷰", result["rows"][0]["content"])

    @patch(
        "student_parts.week05_load_kanas_past_conversations.call_mcp_tool_sync",
        return_value='{"ok": true, "rows": []}',
    )
    def test_extract_schedules_delegates_without_wrapper_normalization(self, call_mcp):
        result = extract_schedules_from_history.invoke(
            {
                "member_names": ["철수"],
                "date_from": "2026-07-07T00:00:00",
                "date_to": "2026-07-17T23:59:59",
            }
        )

        self.assertEqual(result, '{"ok": true, "rows": []}')
        call_mcp.assert_called_once_with(
            "extract_schedules_from_history",
            {
                "member_names": ["철수"],
                "date_from": "2026-07-07T00:00:00",
                "date_to": "2026-07-17T23:59:59",
            },
        )

    @patch(
        "student_parts.week05_load_kanas_past_conversations.call_mcp_tool_sync",
        return_value='{"ok": true}',
    )
    def test_shared_schedule_wrappers_keep_identifiers(self, call_mcp):
        create_shared_schedule.invoke(
            {
                "member_name": "철수",
                "title": "회의",
                "date": "2026-07-09",
                "start_time": "14:00",
                "source_conversation_id": "ext_cs",
                "schedule_id": "shared_test",
            }
        )
        delete_shared_schedule.invoke(
            {
                "schedule_id": "shared_test",
                "source_conversation_id": "ext_cs",
            }
        )
        list_shared_schedules.invoke(
            {
                "member_names": ["철수"],
                "date_from": "2026-07-07",
                "date_to": "2026-07-17",
                "source_conversation_id": "ext_cs",
                "limit": 20,
            }
        )

        self.assertEqual(call_mcp.call_args_list[0].args[0], "create_shared_schedule")
        self.assertEqual(
            call_mcp.call_args_list[0].args[1]["source_conversation_id"],
            "ext_cs",
        )
        self.assertEqual(call_mcp.call_args_list[0].args[1]["schedule_id"], "shared_test")
        self.assertEqual(call_mcp.call_args_list[1].args[0], "delete_shared_schedule")
        self.assertEqual(call_mcp.call_args_list[2].args[0], "list_shared_schedules")


class Week05ScheduleCollectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_personal_schedules = list(PERSONAL_SCHEDULES)
        PERSONAL_SCHEDULES.clear()

    def tearDown(self) -> None:
        PERSONAL_SCHEDULES[:] = self.original_personal_schedules

    @patch("student_parts.week05_load_kanas_past_conversations.AppSQLiteStore")
    def test_personal_schedules_use_200_limit_scope_and_id_deduplication(
        self,
        store_class,
    ):
        store = Mock()
        store.list_schedules.return_value = [
            {
                "schedule_id": "personal_saved",
                "title": "저장 일정",
                "date": "2026-07-09",
                "start_time": "09:00",
                "end_time": "10:00",
                "attendees": [],
            }
        ]
        store_class.return_value = store
        PERSONAL_SCHEDULES.extend(
            [
                {
                    "id": "personal_saved",
                    "session_id": "session-a",
                    "title": "중복 임시 일정",
                    "date": "2026-07-09",
                    "start_time": "09:00",
                    "end_time": "10:00",
                },
                {
                    "id": "personal_new",
                    "session_id": "session-a",
                    "title": "현재 대화 임시 일정",
                    "date": "2026-07-10",
                    "start_time": "13:00",
                    "end_time": "14:00",
                },
                {
                    "id": "personal_other",
                    "session_id": "session-b",
                    "title": "다른 대화 일정",
                    "date": "2026-07-11",
                    "start_time": "15:00",
                    "end_time": "16:00",
                },
            ]
        )

        with conversation_session_scope("session-a"):
            result = _personal_schedules_for_current_scope()

        store.list_schedules.assert_called_once_with(limit=200, kind="personal_schedule")
        result_ids = [
            row.get("schedule_id") or row.get("id")
            for row in result
        ]
        self.assertEqual(result_ids, ["personal_saved", "personal_new"])

    @patch(
        "student_parts.week05_load_kanas_past_conversations.call_mcp_tool_sync"
    )
    def test_collect_member_schedules_normalizes_filters_and_keeps_source(
        self,
        call_mcp,
    ):
        call_mcp.return_value = json.dumps(
            {
                "ok": True,
                "rows": [
                    {
                        "member_name": "철수",
                        "title": "고객 인터뷰",
                        "date": "2026-07-09",
                        "start_time": "14:00",
                        "end_time": "15:30",
                        "notes": "",
                        "source_conversation_id": "ext_cs",
                    }
                ],
            },
            ensure_ascii=False,
        )

        result = _collect_member_schedules(
            member_names=[" 철수 "],
            date_from="2026-07-07T00:00:00",
            date_to="2026-07-17T23:59:59",
            personal_schedules=[
                {
                    "schedule_id": "mine-in-range",
                    "title": "내 회의",
                    "date": "2026-07-08",
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "attendees": ["영희", "민수"],
                },
                {
                    "schedule_id": "mine-out-of-range",
                    "title": "범위 밖 일정",
                    "date": "2026-07-20",
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "attendees": [],
                },
            ],
        )

        call_mcp.assert_called_once_with(
            "extract_schedules_from_history",
            {
                "member_names": ["철수"],
                "date_from": "2026-07-07",
                "date_to": "2026-07-17",
            },
        )
        self.assertEqual([row["member_name"] for row in result["rows"]], ["나", "철수"])
        self.assertEqual(result["rows"][0]["members"], ["영희", "민수"])
        self.assertEqual(result["rows"][1]["source_conversation_id"], "ext_cs")
        self.assertIn("내 회의", result["schedule_summary"])
        self.assertIn("고객 인터뷰", result["schedule_summary"])

    @patch(
        "student_parts.week05_load_kanas_past_conversations.call_mcp_tool_sync"
    )
    def test_collect_member_schedules_skips_mcp_when_member_names_empty(
        self,
        call_mcp,
    ):
        result = _collect_member_schedules(
            member_names=[],
            date_from="2026-07-07T00:00:00",
            date_to="2026-07-17T23:59:59",
            personal_schedules=[],
        )

        call_mcp.assert_not_called()
        self.assertEqual(result["rows"], [])

    @patch(
        "student_parts.week05_load_kanas_past_conversations.call_mcp_tool_sync"
    )
    def test_collect_member_schedules_skips_mcp_when_member_names_are_blank(
        self,
        call_mcp,
    ):
        result = _collect_member_schedules(
            member_names=["  ", ""],
            date_from="2026-07-07T00:00:00",
            date_to="2026-07-17T23:59:59",
            personal_schedules=[],
        )

        call_mcp.assert_not_called()
        self.assertEqual(result["rows"], [])


class Week05PromptAndTraceTest(unittest.TestCase):
    def test_week05_prompt_accumulates_week04_then_adds_unique_week05_parts(self):
        week04_parts = week04_prompt_parts()
        parts = week05_prompt_parts()

        self.assertEqual(parts[: len(week04_parts)], week04_parts)
        self.assertEqual(parts[-1], WEEK05_SCOPE_PROMPT)
        for prompt_part in (
            WEEK05_MCP_BOUNDARY_PROMPT,
            WEEK05_HISTORY_WORKFLOW_PROMPT,
            WEEK05_TRACEABILITY_PROMPT,
            WEEK05_SCHEDULE_COLLECTION_PROMPT,
            WEEK05_SCOPE_PROMPT,
        ):
            self.assertEqual(parts.count(prompt_part), 1)

        prompt = week05_system_prompt()
        self.assertIn("직접 SQL을 작성", prompt)
        self.assertIn("다음 세 유형 중 정확히 하나로 분류", prompt)
        self.assertIn("외부 멤버 이름이 여러 명이라는 이유만으로 C로 분류하지 않는다", prompt)
        self.assertIn(
            "검색 결과 rows가 비어 있더라도 extract_schedules_from_history",
            prompt,
        )
        self.assertIn("extract 결과 rows도 비어 있으면 조회를 중단", prompt)
        self.assertIn(
            "search_previous_conversations -> extract_schedules_from_history",
            prompt,
        )
        self.assertIn("collect_member_schedules 하나만 호출", prompt)
        self.assertLess(
            prompt.index("search_previous_conversations"),
            prompt.index("extract_schedules_from_history"),
        )

    @patch(
        "student_parts.week05_load_kanas_past_conversations.call_external_tool_payload",
        return_value={
            "ok": True,
            "tool_name": "load_conversation_messages",
            "rows": [
                {
                    "sender": "철수",
                    "content": "7월 9일 14시는 고객 인터뷰가 있어요.",
                    "created_at": "2026-07-01T10:00:00+09:00",
                }
            ],
        },
    )
    @patch(
        "student_parts.week05_load_kanas_past_conversations.call_mcp_tool_sync"
    )
    def test_agent_trace_interleaves_search_extract_and_optional_load_results(
        self,
        call_mcp,
        call_external,
    ):
        call_mcp.side_effect = [
            json.dumps(
                {
                    "ok": True,
                    "tool_name": "search_previous_conversations",
                    "rows": [{"conversation_id": "ext_cs"}],
                }
            ),
            json.dumps(
                {
                    "ok": True,
                    "tool_name": "extract_schedules_from_history",
                    "rows": [
                        {
                            "member_name": "철수",
                            "title": "고객 인터뷰",
                            "date": "2026-07-09",
                            "start_time": "14:00",
                            "end_time": "15:30",
                            "notes": "",
                            "source_conversation_id": "ext_cs",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        ]
        model = ToolCallingFakeChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "search_previous_conversations",
                            "args": {"query": "고객 인터뷰"},
                            "id": "call-search",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "extract_schedules_from_history",
                            "args": {
                                "member_names": ["철수"],
                                "date_from": "2026-07-07",
                                "date_to": "2026-07-17",
                            },
                            "id": "call-extract",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "load_conversation_messages",
                            "args": {"conversation_id": "ext_cs"},
                            "id": "call-load",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="철수의 고객 인터뷰 원문을 확인했습니다."),
            ]
        )
        agent = create_agent(
            model=model,
            tools=[
                search_previous_conversations,
                extract_schedules_from_history,
                load_conversation_messages,
            ],
            system_prompt=week05_system_prompt(),
        )

        result = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "철수의 고객 인터뷰 일정과 원문을 알려줘.",
                    }
                ]
            }
        )
        trace = extract_langchain_trace(result)
        event_signatures = [
            (event["event"], event["tool_name"])
            for event in trace["events"]
        ]

        self.assertEqual(
            event_signatures,
            [
                ("tool_call", "search_previous_conversations"),
                ("tool_result", "search_previous_conversations"),
                ("tool_call", "extract_schedules_from_history"),
                ("tool_result", "extract_schedules_from_history"),
                ("tool_call", "load_conversation_messages"),
                ("tool_result", "load_conversation_messages"),
            ],
        )
        self.assertEqual(
            [call.args[0] for call in call_mcp.call_args_list],
            [
                "search_previous_conversations",
                "extract_schedules_from_history",
            ],
        )
        call_external.assert_called_once_with(
            "load_conversation_messages",
            {"conversation_id": "ext_cs"},
        )

    @patch(
        "student_parts.week05_load_kanas_past_conversations.call_external_tool_payload"
    )
    @patch(
        "student_parts.week05_load_kanas_past_conversations.call_mcp_tool_sync"
    )
    def test_agent_trace_omits_optional_load_when_original_text_is_not_requested(
        self,
        call_mcp,
        call_external,
    ):
        call_mcp.side_effect = [
            '{"ok": true, "tool_name": "search_previous_conversations", "rows": []}',
            '{"ok": true, "tool_name": "extract_schedules_from_history", "rows": []}',
        ]
        model = ToolCallingFakeChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "search_previous_conversations",
                            "args": {"query": "일정", "member_names": ["철수"]},
                            "id": "call-search",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "extract_schedules_from_history",
                            "args": {
                                "member_names": ["철수"],
                                "date_from": "2026-07-07",
                                "date_to": "2026-07-17",
                            },
                            "id": "call-extract",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="조회된 일정이 없습니다."),
            ]
        )
        agent = create_agent(
            model=model,
            tools=[
                search_previous_conversations,
                extract_schedules_from_history,
                load_conversation_messages,
            ],
            system_prompt=week05_system_prompt(),
        )

        result = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "철수의 7월 7일부터 17일까지 일정을 알려줘.",
                    }
                ]
            }
        )
        trace = extract_langchain_trace(result)
        event_signatures = [
            (event["event"], event["tool_name"])
            for event in trace["events"]
        ]

        self.assertEqual(
            event_signatures,
            [
                ("tool_call", "search_previous_conversations"),
                ("tool_result", "search_previous_conversations"),
                ("tool_call", "extract_schedules_from_history"),
                ("tool_result", "extract_schedules_from_history"),
            ],
        )
        call_external.assert_not_called()


if __name__ == "__main__":
    unittest.main()
