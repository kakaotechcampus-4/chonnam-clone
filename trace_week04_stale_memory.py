"""Week 4 리뷰 대응 대본 (3): 대화 기억 vs 저장소 재검색 — stale 위험 결정 실험.

배경
    trace_week04_probe.py에서 "확인 질문(있어?)인데 검색 없이 대화 기억으로 답하는"
    under-trigger가 관측됐다. 다만 그때는 기억이 우연히 최신이라 답이 맞았다.
    이 대본은 "기억이 실제로 낡았을 때" 어떤 일이 벌어지는지 못박는다.

실험 설계
    1) agent로 일정을 저장한다(예: 스탠드업 09:00).
    2) agent에게 시간을 물어 답을 대화 컨텍스트(기억)에 넣는다 → 이제 기억=09:00.
    3) 대화 '밖에서' SQLite 저장값을 몰래 바꾼다(09:00 → 10:30).
       (agent는 이 변경을 대화로 보지 못한다.)
    4) agent에게 다시 시간을 확인해 달라고 한다.
       - 저장소를 재검색하면 → 10:30 (정답, 견고)
       - 대화 기억으로 답하면 → 09:00 (stale, 틀림) = 위험 재현

판정
    4)에서 검색 tool을 호출했는지, 답에 10:30이 들어갔는지로 stale 여부를 결정한다.

실행:
    KANANA_ACTIVE_WEEK=4 PYTHONNOUSERSITE=1 PYTHONIOENCODING=utf-8 uv run python trace_week04_stale_memory.py
"""

from __future__ import annotations

from fixed.config import CONFIG
from fixed.langchain_trace import extract_agent_events, extract_final_text
from fixed.session_scope import conversation_session_scope
from student_parts.week04_retrieve_nanas_memory import SQLITE_STORE, build_week04_agent

TRACE_SESSION_ID = "trace_week04_stale_session"
SEARCH_TOOLS = {
    "search_personal_references",
    "search_saved_requests",
    "search_conversation_messages",
    "search_nana_memory",
    "personal_list_saved_schedules",
    "list_saved_requests",
    "get_saved_request",
}
OLD_TIME = "09:00"
NEW_TIME = "10:30"
TITLE = "스탠드업 회의"


def _turn(agent, history: list, text: str) -> tuple[list, list[str], str]:
    prev = len(history)
    res = agent.invoke({"messages": history + [{"role": "user", "content": text}]})
    history = res["messages"]
    try:
        events = extract_agent_events({"messages": history[prev:]})
    except Exception:
        events = []
    called = [ev["tool_name"] for ev in events if ev.get("event") == "tool_call"]
    return history, called, extract_final_text(res)


def _find_standup_id() -> str | None:
    rows = SQLITE_STORE.find_schedules(title="스탠드업", limit=10)
    return rows[0]["schedule_id"] if rows else None


def main() -> None:
    if not CONFIG.has_openai_key:
        print("⚠️ .env의 PROXY_TOKEN이 필요합니다. 키를 넣고 다시 실행하세요.")
        return

    agent = build_week04_agent()
    history: list = []
    sid: str | None = None

    with conversation_session_scope(TRACE_SESSION_ID):
        # 1) 저장
        history, called, ans = _turn(agent, history, f"내일 오전 9시에 '{TITLE}' 일정 저장해줘.")
        print(f"[1] 저장   tools={called}\n    답변: {ans[:140].strip()}\n")

        # 2) 시간 질문 → 기억에 09:00 심기
        history, called, ans = _turn(agent, history, "방금 저장한 스탠드업 회의 몇 시야?")
        print(f"[2] 첫 질문 tools={called}\n    답변: {ans[:140].strip()}\n")

        # 3) 대화 밖에서 저장값 변경 (09:00 -> 10:30)
        sid = _find_standup_id()
        if not sid:
            print("❌ 저장된 스탠드업 일정을 찾지 못했습니다. (1단계 저장 실패)")
            return
        SQLITE_STORE.update_schedule(sid, start_time=NEW_TIME)
        row = SQLITE_STORE.find_schedules(schedule_ids=[sid])[0]
        print(f"[3] 대화 밖 변경: {sid} start_time -> {row.get('start_time')} (저장소=최신 {NEW_TIME}, 대화 기억=낡은 {OLD_TIME})\n")

        # 4) 캐주얼한 확인(probe 턴19와 같은 결) → 재검색? or stale 기억?
        #    "다시/저장된 걸로 확인" 같은 강한 검색 신호를 일부러 빼고 물어본다.
        history, called, ans = _turn(agent, history, "참, 스탠드업 회의 몇 시였지?")
        searched = [t for t in called if t in SEARCH_TOOLS]
        print(f"[4] 재확인 tools={called}\n    답변: {ans[:200].strip()}\n")

    # ---- 판정 ----
    said_new = NEW_TIME in ans or "10시 30" in ans or "10:30" in ans
    said_old = (OLD_TIME in ans or "9시" in ans or "09시" in ans or "오전 9" in ans) and not said_new
    print("=" * 78)
    print("판정")
    print("-" * 78)
    print(f"  재확인 턴에서 검색 tool 호출: {searched or '없음'}")
    if searched and said_new:
        print("  ✅ 견고: 저장소를 재검색해 최신값(10:30)으로 답함 — stale 없음.")
    elif not searched and said_old:
        print("  ❗ 위험 재현: 검색 없이 대화 기억(09:00)으로 답함 = STALE 오답.")
        print("     → 프롬프트 넛지만으로는 '확인 질문엔 반드시 검색'이 보장되지 않음을 입증.")
    elif not searched and said_new:
        print("  ⚠️ 검색은 안 했지만 최신값이 나옴 — 기억에 변경이 섞였을 수 있어 재현 불안정.")
    else:
        print(f"  ⚠️ 애매: searched={bool(searched)}, said_new={said_new}, said_old={said_old} — 답변 원문 확인 필요.")

    # 정리: 실험용 일정 삭제
    if sid:
        SQLITE_STORE.delete_schedule(sid)
        print("\n(정리) 실험용 스탠드업 일정 삭제 완료.")


if __name__ == "__main__":
    main()
