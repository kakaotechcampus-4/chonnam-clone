from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fixed.app_store import AppSQLiteStore
from student_parts.week03_build_nanas_logbook import (
    _persist_structured_request,
    personal_create_schedule,
    structured_request_from_week01_schedule,
)


class Week03OriginalTextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = AppSQLiteStore(Path(self.temp_dir.name) / "app.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_week01_schedule_conversion_keeps_only_user_text(self):
        schedule = {
            "id": "personal_test",
            "title": "병원",
            "date": "2026-07-20",
            "start_time": "15:00",
            "end_time": "미정",
            "attendees": [],
            "created_at": "2026-07-19T10:00:00+09:00",
            "session_id": "session-internal",
        }

        result = structured_request_from_week01_schedule(
            schedule,
            original_text="내일 오후 3시에 병원 일정 잡아줘",
        )

        self.assertEqual(result.original_text, "내일 오후 3시에 병원 일정 잡아줘")
        self.assertEqual(result.source_schedule_id, "personal_test")
        self.assertNotIn("session_id", result.original_text)
        self.assertNotIn("created_at", result.original_text)

    @patch("fixed.app_store.sync_personal_schedule_to_shared", return_value={"ok": True})
    def test_common_persistence_keeps_original_text_and_is_idempotent(self, _sync):
        request = structured_request_from_week01_schedule(
            {
                "id": "personal_same",
                "title": "병원",
                "date": "2026-07-20",
                "start_time": "15:00",
                "end_time": "미정",
                "attendees": [],
            },
            original_text="내일 오후 3시에 병원 일정 잡아줘",
        )

        first = _persist_structured_request(request, store=self.store)
        second = _persist_structured_request(request, store=self.store)
        saved = self.store.get_saved_request(first["request_id"])
        raw = json.loads(saved["raw_json"])

        self.assertEqual(raw["original_text"], "내일 오후 3시에 병원 일정 잡아줘")
        self.assertEqual(raw["source_schedule_id"], "personal_same")
        self.assertTrue(second["already_exists"])
        self.assertEqual(len(self.store.list_schedules()), 1)

    @patch("fixed.app_store.sync_personal_schedule_to_shared", return_value={"ok": True})
    def test_personal_create_schedule_passes_original_text_to_sqlite(self, _sync):
        original_text = "7월 21일 오전 9시에 치과 일정 잡아줘"

        with patch("student_parts.week03_build_nanas_logbook._store", return_value=self.store):
            result = json.loads(
                personal_create_schedule.invoke(
                    {
                        "title": "치과",
                        "date": "2026-07-21",
                        "start_time": "09:00",
                        "original_text": original_text,
                    }
                )
            )

        request_id = result["sqlite_save"]["request_id"]
        raw = json.loads(self.store.get_saved_request(request_id)["raw_json"])
        self.assertEqual(raw["original_text"], original_text)
        self.assertNotIn("session_id", raw["original_text"])
        self.assertEqual(raw["source_schedule_id"], result["created_schedule"]["id"])


if __name__ == "__main__":
    unittest.main()
