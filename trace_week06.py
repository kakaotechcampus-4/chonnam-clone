"""Week 6 트레이스 — 가장 기본 대본 (supervisor 위임 확인).

실행:
    KANANA_ACTIVE_WEEK=6 PYTHONNOUSERSITE=1 uv run python trace_week06.py

무엇을 보나요
    Week 6의 본체는 supervisor가 요청을 알맞은 하위 agent로 위임하는지입니다.
    supervisor가 직접 보는 tool은 nana_agent / kana_agent 둘뿐이라, 실제 일정 도구는
    하위 agent의 trace(inner_tool_names) 안에서 확인합니다.

    ① 개인 요청 → nana_agent 로 위임, 하위에서 개인 일정 조회 도구가 돌았는가
    ② 그룹 조율 요청 → kana_agent 로 위임, 하위에서 collect → find → decide 로 이어졌는가

각 케이스는 대화를 새로 시작합니다(앞 대화 기억으로 도구를 건너뛰지 않게).
읽기 전용에 가깝습니다 — Kana는 저장 도구가 없어 일정을 새로 만들지 않습니다.
"""

from __future__ import annotations

from fixed.config import CONFIG
from fixed.session_scope import conversation_session_scope
from student_parts.week06_kanamate_decides_schedule import (
    build_week_agent,
    extract_langchain_trace,
)


def _run_turn(agent: object, session_id: str, text: str) -> dict:
    """supervisor에게 한 요청을 던지고 위임 trace를 정리해 돌려줍니다."""

    with conversation_session_scope(session_id):
        result = agent.invoke({"messages": [{"role": "user", "content": text}]})
    return extract_langchain_trace(result)


def _print_trace(trace: dict) -> None:
    print(f"     위임된 하위 agent : {trace.get('supervisor_selected_agent')}")
    inner = trace.get("inner_tool_names") or []
    print(f"     하위 도구 순서      : {' → '.join(inner) if inner else '(없음)'}")
    if trace.get("final_slot_payload"):
        fs = trace["final_slot_payload"]
        print(f"     최종 시간 payload   : final_slot={fs.get('final_slot')!r} "
              f"needs_agent_selection={fs.get('needs_agent_selection')}")


def run() -> int:
    if not CONFIG.has_openai_key:
        print("⚠️ .env의 PROXY_TOKEN이 필요합니다. 키를 넣고 다시 실행하세요.")
        return 1

    agent = build_week_agent()
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

    print("#" * 78)
    print("# Week 6 기본 대본 — supervisor 위임 확인")
    print("#" * 78)

    # ── ① 개인 요청 → Nana
    print("\n" + "=" * 78)
    q1 = "내가 저장해둔 일정 목록을 보여줘."
    print(f"[01] (개인) {q1}")
    t1 = _run_turn(agent, "trace_week06_personal", q1)
    _print_trace(t1)
    check("개인 요청은 nana_agent로 위임", t1.get("supervisor_selected_agent") == "nana_agent",
          str(t1.get("supervisor_selected_agent")))
    # 목록 요청은 앱 DB 전체를 나열하는 personal_list_saved_schedules로 가야 합니다.
    # (retrieval_gate를 얹으면 상한 걸린 search_saved_requests로 새 목록이 누락돼 되돌렸습니다.)
    check("Nana 하위에서 저장 일정 목록 도구가 돎",
          "personal_list_saved_schedules" in (t1.get("inner_tool_names") or []),
          str(t1.get("inner_tool_names")))

    # ── ② 그룹 조율 요청 → Kana (collect → find → decide)
    print("\n" + "=" * 78)
    q2 = "철수랑 영희랑 2026년 7월 8일에 같이 회의할 수 있는 시간을 찾아줘."
    print(f"[02] (그룹) {q2}")
    t2 = _run_turn(agent, "trace_week06_group", q2)
    _print_trace(t2)
    inner2 = t2.get("inner_tool_names") or []
    check("그룹 조율 요청은 kana_agent로 위임", t2.get("supervisor_selected_agent") == "kana_agent",
          str(t2.get("supervisor_selected_agent")))
    check("Kana 하위에서 busy-time을 모음 (collect_member_schedules)",
          "collect_member_schedules" in inner2, str(inner2))
    check("공통 가능 시간 후보를 검증함 (find_common_available_slots)",
          "find_common_available_slots" in inner2, str(inner2))
    check("최종 시간 결정까지 이어감 (decide_final_slot)",
          "decide_final_slot" in inner2, str(inner2))

    print("\n" + "=" * 78)
    print("요약 — Week 6 기본 대본")
    print("-" * 78)
    print(f"내용 판정: {passed}개 통과" + (f", 실패 {len(failed)}개" if failed else ", 실패 0개"))
    for label in failed:
        print(f"  ❌ {label}")
    print("(⚠️ 라우팅은 LLM 판단이라 실행마다 갈릴 수 있습니다. 실패 시 args와 답변을 함께 보세요.)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
