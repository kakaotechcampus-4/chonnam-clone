"""Week 2 agent 트레이스 보기 대본.

실행:
    KANANA_ACTIVE_WEEK=2 PYTHONNOUSERSITE=1 .venv/Scripts/python.exe trace_week02.py

agent.invoke 결과에서 fixed/langchain_trace.py 헬퍼로
tool 호출/결과(events)와 최종 structured_response를 보여줍니다.
- 첫 입력은 week01 tool(personal_create_schedule)을 부르는 흐름 → tool_call/tool_result가 보입니다.
- 둘째 입력은 순수 자연어 구조화 → tool 없이 structured_response만 나올 수 있습니다.
"""

from __future__ import annotations

import json

from fixed.langchain_trace import extract_agent_events, extract_final_text
from student_parts.week02_structure_natural_language_requests import build_week02_agent

INPUTS = [
    "내일 오전 9시에 개인 코딩 공부 일정 만들어줘",     # week01 tool 흐름 유도
    "다음 주 화요일 오후 3시에 철수랑 회의 잡아줘",     # 순수 자연어 구조화
]


def show(text: str, agent) -> None:
    print("=" * 72)
    print(f"입력: {text}")
    res = agent.invoke({"messages": [{"role": "user", "content": text}]})

    events = extract_agent_events(res)
    print(f"\n[TRACE] events {len(events)}개")
    if not events:
        print("  (tool 호출 없음 — 모델이 바로 구조화)")
    for i, ev in enumerate(events, 1):
        if ev["event"] == "tool_call":
            print(f"  {i}. [call]   tool_call   {ev['tool_name']}  args={json.dumps(ev['arguments'], ensure_ascii=False)}")
        else:
            content = ev["content"]
            preview = json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content
            print(f"  {i}. [result] tool_result {ev['tool_name']}  -> {preview[:200]}")

    print(f"\n[최종 답변 텍스트]\n  {extract_final_text(res)[:300]}")

    sr = res.get("structured_response")
    print("\n[structured_response]")
    if sr is not None and hasattr(sr, "model_dump"):
        print("  " + json.dumps(sr.model_dump(), ensure_ascii=False, indent=2).replace("\n", "\n  "))
    else:
        print(f"  {sr}")
    print()


def main() -> None:
    agent = build_week02_agent()
    for text in INPUTS:
        show(text, agent)


if __name__ == "__main__":
    main()
