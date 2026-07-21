from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import patch

from pydantic import ValidationError

import student_parts.week03_build_nanas_logbook as week03
from student_parts.week02_structure_natural_language_requests import StructuredRequest


class DeleteStoreSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def delete_all_schedules(self) -> list[dict[str, Any]]:
        self.calls.append(("delete_all_schedules", {}))
        return []

    def delete_schedules_by_filter(self, **filters: Any) -> list[dict[str, Any]]:
        self.calls.append(("delete_schedules_by_filter", filters))
        return []


class Week01ToolStub:
    def __init__(self, result: Any) -> None:
        self.result = result

    def invoke(self, _arguments: dict[str, Any]) -> Any:
        return self.result


class UpdateStoreStub:
    def update_schedule(self, _schedule_id: str, **_updates: Any) -> None:
        return None


class SaveInputNormalizationTests(unittest.TestCase):
    def test_week02_bridge_wrapper_preserves_structured_request(self) -> None:
        bridge = {
            "ok": True,
            "tool_name": "extract_schedule_request",
            "base_date": "2026-07-19",
            "base_datetime": "2026-07-19T09:00:00+09:00",
            "structured_request": {
                "kind": "todo",
                "title": "과제 제출",
                "date": "2026-07-20",
                "original_text": "내일까지 과제 제출하기",
            },
        }

        result = week03._save_input_from(json.dumps(bridge, ensure_ascii=False))

        self.assertEqual(result.kind, "todo")
        self.assertEqual(result.title, "과제 제출")
        self.assertEqual(result.date, "2026-07-20")

    def test_legacy_payload_wrapper_is_supported_for_one_level(self) -> None:
        result = week03._save_input_from(
            {
                "payload": StructuredRequest(
                    kind="reminder",
                    title="약 복용",
                    original_text="저녁에 약 먹으라고 알려줘",
                )
            }
        )

        self.assertEqual(result.kind, "reminder")
        self.assertEqual(result.title, "약 복용")

    def test_structured_request_takes_precedence_over_payload(self) -> None:
        result = week03._save_input_from(
            {
                "structured_request": {"kind": "todo", "title": "우선 요청"},
                "payload": {"kind": "reminder", "title": "무시할 요청"},
            }
        )

        self.assertEqual(result.kind, "todo")
        self.assertEqual(result.title, "우선 요청")

    def test_unknown_extra_field_is_rejected_at_storage_boundary(self) -> None:
        with self.assertRaises(ValidationError):
            week03.SaveStructuredRequestInput.model_validate(
                {
                    "kind": "todo",
                    "title": "과제 제출",
                    "unexpected_metadata": True,
                }
            )

    def test_nested_wrapper_is_not_a_supported_input(self) -> None:
        with self.assertRaises(ValidationError):
            week03.SaveStructuredRequestInput.model_validate(
                {
                    "payload": {
                        "structured_request": {
                            "kind": "todo",
                            "title": "중첩 요청",
                        }
                    }
                }
            )

    def test_wrapper_value_must_be_an_object(self) -> None:
        with self.assertRaises(ValidationError):
            week03.SaveStructuredRequestInput.model_validate({"payload": "not-an-object"})


class SavedScheduleDeleteGuardTests(unittest.TestCase):
    def test_blank_conditions_do_not_call_store(self) -> None:
        cases = [
            {},
            {"schedule_ids": []},
            {"schedule_ids": [" ", "\t"]},
            {"date": ""},
            {"date": " ", "title": "\t", "start_time": "\n"},
        ]

        for arguments in cases:
            with self.subTest(arguments=arguments):
                store = DeleteStoreSpy()

                result = week03.delete_saved_schedules_dict(
                    app_store=store,
                    **arguments,
                )

                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], "delete_condition_required")
                self.assertIn("아무 일정도 삭제하지 않았습니다", result["message"])
                self.assertEqual(result["deleted_count"], 0)
                self.assertEqual(store.calls, [])

    def test_mixed_schedule_ids_pass_only_normalized_ids_to_store(self) -> None:
        store = DeleteStoreSpy()

        result = week03.delete_saved_schedules_dict(
            schedule_ids=[" ", " sch_1 ", "\tsch_2"],
            date=" ",
            app_store=store,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["filters"]["schedule_ids"], ["sch_1", "sch_2"])
        self.assertIsNone(result["filters"]["date"])
        self.assertEqual(
            store.calls,
            [
                (
                    "delete_schedules_by_filter",
                    {
                        "schedule_ids": ["sch_1", "sch_2"],
                        "date": None,
                        "title": None,
                        "start_time": None,
                        "time_unspecified": False,
                    },
                )
            ],
        )

    def test_text_filters_are_trimmed_before_store_call(self) -> None:
        store = DeleteStoreSpy()

        result = week03.delete_saved_schedules_dict(
            title="  주간 회의  ",
            start_time=" 10:00 ",
            app_store=store,
        )

        self.assertEqual(result["filters"]["title"], "주간 회의")
        self.assertEqual(result["filters"]["start_time"], "10:00")
        self.assertEqual(
            store.calls[0][1]["title"],
            "주간 회의",
        )
        self.assertEqual(
            store.calls[0][1]["start_time"],
            "10:00",
        )


class RecoverableToolFailureTests(unittest.TestCase):
    def _invoke_week03_personal_create_schedule(self) -> str:
        return week03.personal_create_schedule.invoke(
            {
                "title": "개인 코칭",
                "date": "2026-07-20",
                "start_time": "10:00",
                "end_time": "11:00",
                "attendees": [],
            }
        )

    def test_malformed_week01_json_returns_failure_envelope(self) -> None:
        with patch.object(
            week03,
            "week01_personal_create_schedule",
            Week01ToolStub("not-json"),
        ):
            raw_result = self._invoke_week03_personal_create_schedule()

        result = json.loads(raw_result)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_week01_result")
        self.assertIn("영속 저장을 진행하지 않았습니다", result["message"])
        self.assertIsNone(result["created_schedule"])
        self.assertIsNone(result["structured_request"])
        self.assertIsNone(result["sqlite_save"])
        self.assertIn("개인 일정 생성 결과", raw_result)

    def test_missing_created_schedule_returns_failure_envelope(self) -> None:
        with patch.object(
            week03,
            "week01_personal_create_schedule",
            Week01ToolStub(json.dumps({"ok": True, "tool_name": "personal_create_schedule"})),
        ):
            raw_result = self._invoke_week03_personal_create_schedule()

        result = json.loads(raw_result)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_week01_result")
        self.assertIn("다시 요청해 주세요", result["message"])

    def test_missing_update_target_has_machine_code_and_user_message(self) -> None:
        with patch.object(week03, "_store", return_value=UpdateStoreStub()):
            raw_result = week03.personal_update_saved_schedule.invoke(
                {
                    "schedule_id": "sch_missing",
                    "title": "변경할 제목",
                }
            )

        result = json.loads(raw_result)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "schedule_not_found")
        self.assertIn("수정하지 않았습니다", result["message"])
        self.assertIsNone(result["updated_schedule"])


if __name__ == "__main__":
    unittest.main()
