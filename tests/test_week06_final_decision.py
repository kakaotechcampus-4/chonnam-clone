from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from student_parts.week06_kanamate_decides_schedule import decide_final_slot


CANDIDATES = [
    {
        "date": "2026-08-10",
        "start_time": "11:00",
        "end_time": "12:00",
        "duration_minutes": 60,
        "reason": "첫 후보",
    },
    {
        "date": "2026-08-11",
        "start_time": "15:00",
        "end_time": "16:00",
        "duration_minutes": 60,
        "reason": "두 번째 후보",
    },
]


class Week06FinalDecisionTest(unittest.TestCase):
    def test_selected_index_resolves_slot_and_preserves_evidence(self):
        busy_rows = [{"member_name": "철수", "date": "2026-08-10"}]
        payload = json.loads(
            decide_final_slot.invoke(
                {
                    "candidate_slots": CANDIDATES,
                    "selected_index": 1,
                    "final_slot": "2026-08-11 15:00-16:00",
                    "needs_agent_selection": False,
                    "member_names": ["나", "철수"],
                    "date_from": "2026-08-10T00:00:00+09:00",
                    "date_to": "2026-08-12T23:59:59+09:00",
                    "reason": "두 번째 후보 선택",
                    "busy_rows": busy_rows,
                }
            )
        )

        self.assertEqual(payload["final_slot"], "2026-08-11 15:00-16:00")
        self.assertFalse(payload["needs_agent_selection"])
        self.assertEqual(payload["selected_index"], 1)
        self.assertEqual(payload["selected_slot"], CANDIDATES[1])
        self.assertEqual(payload["members"], ["나", "철수"])
        self.assertEqual(payload["date_from"], "2026-08-10")
        self.assertEqual(payload["date_to"], "2026-08-12")
        self.assertEqual(payload["busy_rows"], busy_rows)
        self.assertEqual(payload["candidate_slots"], CANDIDATES)

    def test_selected_slot_without_final_text_is_rendered(self):
        payload = json.loads(
            decide_final_slot.invoke(
                {
                    "candidate_slots": CANDIDATES,
                    "selected_slot": CANDIDATES[0],
                }
            )
        )

        self.assertEqual(payload["final_slot"], "2026-08-10 11:00-12:00")
        self.assertFalse(payload["needs_agent_selection"])
        self.assertEqual(payload["reason"], "첫 후보")

    def test_candidates_without_selection_are_not_auto_selected(self):
        payload = json.loads(
            decide_final_slot.invoke({"candidate_slots": CANDIDATES})
        )

        self.assertIsNone(payload["final_slot"])
        self.assertTrue(payload["needs_agent_selection"])
        self.assertEqual(len(payload["candidates"]), 2)

    def test_no_candidates_remains_unselected(self):
        payload = json.loads(decide_final_slot.invoke({"candidate_slots": []}))

        self.assertIsNone(payload["final_slot"])
        self.assertTrue(payload["needs_agent_selection"])
        self.assertEqual(payload["candidates"], [])
        self.assertIn("찾지 못했습니다", payload["reason"])

    def test_out_of_range_index_does_not_select(self):
        payload = json.loads(
            decide_final_slot.invoke(
                {"candidate_slots": CANDIDATES, "selected_index": 9}
            )
        )

        self.assertIsNone(payload["final_slot"])
        self.assertTrue(payload["needs_agent_selection"])
        self.assertIn("범위를 벗어났습니다", payload["reason"])

    @patch("student_parts.week06_kanamate_decides_schedule.create_agent")
    @patch("student_parts.week06_kanamate_decides_schedule.chat_model")
    def test_decision_tool_does_not_create_nested_model_or_agent(self, model, create):
        decide_final_slot.invoke(
            {"candidate_slots": CANDIDATES, "selected_index": 0}
        )

        model.assert_not_called()
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
