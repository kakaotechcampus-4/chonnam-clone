"""Week 6 트레이스 — 위임 구조가 의도대로 도는가 (역할 경계·혼합·역방향 회귀).

실행:
    KANANA_ACTIVE_WEEK=6 PYTHONNOUSERSITE=1 uv run python trace_week06_delegation.py

무엇을 보나요
    ① 역할 경계 — 하위 agent를 직접 호출해 담당을 넘어서지 않는지 격리 확인
       · Nana에 그룹 조율을 시키면: 조율 도구를 부르지 못하고(없음), 일정을 저장하지도 않고,
         그룹 담당(Kana)에게 넘기라고 답한다.
       · Kana에 개인 저장을 시키면: 저장 도구를 부르지 못하고(없음),
         저장은 개인 담당(Nana)이라고 답한다.
    ② 혼합 요청 — "시간을 찾고 저장까지" 한 요청. 하드 판정은 'Kana에 위임해 시간을 찾는가'까지.
       저장(Nana)까지 잇는 2단계 위임은 가이드 기본이 '요청당 하나 위임'이라 보장 밖 → 관찰(➖)로만.
    ③ 역방향 회귀 — 6주차 supervisor에서도 1~4주차 개인 기능이 Nana 경로로 살아 있는가.
       하드 판정은 'Nana로 위임되는가'. Nana 하위에서 어떤 tool이 도는지는 관찰 —
       nana_agent는 가이드 spec상 week4의 retrieval_gate 없이 만들어져 검색 여부가 모델 판단이다.

    ①은 하위 tool을 직접 invoke합니다(supervisor 우회). ②③은 supervisor를 거칩니다.
    각 supervisor 케이스는 대화를 새로 시작합니다.

주의
    ②는 실제로 일정을 저장하므로 앱 DB/공유 저장소가 변합니다. 끝에서 실행 중 생긴 row를 정리합니다.
"""

from __future__ import annotations

import json

from fixed.config import CONFIG
from fixed.langchain_trace import extract_agent_events
from fixed.session_scope import conversation_session_scope
from student_parts.week06_kanamate_decides_schedule import (
    build_week_agent,
    extract_langchain_trace,
    kana_agent,
    nana_agent,
)
from trace_week06_common import app_ids, cleanup_new_rows, shared_ids

COORD_TOOLS = {
    "collect_member_schedules",
    "find_common_available_slots",
    "decide_final_slot",
    "extract_schedules_from_history",
}
SAVE_TOOLS = {"save_structured_request", "personal_create_schedule", "create_shared_schedule"}
REDIRECT_TO_KANA = ("kana", "카나", "그룹", "조율", "담당", "할 수 없", "제 역할", "권한")
REDIRECT_TO_NANA = ("nana", "나나", "개인", "저장 담당", "담당", "직접 저장", "할 수 없")


def _call_subagent(subagent_tool: object, query: str) -> dict:
    """하위 agent tool을 직접 호출하고 결과 JSON을 dict로 돌려줍니다."""

    return json.loads(subagent_tool.invoke({"query": query}))


def _run_supervisor(agent: object, session_id: str, text: str) -> tuple[dict, dict]:
    with conversation_session_scope(session_id):
        result = agent.invoke({"messages": [{"role": "user", "content": text}]})
    return extract_langchain_trace(result), result


def _supervisor_agent_calls(result: dict) -> list[str]:
    """supervisor가 부른 하위 agent tool 이름을 호출 순서대로 모읍니다."""

    return [
        ev["tool_name"]
        for ev in extract_agent_events(result)
        if ev.get("event") == "tool_call" and ev.get("tool_name") in {"nana_agent", "kana_agent"}
    ]


