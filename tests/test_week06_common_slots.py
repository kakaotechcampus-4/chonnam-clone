from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from student_parts.week06_kanamate_decides_schedule import (
    find_common_available_slots,
    find_common_available_slots_dict,
)


VALID_CANDIDATE = {
    "date": "2026-08-10",
    "start_time": "11:00",
    "end_time": "12:00",
    "duration_minutes": 60,
    "reason": "모든 멤버가 가능합니다.",
}

BUSY_ROWS = [
    {
        "member_name": "나",
        "title": "내 회의",
        "date": "2026-08-10",
        "start_time": "10:00",
        "end_time": "11:00",
    },
    {
        "member_name": "철수",
        "title": "외부 회의",
        "date": "2026-08-10",
        "start_time": "13:00",
        "end_time": "14:30",
        "source_conversation_id": "ext_cs",
    },
]


class Week06CommonSlotsCollectionTest(unittest.TestCase):
    @patch("student_parts.week06_kanamate_decides_schedule.find_common_available_slots_payload")
    @patch("student_parts.week06_kanamate_decides_schedule.collect_member_schedules")
    @patch("student_parts.week06_kanamate_decides_schedule.normalize_date_bound")
    @patch("student_parts.week06_kanamate_decides_schedule.normalize_external_member_names")
    def test_none_busy_rows_collects_once_with_normalized_values(
        self,
        normalize_names,
        normalize_date,
        collect,
        payload_helper,
    ):
        normalize_names.return_value = ["나", "철수", "철수"]
        normalize_date.side_effect = ["2026-08-10", "2026-08-12"]
        collect.invoke.return_value = json.dumps({"ok": True, "rows": BUSY_ROWS}, ensure_ascii=False)
        expected = {"ok": True, "candidate_slots": []}
        payload_helper.return_value = expected

        result = find_common_available_slots_dict(
            member_names=["나", " 철수 ", "철수"],
            date_from="2026-08-10T09:00:00+09:00",
            date_to="2026-08-12T18:00:00+09:00",
            candidate_slots=[VALID_CANDIDATE],
            llm_reason="후보 판단",
        )

        self.assertIs(result, expected)
        normalize_names.assert_called_once_with(["나", " 철수 ", "철수"])
        self.assertEqual(normalize_date.call_count, 2)
        collect.invoke.assert_called_once_with(
            {
                "member_names": ["철수"],
                "date_from": "2026-08-10",
                "date_to": "2026-08-12",
            }
        )
        payload_helper.assert_called_once_with(
            member_names=["나", "철수"],
            date_from="2026-08-10",
            date_to="2026-08-12",
            busy_rows=BUSY_ROWS,
            duration_minutes=60,
            workday_start="09:00",
            workday_end="18:00",
            limit=5,
            candidate_slots=[VALID_CANDIDATE],
            llm_reason="후보 판단",
        )

    @patch("student_parts.week06_kanamate_decides_schedule.collect_member_schedules")
    def test_explicit_empty_busy_rows_does_not_collect(self, collect):
        result = find_common_available_slots_dict(
            member_names=["철수"],
            date_from="2026-08-10",
            date_to="2026-08-12",
            busy_rows=[],
            candidate_slots=[VALID_CANDIDATE],
        )

        collect.invoke.assert_not_called()
        self.assertEqual(result["members"], ["나", "철수"])
        self.assertEqual(result["candidate_slots"], [VALID_CANDIDATE])

    @patch("student_parts.week06_kanamate_decides_schedule.collect_member_schedules")
    def test_invalid_collection_json_is_not_treated_as_empty_success(self, collect):
        collect.invoke.return_value = "not-json"
        with self.assertRaises(json.JSONDecodeError):
            find_common_available_slots_dict(
                member_names=["철수"],
                date_from="2026-08-10",
                date_to="2026-08-12",
            )

    @patch("student_parts.week06_kanamate_decides_schedule.collect_member_schedules")
    def test_failed_collection_payload_is_not_treated_as_empty_success(self, collect):
        collect.invoke.return_value = json.dumps(
            {"ok": False, "error": "external lookup failed"}
        )

        with self.assertRaisesRegex(RuntimeError, "external lookup failed"):
            find_common_available_slots_dict(
                member_names=["철수"],
                date_from="2026-08-10",
                date_to="2026-08-12",
            )


