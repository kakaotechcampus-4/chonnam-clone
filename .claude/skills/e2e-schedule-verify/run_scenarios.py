from __future__ import annotations

"""Week 3/4 agent가 실제로 저장/조회 tool을 호출하는지 확인하는 E2E 회귀 테스트 러너입니다.

배경: 2026-07 회고에서 "제목/날짜/시간이 문장에 이미 있는데도 agent가 되묻기만 하고
save_structured_request를 안 부른다", "tool을 아예 안 부르고 대화 기억만으로 답한다"는
문제가 발견됐다. 이 문제는 코드 버그가 아니라 system prompt가 만드는 판단 실수라서
유닛 테스트로는 못 잡고, 실제 LLM을 호출하는 시나리오 재생으로만 재발을 감지할 수 있다.

이 스크립트는:
1. scenarios.json에 정의된 대화를 순서대로 재생하면서 실제 Week 3/4 agent(create_agent)를 호출하고,
2. 각 turn에서 기대한 tool이 실제로 호출됐는지/안 됐는지, 답변 문구가 기대와 맞는지 확인하고,
3. 시나리오가 끝난 뒤 SQLite에 실제로 값이 반영됐는지까지 확인한다.

실행 중 만들어지는 대화/일정 데이터는 매 실행마다 새로 만드는 임시 디렉터리에 저장되므로
`data/kanana_app.sqlite3` 같은 실제 개발용 DB는 건드리지 않는다.

요구 사항: `.env`에 실제로 동작하는 PROXY_TOKEN이 있어야 한다(실제 LLM 호출이 필요하기 때문).
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 아래 patch는 student_parts/fixed 모듈이 import되기 전에 실행돼야 한다.
# week03/week04 모듈은 import 시점에 `AppSQLiteStore(CONFIG.app_db_path)` 같은
# 모듈 전역 store를 만들기 때문에, CONFIG를 먼저 가짜 경로로 바꿔치기해야
# 실제 개발용 data/ DB 대신 이 스크립트 전용 임시 DB를 쓰게 된다.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="kanana_e2e_"))
os.environ.setdefault("KANANA_EXTERNAL_DB_PATH", str(_TMP_DIR / "external.sqlite3"))

from fixed.config import CONFIG  # noqa: E402

object.__setattr__(CONFIG, "app_db_path", _TMP_DIR / "app.sqlite3")
object.__setattr__(CONFIG, "chroma_dir", _TMP_DIR / "chroma")
object.__setattr__(CONFIG, "external_db_path", Path(os.environ["KANANA_EXTERNAL_DB_PATH"]))

from fixed.app_store import AppSQLiteStore  # noqa: E402
from fixed.runtime_clock import current_app_date  # noqa: E402
from fixed.session_scope import conversation_session_scope  # noqa: E402
from fixed.week_agent_registry import run_active_week_agent  # noqa: E402


def _tool_calls(events: list[dict[str, Any]]) -> list[str]:
    return [event.get("tool_name") for event in events if event.get("event") == "tool_call" and event.get("tool_name")]


def _run_turn(week: int, conversation_id: str, history: list[dict[str, str]], message: str) -> dict[str, Any]:
    history.append({"role": "user", "content": message})
    with conversation_session_scope(conversation_id):
        result = run_active_week_agent(week, history)
    history.append({"role": "assistant", "content": result.answer})
    return {
        "answer": result.answer or "",
        "tool_calls": _tool_calls(result.trace.get("events", [])),
        "trace": result.trace,
        "error": result.trace.get("error"),
    }


def _check_turn(turn_spec: dict[str, Any], outcome: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    called = set(outcome["tool_calls"])
    answer = outcome["answer"]

    for name in turn_spec.get("expect_tool_called", []):
        if name not in called:
            failures.append(f"'{name}' tool이 호출됐어야 하는데 안 불림 (실제 호출: {sorted(called) or '없음'})")

    any_expected = turn_spec.get("expect_any_tool_called")
    if any_expected and not (called & set(any_expected)):
        failures.append(f"{any_expected} 중 하나는 호출됐어야 하는데 아무것도 안 불림 (실제 호출: {sorted(called) or '없음'})")

    for name in turn_spec.get("expect_no_tool_called", []):
        if name in called:
            failures.append(f"'{name}' tool은 호출되면 안 되는데 불림")

    for phrase in turn_spec.get("expect_answer_not_contains", []):
        if phrase in answer:
            failures.append(f"답변에 '{phrase}'가 있으면 안 되는데 포함됨 (답변: {answer!r})")

    contains_any = turn_spec.get("expect_answer_contains_any")
    if contains_any and not any(phrase in answer for phrase in contains_any):
        failures.append(f"답변에 {contains_any} 중 하나는 있어야 하는데 없음 (답변: {answer!r})")

    return failures


def _check_db(db_check: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    store = AppSQLiteStore(CONFIG.app_db_path)
    kind = db_check.get("kind", "personal_schedule")
    rows = store.list_schedules(limit=50, kind=kind)

    title_contains = db_check.get("title_contains")
    expected_date = None
    if "date_offset_days" in db_check:
        expected_date = (current_app_date() + timedelta(days=db_check["date_offset_days"])).isoformat()
    expected_start_time = db_check.get("start_time")

    def matches(row: dict[str, Any]) -> bool:
        if title_contains and title_contains not in (row.get("title") or ""):
            return False
        if expected_date and row.get("date") != expected_date:
            return False
        if expected_start_time and row.get("start_time") != expected_start_time:
            return False
        return True

    if not any(matches(row) for row in rows):
        failures.append(
            "저장이 끝난 뒤에도 조건에 맞는 schedule row가 SQLite에 없음 "
            f"(kind={kind}, title_contains={title_contains!r}, date={expected_date}, "
            f"start_time={expected_start_time!r}); 실제 rows={rows}"
        )
    return failures


def run_scenario(scenario: dict[str, Any]) -> tuple[bool, list[str]]:
    week = scenario["week"]
    conversation_id = f"e2e-{scenario['id']}"
    history: list[dict[str, str]] = []
    failures: list[str] = []

    for turn_index, turn_spec in enumerate(scenario["turns"]):
        outcome = _run_turn(week, conversation_id, history, turn_spec["message"])
        if outcome["error"]:
            failures.append(
                f"[turn {turn_index + 1}: {turn_spec['message']!r}] agent 실행 자체가 실패함 (tool 판단 문제가 아님): "
                f"{outcome['error']}"
            )
            break
        turn_failures = _check_turn(turn_spec, outcome)
        for failure in turn_failures:
            failures.append(f"[turn {turn_index + 1}: {turn_spec['message']!r}] {failure}")

    if not failures and "db_check" in scenario:
        failures.extend(_check_db(scenario["db_check"]))

    return (len(failures) == 0, failures)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", default=str(SCRIPT_DIR / "scenarios.json"), help="시나리오 JSON 파일 경로")
    parser.add_argument("--only", action="append", default=None, help="이 id만 실행 (여러 번 지정 가능)")
    parser.add_argument("--keep-tmp", action="store_true", help="종료 후 임시 DB 디렉터리를 지우지 않음(디버깅용)")
    args = parser.parse_args()

    if not CONFIG.has_openai_key:
        print("PROXY_TOKEN이 .env에 없어 실제 LLM을 호출할 수 없습니다. E2E 시나리오를 건너뜁니다.")
        return 1

    scenarios = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))
    if args.only:
        scenarios = [s for s in scenarios if s["id"] in args.only]
        missing = set(args.only) - {s["id"] for s in scenarios}
        if missing:
            print(f"scenarios.json에 없는 id: {sorted(missing)}")
            return 1

    print(f"임시 DB: {_TMP_DIR}")
    all_ok = True
    for scenario in scenarios:
        print(f"\n=== {scenario['id']} (week {scenario['week']}) ===")
        print(scenario.get("description", ""))
        ok, failures = run_scenario(scenario)
        if ok:
            print("PASS")
        else:
            all_ok = False
            print("FAIL")
            for failure in failures:
                print(f"  - {failure}")

    if not args.keep_tmp:
        shutil.rmtree(_TMP_DIR, ignore_errors=True)
    else:
        print(f"\n임시 DB를 남겨둠: {_TMP_DIR}")

    print("\n결과:", "ALL PASS" if all_ok else "일부 실패")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
