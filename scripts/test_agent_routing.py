"""Agent tool 라우팅 회귀 테스트.

프롬프트를 고칠 때마다 브라우저로 손으로 재확인하는 대신, 정해둔 질문 목록을
실제 agent에 던져서 기대한 tool이 호출됐는지 자동으로 확인합니다.

LLM을 실제로 호출하므로 완전히 결정적이지는 않습니다. 그래서 "정확한 답변 문구"가
아니라 "이 tool이 호출됐는가"만 느슨하게 검증합니다.

사용법:
    uv run python scripts/test_agent_routing.py            # 전체 케이스
    uv run python scripts/test_agent_routing.py --week 6   # 특정 주차만
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
]


def tool_call_names(trace: dict) -> list[str]:
    return [
        event["tool_name"]
        for event in trace.get("events", [])
        if event.get("event") == "tool_call" and event.get("tool_name")
    ]


def run_case(case: dict) -> bool:
    result = run_active_week_agent(case["week"], [{"role": "user", "content": case["query"]}])
    called = tool_call_names(result.trace)
    expected = case["expect_tool"]
    passed = expected in called

    status = "PASS" if passed else "FAIL"
    print(f'[{status}] week{case["week"]} · "{case["query"]}"')
    print(f"       기대: {expected}")
    print(f"       실제 호출된 tool: {called or '(없음)'}")
    if not passed:
        print(f"       answer: {result.answer[:200]}")
    print()
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description="agent tool 라우팅 회귀 테스트")
    parser.add_argument("--week", type=int, default=None, help="이 주차만 테스트 (기본: 전체)")
    args = parser.parse_args()

    cases = [case for case in TEST_CASES if args.week is None or case["week"] == args.week]
    if not cases:
        print(f"week {args.week}에 대한 테스트 케이스가 없습니다.")
        return

    results = [run_case(case) for case in cases]
    passed_count = sum(results)
    print(f"결과: {passed_count}/{len(results)} passed")
    if passed_count < len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
