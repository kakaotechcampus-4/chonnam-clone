"""Week 6 트레이스 — 리뷰 ③: 혼합 요청(시간 찾기→저장) 2단계 위임이 왜 불안정한가.

배경
    PR 본문은 "시간 찾고 저장까지" 같은 혼합 요청에서 Kana→Nana 2단계 위임이 unstable하다고만
    적었습니다. 리뷰어(GitJIHO)는 이게 구조적 한계인지 프롬프트 튜닝 문제인지 갈라달라고 했습니다.
    가이드 기본은 '요청당 하나 위임'이라, supervisor가 한 번 위임하고 끝내는지(구조적) 아니면
    실행마다 2단계가 됐다 안 됐다 하는지(프롬프트) 반복 실행 분포로 판정합니다.

무엇을 보나요
    동일한 혼합 발화를 N회 돌려 매 실행의 supervisor 위임 순서를 모읍니다. 집계:
      · kana만: 시간만 찾고 끝 (저장 누락)
      · kana→nana: 의도한 2단계 (시간 찾고 저장)
      · nana만 / 그 외: 라우팅 자체가 어긋남
    저장 도구가 Nana 내부에서 실제로 돌았는지도 함께 봅니다.

    판정(사람이 읽고):
      · 항상 kana만 → 구조적(한 번 위임에서 멈춤). 2단계가 필요하면 supervisor가 여러 번
        위임하도록 프롬프트/구조를 바꿔야 함.
      · kana→nana가 실행마다 갈림 → 프롬프트 튜닝 문제(위임 지시를 더 강하게).

실행:
    KANANA_ACTIVE_WEEK=6 PYTHONNOUSERSITE=1 uv run python trace_week06_mixed_stability.py

주의
    실제로 일정을 저장할 수 있으므로 끝에서 실행 중 생긴 row를 정리합니다.
"""

from __future__ import annotations

from collections import Counter

from fixed.config import CONFIG
from fixed.langchain_trace import extract_agent_events
from fixed.session_scope import conversation_session_scope
from fixed.langchain_trace import extract_final_text
from student_parts.week06_kanamate_decides_schedule import build_week_agent
from trace_week06_common import app_ids, cleanup_new_rows, shared_ids

MIXED_UTTERANCE = (
    "철수랑 2026년 7월 10일에 회의할 수 있는 시간을 먼저 찾고, "
    "정해지면 그 회의를 내 일정으로 저장까지 해줘."
)
REPEAT = 6
SAVE_TOOLS = {"save_structured_request", "personal_create_schedule", "create_shared_schedule"}


def _supervisor_calls(result: dict) -> list[str]:
    return [
        ev["tool_name"]
        for ev in extract_agent_events(result)
        if ev.get("event") == "tool_call" and ev.get("tool_name") in {"nana_agent", "kana_agent"}
    ]


def _inner_tool_names(result: dict, agent_name: str) -> list[str]:
    names: list[str] = []
    for ev in extract_agent_events(result):
        if ev.get("event") == "tool_result" and ev.get("tool_name") == agent_name:
            content = ev.get("content")
            if isinstance(content, dict):
                names.extend(content.get("inner_tool_names") or [])
    return names


def _classify(calls: list[str]) -> str:
    has_k = "kana_agent" in calls
    has_n = "nana_agent" in calls
    if has_k and has_n:
        return "kana→nana" if calls.index("kana_agent") < calls.index("nana_agent") else "nana→kana"
    if has_k:
        return "kana만"
    if has_n:
        return "nana만"
    return "위임없음"


def run() -> int:
    if not CONFIG.has_openai_key:
        print("⚠️ .env의 PROXY_TOKEN이 필요합니다. 키를 넣고 다시 실행하세요.")
        return 1

    print("#" * 78)
    print("# Week 6 트레이스 — 리뷰 ③: 혼합 요청 2단계 위임 안정성 (구조적 vs 프롬프트)")
    print("#" * 78)
    print(f"발화: {MIXED_UTTERANCE}\n반복: {REPEAT}회\n")

    app_before, shared_before = app_ids(), shared_ids()
    agent = build_week_agent()

    dist: Counter[str] = Counter()
    saved_count = 0
    try:
        for i in range(1, REPEAT + 1):
            with conversation_session_scope(f"trace_w6_mixed_{i}"):
                result = agent.invoke({"messages": [{"role": "user", "content": MIXED_UTTERANCE}]})
            calls = _supervisor_calls(result)
            shape = _classify(calls)
            dist[shape] += 1
            nana_inner = _inner_tool_names(result, "nana_agent")
            saved = bool(SAVE_TOOLS & set(nana_inner))
            saved_count += int(saved)
            ans = extract_final_text(result)[:120].replace("\n", " ")
            print(f"  run{i}: [{shape}] 위임={' → '.join(calls) or '(없음)'}"
                  f" | Nana저장도구={saved} | 답변앞={ans}")
    finally:
        cleanup_new_rows(app_before, shared_before)

    print("\n" + "=" * 78)
    print("요약 — 위임 형태 분포")
    print("-" * 78)
    for shape, n in dist.most_common():
        print(f"  {shape:10s}: {n}/{REPEAT}")
    print(f"  Nana 저장도구 실제 실행: {saved_count}/{REPEAT}")
    print("\n판정(사람이 읽고):")
    print("  · 'kana만'이 대부분 → 구조적: supervisor가 한 번 위임하고 멈춤(가이드 기본).")
    print("    2단계가 필요하면 supervisor가 재위임하도록 구조/프롬프트를 바꿔야 함.")
    print("  · 'kana→nana'가 실행마다 들쭉날쭉 → 프롬프트 튜닝 문제(위임 지시 강화로 개선 가능).")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