def _inner_tool_names(result: dict, agent_name: str) -> list[str]:
    """supervisor 결과에서 특정 하위 agent의 내부 tool 이름을 모읍니다."""

    names: list[str] = []
    for ev in extract_agent_events(result):
        if ev.get("event") == "tool_result" and ev.get("tool_name") == agent_name:
            content = ev.get("content")
            if isinstance(content, dict):
                names.extend(content.get("inner_tool_names") or [])
    return names


def run() -> int:
    if not CONFIG.has_openai_key:
        print("⚠️ .env의 PROXY_TOKEN이 필요합니다. 키를 넣고 다시 실행하세요.")
        return 1

    passed = 0
    failed: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal passed
        if ok:
            passed += 1
            print(f"     ✅ {label}")
        else:
            failed.append(label)
            print(f"     ❌ {label}" + (f"  ({detail})" if detail else ""))

    def observe(label: str, ok: bool, detail: str = "") -> None:
        """보장 밖 동작(모델 판단·가이드 spec 경계)은 실패로 세지 않고 관찰만 남깁니다."""

        mark = "✅(관찰)" if ok else "➖(관찰)"
        print(f"     {mark} {label}" + (f"  ({detail})" if detail else ""))

    print("#" * 78)
    print("# Week 6 위임 대본 — 역할 경계 · 혼합 요청 · 역방향 회귀")
    print("#" * 78)

    app_before = app_ids()
    shared_before = shared_ids()
    agent = build_week_agent()

    try:
        # ── ① 역할 경계: Nana에 그룹 조율을 직접 시킨다
        print("\n" + "=" * 78)
        print("[01] (경계) Nana에 직접: '철수랑 영희가 공통으로 비는 회의 시간을 찾아줘.'")
        n = _call_subagent(nana_agent, "철수랑 영희가 공통으로 비는 회의 시간을 찾아줘.")
        n_inner = n.get("inner_tool_names") or []
        print(f"     Nana 내부 도구: {n_inner}")
        print(f"     [답변] {str(n.get('answer'))[:200].strip()}")
        # 하드 보장: Nana는 조율/저장 도구 자체를 갖지 않으므로 구조적으로 넘어설 수 없다.
        check("Nana는 조율 도구를 부르지 못함(담당 아님)",
              not (COORD_TOOLS & set(n_inner)), str(n_inner))
        check("Nana는 그룹 요청을 일정으로 저장하지 않음",
              not (SAVE_TOOLS & set(n_inner)), str(n_inner))
        # 답변 문구로 Kana에 넘기는지는 모델 표현마다 달라지는 자유텍스트라 관찰만 합니다.
        # (구조적 경계 — 조율/저장 도구를 못 가짐 — 은 위 두 check에서 이미 보장됩니다.)
        observe("Nana 답변이 그룹/조율 담당으로 넘김",
                any(k in str(n.get("answer", "")).lower() for k in REDIRECT_TO_KANA),
                str(n.get("answer"))[:120])

        # ── ① 역할 경계: Kana에 개인 저장을 직접 시킨다
        print("\n" + "=" * 78)
        print("[02] (경계) Kana에 직접: '2026년 7월 9일 14시 팀 회의를 내 개인 일정으로 저장해줘.'")
        k = _call_subagent(kana_agent, "2026년 7월 9일 14시 팀 회의를 내 개인 일정으로 저장해줘.")
        k_inner = k.get("inner_tool_names") or []
        print(f"     Kana 내부 도구: {k_inner}")
        print(f"     [답변] {str(k.get('answer'))[:200].strip()}")
        check("Kana는 저장 도구를 부르지 못함(담당 아님)",
              not (SAVE_TOOLS & set(k_inner)), str(k_inner))
        observe("Kana 답변이 개인 저장 담당(Nana)으로 넘김",
                any(k2 in str(k.get("answer", "")).lower() for k2 in REDIRECT_TO_NANA),
                str(k.get("answer"))[:120])

        # ── ② 혼합 요청: 시간 찾기(Kana) + 저장(Nana)
        print("\n" + "=" * 78)
        q3 = "철수랑 2026년 7월 10일에 회의할 수 있는 시간을 먼저 찾고, 정해지면 그 회의를 내 일정으로 저장까지 해줘."
        print(f"[03] (혼합) {q3}")
        t3, r3 = _run_supervisor(agent, "trace_week06_mixed", q3)
        calls3 = _supervisor_agent_calls(r3)
        print(f"     supervisor 위임 순서: {' → '.join(calls3) or '(없음)'}")
        print(f"     Kana 내부: {_inner_tool_names(r3, 'kana_agent')}")
        print(f"     Nana 내부: {_inner_tool_names(r3, 'nana_agent')}")
        check("Kana에 위임해 시간을 찾음", "kana_agent" in calls3, str(calls3))
        # 아래는 2단계 위임 — 가이드 기본(요청당 하나 위임) 밖이라 관찰만 합니다.
        observe("Nana에도 위임해 저장까지 함", "nana_agent" in calls3, str(calls3))
        observe("Kana → Nana 순서(시간 결정 후 저장)",
                "kana_agent" in calls3 and "nana_agent" in calls3
                and calls3.index("kana_agent") < calls3.index("nana_agent"), str(calls3))
        observe("Nana 내부에서 실제 저장 도구가 돎",
                bool(SAVE_TOOLS & set(_inner_tool_names(r3, "nana_agent"))),
                str(_inner_tool_names(r3, "nana_agent")))

        # ── ③ 역방향 회귀: 1~4주차 개인 기능이 Nana 경로로 살아 있는가 (읽기 전용)
        print("\n" + "=" * 78)
        q4 = "내가 저장해둔 일정 목록을 보여줘."
        print(f"[04] (회귀·week3) {q4}")
        t4, r4 = _run_supervisor(agent, "trace_week06_reg_list", q4)
        print(f"     위임: {t4.get('supervisor_selected_agent')} | Nana 내부: {_inner_tool_names(r4, 'nana_agent')}")
        check("저장 일정 조회는 Nana로 위임", t4.get("supervisor_selected_agent") == "nana_agent",
              str(t4.get("supervisor_selected_agent")))
        observe("Nana 내부에서 week3 조회 도구가 돎",
                "personal_list_saved_schedules" in _inner_tool_names(r4, "nana_agent"),
                str(_inner_tool_names(r4, "nana_agent")))

        print("\n" + "=" * 78)
        q5 = "내 개인 참고자료에서 '집중'이라는 내용이 있는지 검색해줘."
        print(f"[05] (회귀·week4) {q5}")
        t5, r5 = _run_supervisor(agent, "trace_week06_reg_rag", q5)
        print(f"     위임: {t5.get('supervisor_selected_agent')} | Nana 내부: {_inner_tool_names(r5, 'nana_agent')}")
        check("개인 참고자료 검색은 Nana로 위임", t5.get("supervisor_selected_agent") == "nana_agent",
              str(t5.get("supervisor_selected_agent")))
        observe("Nana 내부에서 week4 RAG 검색 도구가 돎 (gate 없어 모델 판단)",
                "search_personal_references" in _inner_tool_names(r5, "nana_agent"),
                str(_inner_tool_names(r5, "nana_agent")))

    finally:
        # 뒷정리: 실행 중 새로 생긴 앱/공유 row (혼합 요청의 저장 등)
        cleanup_new_rows(app_before, shared_before)

    print("\n" + "=" * 78)
    print("요약 — Week 6 위임 대본")
    print("-" * 78)
    print(f"내용 판정: {passed}개 통과" + (f", 실패 {len(failed)}개" if failed else ", 실패 0개"))
    for label in failed:
        print(f"  ❌ {label}")
    print("(라우팅·혼합 위임은 LLM 판단이라 실행마다 갈릴 수 있습니다. 실패 시 위임 순서와 답변을 함께 보세요.)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
