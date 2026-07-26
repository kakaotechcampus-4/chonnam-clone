"""Week 4 비교 실험: '프롬프트 강화만'으로 stale이 잡히는가 (게이트 미들웨어 제외).

trace_week04_stale_memory.py와 '완전히 같은' stale 시나리오를 돌리되,
agent를 retrieval_gate 미들웨어 '없이' 만든다(= 강화된 system prompt만 사용).
게이트 유무의 효과를 분리해서 본다.

실행:
    KANANA_ACTIVE_WEEK=4 PYTHONNOUSERSITE=1 PYTHONIOENCODING=utf-8 uv run python trace_week04_stale_prompt_only.py
"""

from __future__ import annotations

from langchain.agents import create_agent

from fixed.config import CONFIG
from fixed.langchain_trace import extract_agent_events, extract_final_text
from fixed.llm import chat_model
from fixed.session_scope import conversation_session_scope
from student_parts.week04_retrieve_nanas_memory import (
    SQLITE_STORE,
    week04_system_prompt,
    week04_tools,
)

TRACE_SESSION_ID = "trace_week04_stale_prompt_only"
OLD_TIME = "09:00"
NEW_TIME = "10:30"
TITLE = "스탠드업 회의"


def _build_prompt_only_agent() -> object:
    """retrieval_gate 미들웨어 없이, 강화된 system prompt만 가진 agent."""

    return create_agent(
        model=chat_model(),
        tools=week04_tools(),
        system_prompt=week04_system_prompt(),
        # middleware 없음 — 프롬프트 강화만으로 stale을 막을 수 있는지 본다.
    )


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


def main() -> None:
    if not CONFIG.has_openai_key:
        print("⚠️ .env의 PROXY_TOKEN이 필요합니다. 키를 넣고 다시 실행하세요.")
        return

    agent = _build_prompt_only_agent()
    history: list = []
    sid = None

    with conversation_session_scope(TRACE_SESSION_ID):
        history, called, ans = _turn(agent, history, f"내일 오전 9시에 '{TITLE}' 일정 저장해줘.")
        print(f"[1] 저장   tools={called}\n    답변: {ans[:140].strip()}\n")

        history, called, ans = _turn(agent, history, "방금 저장한 스탠드업 회의 몇 시야?")
        print(f"[2] 첫 질문 tools={called}\n    답변: {ans[:140].strip()}\n")

        sid = SQLITE_STORE.find_schedules(title="스탠드업", limit=10)
        sid = sid[0]["schedule_id"] if sid else None
        if not sid:
            print("❌ 저장된 스탠드업 일정을 찾지 못했습니다.")
            return
        SQLITE_STORE.update_schedule(sid, start_time=NEW_TIME)
        print(f"[3] 대화 밖 변경: {sid} start_time -> {NEW_TIME} (저장소=최신, 대화 기억=낡은 {OLD_TIME})\n")

        history, called, ans = _turn(agent, history, "참, 스탠드업 회의 몇 시였지?")
        searched = [t for t in called if "search" in t or "list_saved" in t or "get_saved" in t]
        print(f"[4] 재확인 tools={called}\n    답변: {ans[:200].strip()}\n")

    said_new = NEW_TIME in ans or "10시 30" in ans or "10:30" in ans
    said_old = (OLD_TIME in ans or "9시" in ans or "오전 9" in ans) and not said_new
    print("=" * 78)
    print("판정 (프롬프트 강화만, 게이트 없음)")
    print("-" * 78)
    print(f"  재확인 턴에서 검색 tool 호출: {searched or '없음'}")
    if searched and said_new:
        print("  ✅ 견고: 프롬프트만으로도 재검색해 최신값(10:30)으로 답함.")
    elif not searched and said_old:
        print("  ❗ 위험 재현: 검색 없이 대화 기억(09:00)으로 답함 = STALE 오답.")
    else:
        print(f"  ⚠️ 애매: searched={bool(searched)}, said_new={said_new}, said_old={said_old} — 답변 원문 확인.")

    if sid:
        SQLITE_STORE.delete_schedule(sid)
        print("\n(정리) 실험용 스탠드업 일정 삭제 완료.")


if __name__ == "__main__":
    main()
