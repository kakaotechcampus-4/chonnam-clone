from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

import student_parts.week06_kanamate_decides_schedule as week06


class CommonAvailableSlotTests(unittest.TestCase):
    def test_description_makes_kana_choose_candidates_before_validation(self) -> None:
        description = week06.FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION

        self.assertIn("대신 계산하는 도구가 아니라", description)
        self.assertIn("collect_member_schedules", description)
        self.assertIn("date(YYYY-MM-DD)", description)
        self.assertIn("busy_rows", description)
        self.assertIn("decide_final_slot", description)

    def test_helper_collects_normalized_busy_rows_and_filters_invalid_candidates(self) -> None:
        collected = {
            "ok": True,
            "tool_name": "collect_member_schedules",
            "members": ["나", "철수"],
            "rows": [
                {
                    "member_name": "나",
                    "title": "기존 회의",
                    "date": "2026-08-06",
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "notes": "Nana 개인 일정",
                }
            ],
            "schedule_summary": "기존 회의 1건",
        }
        candidates = [
            {
                "date": "2026-08-06",
                "start_time": "11:00",
                "end_time": "12:00",
                "duration_minutes": 60,
                "reason": "기존 회의 직후",
            },
            {
                "date": "2026-08-06",
                "start_time": "10:30",
                "end_time": "11:30",
                "duration_minutes": 60,
                "reason": "기존 회의와 겹침",
            },
            {
                "date": "2026-08-07",
                "start_time": "11:00",
                "end_time": "12:00",
                "duration_minutes": 60,
                "reason": "날짜 범위 밖",
            },
            {
                "date": "2026-08-06",
                "start_time": "08:00",
                "end_time": "09:00",
                "duration_minutes": 60,
                "reason": "업무 시간 밖",
            },
        ]

        collect = Mock()
        collect.invoke.return_value = json.dumps(collected, ensure_ascii=False)
        with patch.object(week06, "collect_member_schedules", collect):
            result = week06.find_common_available_slots_dict(
                member_names=[" 철수 ", ""],
                date_from="2026-08-06T00:00:00+09:00",
                date_to="2026-08-06T23:59:59+09:00",
                busy_rows=None,
                candidate_slots=candidates,
                llm_reason="busy rows를 비교함",
            )

        collect.invoke.assert_called_once_with(
            {
                "member_names": ["철수"],
                "date_from": "2026-08-06",
                "date_to": "2026-08-06",
            }
        )
        self.assertEqual(result["members"], ["나", "철수"])
        self.assertEqual(result["busy_rows"], collected["rows"])
        self.assertEqual(len(result["candidate_slots"]), 1)
        self.assertEqual(result["candidate_slots"][0]["start_time"], "11:00")
        self.assertEqual(result["slot_source"], "llm")
        self.assertEqual(result["llm_reason"], "busy rows를 비교함")

    def test_explicit_busy_rows_skip_collection_and_include_me_once(self) -> None:
        collect = Mock()
        with patch.object(week06, "collect_member_schedules", collect):
            result = week06.find_common_available_slots_dict(
                member_names=["나", "민준"],
                date_from="2026-08-06",
                date_to="2026-08-06",
                busy_rows=[],
                candidate_slots=[],
            )

        collect.invoke.assert_not_called()
        self.assertEqual(result["members"], ["나", "민준"])
        self.assertEqual(result["busy_rows"], [])

    def test_unspecified_busy_time_blocks_the_whole_day(self) -> None:
        result = week06.find_common_available_slots_dict(
            member_names=["민준"],
            date_from="2026-08-06",
            date_to="2026-08-06",
            busy_rows=[
                {
                    "member_name": "나",
                    "date": "2026-08-06",
                    "start_time": None,
                    "end_time": None,
                }
            ],
            candidate_slots=[
                {
                    "date": "2026-08-06",
                    "start_time": "14:00",
                    "end_time": "15:00",
                    "duration_minutes": 60,
                    "reason": "오후 후보",
                }
            ],
        )

        self.assertEqual(result["candidate_slots"], [])

    def test_malformed_collection_payloads_fail_instead_of_looking_empty(self) -> None:
        malformed_payloads = [
            ("not JSON", "invalid JSON"),
            ("[]", "non-object payload"),
            ('{"ok": false, "rows": []}', "failed collection"),
            ('{"ok": true}', "non-list rows field"),
            ('{"ok": true, "rows": {}}', "non-list rows field"),
            ('{"ok": true, "rows": [1]}', "non-object row"),
        ]

        for payload, expected_error in malformed_payloads:
            with self.subTest(payload=payload):
                collect = Mock()
                collect.invoke.return_value = payload
                with patch.object(week06, "collect_member_schedules", collect):
                    with self.assertRaisesRegex(RuntimeError, expected_error):
                        week06.find_common_available_slots_dict(
                            member_names=["철수"],
                            date_from="2026-08-06",
                            date_to="2026-08-06",
                        )

    def test_public_tool_returns_unescaped_korean_json(self) -> None:
        raw_result = week06.find_common_available_slots.invoke(
            {
                "member_names": ["철수"],
                "date_from": "2026-08-06",
                "date_to": "2026-08-06",
                "busy_rows": [],
                "candidate_slots": [
                    {
                        "date": "2026-08-06",
                        "start_time": "14:00",
                        "end_time": "15:00",
                        "duration_minutes": 60,
                        "reason": "모두 가능한 시간",
                    }
                ],
                "llm_reason": "일정을 비교함",
            }
        )

        self.assertNotIn("\\u", raw_result)
        payload = json.loads(raw_result)
        self.assertEqual(payload["tool_name"], "find_common_available_slots")
        self.assertEqual(payload["candidate_slots"][0]["reason"], "모두 가능한 시간")


if __name__ == "__main__":
    unittest.main()