class Week06CommonSlotsValidationTest(unittest.TestCase):
    def test_valid_candidate_and_touching_boundaries_are_kept(self):
        candidates = [
            VALID_CANDIDATE,
            {
                "date": "2026-08-10",
                "start_time": "09:00",
                "end_time": "10:00",
                "duration_minutes": 60,
                "reason": "busy 시작 직전",
            },
            {
                "date": "2026-08-10",
                "start_time": "14:30",
                "end_time": "15:30",
                "duration_minutes": 60,
                "reason": "busy 종료 직후",
            },
        ]

        result = find_common_available_slots_dict(
            member_names=["철수"],
            date_from="2026-08-10",
            date_to="2026-08-12",
            busy_rows=BUSY_ROWS,
            candidate_slots=candidates,
        )

        self.assertEqual(result["candidate_slots"], candidates)
        self.assertEqual(result["busy_rows"][1]["source_conversation_id"], "ext_cs")

    def test_overlap_out_of_range_outside_workday_and_short_slots_are_rejected(self):
        candidates = [
            {
                "date": "2026-08-10",
                "start_time": "10:30",
                "end_time": "11:30",
                "duration_minutes": 60,
                "reason": "겹침",
            },
            {
                "date": "2026-08-13",
                "start_time": "11:00",
                "end_time": "12:00",
                "duration_minutes": 60,
                "reason": "범위 밖",
            },
            {
                "date": "2026-08-11",
                "start_time": "08:00",
                "end_time": "09:00",
                "duration_minutes": 60,
                "reason": "업무시간 밖",
            },
            {
                "date": "2026-08-11",
                "start_time": "11:00",
                "end_time": "11:30",
                "duration_minutes": 30,
                "reason": "너무 짧음",
            },
        ]

        result = find_common_available_slots_dict(
            member_names=["철수"],
            date_from="2026-08-10",
            date_to="2026-08-12",
            duration_minutes=60,
            busy_rows=BUSY_ROWS,
            candidate_slots=candidates,
        )

        self.assertEqual(result["candidate_slots"], [])

    def test_limit_applies_to_valid_candidates(self):
        candidates = [
            {
                "date": "2026-08-11",
                "start_time": f"{hour:02d}:00",
                "end_time": f"{hour + 1:02d}:00",
                "duration_minutes": 60,
                "reason": str(hour),
            }
            for hour in (9, 10, 11)
        ]
        result = find_common_available_slots_dict(
            member_names=["철수"],
            date_from="2026-08-10",
            date_to="2026-08-12",
            limit=2,
            busy_rows=BUSY_ROWS,
            candidate_slots=candidates,
        )

        self.assertEqual(len(result["candidate_slots"]), 2)

    def test_langchain_tool_returns_korean_json_contract(self):
        payload = json.loads(
            find_common_available_slots.invoke(
                {
                    "member_names": ["철수"],
                    "date_from": "2026-08-10",
                    "date_to": "2026-08-12",
                    "busy_rows": BUSY_ROWS,
                    "candidate_slots": [VALID_CANDIDATE],
                    "llm_reason": "한국어 판단",
                }
            )
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tool_name"], "find_common_available_slots")
        self.assertEqual(payload["members"], ["나", "철수"])
        self.assertEqual(payload["candidate_slots"][0]["reason"], VALID_CANDIDATE["reason"])
        self.assertEqual(payload["llm_reason"], "한국어 판단")


if __name__ == "__main__":
    unittest.main()
