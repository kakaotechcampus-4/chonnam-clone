from __future__ import annotations

import importlib.util
import json
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "tests/e2e/week06_supervisor/run_scenarios.py"
SCENARIOS_PATH = REPO_ROOT / "tests/e2e/week06_supervisor/scenarios.json"

SPEC = importlib.util.spec_from_file_location("week06_e2e_runner", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"E2E runner를 import할 수 없습니다: {RUNNER_PATH}")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def result_with_inner_events(
    *,
    agent: str,
    inner_events: list[dict],
    final_payload: dict | None = None,
    answer: str = "완료",
):
    wrapper_content = {
        "selected_agent": agent,
        "answer": answer,
        "trace": inner_events,
        "inner_tool_names": RUNNER.tool_names(inner_events),
        "final_slot_payload": final_payload,
        "final_decision_payload": None,
    }
    return SimpleNamespace(
        answer=answer,
        trace={
            "supervisor_selected_agent": agent,
            "inner_tool_names": wrapper_content["inner_tool_names"],
            "final_slot_payload": final_payload,
            "events": [
                {
                    "event": "tool_call",
                    "tool_name": agent,
                    "arguments": {"query": "나와 철수 2026년 회의"},
                },
                {
                    "event": "tool_result",
                    "tool_name": agent,
                    "content": wrapper_content,
                },
            ],
        },
    )


