from __future__ import annotations

import unittest

from pydantic import ValidationError

from student_parts.schedule_clarification import (
    clarification_question,
    validate_schedule_input,
)
from student_parts.week02_structure_natural_language_requests import Week02Response, Week02ResponseAgent


class _FakeAgent:
    def __init__(self, response):
        self.response = response

    def invoke(self, payload, *args, **kwargs):
        return {"structured_response": self.response, **payload}

    def stream(self, payload, *args, **kwargs):
        yield {"model": {"structured_response": self.response}}


class ScheduleClarificationTest(unittest.TestCase):
    def test_common_validation_reports_missing_and_invalid_fields(self):
        result = validate_schedule_input("", "2026-13-40", "25:70")

        self.assertEqual(result["missing_fields"], ["title"])
        self.assertEqual(set(result["invalid_fields"]), {"date", "start_time"})
        self.assertIsNotNone(clarification_question(result))

    def test_week02_clarification_is_exposed_as_a_question(self):
        agent = Week02ResponseAgent(
            _FakeAgent(
                {
                    "status": "needs_clarification",
                    "clarification_question": "회의는 몇 시에 시작하나요?",
                    "missing_fields": ["start_time"],
                    "structured_request": None,
                }
            )
        )

        result = agent.invoke({"messages": []})

        self.assertNotIn("structured_response", result)
        self.assertEqual(result["messages"][0]["content"], "회의는 몇 시에 시작하나요?")

    def test_week02_complete_response_exposes_original_batch(self):
        agent = Week02ResponseAgent(
            _FakeAgent(
                {
                    "status": "complete",
                    "clarification_question": None,
                    "missing_fields": [],
                    "structured_request": {
                        "requests": [{"kind": "personal_schedule", "title": "회의"}],
                        "base_date": "2026-07-12",
                    },
                }
            )
        )

        result = agent.invoke({"messages": []})

        self.assertEqual(result["structured_response"].requests[0].title, "회의")
        self.assertEqual(result["structured_response"].base_date, "2026-07-12")

    def test_week02_stream_translates_nested_structured_response(self):
        agent = Week02ResponseAgent(
            _FakeAgent(
                {
                    "status": "needs_clarification",
                    "clarification_question": "날짜는 언제인가요?",
                    "missing_fields": ["date"],
                    "structured_request": None,
                }
            )
        )

        chunks = list(agent.stream({"messages": []}, stream_mode="updates"))

        self.assertEqual(chunks[0]["messages"][0]["content"], "날짜는 언제인가요?")

    def test_week02_clarification_requires_llm_question(self):
        with self.assertRaises(ValidationError):
            Week02Response.model_validate(
                {
                    "status": "needs_clarification",
                    "clarification_question": None,
                    "missing_fields": ["date"],
                    "structured_request": None,
                }
            )

    def test_week02_complete_rejects_clarification_fields(self):
        with self.assertRaises(ValidationError):
            Week02Response.model_validate(
                {
                    "status": "complete",
                    "clarification_question": "날짜는 언제인가요?",
                    "missing_fields": ["date"],
                    "structured_request": {
                        "requests": [{"kind": "personal_schedule", "title": "회의"}],
                        "base_date": "2026-07-12",
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
