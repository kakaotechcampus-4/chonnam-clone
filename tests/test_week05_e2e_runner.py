from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "tests/e2e/week05_mcp/run_scenarios.py"
SCENARIOS_PATH = REPO_ROOT / "tests/e2e/week05_mcp/scenarios.json"
UPDATE_SCENARIOS_PATH = (
    REPO_ROOT / "tests/e2e/week05_mcp/schedule_update_scenarios.json"
)

SPEC = importlib.util.spec_from_file_location("week05_e2e_runner", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"E2E runner를 import할 수 없습니다: {RUNNER_PATH}")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class Week05E2ERunnerTest(unittest.TestCase):
    def test_collect_result_check_supports_update_regression_contracts(self):
        events = [
            {
                "event": "tool_result",
                "tool_name": "collect_member_schedules",
                "content": {
                    "ok": True,
                    "tool_name": "collect_member_schedules",
                    "members": ["나", "민준"],
                    "rows": [
                        {
                            "member_name": "나",
                            "title": "팀 회의 (온라인)",
                            "date": "2026-08-23",
                            "start_time": "15:00",
                            "end_time": "미정",
                            "notes": "Nana 개인 일정",
                        }
                    ],
                    "schedule_summary": "- 나 | 팀 회의 | 2026-08-23 15:00-미정",
                },
            }
        ]
        matching_spec = {
            "exact_payload_keys": [
                "ok",
                "tool_name",
                "members",
                "rows",
                "schedule_summary",
            ],
            "expected_members": ["나", "민준"],
            "exact_row_count": 1,
            "rows_must_include": [
                {"member_name": "나", "title": "팀 회의 (온라인)"}
            ],
        }

        self.assertEqual(
            RUNNER._check_collect_member_schedules_rows(matching_spec, events),
            [],
        )
        self.assertTrue(
            RUNNER._check_collect_member_schedules_rows(
                {**matching_spec, "exact_row_count": 2},
                events,
            )
        )
        self.assertTrue(
            RUNNER._check_collect_member_schedules_rows(
                {**matching_spec, "expected_members": ["나", "나", "민준"]},
                events,
            )
        )

    def test_exact_tool_calls_reject_extra_calls(self):
        self.assertEqual(
            RUNNER._check_tool_calls_exact(
                ["search_previous_conversations", "extract_schedules_from_history"],
                ["search_previous_conversations", "extract_schedules_from_history"],
            ),
            [],
        )
        self.assertTrue(
            RUNNER._check_tool_calls_exact(
                ["search_previous_conversations", "extract_schedules_from_history"],
                [
                    "personal_list_saved_schedules",
                    "search_previous_conversations",
                    "extract_schedules_from_history",
                ],
            )
        )

    def test_tool_call_argument_check_uses_partial_expected_arguments(self):
        events = [
            {
                "event": "tool_call",
                "tool_name": "extract_schedules_from_history",
                "arguments": {
                    "member_names": ["철수"],
                    "date_from": "2026-07-09",
                    "date_to": "2026-07-09",
                },
            }
        ]
        matching_spec = [
            {
                "tool_name": "extract_schedules_from_history",
                "arguments": {"member_names": ["철수"], "date_from": "2026-07-09"},
            }
        ]
        wrong_spec = [
            {
                "tool_name": "extract_schedules_from_history",
                "arguments": {"member_names": ["영희"]},
            }
        ]

        self.assertEqual(RUNNER._check_tool_call_arguments(matching_spec, events), [])
        self.assertTrue(RUNNER._check_tool_call_arguments(wrong_spec, events))

        multi_member_events = [
            {
                "event": "tool_call",
                "tool_name": "extract_schedules_from_history",
                "arguments": {"member_names": ["영희", "철수"]},
            }
        ]
        multi_member_spec = [
            {
                "tool_name": "extract_schedules_from_history",
                "arguments": {"member_names": ["철수", "영희"]},
            }
        ]
        self.assertEqual(
            RUNNER._check_tool_call_arguments(multi_member_spec, multi_member_events),
            [],
        )

    def test_load_conversation_id_must_come_from_extract_result(self):
        base_events = [
            {
                "event": "tool_result",
                "tool_name": "extract_schedules_from_history",
                "content": {
                    "rows": [
                        {
                            "member_name": "철수",
                            "source_conversation_id": "ext_cs",
                        }
                    ]
                },
            }
        ]
        valid_events = [
            *base_events,
            {
                "event": "tool_call",
                "tool_name": "load_conversation_messages",
                "arguments": {"conversation_id": "ext_cs"},
            },
        ]
        invalid_events = [
            *base_events,
            {
                "event": "tool_call",
                "tool_name": "load_conversation_messages",
                "arguments": {"conversation_id": "invented"},
            },
        ]

        self.assertEqual(RUNNER._check_load_uses_extract_source_id(valid_events), [])
        self.assertTrue(RUNNER._check_load_uses_extract_source_id(invalid_events))

    def test_scenarios_use_exact_calls_and_consistent_no_match_flow(self):
        scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
        by_id = {scenario["id"]: scenario for scenario in scenarios}
        self.assertEqual(
            set(by_id),
            {
                "general-external-schedule-lookup",
                "schedule-lookup-with-source-evidence",
                "no-match-external-search",
                "integrate-personal-and-external-schedules",
                "external-only-with-personal-negation",
                "personal-saved-schedule-stays-in-app",
                "registered-shared-schedule-uses-shared-store",
                "missing-date-range-external-lookup",
                "missing-member-name-external-lookup",
                "missing-date-range-then-followup-provides-it",
                "mixed-schedule-paraphrase-uses-collector",
                "unknown-personal-end-time-is-collected-as-undecided",
            },
        )
        for scenario in scenarios:
            for turn in scenario["turns"]:
                if scenario["id"] == "unknown-personal-end-time-is-collected-as-undecided":
                    self.assertTrue(
                        "expect_tool_calls_exact" in turn or "expect_tool_called" in turn
                    )
                else:
                    self.assertIn("expect_tool_calls_exact", turn)

        general = by_id["general-external-schedule-lookup"]["turns"][0]
        self.assertEqual(
            general["expect_tool_calls_exact"],
            ["search_previous_conversations", "extract_schedules_from_history"],
        )
        self.assertEqual(general["expect_answer_contains_all"], ["철수", "영희"])

        evidence = by_id["schedule-lookup-with-source-evidence"]["turns"][0]
        self.assertEqual(
            evidence["expect_tool_calls_exact"],
            [
                "search_previous_conversations",
                "extract_schedules_from_history",
                "load_conversation_messages",
            ],
        )
        self.assertTrue(evidence["expect_load_uses_extract_source_id"])

        no_match = by_id["no-match-external-search"]["turns"][0]
        self.assertEqual(
            no_match["expect_tool_calls_exact"],
            ["search_previous_conversations", "extract_schedules_from_history"],
        )
        self.assertIn("load_conversation_messages", no_match["expect_no_tool_called"])
        self.assertEqual(
            no_match["expect_tool_result_rows_empty"],
            ["search_previous_conversations", "extract_schedules_from_history"],
        )

        integrated = by_id["integrate-personal-and-external-schedules"]["turns"][1]
        self.assertEqual(
            integrated["expect_tool_calls_exact"],
            ["collect_member_schedules"],
        )

        external_negation = by_id["external-only-with-personal-negation"]["turns"][0]
        self.assertEqual(
            external_negation["expect_tool_calls_exact"],
            ["search_previous_conversations", "extract_schedules_from_history"],
        )

        personal_lookup = by_id["personal-saved-schedule-stays-in-app"]["turns"][1]
        self.assertEqual(
            personal_lookup["expect_tool_calls_exact"],
            ["personal_list_saved_schedules"],
        )

        shared_lookup = by_id["registered-shared-schedule-uses-shared-store"]["turns"][0]
        self.assertEqual(
            shared_lookup["expect_tool_calls_exact"],
            ["list_shared_schedules"],
        )

        mixed_paraphrase = by_id["mixed-schedule-paraphrase-uses-collector"]["turns"][1]
        self.assertEqual(
            mixed_paraphrase["expect_tool_calls_exact"],
            ["collect_member_schedules"],
        )

        unknown_end_turns = by_id["unknown-personal-end-time-is-collected-as-undecided"]["turns"]
        self.assertEqual(unknown_end_turns[0]["expect_tool_calls_exact"], [])
        self.assertEqual(
            unknown_end_turns[1]["expect_tool_called"],
            ["personal_create_schedule"],
        )
        unknown_end = unknown_end_turns[2]
        self.assertEqual(unknown_end["expect_tool_called"], ["collect_member_schedules"])
        self.assertIn(
            {
                "member_name": "나",
                "title": "집중 작업",
                "date": "2026-07-09",
                "start_time": "10:00",
                "end_time": "미정",
            },
            unknown_end["expect_collect_member_schedules_rows"]["rows_must_include"],
        )

    def test_schedule_update_scenarios_cover_each_requested_tc(self):
        scenarios = json.loads(UPDATE_SCENARIOS_PATH.read_text(encoding="utf-8"))
        by_id = {scenario["id"]: scenario for scenario in scenarios}

        self.assertEqual(
            set(by_id),
            {
                "tc01-group-schedule-is-not-omitted",
                "tc02-personal-schedule-still-works",
                "tc04-duplicate-schedule-is-collapsed",
                "tc07-distinct-schedules-are-preserved",
                "tc08-notes-identify-schedule-kind",
                "tc09-me-is-listed-once",
                "tc10-legacy-schedule-is-personal",
                "tc11-payload-contract-is-stable",
            },
        )
        for scenario in scenarios:
            self.assertTrue(
                scenario.get("seed_app_requests")
                or scenario.get("seed_legacy_schedules")
                or scenario.get("seed_shared_schedules")
            )
            self.assertEqual(len(scenario["turns"]), 1)
            turn = scenario["turns"][0]
            self.assertEqual(turn["expect_tool_calls_exact"], ["collect_member_schedules"])
            self.assertIn("expect_collect_member_schedules_rows", turn)

        duplicate_spec = by_id["tc04-duplicate-schedule-is-collapsed"]["turns"][0][
            "expect_collect_member_schedules_rows"
        ]
        self.assertEqual(duplicate_spec["exact_row_count"], 1)

        distinct_spec = by_id["tc07-distinct-schedules-are-preserved"]["turns"][0][
            "expect_collect_member_schedules_rows"
        ]
        self.assertEqual(distinct_spec["exact_row_count"], 4)

        members_spec = by_id["tc09-me-is-listed-once"]["turns"][0][
            "expect_collect_member_schedules_rows"
        ]
        self.assertEqual(members_spec["expected_members"], ["나", "민준"])

        payload_spec = by_id["tc11-payload-contract-is-stable"]["turns"][0][
            "expect_collect_member_schedules_rows"
        ]
        self.assertEqual(
            set(payload_spec["exact_payload_keys"]),
            {"ok", "tool_name", "members", "rows", "schedule_summary"},
        )


if __name__ == "__main__":
    unittest.main()