class Week06E2ERunnerTest(unittest.TestCase):
    def test_runtime_date_placeholders_are_resolved_recursively(self):
        from fixed.runtime_clock import current_app_date

        today = current_app_date()

        self.assertEqual(
            RUNNER.resolve_runtime_value(
                {"date_range": ["$APP_TODAY", "$APP_TOMORROW"]}
            ),
            {
                "date_range": [
                    today.isoformat(),
                    (today + timedelta(days=1)).isoformat(),
                ]
            },
        )

    def test_scenarios_cover_required_week06_workflows(self):
        scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
        ids = {scenario["id"] for scenario in scenarios}

        self.assertEqual(len(ids), len(scenarios))
        self.assertTrue(
            {
                "personal-schedule-routing-and-trace",
                "personal-schedule-create-update-delete",
                "personal-reference-save-and-search",
                "external-schedule-search-extract",
                "external-source-evidence",
                "external-no-match-does-not-load",
                "shared-schedule-row-routing",
                "collect-mine-and-external-without-duplicate-search",
                "group-collect-find-decide-confirmed",
                "group-external-search-find-decide-confirmed",
                "group-custom-duration-90-minutes",
                "group-iso-datetime-bounds-normalized",
                "group-no-common-slot-remains-pending",
                "saved-record-rag-routing",
                "conversation-rag-routing",
                "missing-date-clarification-and-resume",
                "missing-member-clarification-and-resume",
                "relative-date-uses-runtime-clock",
            }.issubset(ids)
        )
        self.assertGreaterEqual(
            sum(len(scenario["turns"]) for scenario in scenarios),
            25,
        )

        by_id = {scenario["id"]: scenario for scenario in scenarios}
        reminder_turn = by_id["todo-reminder-storage-routing"]["turns"][1]
        self.assertIn("알림", reminder_turn["message"])
        self.assertIn("save_structured_request", reminder_turn["expect_inner_order"])
        self.assertIn(
            "search_saved_requests",
            by_id["saved-record-rag-routing"]["turns"][1]["expect_inner_contains"],
        )
        conversation_rag = by_id["conversation-rag-routing"]
        self.assertTrue(conversation_rag["seed_conversation_messages"])
        self.assertIn(
            "search_conversation_messages",
            conversation_rag["turns"][0]["expect_inner_contains"],
        )
        external_only = by_id["group-external-search-find-decide-confirmed"]["turns"][0]
        self.assertEqual(external_only["expect_find_members_exact"], ["철수", "영희"])
        self.assertNotIn("나", external_only["expect_final_payload"]["members_exact"])
        pending = by_id["group-no-common-slot-remains-pending"]["turns"][0]
        find_arguments = pending["expect_tool_arguments"][0]["arguments"]
        self.assertEqual(find_arguments["workday_start"], "10:00")
        self.assertEqual(find_arguments["workday_end"], "11:00")
        self.assertTrue(pending["expect_no_final_slot_in_answer"])

    def test_runner_accepts_valid_confirmed_group_trace(self):
        rows = [{"member_name": "철수", "date": "2026-07-07"}]
        candidates = [
            {
                "date": "2026-07-07",
                "start_time": "11:00",
                "end_time": "12:00",
                "duration_minutes": 60,
                "reason": "가능",
            }
        ]
        final_slot = "2026-07-07 11:00-12:00"
        inner_events = [
            {"event": "tool_call", "tool_name": "collect_member_schedules", "arguments": {}},
            {
                "event": "tool_result",
                "tool_name": "collect_member_schedules",
                "content": {"rows": rows},
            },
            {
                "event": "tool_call",
                "tool_name": "find_common_available_slots",
                "arguments": {"busy_rows": rows, "candidate_slots": candidates},
            },
            {
                "event": "tool_result",
                "tool_name": "find_common_available_slots",
                "content": {"busy_rows": rows, "candidate_slots": candidates},
            },
            {
                "event": "tool_call",
                "tool_name": "decide_final_slot",
                "arguments": {
                    "candidate_slots": candidates,
                    "selected_index": 0,
                    "final_slot": final_slot,
                    "busy_rows": rows,
                },
            },
        ]
        final_payload = {
            "final_slot": final_slot,
            "reason": "선택",
            "candidates": [final_slot],
            "needs_agent_selection": False,
            "selected_index": 0,
            "members": ["나", "철수"],
            "busy_rows": rows,
            "candidate_slots": candidates,
        }
        result = result_with_inner_events(
            agent="kana_agent",
            inner_events=inner_events,
            final_payload=final_payload,
            answer=f"최종 시간은 {final_slot}입니다.",
        )
        turn = {
            "expected_agent": "kana_agent",
            "expect_query_contains": ["나", "철수", "2026"],
            "expect_inner_exact": [
                "collect_member_schedules",
                "find_common_available_slots",
                "decide_final_slot",
            ],
            "expect_busy_rows_from": "collect_member_schedules",
            "expect_candidate_contract": True,
            "expect_decide_uses_validated_candidates": True,
            "expect_final_payload": {
                "state": "confirmed",
                "require_evidence": True,
                "answer_matches": True,
            },
        }

        self.assertEqual(RUNNER.check_turn(turn, result), [])

    def test_runner_rejects_extra_wrapper_and_forbidden_inner_tool(self):
        result = result_with_inner_events(
            agent="kana_agent",
            inner_events=[
                {"event": "tool_call", "tool_name": "personal_create_schedule", "arguments": {}},
            ],
        )
        result.trace["events"].insert(
            1,
            {"event": "tool_call", "tool_name": "nana_agent", "arguments": {"query": "예비"}},
        )
        turn = {
            "expected_agent": "kana_agent",
            "expect_inner_not_contains": ["personal_create_schedule"],
        }

        failures = RUNNER.check_turn(turn, result)

        self.assertTrue(any("정확히 한 번" in failure for failure in failures))
        self.assertTrue(any("금지 내부 tool" in failure for failure in failures))

    def test_runner_rejects_pending_payload_that_contains_final_slot(self):
        result = result_with_inner_events(
            agent="kana_agent",
            inner_events=[],
            final_payload={
                "final_slot": "2026-07-07 11:00-12:00",
                "reason": "모순",
                "candidates": [],
                "needs_agent_selection": True,
            },
        )
        failures = RUNNER.check_turn(
            {
                "expected_agent": "kana_agent",
                "expect_final_payload": {"state": "pending"},
            },
            result,
        )

        self.assertTrue(any("final_slot은 null" in failure for failure in failures))

    def test_runner_requires_load_id_from_extract_source(self):
        inner_events = [
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
            },
            {
                "event": "tool_call",
                "tool_name": "load_conversation_messages",
                "arguments": {"conversation_id": "invented"},
            },
        ]

        failures = RUNNER.check_load_source_id(
            {"expect_load_uses_extract_source_id": True},
            inner_events,
        )

        self.assertTrue(any("source_conversation_id" in failure for failure in failures))

    def test_runner_rejects_malformed_wrapper_payload(self):
        result = result_with_inner_events(agent="nana_agent", inner_events=[])
        wrapper_content = result.trace["events"][-1]["content"]
        wrapper_content.pop("answer")
        wrapper_content["inner_tool_names"] = ["invented_tool"]

        failures = RUNNER.check_turn(
            {"expected_agent": "nana_agent"},
            result,
        )

        self.assertTrue(any("필수 key 누락" in failure for failure in failures))
        self.assertTrue(any("trace tool_call 순서와 다름" in failure for failure in failures))

    def test_runner_rejects_confirmed_slot_not_matching_selected_candidate(self):
        candidates = [
            {
                "date": "2026-07-07",
                "start_time": "11:00",
                "end_time": "12:00",
                "duration_minutes": 60,
                "reason": "가능",
            }
        ]
        result = result_with_inner_events(
            agent="kana_agent",
            inner_events=[],
            final_payload={
                "final_slot": "2026-07-07 15:00-16:00",
                "reason": "불일치",
                "candidates": ["2026-07-07 11:00-12:00"],
                "needs_agent_selection": False,
                "selected_index": 0,
                "selected_slot": candidates[0],
                "candidate_slots": candidates,
            },
        )

        failures = RUNNER.check_final_payload(
            {"expect_final_payload": {"state": "confirmed"}},
            result,
            result.trace,
        )

        self.assertTrue(any("선택된 후보와 일치하지 않음" in failure for failure in failures))

    def test_runner_rejects_empty_candidates_for_confirmed_scenario(self):
        inner_events = [
            {
                "event": "tool_call",
                "tool_name": "find_common_available_slots",
                "arguments": {"candidate_slots": []},
            }
        ]

        failures = RUNNER.check_candidate_contract(
            {
                "expect_candidate_contract": True,
                "expect_final_payload": {"state": "confirmed"},
            },
            inner_events,
        )

        self.assertTrue(any("비어 있음" in failure for failure in failures))

    def test_runner_requires_source_busy_rows_in_decide_call(self):
        rows = [{"member_name": "철수", "date": "2026-07-07"}]
        inner_events = [
            {
                "event": "tool_result",
                "tool_name": "collect_member_schedules",
                "content": {"rows": rows},
            },
            {
                "event": "tool_call",
                "tool_name": "find_common_available_slots",
                "arguments": {"busy_rows": rows},
            },
            {
                "event": "tool_call",
                "tool_name": "decide_final_slot",
                "arguments": {"busy_rows": []},
            },
        ]

        failures = RUNNER.check_busy_rows_forwarding(
            {"expect_busy_rows_from": "collect_member_schedules"},
            inner_events,
        )

        self.assertTrue(any("decide busy_rows" in failure for failure in failures))

    def test_runner_rejects_final_slot_in_pending_answer(self):
        failures = RUNNER.check_answer(
            {"expect_no_final_slot_in_answer": True},
            "확정 시간은 2026-07-07 11:00-12:00입니다.",
        )

        self.assertTrue(any("미확정 답변" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
