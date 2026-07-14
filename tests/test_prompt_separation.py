from __future__ import annotations

import unittest

from student_parts.week01_wake_up_nana import week01_system_prompt
from student_parts.week02_structure_natural_language_requests import week02_system_prompt


class PromptSeparationTest(unittest.TestCase):
    def test_week01_keeps_crud_specific_policies(self):
        prompt = week01_system_prompt()

        self.assertIn("personal_delete_schedule", prompt)
        self.assertIn("자정을 넘기는 일정", prompt)

    def test_week02_excludes_week01_delete_and_overnight_policies(self):
        prompt = week02_system_prompt()

        self.assertNotIn("personal_delete_schedule", prompt)
        self.assertNotIn("자정을 넘기는 일정", prompt)

    def test_week02_keeps_clarification_and_structured_output_policies(self):
        prompt = week02_system_prompt()

        self.assertIn('status="needs_clarification"', prompt)
        self.assertIn("clarification_question", prompt)
        self.assertIn("StructuredRequestBatch", prompt)
        self.assertIn("personal_create_schedule", prompt)


if __name__ == "__main__":
    unittest.main()
