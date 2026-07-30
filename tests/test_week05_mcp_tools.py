from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fixed.mcp_client import call_local_mcp_tool_sync
from student_parts import week05_load_kanas_past_conversations as week05


class Week05MCPWrapperTests(unittest.TestCase):
    def test_search_previous_conversations_forwards_raw_arguments(self) -> None:
        expected = json.dumps(
            {
                "ok": True,
                "tool_name": "search_previous_conversations",
                "rows": [{"conversation_id": "ext_cs"}],
            },
            ensure_ascii=False,
        )

        with patch.object(week05, "call_mcp_tool_sync", return_value=expected) as call_mcp:
            actual = week05.search_previous_conversations.invoke(
                {"query": "API 연동", "member_names": [" 철수 "], "limit": 3}
            )

        self.assertEqual(actual, expected)
        call_mcp.assert_called_once_with(
            "search_previous_conversations",
            {"query": "API 연동", "member_names": [" 철수 "], "limit": 3},
        )

    def test_load_conversation_messages_keeps_payload_rows(self) -> None:
        payload = {
            "ok": True,
            "tool_name": "load_conversation_messages",
            "rows": [
                {
                    "sender": "철수",
                    "content": "API 연동 실습이 있어요.",
                    "created_at": "2026-07-01T10:00:00",
                }
            ],
        }

        with patch.object(
            week05, "call_external_tool_payload", return_value=payload
        ) as call_external:
            actual = week05.load_conversation_messages.invoke(
                {"conversation_id": "ext_cs"}
            )

        self.assertEqual(json.loads(actual), payload)
        call_external.assert_called_once_with(
            "load_conversation_messages", {"conversation_id": "ext_cs"}
        )

    def test_extract_schedules_from_history_forwards_arguments(self) -> None:
        expected = '{"ok": true, "rows": []}'

        with patch.object(week05, "call_mcp_tool_sync", return_value=expected) as call_mcp:
            actual = week05.extract_schedules_from_history.invoke(
                {
                    "member_names": ["영희"],
                    "date_from": "2026-07-07T00:00:00",
                    "date_to": "2026-07-10T23:59:59",
                }
            )

        self.assertEqual(actual, expected)
        call_mcp.assert_called_once_with(
            "extract_schedules_from_history",
            {
                "member_names": ["영희"],
                "date_from": "2026-07-07T00:00:00",
                "date_to": "2026-07-10T23:59:59",
            },
        )

    def test_list_shared_schedules_forwards_all_filters(self) -> None:
        expected = '{"ok": true, "rows": []}'

        with patch.object(week05, "call_mcp_tool_sync", return_value=expected) as call_mcp:
            actual = week05.list_shared_schedules.invoke(
                {
                    "member_names": ["철수"],
                    "date_from": "2026-07-07",
                    "date_to": "2026-07-17",
                    "source_conversation_id": "ext_cs",
                    "limit": 10,
                }
            )

        self.assertEqual(actual, expected)
        call_mcp.assert_called_once_with(
            "list_shared_schedules",
            {
                "member_names": ["철수"],
                "date_from": "2026-07-07",
                "date_to": "2026-07-17",
                "source_conversation_id": "ext_cs",
                "limit": 10,
            },
        )

    def test_collect_member_schedules_merges_personal_and_external_rows(self) -> None:
        personal_schedules = [
            {
                "title": "개인 코칭",
                "date": "2026-07-08",
                "start_time": "10:00",
                "end_time": "11:00",
                "notes": "내 일정",
            },
            {
                "title": "범위 밖 일정",
                "date": "2026-07-20",
                "start_time": "10:00",
                "end_time": "11:00",
            },
        ]
        external_row = {
            "member_name": "영희",
            "title": "디자인 피드백",
            "date": "2026-07-08",
            "start_time": "13:00",
            "end_time": "14:00",
            "notes": "",
        }
        mcp_payload = json.dumps(
            {
                "ok": True,
                "tool_name": "extract_schedules_from_history",
                "rows": [external_row],
            },
            ensure_ascii=False,
        )

        with (
            patch.object(
                week05,
                "_personal_schedules_for_current_scope",
                return_value=personal_schedules,
            ),
            patch.object(
                week05, "call_mcp_tool_sync", return_value=mcp_payload
            ) as call_mcp,
        ):
            actual = json.loads(
                week05.collect_member_schedules.invoke(
                    {
                        "member_names": ["영희"],
                        "date_from": "2026-07-07",
                        "date_to": "2026-07-10",
                    }
                )
            )

        self.assertTrue(actual["ok"])
        self.assertEqual(actual["tool_name"], "collect_member_schedules")
        self.assertEqual(len(actual["rows"]), 2)
        self.assertEqual(actual["rows"][0]["member_name"], "나")
        self.assertEqual(actual["rows"][1], external_row)
        self.assertIn("개인 코칭", actual["schedule_summary"])
        self.assertIn("디자인 피드백", actual["schedule_summary"])
        call_mcp.assert_called_once_with(
            "extract_schedules_from_history",
            {
                "member_names": ["영희"],
                "date_from": "2026-07-07",
                "date_to": "2026-07-10",
            },
        )

    def test_week05_tools_exposes_only_completed_week05_tools(self) -> None:
        tool_names = {item.name for item in week05.week05_tools()}

        self.assertTrue(
            {
                "search_previous_conversations",
                "load_conversation_messages",
                "extract_schedules_from_history",
                "list_shared_schedules",
                "collect_member_schedules",
            }.issubset(tool_names)
        )
        self.assertNotIn("create_shared_schedule", tool_names)
        self.assertNotIn("delete_shared_schedule", tool_names)


class Week05MCPIntegrationTests(unittest.TestCase):
    def test_wrapper_reaches_real_mcp_server_and_normalizes_at_store_boundary(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "external_people.sqlite3"

            def call_test_mcp(tool_name: str, args: dict[str, object]) -> str:
                return call_local_mcp_tool_sync(tool_name, args, db_path=db_path)

            with patch.object(week05, "call_mcp_tool_sync", side_effect=call_test_mcp):
                search_result = json.loads(
                    week05.search_previous_conversations.invoke(
                        {
                            "query": "API 연동",
                            "member_names": [" 철수 "],
                            "limit": 5,
                        }
                    )
                )
                schedule_result = json.loads(
                    week05.extract_schedules_from_history.invoke(
                        {
                            "member_names": [" 철수 "],
                            "date_from": "2026-07-07T00:00:00",
                            "date_to": "2026-07-09T23:59:59",
                        }
                    )
                )

        self.assertTrue(search_result["ok"])
        self.assertEqual(search_result["rows"][0]["conversation_id"], "ext_cs")
        self.assertIn("API 연동", search_result["rows"][0]["content"])

        self.assertTrue(schedule_result["ok"])
        self.assertEqual(
            [row["title"] for row in schedule_result["rows"]],
            ["API 연동 실습", "고객 인터뷰"],
        )
        self.assertTrue(
            all(row["member_name"] == "철수" for row in schedule_result["rows"])
        )


if __name__ == "__main__":
    unittest.main()
