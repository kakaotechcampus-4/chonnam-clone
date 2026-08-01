from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fixed.app_store import AppSQLiteStore
from student_parts.schedule_clarification import ScheduleInputValidationError
from student_parts.week01_wake_up_nana import PERSONAL_SCHEDULES
from student_parts.week03_build_nanas_logbook import personal_create_schedule


class ScheduleErrorFlowE2ETest(unittest.TestCase):
    """Week 3 진입점부터 검증, 메모리, SQLite 저장까지 실제 경계를 검증합니다."""

    def setUp(self) -> None:
        PERSONAL_SCHEDULES.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = AppSQLiteStore(Path(self.temp_dir.name) / "app.db")

    def tearDown(self) -> None:
        PERSONAL_SCHEDULES.clear()
        self.temp_dir.cleanup()

    @patch("fixed.app_store.sync_personal_schedule_to_shared", return_value={"ok": True})
    def test_invalid_then_clarify_then_complete_and_persist(self, _sync) -> None:
        with patch("student_parts.week03_build_nanas_logbook._store", return_value=self.store):
            with self.assertRaises(ScheduleInputValidationError):
                personal_create_schedule.invoke(
                    {
                        "title": "치과",
                        "date": "2026-13-40",
                        "start_time": "25:70",
                        "end_time": "26:00",
                        "original_text": "13월 40일 25시 70분에 치과 일정 잡아줘",
                    }
                )

            clarification = json.loads(
                personal_create_schedule.invoke(
                    {
                        "title": "치과",
                        "date": "2026-08-03",
                        "start_time": "15:00",
                        "original_text": "8월 3일 오후 3시에 치과 일정 잡아줘",
                    }
                )
            )

            self.assertEqual(clarification["status"], "needs_clarification")
            self.assertEqual(clarification["missing_fields"], ["end_time"])
            self.assertEqual(PERSONAL_SCHEDULES, [])
            self.assertEqual(self.store.list_schedules(), [])

            completed = json.loads(
                personal_create_schedule.invoke(
                    {
                        **clarification["known_values"],
                        "end_time": "16:00",
                        "original_text": "오후 4시에 끝나",
                    }
                )
            )

        self.assertTrue(completed["ok"])
        self.assertEqual(completed["created_schedule"]["title"], "치과")
        self.assertEqual(len(PERSONAL_SCHEDULES), 1)

        saved = self.store.list_schedules()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["title"], "치과")
        self.assertEqual(saved[0]["date"], "2026-08-03")
        self.assertEqual(saved[0]["start_time"], "15:00")
        self.assertEqual(saved[0]["end_time"], "16:00")


if __name__ == "__main__":
    unittest.main()
