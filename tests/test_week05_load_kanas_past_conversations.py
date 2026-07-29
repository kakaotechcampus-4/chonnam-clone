from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import patch

from fixed.config import CONFIG
from fixed.session_scope import conversation_session_scope

import student_parts.week05_load_kanas_past_conversations as week05


class ScheduleStoreFake:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.list_calls: list[dict[str, Any]] = []

    def list_schedules(self, **arguments: Any) -> list[dict[str, Any]]:
        self.list_calls.append(arguments)
        return self.rows


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
                "notes": "내 일정",
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
        self.assertEqual(result["member_names"], ["민아"])
        self.assertEqual(result["date_from"], "2026-07-29")
        self.assertEqual(result["date_to"], "2026-08-02")
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

        with patch.object(
            week05,
            "call_mcp_tool_sync",
            return_value='{"ok": true, "rows": []}',
        ):
            result = week05._collect_member_schedules(
                member_names=[],
                date_from="2026-07-29",
                date_to="2026-08-02",
                personal_schedules=personal_schedules,
            )

        self.assertEqual([row["title"] for row in result["rows"]], ["첫날", "마지막 날"])

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


if __name__ == "__main__":
    unittest.main()
