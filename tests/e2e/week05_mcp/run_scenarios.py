from __future__ import annotations

"""Week 5 MCP wrapper agent(student_parts/week05_load_kanas_past_conversations.py)가
docs/week05-implementation-plan.md가 요구하는 tool 호출 "순서"와 "row 구조"를 실제로
지키는지 확인하는 E2E 회귀 테스트 러너입니다.

배경: Week 5는 최종 자연어 답변만으로는 검증할 수 없다. 계획 문서가 요구하는 것은
1) search_previous_conversations -> extract_schedules_from_history -> (선택) load_conversation_messages
   순서를 실제로 지키는지,
2) collect_member_schedules가 내부에서 이미 외부 일정을 조회하므로 agent가 같은 작업을
   extract_schedules_from_history로 중복 호출하지 않는지,
3) 일정 추출 결과가 없을 때 임의의 conversation_id로 load하거나 일정을 지어내지 않는지,
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

WEEK = 5
STANDARD_ROW_FIELDS = ["member_name", "title", "date", "start_time", "end_time", "notes"]
_TMP_DIR: Path | None = None
_CONFIG: Any | None = None
_conversation_session_scope: Any | None = None
_run_active_week_agent: Any | None = None


def _configure_isolated_runtime() -> Path:
    """실제 agent 모듈을 import하기 전에 이 실행 전용 DB 경로를 강제로 설정합니다."""

    global _TMP_DIR, _CONFIG, _conversation_session_scope, _run_active_week_agent
    if _TMP_DIR is not None:
        return _TMP_DIR

    _TMP_DIR = Path(tempfile.mkdtemp(prefix="kanana_week05_e2e_"))
    os.environ["KANANA_EXTERNAL_DB_PATH"] = str(_TMP_DIR / "external.sqlite3")

    from fixed.config import CONFIG

    object.__setattr__(CONFIG, "app_db_path", _TMP_DIR / "app.sqlite3")
    object.__setattr__(CONFIG, "chroma_dir", _TMP_DIR / "chroma")
    object.__setattr__(CONFIG, "external_db_path", _TMP_DIR / "external.sqlite3")

    from fixed.session_scope import conversation_session_scope
    from fixed.week_agent_registry import run_active_week_agent

    _CONFIG = CONFIG
    _conversation_session_scope = conversation_session_scope
    _run_active_week_agent = run_active_week_agent
    return _TMP_DIR


def _events(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return trace.get("events", []) if isinstance(trace, dict) else []


def _tool_call_names(events: list[dict[str, Any]]) -> list[str]:
    return [event.get("tool_name") for event in events if event.get("event") == "tool_call" and event.get("tool_name")]


def _tool_calls_for(events: list[dict[str, Any]], tool_name: str) -> list[dict[str, Any]]:
    """호출 순서대로 특정 tool의 tool_call 이벤트를 반환합니다."""

    return [
        event
        for event in events
        if event.get("event") == "tool_call" and event.get("tool_name") == tool_name
    ]


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
    if _conversation_session_scope is None or _run_active_week_agent is None:
        raise RuntimeError("E2E runtime이 구성되지 않았습니다.")
    history.append({"role": "user", "content": message})
    with _conversation_session_scope(conversation_id):
        result = _run_active_week_agent(WEEK, history)
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


def _check_tool_calls_exact(expected: list[str], actual: list[str]) -> list[str]:
    """불필요한 앞·뒤·중간 호출까지 포함해 tool 호출 목록 전체가 같은지 확인합니다."""

    if actual != expected:
        return [f"tool 호출 전체가 기대와 다름: 기대 {expected}, 실제 {actual or '없음'}"]
    return []


def _check_tool_call_arguments(
    specs: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[str]:
    """tool 호출 인자가 시나리오에 명시된 부분 기대값과 일치하는지 확인합니다."""

    failures: list[str] = []
    for spec in specs:
        tool_name = spec["tool_name"]
        occurrence = int(spec.get("occurrence", 0))
        calls = _tool_calls_for(events, tool_name)
        if occurrence >= len(calls):
            failures.append(
                f"'{tool_name}'의 {occurrence + 1}번째 호출 인자를 확인할 수 없음 "
                f"(실제 호출 횟수: {len(calls)})"
            )
            continue
        actual_arguments = calls[occurrence].get("arguments")
        if not isinstance(actual_arguments, dict):
            failures.append(f"'{tool_name}' 호출 arguments가 dict가 아님: {actual_arguments!r}")
            continue
        for key, expected_value in spec.get("arguments", {}).items():
            actual_value = actual_arguments.get(key)
            values_match = actual_value == expected_value
            if key == "member_names" and isinstance(expected_value, list) and isinstance(actual_value, list):
                values_match = sorted(str(value) for value in actual_value) == sorted(
                    str(value) for value in expected_value
                )
            if not values_match:
                failures.append(
                    f"'{tool_name}' 인자 '{key}'가 기대와 다름: "
                    f"기대 {expected_value!r}, 실제 {actual_value!r}"
                )
    return failures


def _check_tool_result_rows_empty(names: list[str], events: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for name in names:
        content = _last_tool_result_for(events, name)
        if not isinstance(content, dict):
            failures.append(f"'{name}' tool_result를 JSON으로 확인할 수 없음: {content!r}")
            continue
        rows = content.get("rows")
        if not isinstance(rows, list):
            failures.append(f"'{name}' tool_result의 rows가 list가 아님: {rows!r}")
            continue
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


def _check_tool_result_members(
    specs: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[str]:
    """tool 결과 rows가 요청한 모든 외부 멤버를 포함하는지 확인합니다."""

    failures: list[str] = []
    for spec in specs:
        tool_name = spec["tool_name"]
        content = _last_tool_result_for(events, tool_name)
        if not isinstance(content, dict):
            failures.append(f"'{tool_name}' tool_result를 JSON으로 확인할 수 없음: {content!r}")
            continue
        rows = content.get("rows")
        if not isinstance(rows, list):
            failures.append(f"'{tool_name}' tool_result의 rows가 list가 아님: {rows!r}")
            continue
        actual_members = {row.get("member_name") for row in rows if isinstance(row, dict)}
        missing = [member for member in spec.get("members", []) if member not in actual_members]
        if missing:
            failures.append(
                f"'{tool_name}' 결과에 요청 멤버 {missing}가 없음 "
                f"(실제 멤버: {sorted(member for member in actual_members if member)})"
            )
    return failures


def _check_load_uses_extract_source_id(events: list[dict[str, Any]]) -> list[str]:
    """load 인자가 extract 결과에서 실제로 반환된 source_conversation_id인지 확인합니다."""

    extract_content = _last_tool_result_for(events, "extract_schedules_from_history")
    if not isinstance(extract_content, dict):
        return [f"extract tool_result를 JSON으로 확인할 수 없음: {extract_content!r}"]
    extract_rows = extract_content.get("rows")
    if not isinstance(extract_rows, list) or not extract_rows:
        return [f"extract 결과 rows가 없어 load의 source 연결을 확인할 수 없음: {extract_rows!r}"]
    source_ids = {
        row.get("source_conversation_id")
        for row in extract_rows
        if isinstance(row, dict) and row.get("source_conversation_id")
    }

    load_calls = _tool_calls_for(events, "load_conversation_messages")
    if not load_calls:
        return ["load_conversation_messages 호출이 없어 source 연결을 확인할 수 없음"]
    load_arguments = load_calls[-1].get("arguments")
    load_conversation_id = (
        load_arguments.get("conversation_id")
        if isinstance(load_arguments, dict)
        else None
    )
    if load_conversation_id not in source_ids:
        return [
            "load_conversation_messages의 conversation_id가 extract 결과의 "
            f"source_conversation_id가 아님: load={load_conversation_id!r}, "
            f"extract_sources={sorted(source_ids)}"
        ]
    return []


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

    for expected_row in spec.get("rows_must_include", []):
        if not any(
            isinstance(row, dict)
            and all(row.get(key) == value for key, value in expected_row.items())
            for row in rows
        ):
            failures.append(
                "'collect_member_schedules' 결과에 기대 row가 없음: "
                f"기대 부분값={expected_row}, 실제 rows={rows}"
            )

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

    if "expect_tool_calls_exact" in turn_spec:
        failures.extend(_check_tool_calls_exact(turn_spec["expect_tool_calls_exact"], tool_names))

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

    contains_all = turn_spec.get("expect_answer_contains_all")
    if contains_all:
        missing_phrases = [phrase for phrase in contains_all if phrase not in answer]
        if missing_phrases:
            failures.append(
                f"답변에 {missing_phrases}가 모두 포함돼야 하는데 없음 (답변: {answer!r})"
            )

    if "expect_tool_call_arguments" in turn_spec:
        failures.extend(
            _check_tool_call_arguments(turn_spec["expect_tool_call_arguments"], events)
        )

    if "expect_tool_result_rows_empty" in turn_spec:
        failures.extend(_check_tool_result_rows_empty(turn_spec["expect_tool_result_rows_empty"], events))

    for spec in turn_spec.get("expect_tool_result_row_keys", []):
        failures.extend(_check_tool_result_row_keys(spec, events))

    if "expect_tool_result_members" in turn_spec:
        failures.extend(
            _check_tool_result_members(turn_spec["expect_tool_result_members"], events)
        )

    if turn_spec.get("expect_load_uses_extract_source_id"):
        failures.extend(_check_load_uses_extract_source_id(events))

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
        if turn_failures:
            failures.append(
                f"[turn {turn_index + 1}: {turn_spec['message']!r}] "
                f"agent 답변={outcome['answer']!r}, tool 호출={outcome['tool_names']}"
            )
        for failure in turn_failures:
            failures.append(f"[turn {turn_index + 1}: {turn_spec['message']!r}] {failure}")

    return (len(failures) == 0, failures)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", default=str(SCRIPT_DIR / "scenarios.json"), help="시나리오 JSON 파일 경로")
    parser.add_argument("--only", action="append", default=None, help="이 id만 실행 (여러 번 지정 가능)")
    parser.add_argument("--keep-tmp", action="store_true", help="종료 후 임시 DB 디렉터리를 지우지 않음(디버깅용)")
    args = parser.parse_args()

    tmp_dir = _configure_isolated_runtime()
    try:
        if _CONFIG is None or not _CONFIG.has_openai_key:
            print("PROXY_TOKEN이 .env에 없어 실제 LLM을 호출할 수 없습니다. E2E 시나리오를 건너뜁니다.")
            return 1

        scenarios = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))
        if args.only:
            scenarios = [s for s in scenarios if s["id"] in args.only]
            missing = set(args.only) - {s["id"] for s in scenarios}
            if missing:
                print(f"scenarios.json에 없는 id: {sorted(missing)}")
                return 1

        print(f"임시 DB: {tmp_dir}")
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

        print("\n결과:", "ALL PASS" if all_ok else "일부 실패")
        return 0 if all_ok else 1
    finally:
        if args.keep_tmp:
            print(f"\n임시 DB를 남겨둠: {tmp_dir}")
        else:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
