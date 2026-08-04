"""Week 5 트레이스 전체 실행기.

실행:
    KANANA_ACTIVE_WEEK=5 PYTHONNOUSERSITE=1 uv run python trace_week05.py            # 전부
    KANANA_ACTIVE_WEEK=5 PYTHONNOUSERSITE=1 uv run python trace_week05.py history edge   # 골라서

목적별로 쪼갠 이유
    한 대본에 케이스를 몰아넣으면 대화가 길어지고, 뒤쪽 턴은 도구를 부르지 않고 앞 대화
    기억으로 답해 버립니다(30턴 한 번에 돌렸을 때 실제로 관찰됨). 그러면 그 케이스는
    검증력을 잃습니다. 그래서 대본을 목적별로 나누고, 각 대본은 **대화를 새로 시작**합니다.

대본 목록
    history   외부 과거 대화 검색 → 로드, 빈 query·limit 상한·없는 id 경계
    schedules 외부 멤버 busy-time + 내 일정 병합(스키마·"나" 포함/제외·배치 호출)
    shared    공유 일정 저장소 조회·등록·갱신·삭제 (추가 과제)
    edge      환각·도구 오류·확인 없는 등록·기간 미지정·"미정" 종료 시간
    state     상태 변화(생성→수정→삭제 반영)와 주차 연결(week4 RAG + week5 MCP)

    개별 실행도 됩니다:  uv run python trace_week05_edge.py

⚠️ schedules·edge·state 는 앱 DB와 공유 저장소를 실제로 변경하고, 끝에서 정리합니다.
   전부 돌리면 LLM 호출이 40턴을 넘습니다(대본마다 대화는 새로 시작).
"""

from __future__ import annotations

import sys

import trace_week05_edge
import trace_week05_history
import trace_week05_schedules
import trace_week05_shared
import trace_week05_state
from fixed.config import CONFIG

SCRIPTS = {
    "history": trace_week05_history,
    "schedules": trace_week05_schedules,
    "shared": trace_week05_shared,
    "edge": trace_week05_edge,
    "state": trace_week05_state,
}


def main(argv: list[str]) -> int:
    if not CONFIG.has_openai_key:
        print("⚠️ .env의 PROXY_TOKEN이 필요합니다. 키를 넣고 다시 실행하세요.")
        return 1

    names = argv or list(SCRIPTS)
    unknown = [n for n in names if n not in SCRIPTS]
    if unknown:
        print(f"❌ 모르는 대본: {', '.join(unknown)}")
        print(f"   고를 수 있는 것: {', '.join(SCRIPTS)}")
        return 1

    results: dict[str, int] = {}
    for name in names:
        results[name] = SCRIPTS[name].run()

    print("\n" + "=" * 78)
    print("전체 요약")
    print("-" * 78)
    for name, code in results.items():
        print(f"  {'✅' if code == 0 else '❌'}  {name}")
    failed = [n for n, c in results.items() if c != 0]
    if failed:
        print(f"\n실패한 대본: {', '.join(failed)}")
        print("(각 대본의 요약에서 ❌ 항목과 tool_call args를 함께 확인하세요.)")
    else:
        print("\n모든 대본 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
