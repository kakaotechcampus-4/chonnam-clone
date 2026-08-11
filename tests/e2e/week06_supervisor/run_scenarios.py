from __future__ import annotations

"""실제 Week 6 Supervisor와 Nana/Kana의 위임·인자·trace·최종 결정을 검증합니다."""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

WRAPPER_NAMES = {"nana_agent", "kana_agent"}
FINAL_SLOT_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) "
    r"(?P<start>\d{2}:\d{2})-(?P<end>\d{2}:\d{2})$"
)
FINAL_SLOT_IN_TEXT_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}-\d{2}:\d{2}"
)


def resolve_runtime_value(value: Any) -> Any:
    """시나리오의 앱 기준 날짜 placeholder를 실행 시점 값으로 바꿉니다."""

    if isinstance(value, list):
        return [resolve_runtime_value(item) for item in value]
    if isinstance(value, dict):
        return {key: resolve_runtime_value(item) for key, item in value.items()}
    if isinstance(value, str) and value in {"$APP_TODAY", "$APP_TOMORROW"}:
        from fixed.runtime_clock import current_app_date

        day = current_app_date()
        if value == "$APP_TOMORROW":
            day += timedelta(days=1)
        return day.isoformat()
    return value


def configure_isolated_runtime() -> Path:
    """Agent import 전에 앱 DB, Chroma, 외부 DB를 실행별 임시 경로로 격리합니다."""

    runtime_dir = Path(tempfile.mkdtemp(prefix="kanana_week06_e2e_"))
    external_db_path = runtime_dir / "external.sqlite3"
    os.environ["KANANA_EXTERNAL_DB_PATH"] = str(external_db_path)

    from fixed.config import CONFIG

    object.__setattr__(CONFIG, "app_db_path", runtime_dir / "app.sqlite3")
    object.__setattr__(CONFIG, "chroma_dir", runtime_dir / "chroma")
    object.__setattr__(CONFIG, "external_db_path", external_db_path)
    return runtime_dir


def tool_calls(events: list[dict[str, Any]], name: str | None = None) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event.get("event") == "tool_call"
        and (name is None or event.get("tool_name") == name)
    ]


def tool_results(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event.get("event") == "tool_result" and event.get("tool_name") == name
    ]


def tool_names(events: list[dict[str, Any]]) -> list[str]:
    return [
        str(event["tool_name"])
        for event in tool_calls(events)
        if event.get("tool_name")
    ]


def ordered(required: list[str], actual: list[str]) -> bool:
    position = -1
    for name in required:
        try:
            position = actual.index(name, position + 1)
        except ValueError:
            return False
    return True


def wrapper_result_content(
    outer_events: list[dict[str, Any]],
    expected_agent: str,
) -> dict[str, Any] | None:
    results = tool_results(outer_events, expected_agent)
    if not results:
        return None
    content = results[-1].get("content")
    return content if isinstance(content, dict) else None


def inner_events_from(
    outer_events: list[dict[str, Any]],
    expected_agent: str,
) -> list[dict[str, Any]]:
    content = wrapper_result_content(outer_events, expected_agent)
    if not content:
        return []
    trace = content.get("trace")
    return trace if isinstance(trace, list) else []


def partial_dict_matches(actual: Any, expected: dict[str, Any]) -> bool:
    if not isinstance(actual, dict):
        return False
    for key, raw_value in expected.items():
        value = resolve_runtime_value(raw_value)
        actual_value = actual.get(key)
        if key == "member_names" and isinstance(value, list) and isinstance(actual_value, list):
            if sorted(str(item) for item in actual_value) != sorted(str(item) for item in value):
                return False
        elif actual_value != value:
            return False
    return True


