from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
