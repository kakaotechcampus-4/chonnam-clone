from __future__ import annotations

"""Week 5 MCP wrapper agent(student_parts/week05_load_kanas_past_conversations.py)가
docs/week05-implementation-plan.md가 요구하는 tool 호출 "순서"와 "row 구조"를 실제로
지키는지 확인하는 E2E 회귀 테스트 러너입니다.

배경: Week 5는 최종 자연어 답변만으로는 검증할 수 없다. 계획 문서가 요구하는 것은
1) search_previous_conversations -> extract_schedules_from_history -> (선택) load_conversation_messages
   순서를 실제로 지키는지,
2) collect_member_schedules가 내부에서 이미 외부 일정을 조회하므로 agent가 같은 작업을
   extract_schedules_from_history로 중복 호출하지 않는지,
3) 검색 결과가 없을 때 임의의 conversation_id로 load하거나 일정을 지어내지 않는지,
4) collect_member_schedules의 rows에 "나"와 외부 멤버가 표준 6개 필드로 함께 들어있고
   외부 row의 source_conversation_id가 보존되는지
이다. 이 판단은 system prompt가 만드는 행동이라 유닛 테스트로는 재현할 수 없고, 실제 LLM
호출로 trace를 재생해야만 회귀를 감지할 수 있다.

이 스크립트가 하는 일:
1. scenarios.json의 대화를 순서대로 재생하며 실제 Week 5 agent(run_active_week_agent(5, ...))를 호출한다.
2. 각 turn에서 tool 호출 이름의 "순서"(집합이 아니라 index)와 tool_result의 rows 구조를 확인한다.
3. 실행 중 만들어지는 앱 DB/Chroma는 매 실행마다 새로 만드는 임시 디렉터리를 쓴다.
   외부 SQLite(KANANA_EXTERNAL_DB_PATH)도 임시 경로로 격리하지만, ExternalPeopleSQLiteStore가
   생성 시 항상 같은 "7월 실습" fixture(철수/영희/민준/서연/지훈/하린, 2026-07-07~17)를 다시
   심으므로 시나리오는 이 고정 데이터를 그대로 근거로 쓸 수 있다. `fixed/`, `mcp_server/`는
   수정하지 않는다.

요구 사항: `.env`에 실제로 동작하는 PROXY_TOKEN이 있어야 한다(실제 LLM 호출이 필요하기 때문).
"""

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

# 아래 patch는 student_parts/fixed 모듈이 import되기 전에 실행돼야 한다.
# week05 모듈은 import 시점에 AppSQLiteStore(CONFIG.app_db_path) 같은 모듈 전역 store를
# 만들고, MCP subprocess는 KANANA_EXTERNAL_DB_PATH 환경 변수로 외부 SQLite 경로를 읽으므로
# 실제 개발용 data/ DB 대신 이 스크립트 전용 임시 DB를 쓰게 먼저 바꿔치기한다.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="kanana_week05_e2e_"))
os.environ.setdefault("KANANA_EXTERNAL_DB_PATH", str(_TMP_DIR / "external.sqlite3"))

from fixed.config import CONFIG  # noqa: E402

object.__setattr__(CONFIG, "app_db_path", _TMP_DIR / "app.sqlite3")
object.__setattr__(CONFIG, "chroma_dir", _TMP_DIR / "chroma")
object.__setattr__(CONFIG, "external_db_path", Path(os.environ["KANANA_EXTERNAL_DB_PATH"]))

from fixed.session_scope import conversation_session_scope  # noqa: E402
from fixed.week_agent_registry import run_active_week_agent  # noqa: E402

WEEK = 5
STANDARD_ROW_FIELDS = ["member_name", "title", "date", "start_time", "end_time", "notes"]


