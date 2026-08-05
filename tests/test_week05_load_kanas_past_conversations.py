from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import PropertyMock, patch

from fixed.app_store import AppSQLiteStore
from fixed.config import CONFIG
from fixed.session_scope import conversation_session_scope
from fixed.week_agent_registry import stream_active_week_agent

import student_parts.week05_load_kanas_past_conversations as week05


class ScheduleStoreFake:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.list_calls: list[dict[str, Any]] = []

    def list_schedules(self, **arguments: Any) -> list[dict[str, Any]]:
        self.list_calls.append(arguments)
        return self.rows


class ToolCallMessageFake:
    type = "ai"
    content = ""
    tool_calls = [
        {
            "name": "search_previous_conversations",
            "args": {"query": "고객 인터뷰", "member_names": ["철수"], "limit": 5},
            "id": "call-review-error",
        }
    ]


class FailingStreamAgentFake:
    def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        yield {"model": {"messages": [ToolCallMessageFake()]}}
        raise RuntimeError("MCP unavailable")


class PersonalScheduleCollectionTests(unittest.TestCase):
    def test_sqlite_rows_win_and_only_unique_current_scope_rows_are_appended(self) -> None:
        saved_rows = [
            {"schedule_id": "personal_saved", "title": "saved copy"},
            {"schedule_id": "sch_db", "title": "database only"},
        ]
        temporary_rows = [
            {
                "id": "personal_saved",
                "title": "temporary duplicate",
                "session_id": "conversation-current",
            },
            {
                "id": "personal_current",
                "title": "current temporary",
                "session_id": "conversation-current",
            },
            {
                "id": "personal_current",
                "title": "duplicate temporary",
                "session_id": "conversation-current",
            },
            {
                "id": "personal_other",
                "title": "other conversation",
                "session_id": "conversation-other",
            },
        ]
        store = ScheduleStoreFake(saved_rows)

        with (
            patch.object(week05, "AppSQLiteStore", return_value=store) as constructor,
            patch.object(week05, "PERSONAL_SCHEDULES", temporary_rows),
            conversation_session_scope("conversation-current"),
        ):
            result = week05._personal_schedules_for_current_scope()

        constructor.assert_called_once_with(CONFIG.app_db_path)
        self.assertEqual(store.list_calls, [{"limit": 200}])
        self.assertEqual(
            result,
            [
                *saved_rows,
                {
                    "id": "personal_current",
                    "title": "current temporary",
                    "session_id": "conversation-current",
                },
            ],
        )
        self.assertEqual(len(temporary_rows), 4)

    def test_default_scope_includes_legacy_direct_tool_rows(self) -> None:
        store = ScheduleStoreFake([])
        temporary_rows = [
            {"id": "personal_direct", "title": "direct tool"},
            {
                "id": "personal_conversation",
                "title": "conversation",
                "session_id": "conversation-1",
            },
        ]

        with (
            patch.object(week05, "AppSQLiteStore", return_value=store),
            patch.object(week05, "PERSONAL_SCHEDULES", temporary_rows),
        ):
            result = week05._personal_schedules_for_current_scope()

        self.assertEqual(result, [{"id": "personal_direct", "title": "direct tool"}])

    def test_schedule_row_is_converted_to_week02_schema(self) -> None:
        request = week05._structured_request_from_schedule_row(
            {
                "title": "planning",
                "date": "2026-07-30",
                "start_time": "14:00",
                "end_time": "15:00",
                "attendees": ["Mina"],
            }
        )

        self.assertEqual(request.kind, "personal_schedule")
        self.assertEqual(request.members, ["Mina"])
        self.assertEqual(request.original_text, "planning")

    def test_group_schedule_row_preserves_its_kind(self) -> None:
        request = week05._structured_request_from_schedule_row(
            {
                "request_kind": "group_schedule",
                "title": "team planning",
                "date": "2026-08-04",
                "start_time": "14:00",
                "end_time": "15:00",
                "attendees": ["Mina"],
            }
        )

        self.assertEqual(request.kind, "group_schedule")

    def test_saved_personal_and_group_schedules_are_both_my_busy_time(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            store = AppSQLiteStore(Path(temp_dir) / "app.sqlite3")
            with (
                patch(
                    "fixed.app_store.sync_personal_schedule_to_shared",
                    return_value={"ok": True, "status": "synced"},
                ),
                patch(
                    "fixed.app_store.sync_group_schedule_to_shared",
                    return_value={"ok": True, "status": "synced"},
                ),
            ):
                store.save_structured_request(
                    {
                        "kind": "personal_schedule",
                        "title": "개인 운동",
                        "date": "2026-08-04",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "members": [],
                    }
                )
                store.save_structured_request(
                    {
                        "kind": "group_schedule",
                        "title": "그룹 회의",
                        "date": "2026-08-04",
                        "start_time": "14:00",
                        "end_time": "15:00",
                        "members": ["철수"],
                    }
                )

            saved_schedules = store.list_schedules(limit=10)
            self.assertEqual(
                [row["request_kind"] for row in saved_schedules],
                ["personal_schedule", "group_schedule"],
            )

            with (
                patch.object(week05, "AppSQLiteStore", return_value=store),
                patch.object(week05, "PERSONAL_SCHEDULES", []),
                patch.object(week05, "call_mcp_tool_sync") as mcp_call,
            ):
                result = json.loads(
                    week05.collect_member_schedules.invoke(
                        {
                            "member_names": [],
                            "date_from": "2026-08-04",
                            "date_to": "2026-08-04",
                        }
                    )
                )

        mcp_call.assert_not_called()
        self.assertEqual(result["members"], ["나"])
        self.assertEqual(
            [(row["member_name"], row["title"]) for row in result["rows"]],
            [("나", "개인 운동"), ("나", "그룹 회의")],
        )
        self.assertEqual(
            [row["notes"] for row in result["rows"]],
            ["Nana 개인 일정", "Nana 그룹 일정 · 참석자: 철수"],
        )


class HistoryMCPWrapperTests(unittest.TestCase):
    def test_search_forwards_exact_arguments_and_returns_mcp_text(self) -> None:
        expected = '{"ok":true,"tool_name":"search_previous_conversations","rows":[]}'

        with patch.object(week05, "call_mcp_tool_sync", return_value=expected) as call:
            result = week05.search_previous_conversations.invoke(
                {
                    "query": "project alpha",
                    "member_names": ["Mina", "Jisoo"],
                    "limit": 7,
                }
            )

        self.assertEqual(result, expected)
        call.assert_called_once_with(
            "search_previous_conversations",
            {
                "query": "project alpha",
                "member_names": ["Mina", "Jisoo"],
                "limit": 7,
            },
        )

    def test_search_preserves_none_member_filter(self) -> None:
        with patch.object(week05, "call_mcp_tool_sync", return_value="{}") as call:
            week05.search_previous_conversations.invoke(
                {"query": "meeting", "member_names": None, "limit": 5}
            )

        call.assert_called_once_with(
            "search_previous_conversations",
            {"query": "meeting", "member_names": None, "limit": 5},
        )

    def test_load_preserves_message_order_and_unescaped_korean(self) -> None:
        payload = {
            "ok": True,
            "tool_name": "load_conversation_messages",
            "rows": [
                {
                    "sender": "민아",
                    "role": "user",
                    "content": "오전에는 회의가 있어",
                    "created_at": "2026-07-28T09:00:00+09:00",
                },
                {
                    "sender": "Kana",
                    "role": "assistant",
                    "content": "오후 일정으로 확인할게",
                    "created_at": "2026-07-28T09:01:00+09:00",
                },
            ],
        }

        with patch.object(
            week05,
            "call_external_tool_payload",
            return_value=payload,
        ) as call:
            raw_result = week05.load_conversation_messages.invoke(
                {"conversation_id": "conversation-1"}
            )

        call.assert_called_once_with(
            "load_conversation_messages",
            {"conversation_id": "conversation-1"},
        )
        self.assertNotIn("\\u", raw_result)
        self.assertEqual(json.loads(raw_result), payload)

    def test_extract_forwards_exact_arguments_and_returns_mcp_text(self) -> None:
        expected = '{"ok":true,"tool_name":"extract_schedules_from_history","rows":[]}'

        with patch.object(week05, "call_mcp_tool_sync", return_value=expected) as call:
            result = week05.extract_schedules_from_history.invoke(
                {
                    "member_names": ["Mina"],
                    "date_from": "2026-07-29",
                    "date_to": "2026-08-02",
                }
            )

        self.assertEqual(result, expected)
        call.assert_called_once_with(
            "extract_schedules_from_history",
            {
                "member_names": ["Mina"],
                "date_from": "2026-07-29",
                "date_to": "2026-08-02",
            },
        )

    def test_mcp_errors_propagate_to_the_agent_runtime(self) -> None:
        with patch.object(
            week05,
            "call_mcp_tool_sync",
            side_effect=RuntimeError("MCP unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "MCP unavailable"):
                week05.search_previous_conversations.invoke(
                    {"query": "meeting", "member_names": None, "limit": 5}
                )

    def test_streaming_app_runtime_keeps_tool_call_and_error_in_trace(self) -> None:
        with (
            patch.object(
                type(week05.CONFIG),
                "has_openai_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                week05,
                "build_week_agent",
                return_value=FailingStreamAgentFake(),
            ),
        ):
            events = list(
                stream_active_week_agent(
                    5,
                    [{"role": "user", "content": "철수의 고객 인터뷰 대화를 찾아줘"}],
                )
            )

        self.assertEqual(events[1].status_text, "현재 search_previous_conversations 실행 중")
        result = events[-1].result
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("Week 5 agent 실행 중 오류가 발생했습니다", result.answer)
        self.assertIn("MCP unavailable", result.answer)
        self.assertEqual(result.trace["error"], "MCP unavailable")
        self.assertEqual(result.trace["error_type"], "RuntimeError")
        self.assertEqual(
            result.trace["events"][0]["tool_name"],
            "search_previous_conversations",
        )


class SharedScheduleMCPWrapperTests(unittest.TestCase):
    def test_create_forwards_all_fields_and_preserves_mcp_payload(self) -> None:
        expected_payload = {
            "ok": True,
            "tool_name": "create_shared_schedule",
            "shared_schedule": {
                "schedule_id": "shared-1",
                "source_conversation_id": "conversation-7",
            },
        }
        expected = json.dumps(expected_payload, ensure_ascii=False)
        arguments = {
            "member_name": "민아",
            "title": "주간 회의",
            "date": "2026-07-30",
            "start_time": "13:00",
            "end_time": "14:00",
            "notes": "프로젝트 일정",
            "source_conversation_id": "conversation-7",
            "schedule_id": "shared-1",
        }

        with patch.object(week05, "call_mcp_tool_sync", return_value=expected) as call:
            result = week05.create_shared_schedule.invoke(arguments)

        self.assertEqual(result, expected)
        self.assertEqual(json.loads(result), expected_payload)
        call.assert_called_once_with("create_shared_schedule", arguments)

    def test_delete_forwards_identifiers_without_inventing_a_guard(self) -> None:
        expected = json.dumps(
            {
                "ok": True,
                "tool_name": "delete_shared_schedule",
                "deleted_count": 0,
                "deleted": [],
            }
        )

        with patch.object(week05, "call_mcp_tool_sync", return_value=expected) as call:
            result = week05.delete_shared_schedule.invoke(
                {"schedule_id": None, "source_conversation_id": None}
            )

        self.assertEqual(result, expected)
        call.assert_called_once_with(
            "delete_shared_schedule",
            {"schedule_id": None, "source_conversation_id": None},
        )

    def test_list_forwards_filters_and_preserves_schedule_metadata(self) -> None:
        expected_payload = {
            "ok": True,
            "tool_name": "list_shared_schedules",
            "rows": [
                {
                    "schedule_id": "shared-2",
                    "source_conversation_id": "conversation-8",
                    "member_name": "지수",
                }
            ],
            "schedule_summary": "공유 일정 1건",
        }
        expected = json.dumps(expected_payload, ensure_ascii=False)
        arguments = {
            "member_names": ["지수"],
            "date_from": "2026-07-29",
            "date_to": "2026-08-05",
            "source_conversation_id": "conversation-8",
            "limit": 25,
        }

        with patch.object(week05, "call_mcp_tool_sync", return_value=expected) as call:
            result = week05.list_shared_schedules.invoke(arguments)

        self.assertEqual(json.loads(result), expected_payload)
        call.assert_called_once_with("list_shared_schedules", arguments)


class MemberScheduleAggregationTests(unittest.TestCase):
    def test_collect_normalizes_filters_and_combines_common_row_shapes(self) -> None:
        personal_schedules = [
            {
                "schedule_id": "sch-in-range",
                "title": "내부 회의",
                "date": "2026-07-30",
                "start_time": "09:00",
                "end_time": "10:00",
                "attendees": ["민아"],
            },
            {
                "schedule_id": "sch-before",
                "title": "범위 전 일정",
                "date": "2026-07-28",
                "start_time": "09:00",
                "end_time": "10:00",
            },
            {
                "schedule_id": "sch-after",
                "title": "범위 후 일정",
                "date": "2026-08-03",
                "start_time": "09:00",
                "end_time": "10:00",
            },
            {
                "schedule_id": "sch-no-date",
                "title": "날짜 미정 일정",
                "date": None,
                "start_time": None,
                "end_time": None,
            },
        ]
        external_payload = {
            "ok": True,
            "tool_name": "extract_schedules_from_history",
            "rows": [
                {
                    "member_name": "민아",
                    "title": "고객 미팅",
                    "date": "2026-07-31",
                    "start_time": "14:00",
                    "end_time": "15:00",
                    "notes": "외부 대화에서 추출",
                    "source_conversation_id": "external-conversation-1",
                }
            ],
        }

        with patch.object(
            week05,
            "call_mcp_tool_sync",
            return_value=json.dumps(external_payload, ensure_ascii=False),
        ) as call:
            result = week05._collect_member_schedules(
                member_names=["  민아  ", "  "],
                date_from="2026-07-29T00:00:00+09:00",
                date_to="2026-08-02T23:59:59+09:00",
                personal_schedules=personal_schedules,
            )

        call.assert_called_once_with(
            "extract_schedules_from_history",
            {
                "member_names": ["민아"],
                "date_from": "2026-07-29",
                "date_to": "2026-08-02",
            },
        )
        expected_rows = [
            {
                "member_name": "나",
                "title": "내부 회의",
                "date": "2026-07-30",
                "start_time": "09:00",
                "end_time": "10:00",
                "notes": "Nana 개인 일정",
            },
            {
                "member_name": "민아",
                "title": "고객 미팅",
                "date": "2026-07-31",
                "start_time": "14:00",
                "end_time": "15:00",
                "notes": "외부 대화에서 추출",
            },
        ]
        self.assertEqual(result["rows"], expected_rows)
        self.assertEqual(result["members"], ["나", "민아"])
        self.assertEqual(
            result["schedule_summary"],
            week05.external_schedule_summary(expected_rows),
        )
        self.assertTrue(all(len(row) == 6 for row in result["rows"]))

    def test_date_range_is_inclusive(self) -> None:
        personal_schedules = [
            {
                "title": "첫날",
                "date": "2026-07-29",
                "start_time": "09:00",
                "end_time": "10:00",
            },
            {
                "title": "마지막 날",
                "date": "2026-08-02",
                "start_time": "18:00",
                "end_time": "19:00",
            },
        ]

        with patch.object(week05, "call_mcp_tool_sync") as mcp_call:
            result = week05._collect_member_schedules(
                member_names=["  ", ""],
                date_from="2026-07-29",
                date_to="2026-08-02",
                personal_schedules=personal_schedules,
            )

        mcp_call.assert_not_called()
        self.assertEqual(result["members"], ["나"])
        self.assertEqual([row["title"] for row in result["rows"]], ["첫날", "마지막 날"])

    def test_my_schedule_notes_distinguish_personal_and_group_rows(self) -> None:
        personal = week05.StructuredRequest(kind="personal_schedule")
        group = week05.StructuredRequest(
            kind="group_schedule",
            members=[" 하린 ", "", "민준"],
        )
        group_without_members = week05.StructuredRequest(kind="group_schedule")

        self.assertEqual(week05._my_schedule_notes(personal), "Nana 개인 일정")
        self.assertEqual(
            week05._my_schedule_notes(group),
            "Nana 그룹 일정 · 참석자: 하린, 민준",
        )
        self.assertEqual(week05._my_schedule_notes(group_without_members), "Nana 그룹 일정")

    def test_duplicate_my_schedule_from_shared_store_keeps_app_row(self) -> None:
        personal_schedules = [
            {
                "request_kind": "personal_schedule",
                "title": "팀 회의 (온라인)",
                "date": "2026-07-14",
                "start_time": "",
                "end_time": "18:00",
            }
        ]
        external_payload = {
            "ok": True,
            "rows": [
                {
                    "member_name": "나",
                    "title": "팀 회의",
                    "date": "2026-07-14",
                    "start_time": "미정",
                    "end_time": "미정",
                    "notes": "앱 개인 일정 자동 동기화",
                },
                {
                    "member_name": "민준",
                    "title": "운영 회의",
                    "date": "2026-07-14",
                    "start_time": "15:00",
                    "end_time": "16:30",
                    "notes": "외부 일정",
                },
            ],
        }

        with patch.object(
            week05,
            "call_mcp_tool_sync",
            return_value=json.dumps(external_payload, ensure_ascii=False),
        ):
            result = week05._collect_member_schedules(
                member_names=["나", "민준"],
                date_from="2026-07-14",
                date_to="2026-07-14",
                personal_schedules=personal_schedules,
            )

        self.assertEqual(result["members"], ["나", "민준"])
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["rows"][0]["title"], "팀 회의 (온라인)")
        self.assertEqual(result["rows"][0]["notes"], "Nana 개인 일정")

    def test_malformed_external_payloads_are_not_treated_as_empty_results(self) -> None:
        malformed_payloads = [
            ("not JSON", "invalid JSON"),
            ("[]", "non-object payload"),
            ('{"rows": {}}', "non-list rows field"),
            ('{"rows": [1]}', "non-object row"),
        ]

        for payload, expected_error in malformed_payloads:
            with self.subTest(payload=payload):
                with patch.object(
                    week05,
                    "call_mcp_tool_sync",
                    return_value=payload,
                ):
                    with self.assertRaisesRegex(RuntimeError, expected_error):
                        week05._collect_member_schedules(
                            member_names=["Mina"],
                            date_from="2026-07-29",
                            date_to="2026-08-02",
                            personal_schedules=[],
                        )

    def test_public_tool_uses_current_personal_schedules_and_unescaped_json(self) -> None:
        personal_schedules = [
            {
                "title": "내 일정",
                "date": "2026-07-30",
                "start_time": "10:00",
                "end_time": "11:00",
            }
        ]

        with (
            patch.object(
                week05,
                "_personal_schedules_for_current_scope",
                return_value=personal_schedules,
            ) as personal_call,
            patch.object(
                week05,
                "call_mcp_tool_sync",
                return_value='{"ok": true, "rows": []}',
            ),
        ):
            raw_result = week05.collect_member_schedules.invoke(
                {
                    "member_names": ["민아"],
                    "date_from": "2026-07-29",
                    "date_to": "2026-08-02",
                }
            )

        personal_call.assert_called_once_with()
        self.assertNotIn("\\u", raw_result)
        result = json.loads(raw_result)
        self.assertEqual(result["tool_name"], "collect_member_schedules")
        self.assertEqual(result["rows"][0]["member_name"], "나")


class Week05AgentTests(unittest.TestCase):
    def test_tool_list_accumulates_unique_week05_tools(self) -> None:
        tool_names = [tool.name for tool in week05.week05_tools()]
        week05_tool_names = {
            "search_previous_conversations",
            "load_conversation_messages",
            "extract_schedules_from_history",
            "create_shared_schedule",
            "delete_shared_schedule",
            "list_shared_schedules",
            "collect_member_schedules",
        }

        self.assertTrue(week05_tool_names.issubset(tool_names))
        self.assertIn("search_conversation_messages", tool_names)
        self.assertIn("personal_list_saved_schedules", tool_names)
        self.assertEqual(len(tool_names), len(set(tool_names)))

    def test_prompt_defines_source_routing_and_week06_boundary(self) -> None:
        prompt = week05.week05_system_prompt()

        self.assertIn("사용자가 명시한 데이터 출처를 우선", prompt)
        self.assertIn("사용자가 자신이 Nana 앱에서 전에 한 말", prompt)
        self.assertIn("search_conversation_messages", prompt)
        self.assertIn("철수, 영희처럼 이름이 지정된 다른 구성원", prompt)
        self.assertIn("search_previous_conversations", prompt)
        self.assertIn("search_conversation_messages를 사용하지 않는다", prompt)
        self.assertIn("철수가 검색어로 포함됐더라도", prompt)
        self.assertIn("명시된 출처가 사용자의 Nana 앱 대화", prompt)
        self.assertIn("문맥이 부족할 때만", prompt)
        self.assertIn("extract_schedules_from_history를 직접 호출", prompt)
        self.assertIn("collect_member_schedules만 호출", prompt)
        self.assertIn("중복 호출하지 않는다", prompt)
        self.assertIn("일반 일정 저장", prompt)
        self.assertIn("자동 동기화", prompt)
        self.assertIn("명시적으로 요청한 경우에만", prompt)
        self.assertIn("최종 공통 가능 시간 선택", prompt)
        self.assertIn("Week 6의 책임", prompt)
        self.assertIn(week05.current_app_date_iso(), prompt)

    def test_agent_is_built_once_without_mutating_global_config(self) -> None:
        previous_agent = week05._WEEK05_AGENT
        fake_model = object()
        fake_agent = object()
        week05._WEEK05_AGENT = None
        try:
            with (
                patch.object(
                    type(week05.CONFIG),
                    "has_openai_key",
                    new_callable=PropertyMock,
                    return_value=True,
                ),
                patch.object(
                    week05,
                    "chat_model",
                    return_value=fake_model,
                ) as model_mock,
                patch.object(
                    week05,
                    "create_agent",
                    return_value=fake_agent,
                ) as create_mock,
            ):
                first = week05.build_week05_agent()
                second = week05.build_week05_agent()
        finally:
            week05._WEEK05_AGENT = previous_agent

        self.assertIs(first, fake_agent)
        self.assertIs(second, fake_agent)
        model_mock.assert_called_once_with()
        create_mock.assert_called_once()
        arguments = create_mock.call_args.kwargs
        self.assertIs(arguments["model"], fake_model)
        self.assertIn(
            "collect_member_schedules",
            [tool.name for tool in arguments["tools"]],
        )
        self.assertIn("Week 6의 책임", arguments["system_prompt"])


if __name__ == "__main__":
    unittest.main()
