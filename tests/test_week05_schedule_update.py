from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from student_parts.week02_structure_natural_language_requests import StructuredRequest
from student_parts import week05_load_kanas_past_conversations as week05


class Week05ScheduleUpdateRegressionTest(unittest.TestCase):
    """공지의 Week 5 일정 수집 변경을 고정하는 회귀 테스트입니다."""

    @patch("student_parts.week05_load_kanas_past_conversations.AppSQLiteStore")
    def test_tc01_group_schedule_is_not_omitted(self, store_class):
        """TC-01: 앱 DB의 그룹 일정도 내 busy-time에 포함된다."""

        group_schedule = {
            "schedule_id": "group-harin",
            "request_kind": "group_schedule",
            "title": "사전 미팅",
            "date": "2026-07-14",
            "start_time": "15:00",
            "end_time": "16:00",
            "attendees": ["하린"],
        }
        store = Mock()
        store.list_schedules.return_value = [group_schedule]
        store_class.return_value = store

        schedules = week05._personal_schedules_for_current_scope()
        result = week05._collect_member_schedules(
            member_names=[],
            date_from="2026-07-14",
            date_to="2026-07-14",
            personal_schedules=schedules,
        )

        store.list_schedules.assert_called_once_with(limit=200)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["title"], "사전 미팅")
        self.assertEqual(
            result["rows"][0]["notes"],
            "Nana 그룹 일정 · 참석자: 하린",
        )

    def test_tc02_personal_schedule_keeps_existing_behavior(self):
        """TC-02: 개인 일정은 기존처럼 내 busy-time으로 수집된다."""

        result = week05._collect_member_schedules(
            member_names=[],
            date_from="2026-07-14",
            date_to="2026-07-14",
            personal_schedules=[
                {
                    "schedule_id": "personal-hospital",
                    "request_kind": "personal_schedule",
                    "title": "병원 방문",
                    "date": "2026-07-14",
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "attendees": [],
                }
            ],
        )

        self.assertEqual(
            result["rows"],
            [
                {
                    "member_name": "나",
                    "title": "병원 방문",
                    "date": "2026-07-14",
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "members": [],
                    "notes": "Nana 개인 일정",
                }
            ],
        )

    def test_tc04_same_schedule_from_two_sources_is_deduplicated(self):
        """TC-04: 괄호·종료 시각 표현이 달라도 같은 일정은 하나만 남는다."""

        app_row = {
            "member_name": "나",
            "date": "2026-07-14",
            "start_time": "15:00",
            "end_time": "18:00",
            "title": "팀 회의 (온라인)",
            "notes": "Nana 개인 일정",
        }
        shared_row = {
            "member_name": "나",
            "date": "2026-07-14",
            "start_time": "15:00",
            "end_time": "미정",
            "title": "팀 회의",
            "notes": "앱 개인 일정 자동 동기화",
        }

        result = week05._dedupe_schedule_rows([app_row, shared_row])

        self.assertEqual(result, [app_row])

    def test_tc07_distinct_schedules_are_preserved(self):
        """TC-07: 날짜, 시작 시각, 제목, 멤버가 다르면 별도 일정으로 남는다."""

        rows = [
            {
                "member_name": "나",
                "date": "2026-07-14",
                "start_time": "15:00",
                "title": "팀 회의",
            },
            {
                "member_name": "나",
                "date": "2026-07-14",
                "start_time": "16:00",
                "title": "팀 회의",
            },
            {
                "member_name": "나",
                "date": "2026-07-15",
                "start_time": "15:00",
                "title": "팀 회의",
            },
            {
                "member_name": "민준",
                "date": "2026-07-14",
                "start_time": "15:00",
                "title": "팀 회의",
            },
        ]

        self.assertEqual(week05._dedupe_schedule_rows(rows), rows)

    def test_tc08_notes_distinguish_personal_and_group_schedules(self):
        """TC-08: notes가 개인·그룹 일정과 그룹 참석자를 구분한다."""

        cases = [
            ("personal_schedule", [], "Nana 개인 일정"),
            ("group_schedule", ["하린"], "Nana 그룹 일정 · 참석자: 하린"),
            (
                "group_schedule",
                ["하린", "민준"],
                "Nana 그룹 일정 · 참석자: 하린, 민준",
            ),
            ("group_schedule", [], "Nana 그룹 일정"),
        ]

        for kind, members, expected in cases:
            with self.subTest(kind=kind, members=members):
                request = StructuredRequest(kind=kind, members=members)
                self.assertEqual(week05._my_schedule_notes(request), expected)

    @patch(
        "student_parts.week05_load_kanas_past_conversations.call_mcp_tool_sync",
        return_value=json.dumps({"ok": True, "rows": []}),
    )
    def test_tc09_me_appears_once_in_members(self, call_mcp):
        """TC-09: 요청 멤버에 '나'가 있어도 반환 members에는 한 번만 들어간다."""

        result = week05._collect_member_schedules(
            member_names=["나", "민준"],
            date_from="2026-07-14",
            date_to="2026-07-14",
            personal_schedules=[],
        )

        self.assertEqual(result["members"], ["나", "민준"])
        self.assertEqual(result["members"].count("나"), 1)
        call_mcp.assert_called_once()

    def test_tc10_legacy_row_without_request_kind_is_personal(self):
        """TC-10: request_kind가 없는 기존 row는 개인 일정으로 호환 처리한다."""

        request = week05._structured_request_from_schedule_row(
            {
                "title": "과제 제출",
                "date": "2026-07-14",
                "start_time": "17:00",
                "end_time": "18:00",
            }
        )

        self.assertEqual(request.kind, "personal_schedule")

    def test_tc11_collection_payload_contract_is_unchanged(self):
        """TC-11: 수집 결과는 기존 5개 payload key 계약을 유지한다."""

        result = week05._collect_member_schedules(
            member_names=[],
            date_from="2026-07-14",
            date_to="2026-07-14",
            personal_schedules=[],
        )

        self.assertEqual(
            set(result),
            {"ok", "tool_name", "members", "rows", "schedule_summary"},
        )
        self.assertIs(result["ok"], True)
        self.assertEqual(result["tool_name"], "collect_member_schedules")
        self.assertIsInstance(result["members"], list)
        self.assertIsInstance(result["rows"], list)
        self.assertIsInstance(result["schedule_summary"], str)


if __name__ == "__main__":
    unittest.main()