def check_wrapper_contract(
    turn: dict[str, Any],
    trace: dict[str, Any],
    outer_events: list[dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    expected_agent = turn["expected_agent"]
    selected_agent = trace.get("supervisor_selected_agent")
    wrapper_calls = [
        event for event in tool_calls(outer_events) if event.get("tool_name") in WRAPPER_NAMES
    ]

    if selected_agent != expected_agent:
        failures.append(
            f"선택 agent 불일치: expected={expected_agent}, actual={selected_agent}"
        )
    if [event.get("tool_name") for event in wrapper_calls] != [expected_agent]:
        failures.append(
            "Supervisor wrapper 호출은 담당 하나를 정확히 한 번이어야 함: "
            f"actual={[event.get('tool_name') for event in wrapper_calls]}"
        )
    wrapper_content = wrapper_result_content(outer_events, expected_agent)
    if not isinstance(wrapper_content, dict):
        failures.append(f"{expected_agent} wrapper 결과가 JSON object가 아님")
    else:
        required_keys = {"selected_agent", "answer", "trace", "inner_tool_names"}
        if expected_agent == "kana_agent":
            required_keys.update({"final_slot_payload", "final_decision_payload"})
        missing_keys = sorted(required_keys - wrapper_content.keys())
        if missing_keys:
            failures.append(f"{expected_agent} wrapper 필수 key 누락: {missing_keys}")
        if wrapper_content.get("selected_agent") != expected_agent:
            failures.append(
                f"wrapper selected_agent 불일치: expected={expected_agent}, "
                f"actual={wrapper_content.get('selected_agent')!r}"
            )
        if not isinstance(wrapper_content.get("answer"), str):
            failures.append("wrapper answer가 문자열이 아님")
        if expected_agent == "kana_agent":
            for key in ("final_slot_payload", "final_decision_payload"):
                if trace.get(key) != wrapper_content.get(key):
                    failures.append(
                        f"Supervisor trace {key}가 Kana wrapper 결과와 다름: "
                        f"wrapper={wrapper_content.get(key)!r}, trace={trace.get(key)!r}"
                    )
        wrapper_trace = wrapper_content.get("trace")
        if not isinstance(wrapper_trace, list):
            failures.append("wrapper trace가 list가 아님")
        else:
            expected_inner_names = tool_names(wrapper_trace)
            if wrapper_content.get("inner_tool_names") != expected_inner_names:
                failures.append(
                    "wrapper inner_tool_names가 trace tool_call 순서와 다름: "
                    f"expected={expected_inner_names}, "
                    f"actual={wrapper_content.get('inner_tool_names')!r}"
                )
            if trace.get("inner_tool_names") != expected_inner_names:
                failures.append(
                    "Supervisor trace inner_tool_names가 wrapper trace와 다름: "
                    f"expected={expected_inner_names}, actual={trace.get('inner_tool_names')!r}"
                )
    if wrapper_calls:
        arguments = wrapper_calls[0].get("arguments")
        query = arguments.get("query") if isinstance(arguments, dict) else None
        if not isinstance(query, str) or not query.strip():
            failures.append(f"wrapper query가 비어 있거나 문자열이 아님: {query!r}")
        else:
            for text in turn.get("expect_query_contains", []):
                text = str(resolve_runtime_value(text))
                if text not in query:
                    failures.append(f"wrapper query에 필수 문구가 없음: {text!r}, query={query!r}")
            for text in turn.get("expect_query_not_contains", []):
                text = str(resolve_runtime_value(text))
                if text in query:
                    failures.append(f"wrapper query에 추측한 문구가 포함됨: {text!r}, query={query!r}")
    return failures


def check_inner_tools(turn: dict[str, Any], inner_events: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    actual_names = tool_names(inner_events)

    if "expect_inner_exact" in turn and actual_names != turn["expect_inner_exact"]:
        failures.append(
            f"내부 tool 전체 불일치: expected={turn['expect_inner_exact']}, actual={actual_names}"
        )
    expected_order = turn.get("expect_inner_order", [])
    if expected_order and not ordered(expected_order, actual_names):
        failures.append(
            f"내부 tool 순서 불일치: expected={expected_order}, actual={actual_names}"
        )
    for name in turn.get("expect_inner_contains", []):
        if name not in actual_names:
            failures.append(f"필수 내부 tool 누락: {name}, actual={actual_names}")
    for name in turn.get("expect_inner_not_contains", []):
        if name in actual_names:
            failures.append(f"금지 내부 tool 호출: {name}, actual={actual_names}")

    for spec in turn.get("expect_tool_arguments", []):
        calls = tool_calls(inner_events, spec["tool_name"])
        occurrence = int(spec.get("occurrence", 0))
        if occurrence >= len(calls):
            failures.append(
                f"{spec['tool_name']} {occurrence + 1}번째 호출 인자를 확인할 수 없음"
            )
            continue
        arguments = calls[occurrence].get("arguments")
        if not partial_dict_matches(arguments, spec.get("arguments", {})):
            failures.append(
                f"{spec['tool_name']} 인자 불일치: expected subset={spec.get('arguments', {})}, "
                f"actual={arguments}"
            )
    return failures


def check_busy_rows_forwarding(
    turn: dict[str, Any],
    inner_events: list[dict[str, Any]],
) -> list[str]:
    source_name = turn.get("expect_busy_rows_from")
    if not source_name:
        return []
    source_results = tool_results(inner_events, source_name)
    find_calls = tool_calls(inner_events, "find_common_available_slots")
    if not source_results or not find_calls:
        return [f"busy_rows 전달 검증에 필요한 {source_name} 결과 또는 find 호출이 없음"]

    source_content = source_results[-1].get("content")
    source_rows = source_content.get("rows") if isinstance(source_content, dict) else None
    find_arguments = find_calls[-1].get("arguments")
    forwarded_rows = find_arguments.get("busy_rows") if isinstance(find_arguments, dict) else None
    if source_rows != forwarded_rows:
        failures = [
            f"{source_name} rows가 find busy_rows로 보존되지 않음: "
            f"source={source_rows!r}, forwarded={forwarded_rows!r}"
        ]
    else:
        failures = []
    find_results = tool_results(inner_events, "find_common_available_slots")
    if find_results:
        find_content = find_results[-1].get("content")
        find_rows = find_content.get("busy_rows") if isinstance(find_content, dict) else None
        if source_rows != find_rows:
            failures.append(
                f"{source_name} rows가 find 결과 근거에 보존되지 않음: "
                f"source={source_rows!r}, result={find_rows!r}"
            )

    decide_calls = tool_calls(inner_events, "decide_final_slot")
    if decide_calls:
        decide_arguments = decide_calls[-1].get("arguments")
        decide_rows = (
            decide_arguments.get("busy_rows")
            if isinstance(decide_arguments, dict)
            else None
        )
        if source_rows != decide_rows:
            failures.append(
                f"{source_name} rows가 decide busy_rows로 보존되지 않음: "
                f"source={source_rows!r}, forwarded={decide_rows!r}"
            )
    return failures


def check_load_source_id(turn: dict[str, Any], inner_events: list[dict[str, Any]]) -> list[str]:
    if not turn.get("expect_load_uses_extract_source_id"):
        return []
    extract_results = tool_results(inner_events, "extract_schedules_from_history")
    load_calls = tool_calls(inner_events, "load_conversation_messages")
    if not extract_results or not load_calls:
        return ["extract 결과 또는 load 호출이 없어 source_conversation_id를 검증할 수 없음"]
    extract_content = extract_results[-1].get("content")
    rows = extract_content.get("rows") if isinstance(extract_content, dict) else None
    source_ids = {
        row.get("source_conversation_id")
        for row in rows or []
        if isinstance(row, dict) and row.get("source_conversation_id")
    }
    load_arguments = load_calls[-1].get("arguments")
    conversation_id = (
        load_arguments.get("conversation_id") if isinstance(load_arguments, dict) else None
    )
    if conversation_id not in source_ids:
        return [
            "load conversation_id가 extract source_conversation_id에서 오지 않음: "
            f"load={conversation_id!r}, sources={sorted(source_ids)}"
        ]
    return []


def check_decide_uses_validated_candidates(
    turn: dict[str, Any],
    inner_events: list[dict[str, Any]],
) -> list[str]:
    if not turn.get("expect_decide_uses_validated_candidates"):
        return []
    find_results = tool_results(inner_events, "find_common_available_slots")
    decide_calls = tool_calls(inner_events, "decide_final_slot")
    if not find_results or not decide_calls:
        return ["find 결과 또는 decide 호출이 없어 검증 후보 전달을 확인할 수 없음"]
    find_content = find_results[-1].get("content")
    validated = find_content.get("candidate_slots") if isinstance(find_content, dict) else None
    decide_arguments = decide_calls[-1].get("arguments")
    decided_candidates = (
        decide_arguments.get("candidate_slots") if isinstance(decide_arguments, dict) else None
    )
    if validated != decided_candidates:
        return [
            "검증된 candidate_slots가 decide에 그대로 전달되지 않음: "
            f"validated={validated!r}, decided={decided_candidates!r}"
        ]
    return []


def check_candidate_contract(turn: dict[str, Any], inner_events: list[dict[str, Any]]) -> list[str]:
    if not turn.get("expect_candidate_contract"):
        return []
    calls = tool_calls(inner_events, "find_common_available_slots")
    if not calls:
        return ["find_common_available_slots 호출이 없어 후보 계약을 확인할 수 없음"]
    arguments = calls[-1].get("arguments")
    candidates = arguments.get("candidate_slots") if isinstance(arguments, dict) else None
    if not isinstance(candidates, list):
        return [f"candidate_slots가 list가 아님: {candidates!r}"]
    required_keys = {"date", "start_time", "end_time", "duration_minutes", "reason"}
    failures: list[str] = []
    final_state = (turn.get("expect_final_payload") or {}).get("state")
    requested_duration = arguments.get("duration_minutes", 60) if isinstance(arguments, dict) else 60
    if final_state == "confirmed" and not candidates:
        failures.append("확정 시나리오의 candidate_slots가 비어 있음")
    for candidate in candidates:
        if not isinstance(candidate, dict) or not required_keys.issubset(candidate):
            failures.append(f"후보 필드 계약 위반: {candidate!r}")
            continue
        slot_text = (
            f"{candidate['date']} {candidate['start_time']}-{candidate['end_time']}"
        )
        if FINAL_SLOT_PATTERN.fullmatch(slot_text) is None:
            failures.append(f"후보 날짜/시간 형식 위반: {candidate!r}")
            continue
        try:
            date.fromisoformat(candidate["date"])
            start_minutes = parse_hhmm(candidate["start_time"])
            end_minutes = parse_hhmm(candidate["end_time"])
        except (TypeError, ValueError):
            failures.append(f"후보 날짜/시간 값이 유효하지 않음: {candidate!r}")
            continue
        if not isinstance(candidate.get("duration_minutes"), int):
            failures.append(f"후보 duration_minutes가 정수가 아님: {candidate!r}")
        elif candidate["duration_minutes"] != end_minutes - start_minutes:
            failures.append(f"후보 duration_minutes가 시작·종료 시각과 다름: {candidate!r}")
        elif candidate["duration_minutes"] < requested_duration:
            failures.append(
                f"후보가 요청 회의 길이보다 짧음: requested={requested_duration}, candidate={candidate!r}"
            )
        if not isinstance(candidate.get("reason"), str) or not candidate["reason"].strip():
            failures.append(f"후보 reason이 비어 있음: {candidate!r}")
    return failures


def parse_hhmm(value: str) -> int:
    hour_text, minute_text = value.split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(value)
    return hour * 60 + minute


def slot_to_text(slot: Any) -> str | None:
    if not isinstance(slot, dict):
        return None
    date = slot.get("date")
    start = slot.get("start_time")
    end = slot.get("end_time")
    if not all(isinstance(value, str) and value for value in (date, start, end)):
        return None
    return f"{date} {start}-{end}"


def answer_mentions_final_slot(answer: str, final_slot: str) -> bool:
    """ISO payload와 한국어 자연어 답변이 같은 날짜·시각을 말하는지 확인합니다."""

    match = FINAL_SLOT_PATTERN.fullmatch(final_slot)
    if match is None:
        return False
    if final_slot in answer:
        return True

    day = date.fromisoformat(match.group("date"))
    date_mentions = {
        day.isoformat(),
        f"{day.year}년 {day.month}월 {day.day}일",
        f"{day.month}월 {day.day}일",
    }

    def mentions_time(value: str) -> bool:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
        variants = {value, f"{hour:02d}:{minute:02d}"}
        if minute == 0:
            variants.update({f"{hour}시", f"{hour}시 00분"})
        else:
            variants.update({f"{hour}시 {minute}분", f"{hour}시{minute}분"})
        return any(variant in answer for variant in variants)

    return (
        any(value in answer for value in date_mentions)
        and mentions_time(match.group("start"))
        and mentions_time(match.group("end"))
    )


def selected_candidate(payload: dict[str, Any]) -> dict[str, Any] | None:
    candidates = payload.get("candidate_slots")
    if not isinstance(candidates, list):
        return None
    selected_slot = payload.get("selected_slot")
    if isinstance(selected_slot, dict):
        return selected_slot
    selected_index = payload.get("selected_index")
    if isinstance(selected_index, int) and 0 <= selected_index < len(candidates):
        candidate = candidates[selected_index]
        return candidate if isinstance(candidate, dict) else None
    return None


def check_final_payload(turn: dict[str, Any], result: Any, trace: dict[str, Any]) -> list[str]:
    expectation = turn.get("expect_final_payload")
    if not expectation:
        return []
    payload = trace.get("final_slot_payload")
    if not isinstance(payload, dict):
        return [f"final_slot_payload 누락: {payload!r}"]
    failures: list[str] = []
    required_keys = {"final_slot", "reason", "candidates"}
    if not required_keys.issubset(payload):
        failures.append(f"최종 payload 필수 key 누락: {payload}")
        return failures

    state = expectation.get("state")
    if state == "confirmed":
        final_slot = payload.get("final_slot")
        if not final_slot:
            failures.append(f"확정 시 final_slot이 필요함: {payload}")
        elif not isinstance(final_slot, str) or FINAL_SLOT_PATTERN.fullmatch(final_slot) is None:
            failures.append(f"final_slot 형식이 YYYY-MM-DD HH:MM-HH:MM이 아님: {final_slot!r}")
        else:
            match = FINAL_SLOT_PATTERN.fullmatch(final_slot)
            assert match is not None
            try:
                date.fromisoformat(match.group("date"))
                if parse_hhmm(match.group("end")) <= parse_hhmm(match.group("start")):
                    raise ValueError(final_slot)
            except ValueError:
                failures.append(f"final_slot 날짜/시간 값이 유효하지 않음: {final_slot!r}")
        if payload.get("needs_agent_selection") is not False:
            failures.append(f"확정 시 needs_agent_selection=false여야 함: {payload}")
        selected = selected_candidate(payload)
        if selected is None:
            failures.append(f"확정 시 유효한 selected_index 또는 selected_slot이 필요함: {payload}")
        elif selected not in (payload.get("candidate_slots") or []):
            failures.append(f"selected_slot이 검증된 후보에 포함되지 않음: {payload}")
        elif final_slot and slot_to_text(selected) != final_slot:
            failures.append(
                "final_slot이 선택된 후보와 일치하지 않음: "
                f"selected={selected!r}, final_slot={final_slot!r}"
            )
        expected_candidate_texts = [
            slot_to_text(candidate) for candidate in payload.get("candidate_slots") or []
        ]
        if payload.get("candidates") != expected_candidate_texts:
            failures.append(
                "candidates 요약이 candidate_slots와 일치하지 않음: "
                f"expected={expected_candidate_texts!r}, actual={payload.get('candidates')!r}"
            )
    if state == "pending":
        if payload.get("final_slot") is not None:
            failures.append(f"미확정 시 final_slot은 null이어야 함: {payload}")
        if payload.get("needs_agent_selection") is not True:
            failures.append(f"미확정 시 needs_agent_selection=true여야 함: {payload}")
    if expectation.get("require_evidence"):
        for key in ("members", "busy_rows", "candidate_slots"):
            if key not in payload:
                failures.append(f"최종 payload 근거 key 누락: {key}, payload={payload}")
    expected_members = expectation.get("members_exact")
    if expected_members is not None:
        actual_members = payload.get("members")
        if not isinstance(actual_members, list) or sorted(actual_members) != sorted(expected_members):
            failures.append(
                f"최종 payload members 불일치: expected={expected_members}, actual={actual_members}"
            )
    if expectation.get("answer_matches") and payload.get("final_slot"):
        if not answer_mentions_final_slot(result.answer, payload["final_slot"]):
            failures.append(
                "최종 답변이 final_slot과 일치하지 않음: "
                f"slot={payload['final_slot']!r}, answer={result.answer!r}"
            )
    return failures


def check_answer(turn: dict[str, Any], answer: str) -> list[str]:
    failures: list[str] = []
    for text in turn.get("expect_answer_contains_all", []):
        if text not in answer:
            failures.append(f"답변에 필수 문구가 없음: {text!r}, answer={answer!r}")
    any_values = turn.get("expect_answer_contains_any", [])
    if any_values and not any(text in answer for text in any_values):
        failures.append(f"답변에 기대 문구 중 하나도 없음: {any_values}, answer={answer!r}")
    for text in turn.get("expect_answer_not_contains", []):
        if text in answer:
            failures.append(f"답변에 금지 문구가 포함됨: {text!r}, answer={answer!r}")
    if turn.get("expect_no_final_slot_in_answer") and FINAL_SLOT_IN_TEXT_PATTERN.search(answer):
        failures.append(f"미확정 답변에 최종 시간 형식이 포함됨: answer={answer!r}")
    return failures


def check_find_result_dates(turn: dict[str, Any], inner_events: list[dict[str, Any]]) -> list[str]:
    check_dates = turn.get("expect_find_result_dates")
    expected_members = turn.get("expect_find_members_exact")
    if not check_dates and expected_members is None:
        return []
    results = tool_results(inner_events, "find_common_available_slots")
    if not results:
        return ["find 결과가 없어 정규화된 날짜 범위를 확인할 수 없음"]
    content = results[-1].get("content")
    if not isinstance(content, dict):
        return [f"find 결과가 JSON object가 아님: {content!r}"]
    failures: list[str] = []
    if expected_members is not None:
        actual_members = content.get("members")
        if not isinstance(actual_members, list) or sorted(actual_members) != sorted(expected_members):
            failures.append(
                f"find 결과 members 불일치: expected={expected_members}, actual={actual_members}"
            )
    candidates = content.get("candidate_slots")
    if check_dates:
        for candidate in candidates or []:
            candidate_date = candidate.get("date") if isinstance(candidate, dict) else None
            if not isinstance(candidate_date, str) or "T" in candidate_date:
                failures.append(f"후보 날짜가 YYYY-MM-DD로 정규화되지 않음: {candidate!r}")
    return failures


def check_final_evidence_matches_source(
    turn: dict[str, Any],
    inner_events: list[dict[str, Any]],
    trace: dict[str, Any],
) -> list[str]:
    source_name = turn.get("expect_busy_rows_from")
    if not source_name:
        return []
    source_results = tool_results(inner_events, source_name)
    payload = trace.get("final_slot_payload")
    if not source_results or not isinstance(payload, dict):
        return []
    source_content = source_results[-1].get("content")
    source_rows = source_content.get("rows") if isinstance(source_content, dict) else None
    if payload.get("busy_rows") != source_rows:
        return [
            f"{source_name} rows가 final_slot_payload 근거에 보존되지 않음: "
            f"source={source_rows!r}, payload={payload.get('busy_rows')!r}"
        ]
    return []


def check_turn(turn: dict[str, Any], result: Any) -> list[str]:
    trace = result.trace if isinstance(result.trace, dict) else {}
    outer_events = trace.get("events") or []
    expected_agent = turn["expected_agent"]
    inner_events = inner_events_from(outer_events, expected_agent)

    failures = check_wrapper_contract(turn, trace, outer_events)
    failures.extend(check_inner_tools(turn, inner_events))
    failures.extend(check_busy_rows_forwarding(turn, inner_events))
    failures.extend(check_load_source_id(turn, inner_events))
    failures.extend(check_candidate_contract(turn, inner_events))
    failures.extend(check_decide_uses_validated_candidates(turn, inner_events))
    failures.extend(check_find_result_dates(turn, inner_events))
    failures.extend(check_final_payload(turn, result, trace))
    failures.extend(check_final_evidence_matches_source(turn, inner_events, trace))
    failures.extend(check_answer(turn, result.answer or ""))
    if trace.get("error"):
        failures.append(f"Agent 실행 오류: {trace['error']}")
    return failures


def selected_scenarios(
    scenarios: list[dict[str, Any]],
    requested_ids: list[str],
) -> list[dict[str, Any]]:
    if not requested_ids:
        return scenarios
    requested = set(requested_ids)
    selected = [scenario for scenario in scenarios if scenario.get("id") in requested]
    missing = requested - {str(scenario.get("id")) for scenario in selected}
    if missing:
        raise ValueError(f"존재하지 않는 scenario id: {sorted(missing)}")
    return selected


def should_skip_turn(turn: dict[str, Any], state_chain_blocked: bool) -> bool:
    """이전 실패로 필요한 상태가 없을 때 명시적으로 의존하는 turn만 건너뜁니다."""

    return bool(turn.get("depends_on_previous_turn") and state_chain_blocked)


def seed_conversation_messages(scenario: dict[str, Any]) -> None:
    rows = scenario.get("seed_conversation_messages") or []
    if not rows:
        return
    from fixed.app_store import AppSQLiteStore
    from fixed.config import CONFIG

    store = AppSQLiteStore(CONFIG.app_db_path)
    conversation = store.create_conversation(
        str(scenario.get("seed_conversation_title") or "Week 6 E2E 이전 대화")
    )
    for row in rows:
        store.append_message(
            conversation["conversation_id"],
            str(row.get("role") or "user"),
            str(row.get("content") or ""),
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=Path, default=SCRIPT_DIR / "scenarios.json")
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--keep-runtime", action="store_true")
    args = parser.parse_args()

    runtime_dir = configure_isolated_runtime()
    failures: list[str] = []
    skipped_turns = 0
    try:
        from fixed.session_scope import conversation_session_scope
        from fixed.week_agent_registry import run_active_week_agent

        all_scenarios = json.loads(args.scenarios.read_text(encoding="utf-8"))
        scenarios = selected_scenarios(all_scenarios, args.scenario)
        for scenario in scenarios:
            seed_conversation_messages(scenario)
            history: list[dict[str, str]] = []
            state_chain_blocked = False
            turns = scenario.get("turns") or [{**scenario, "message": scenario["message"]}]
            for turn_index, turn in enumerate(turns, start=1):
                if should_skip_turn(turn, state_chain_blocked):
                    skipped_turns += 1
                    print(
                        f"[SKIP] {scenario['id']} turn={turn_index} "
                        "(상태를 만드는 선행 turn 실패)"
                    )
                    continue
                history.append({"role": "user", "content": turn["message"]})
                with conversation_session_scope(f"week06-e2e-{scenario['id']}"):
                    result = run_active_week_agent(6, history)
                history.append({"role": "assistant", "content": result.answer})
                turn_failures = check_turn(turn, result)
                status = "PASS" if not turn_failures else "FAIL"
                print(f"[{status}] {scenario['id']} turn={turn_index}")
                if turn_failures:
                    wrapper_content = wrapper_result_content(
                        result.trace.get("events") or [],
                        turn["expected_agent"],
                    )
                    if isinstance(wrapper_content, dict) and "retry_count" in wrapper_content:
                        print(
                            "  - [진단] 하위 agent retry_count="
                            f"{wrapper_content['retry_count']}"
                        )
                    supervisor_retry_count = result.trace.get("supervisor_retry_count")
                    if supervisor_retry_count is not None:
                        print(
                            "  - [진단] supervisor_retry_count="
                            f"{supervisor_retry_count}"
                        )
                for failure in turn_failures:
                    print(f"  - {failure}")
                failures.extend(
                    f"{scenario['id']} turn={turn_index}: {item}"
                    for item in turn_failures
                )
                state_chain_blocked = bool(turn_failures)
    finally:
        if args.keep_runtime:
            print(f"runtime preserved: {runtime_dir}")
        else:
            shutil.rmtree(runtime_dir, ignore_errors=True)

    if failures:
        print(f"Week06 E2E failed: {len(failures)} (skipped turns: {skipped_turns})")
        return 1
    print(f"Week06 E2E passed (skipped turns: {skipped_turns})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
