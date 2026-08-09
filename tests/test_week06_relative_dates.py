from __future__ import annotations

import unittest
from datetime import date, timedelta

from fixed.runtime_clock import current_app_date_iso
from student_parts import week06_kanamate_decides_schedule as week06


class Week06RelativeDatePromptTests(unittest.TestCase):
    def test_kana_prompt_defines_next_week_from_monday_to_sunday(self) -> None:
        today = date.fromisoformat(current_app_date_iso())
        next_monday = today + timedelta(days=7 - today.weekday())
        next_sunday = next_monday + timedelta(days=6)

        prompt = week06.kana_system_prompt()

        self.assertIn(f"오늘 날짜는 {today.isoformat()}이다", prompt)
        self.assertIn(
            f"'다음 주'는 {next_monday.isoformat()}부터 {next_sunday.isoformat()}까지다",
            prompt,
        )
        self.assertIn("사용자에게 구체적인 날짜를 되묻지 않는다", prompt)
        self.assertIn("date_from과 date_to", prompt)
        self.assertIn("반드시 collect_member_schedules를 사용", prompt)
        self.assertIn("extract_schedules_from_history만으로 답하지 않는다", prompt)

    def test_kana_tools_excludes_unimplemented_schedule_request_bridge(self) -> None:
        self.assertNotIn("extract_schedule_request", week06.agent_tool_names("kana_agent"))


if __name__ == "__main__":
    unittest.main()
