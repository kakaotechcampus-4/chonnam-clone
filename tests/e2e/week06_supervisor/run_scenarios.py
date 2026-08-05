from __future__ import annotations

"""실제 Week 6 Supervisor와 Nana/Kana의 위임 및 내부 tool 순서를 검증합니다."""

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def configure_isolated_runtime() -> Path:
    runtime_dir = Path(tempfile.mkdtemp(prefix="kanana_week06_e2e_"))
    external_db_path = runtime_dir / "external.sqlite3"
    os.environ["KANANA_EXTERNAL_DB_PATH"] = str(external_db_path)

    from fixed.config import CONFIG

    object.__setattr__(CONFIG, "app_db_path", runtime_dir / "app.sqlite3")
    object.__setattr__(CONFIG, "chroma_dir", runtime_dir / "chroma")
    object.__setattr__(CONFIG, "external_db_path", external_db_path)
    return runtime_dir


def ordered(required: list[str], actual: list[str]) -> bool:
    position = -1
    for name in required:
        try:
            position = actual.index(name, position + 1)
        except ValueError:
            return False
    return True


def check_scenario(scenario: dict[str, Any], result: Any) -> list[str]:
    failures: list[str] = []
    trace = result.trace if isinstance(result.trace, dict) else {}
    selected_agent = trace.get("supervisor_selected_agent")
    inner_names = trace.get("inner_tool_names") or []
    events = trace.get("events") or []
    wrapper_calls = [
        event.get("tool_name")
        for event in events
        if event.get("event") == "tool_call"
        and event.get("tool_name") in {"nana_agent", "kana_agent"}
    ]

    expected_agent = scenario["expected_agent"]
    if selected_agent != expected_agent:
        failures.append(
            f"선택 agent 불일치: expected={expected_agent}, actual={selected_agent}"
        )
    if wrapper_calls != [expected_agent]:
        failures.append(
            f"Supervisor wrapper 호출은 정확히 하나여야 함: actual={wrapper_calls}"
        )
    for name in scenario.get("expected_inner_contains", []):
        if name not in inner_names:
            failures.append(f"필수 내부 tool 누락: {name}, actual={inner_names}")
    expected_order = scenario.get("expected_inner_order", [])
    if expected_order and not ordered(expected_order, inner_names):
        failures.append(
            f"내부 tool 순서 불일치: expected={expected_order}, actual={inner_names}"
        )
    if scenario.get("expect_final_slot_payload"):
        final_payload = trace.get("final_slot_payload")
        if not isinstance(final_payload, dict):
            failures.append(f"final_slot_payload 누락: {final_payload!r}")
        elif not {"final_slot", "reason", "candidates"}.issubset(final_payload):
            failures.append(f"최종 payload 필수 key 누락: {final_payload}")
        elif final_payload.get("final_slot") and final_payload["final_slot"] not in result.answer:
            failures.append(
                "최종 답변이 final_slot_payload.final_slot과 일치하지 않음: "
                f"slot={final_payload['final_slot']!r}, answer={result.answer!r}"
            )
    if trace.get("error"):
        failures.append(f"Agent 실행 오류: {trace['error']}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=Path, default=SCRIPT_DIR / "scenarios.json")
    parser.add_argument("--keep-runtime", action="store_true")
    args = parser.parse_args()

    runtime_dir = configure_isolated_runtime()
    failures: list[str] = []
    try:
        from fixed.session_scope import conversation_session_scope
        from fixed.week_agent_registry import run_active_week_agent

        scenarios = json.loads(args.scenarios.read_text(encoding="utf-8"))
        for scenario in scenarios:
            with conversation_session_scope(f"week06-e2e-{scenario['id']}"):
                result = run_active_week_agent(
                    6,
                    [{"role": "user", "content": scenario["message"]}],
                )
            scenario_failures = check_scenario(scenario, result)
            status = "PASS" if not scenario_failures else "FAIL"
            print(f"[{status}] {scenario['id']}")
            for failure in scenario_failures:
                print(f"  - {failure}")
            failures.extend(f"{scenario['id']}: {item}" for item in scenario_failures)
    finally:
        if args.keep_runtime:
            print(f"runtime preserved: {runtime_dir}")
        else:
            shutil.rmtree(runtime_dir, ignore_errors=True)

    if failures:
        print(f"Week06 E2E failed: {len(failures)}")
        return 1
    print("Week06 E2E passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
