"""Agent tool 라우팅 회귀 테스트.

프롬프트를 고칠 때마다 브라우저로 손으로 재확인하는 대신, 정해둔 질문 목록을
실제 agent에 던져서 기대한 tool이 호출됐는지 자동으로 확인합니다.

LLM은 확률적인 결과를 내놓기 때문에 한 번만 돌려서 PASS/FAIL로 보면 오해하기
쉽습니다. 그래서 케이스마다 여러 번 반복 호출하고 통과율(passed/samples)로
집계합니다. 프롬프트를 고친 뒤 이 통과율이 이전보다 올랐는지/내렸는지를 비교
기준으로 씁니다.

사용법:
    uv run python scripts/test_agent_routing.py                  # 전체 케이스, 케이스당 1회
    uv run python scripts/test_agent_routing.py --samples 5       # 케이스당 5회 반복
    uv run python scripts/test_agent_routing.py --week 6 --samples 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fixed.week_agent_registry import run_active_week_agent


TEST_CASES = [
    {"week": 4, "query": "나 오전 회의 선호한다고 했었나?", "expect_tool": "search_personal_references"},
    {"week": 4, "query": "등록해둔 할 일이나 일정 뭐 있어?", "expect_tool": "list_saved_requests"},
    {"week": 5, "query": "철수는 이번 주에 언제 바빠?", "expect_tool": "extract_schedules_from_history"},
    {"week": 5, "query": "철수랑 저번에 무슨 얘기 했었지?", "expect_tool": "search_previous_conversations"},
    {"week": 5, "query": "나랑 철수, 영희 다 같이 언제 비어?", "expect_tool": "collect_member_schedules"},
    {"week": 6, "query": "나 오전 회의 선호한다고 했었나?", "expect_tool": "nana_agent"},
    {"week": 6, "query": "철수는 이번 주에 언제 바빠?", "expect_tool": "kana_agent"},
    {
        "week": 6,
        "query": "지훈이랑 아무 때나 괜찮은 걸로 8월 20일부터 22일 사이에 회의 하나 잡아줘",
        "expect_tool": "kana_agent",
        "expect_final_slot": True,
    },
]


def tool_call_names(trace: dict) -> list[str]:
    return [
        event["tool_name"]
        for event in trace.get("events", [])
        if event.get("event") == "tool_call" and event.get("tool_name")
    ]


def case_passed(case: dict, called: list[str], result) -> bool:
    if case["expect_tool"] not in called:
        return False
    if case.get("expect_final_slot"):
        final_slot_payload = result.trace.get("final_slot_payload")
        if not final_slot_payload or not final_slot_payload.get("final_slot"):
            return False
    return True


def run_case(case: dict, samples: int) -> tuple[int, int]:
    passed = 0
    for i in range(samples):
        result = run_active_week_agent(case["week"], [{"role": "user", "content": case["query"]}])
        called = tool_call_names(result.trace)
        ok = case_passed(case, called, result)
        passed += int(ok)
        if not ok:
            print(f'  시도 {i + 1}/{samples}: FAIL · 실제 호출: {called or "(없음)"}')
            print(f"    answer: {result.answer[:150]}")
    return passed, samples


def main() -> None:
    parser = argparse.ArgumentParser(description="agent tool 라우팅 회귀 테스트")
    parser.add_argument("--week", type=int, default=None, help="이 주차만 테스트 (기본: 전체)")
    parser.add_argument("--samples", type=int, default=1, help="케이스당 반복 횟수 (기본: 1)")
    args = parser.parse_args()

    cases = [case for case in TEST_CASES if args.week is None or case["week"] == args.week]
    if not cases:
        print(f"week {args.week}에 대한 테스트 케이스가 없습니다.")
        return

    total_passed = 0
    total_samples = 0
    for case in cases:
        print(f'week{case["week"]} · "{case["query"]}" (기대: {case["expect_tool"]})')
        passed, samples = run_case(case, args.samples)
        rate = passed / samples * 100
        print(f"  통과율: {passed}/{samples} ({rate:.0f}%)\n")
        total_passed += passed
        total_samples += samples

    overall_rate = total_passed / total_samples * 100
    print(f"전체 결과: {total_passed}/{total_samples} ({overall_rate:.0f}%)")
    if total_passed < total_samples:
        sys.exit(1)


if __name__ == "__main__":
    main()