def _events(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return trace.get("events", []) if isinstance(trace, dict) else []


def _tool_call_names(events: list[dict[str, Any]]) -> list[str]:
    return [event.get("tool_name") for event in events if event.get("event") == "tool_call" and event.get("tool_name")]


def _tool_results_for(events: list[dict[str, Any]], tool_name: str) -> list[Any]:
    """호출 순서대로 특정 tool의 tool_result content(가능하면 dict로 파싱된 값)를 모읍니다."""

    return [
        event.get("content")
        for event in events
        if event.get("event") == "tool_result" and event.get("tool_name") == tool_name
    ]


def _last_tool_result_for(events: list[dict[str, Any]], tool_name: str) -> Any | None:
    results = _tool_results_for(events, tool_name)
    return results[-1] if results else None


def _run_turn(conversation_id: str, history: list[dict[str, str]], message: str) -> dict[str, Any]:
    history.append({"role": "user", "content": message})
    with conversation_session_scope(conversation_id):
        result = run_active_week_agent(WEEK, history)
    history.append({"role": "assistant", "content": result.answer})
    events = _events(result.trace)
    return {
        "answer": result.answer or "",
        "tool_names": _tool_call_names(events),
        "events": events,
        "error": result.trace.get("error") if isinstance(result.trace, dict) else None,
    }


def _check_tool_order(names_required: list[str], tool_names: list[str]) -> list[str]:
    """names_required에 있는 각 tool이 (첫 등장 기준) 순서대로 먼저 호출됐는지 확인합니다."""

    indices: list[int] = []
    for name in names_required:
        if name not in tool_names:
            return [f"'{name}'가 호출되지 않아 순서를 확인할 수 없음 (실제 호출: {tool_names or '없음'})"]
        indices.append(tool_names.index(name))
    for earlier, later in zip(indices, indices[1:]):
        if earlier >= later:
            return [f"tool 호출 순서가 기대와 다름: 기대 순서 {names_required}, 실제 호출 {tool_names}"]
    return []


def _check_tool_result_rows_empty(names: list[str], events: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for name in names:
        content = _last_tool_result_for(events, name)
        if not isinstance(content, dict):
            failures.append(f"'{name}' tool_result를 JSON으로 확인할 수 없음: {content!r}")
            continue
        rows = content.get("rows")
        if rows:
            failures.append(f"'{name}' 결과 rows가 비어 있어야 하는데 {len(rows)}개가 반환됨: {rows}")
    return failures


def _check_tool_result_row_keys(spec: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    tool_name = spec["tool_name"]
    required_keys = spec["keys"]
    content = _last_tool_result_for(events, tool_name)
    failures: list[str] = []
    if not isinstance(content, dict):
        return [f"'{tool_name}' tool_result를 JSON으로 확인할 수 없음: {content!r}"]
    rows = content.get("rows")
    if not rows:
        return [f"'{tool_name}' 결과에 rows가 없어 필드를 확인할 수 없음"]
    for row in rows:
        missing = [key for key in required_keys if key not in row]
        if missing:
            failures.append(f"'{tool_name}' row에 {missing} 필드가 없음: {row}")
    return failures


def _check_collect_member_schedules_rows(spec: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    content = _last_tool_result_for(events, "collect_member_schedules")
    failures: list[str] = []
    if not isinstance(content, dict):
        return [f"'collect_member_schedules' tool_result를 JSON으로 확인할 수 없음: {content!r}"]
    rows = content.get("rows") or []
    if not rows:
        return ["'collect_member_schedules' 결과 rows가 비어 있음"]

    member_names_present = {row.get("member_name") for row in rows}
    for expected_member in spec.get("must_include_members", []):
        if expected_member not in member_names_present:
            failures.append(
                f"'collect_member_schedules' rows에 '{expected_member}' 일정이 없음 (실제 멤버: {sorted(m for m in member_names_present if m)})"
            )

    required_fields = spec.get("required_row_fields", STANDARD_ROW_FIELDS)
    for row in rows:
        missing = [field for field in required_fields if field not in row]
        if missing:
            failures.append(f"row에 표준 필드 {missing}가 없음: {row}")

    if spec.get("external_rows_require_source_conversation_id"):
        for row in rows:
            if row.get("member_name") == "나":
                continue
            if not row.get("source_conversation_id"):
                failures.append(f"외부 멤버 row에 source_conversation_id가 없음(근거 추적 불가): {row}")

    if not content.get("schedule_summary"):
        failures.append("'collect_member_schedules' 결과에 schedule_summary가 없음")

    return failures


def _check_turn(turn_spec: dict[str, Any], outcome: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    tool_names = outcome["tool_names"]
    called = set(tool_names)
    answer = outcome["answer"]
    events = outcome["events"]

    for name in turn_spec.get("expect_tool_called", []):
        if name not in called:
            failures.append(f"'{name}' tool이 호출됐어야 하는데 안 불림 (실제 호출: {sorted(called) or '없음'})")

    any_expected = turn_spec.get("expect_any_tool_called")
    if any_expected and not (called & set(any_expected)):
        failures.append(f"{any_expected} 중 하나는 호출됐어야 하는데 아무것도 안 불림 (실제 호출: {sorted(called) or '없음'})")

    for name in turn_spec.get("expect_no_tool_called", []):
        if name in called:
            failures.append(f"'{name}' tool은 호출되면 안 되는데 불림 (실제 호출: {tool_names})")

    if "expect_tool_order" in turn_spec:
        failures.extend(_check_tool_order(turn_spec["expect_tool_order"], tool_names))

    if "expect_tool_prefix" in turn_spec:
        prefix = turn_spec["expect_tool_prefix"]
        if tool_names[: len(prefix)] != prefix:
            failures.append(f"처음 {len(prefix)}개 tool 호출이 {prefix}여야 하는데 실제로는 {tool_names[: len(prefix)]}")

    for phrase in turn_spec.get("expect_answer_not_contains", []):
        if phrase in answer:
            failures.append(f"답변에 '{phrase}'가 있으면 안 되는데 포함됨 (답변: {answer!r})")

    contains_any = turn_spec.get("expect_answer_contains_any")
    if contains_any and not any(phrase in answer for phrase in contains_any):
        failures.append(f"답변에 {contains_any} 중 하나는 있어야 하는데 없음 (답변: {answer!r})")

    if "expect_tool_result_rows_empty" in turn_spec:
        failures.extend(_check_tool_result_rows_empty(turn_spec["expect_tool_result_rows_empty"], events))

    for spec in turn_spec.get("expect_tool_result_row_keys", []):
        failures.extend(_check_tool_result_row_keys(spec, events))

    if "expect_collect_member_schedules_rows" in turn_spec:
        failures.extend(_check_collect_member_schedules_rows(turn_spec["expect_collect_member_schedules_rows"], events))

    return failures


def run_scenario(scenario: dict[str, Any]) -> tuple[bool, list[str]]:
    conversation_id = f"e2e-week05-{scenario['id']}"
    history: list[dict[str, str]] = []
    failures: list[str] = []

    for turn_index, turn_spec in enumerate(scenario["turns"]):
        outcome = _run_turn(conversation_id, history, turn_spec["message"])
        if outcome["error"]:
            failures.append(
                f"[turn {turn_index + 1}: {turn_spec['message']!r}] agent 실행 자체가 실패함 (tool 판단 문제가 아님): "
                f"{outcome['error']}"
            )
            break
        turn_failures = _check_turn(turn_spec, outcome)
        for failure in turn_failures:
            failures.append(f"[turn {turn_index + 1}: {turn_spec['message']!r}] {failure}")

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
