"""Week 6 prompt 변경 뒤 supervisor routing 회귀를 확인하는 고정 케이스입니다."""

import argparse
import json
from dataclasses import dataclass
from typing import Any

from fixed.session_scope import conversation_session_scope
from student_parts import week06_kanamate_decides_schedule as week06


@dataclass(frozen=True)
class RoutingCase:
    name: str
    query: str
    selected_agent: str
    required_tools: tuple[str, ...]
    forbidden_outer_tools: tuple[str, ...] = ()
    empty_arguments: tuple[str, ...] = ()


CASES = (
    RoutingCase(
        name="saved_personal_schedule_without_date_filter",
        query="철수랑 잡은 회의 언제였지?",
        selected_agent="nana_agent",
        required_tools=("personal_list_saved_schedules",),
        forbidden_outer_tools=("kana_agent",),
        empty_arguments=("date_from", "date_to"),
    ),
    RoutingCase(
        name="external_conversation",
        query="민준이 지난 대화 목록을 찾아줘.",
        selected_agent="kana_agent",
        required_tools=("search_previous_conversations",),
        forbidden_outer_tools=("nana_agent",),
    ),
    RoutingCase(
        name="group_schedule_without_save",
        query="민준이랑 2026년 7월 14일에 1시간 회의 시간 맞춰줘.",
        selected_agent="kana_agent",
        required_tools=(
            "extract_schedule_request",
            "collect_member_schedules",
            "find_common_available_slots",
            "decide_final_slot",
        ),
        forbidden_outer_tools=("nana_agent",),
    ),
)


def run_case(case: RoutingCase, attempt: int) -> dict[str, Any]:
    agent = week06.build_week_agent()
    with conversation_session_scope(f"week06-routing-{case.name}-{attempt}"):
        result = agent.invoke({"messages": [{"role": "user", "content": case.query}]})
    trace = week06.extract_langchain_trace(result)
    outer_tools = [
        event["tool_name"]
        for event in trace["events"]
        if event.get("event") == "tool_call" and event.get("tool_name") in {"nana_agent", "kana_agent"}
    ]
    inner_tools = trace["inner_tool_names"]
    inner_events = [
        inner_event
        for event in trace["events"]
        if event.get("event") == "tool_result" and isinstance(event.get("content"), dict)
        for inner_event in event["content"].get("trace", [])
    ]
    required_tool_calls = [
        event
        for event in inner_events
        if event.get("event") == "tool_call" and event.get("tool_name") in case.required_tools
    ]
    failures: list[str] = []

    if trace["supervisor_selected_agent"] != case.selected_agent:
        failures.append(f"selected_agent={trace['supervisor_selected_agent']}")
    for tool_name in case.required_tools:
        if tool_name not in inner_tools:
            failures.append(f"missing_inner_tool={tool_name}")
    for tool_name in case.forbidden_outer_tools:
        if tool_name in outer_tools:
            failures.append(f"forbidden_outer_tool={tool_name}")
    if case.empty_arguments and required_tool_calls:
        arguments = required_tool_calls[-1].get("arguments") or {}
        for argument_name in case.empty_arguments:
            if arguments.get(argument_name) not in {None, ""}:
                failures.append(f"expected_empty_argument={argument_name}")

    return {
        "case": case.name,
        "query": case.query,
        "passed": not failures,
        "failures": failures,
        "selected_agent": trace["supervisor_selected_agent"],
        "outer_tools": outer_tools,
        "inner_tools": inner_tools,
        "checked_arguments": required_tool_calls[-1].get("arguments") if required_tool_calls else None,
        "final_slot": (trace["final_slot_payload"] or {}).get("final_slot"),
    }


def run_missing_date_range_case() -> dict[str, Any]:
    payload = week06.find_common_available_slots_dict(
        member_names=["민준"],
        date_from="",
        date_to="",
        candidate_slots=[],
    )
    passed = (
        payload.get("ok") is False
        and payload.get("reason") == "missing_date_range"
        and payload.get("candidate_slots") == []
    )
    return {
        "case": "group_schedule_missing_date_range",
        "passed": passed,
        "failures": [] if passed else ["missing_date_range_was_not_propagated"],
        "payload": payload,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Week 6 supervisor routing regression check")
    parser.add_argument("--repeat", type=int, default=1, help="각 고정 케이스 반복 횟수")
    parser.add_argument(
        "--case",
        choices=[case.name for case in CASES] + ["group_schedule_missing_date_range"],
        help="실행할 고정 케이스 이름",
    )
    args = parser.parse_args()

    selected_cases = CASES if args.case is None else tuple(case for case in CASES if case.name == args.case)
    results = [run_case(case, attempt) for attempt in range(1, args.repeat + 1) for case in selected_cases]
    if args.case in {None, "group_schedule_missing_date_range"}:
        results.append(run_missing_date_range_case())
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if any(not result["passed"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
