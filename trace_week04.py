"""Week 4 agent 트레이스 보기 대본 (Nana의 기억 검색).

실행:
    KANANA_ACTIVE_WEEK=4 PYTHONNOUSERSITE=1 uv run python trace_week04.py

무엇을 보나요
    이번 주차에 구현한 "출처별 검색" 라우팅이 실제로 동작하는지 눈으로 확인합니다.
    각 입력마다 LLM이 어떤 tool을 골랐는지(tool_call), 그 결과(tool_result),
    최종 답변을 보여주고, 기대한 출처의 tool로 갔는지 ✅/⚠️로 표시합니다.

    - search_personal_references : 개인 참고자료(선호·메모) 검색 → top-level hits
    - search_saved_requests      : SQLite 저장 요청(일정/할일/알림) 검색 → top-level rows
    - search_conversation_messages: 앱 일반 대화 발화 RAG (현재 대화 제외)
    - add_personal_reference     : 참고자료 추가
    (week1~3 tool과 근거 없음/모호 입력도 섞어 회귀를 함께 봅니다.)

    라우팅은 LLM 판단이라 "저장 일정"류 질문이 week3의 personal_list_saved_schedules로
    갈 수도 있습니다 — 이건 오답이 아니라 겹치는 영역이며, 대본은 그걸 있는 그대로 보여줍니다.

대화 이어붙이기 (중요)
    모든 입력은 **하나의 이어지는 대화**로 실행됩니다. 매 턴 직전까지의 메시지 전체
    (질문·tool 호출·답변)를 다음 호출에 넘기므로, 에이전트가 앞 질문을 실제로 기억합니다.
    그래서 어떤 질문은 tool을 다시 부르지 않고 "앞 대화만으로" 답할 수 있고, 그 경우
    "tool 호출 없음 (앞 대화/메모리로 답변)"으로 표시됩니다.
    ⚠️ 대화가 길어질수록 컨텍스트(토큰)가 누적되어 비용이 커집니다 — 33턴 1회 실행 기준.
"""

from __future__ import annotations

import json
from collections import Counter

from fixed.config import CONFIG
from fixed.langchain_trace import extract_agent_events, extract_final_text
from fixed.session_scope import conversation_session_scope
from student_parts.week04_retrieve_nanas_memory import build_week04_agent

# 이 대본 실행 전체가 하나의 "현재 대화"인 것처럼 범위를 잡습니다.
# 이렇게 해야 search_conversation_messages의 "현재 대화 제외" 경로가 실제로 동작합니다.
TRACE_SESSION_ID = "trace_week04_session"

# 저장 요청 검색(search_saved_requests)이 찾을 데이터를 먼저 만들어 둡니다.
# (agent를 통해 자연어로 저장 → week3 저장 흐름도 함께 확인됩니다.)
SETUP_INPUTS = [
    "다음 주 월요일 오후 2시에 디자인 리뷰 회의 잡아서 저장해줘.",
    "내일 오전 11시에 병원 예약 알림으로 저장해줘.",
    "이번 주 금요일까지 분기 보고서 초안 쓰는 할 일로 저장해줘.",
]

# (카테고리, 입력, 기대 tool 후보) — 기대 후보 중 하나라도 호출되면 ✅.
# 빈 set()은 "특정 tool을 강하게 기대하지 않음"(엣지/모호)을 뜻합니다.
REFERENCE_TOOLS = {"search_personal_references"}
SAVED_TOOLS = {
    "search_saved_requests",
    "personal_list_saved_schedules",
    "list_saved_requests",
    "get_saved_request",
}
CONVERSATION_TOOLS = {"search_conversation_messages"}
ADD_TOOLS = {"add_personal_reference"}
WEEK123_TOOLS = {
    "personal_create_schedule",
    "personal_list_schedules",
    "personal_delete_schedule",
    "extract_schedule_request",
    "save_structured_request",
    "personal_list_saved_schedules",
    "personal_update_saved_schedule",
    "personal_delete_saved_schedules",
}

CASES: list[tuple[str, str, set[str]]] = [
    # A. 참고자료 추가 (add_personal_reference)
    ("추가", "나 오전 10시에서 12시 사이에 집중이 제일 잘 되니까 기억해둬.", ADD_TOOLS),
    ("추가", "회의는 되도록 30분 이내로 짧게 하는 걸 선호한다고 메모해줘.", ADD_TOOLS),
    ("추가", "금요일 오후엔 외부 미팅을 잡지 않는 게 내 원칙이야. 참고자료로 저장해둬.", ADD_TOOLS),
    ("추가", "나는 커피를 하루 두 잔까지만 마신다는 거 기록해줘.", ADD_TOOLS),

    # B. 개인 참고자료 검색 (search_personal_references)
    ("참고자료검색", "내가 집중이 제일 잘 되는 시간대가 언제라고 했지?", REFERENCE_TOOLS),
    ("참고자료검색", "회의 길이에 대해 내가 선호한다고 적어둔 게 뭐였어?", REFERENCE_TOOLS),
    ("참고자료검색", "점심시간에 대한 내 규칙 알려줘.", REFERENCE_TOOLS),
    ("참고자료검색", "팀 싱크는 어떻게 하는 게 좋다고 참고자료에 적혀 있어?", REFERENCE_TOOLS),
    ("참고자료검색", "금요일 오후에 대해 내가 세워둔 원칙이 있었나?", REFERENCE_TOOLS),
    ("참고자료검색", "내 참고자료 중에 커피 관련된 거 찾아줘.", REFERENCE_TOOLS),

    # C. 저장 요청/일정 검색 (search_saved_requests ↔ personal_list_saved_schedules)
    ("저장검색", "내가 저장해둔 회의 일정들 뭐뭐 있어?", SAVED_TOOLS),
    ("저장검색", "저장된 기록 중에 '디자인'이라는 단어 들어간 요청 찾아줘.", SAVED_TOOLS),
    ("저장검색", "병원 관련해서 저장해둔 알림 있었나?", SAVED_TOOLS),
    ("저장검색", "보고서랑 관련해서 저장한 할 일 검색해줘.", SAVED_TOOLS),
    ("저장검색", "리뷰 회의로 저장한 일정 다시 보여줘.", SAVED_TOOLS),

    # D. 대화 RAG (search_conversation_messages)
    ("대화RAG", "예전 대화에서 회의 잡았던 얘기 찾아봐줘.", CONVERSATION_TOOLS),
    ("대화RAG", "전에 다른 채팅에서 알림 관련해서 뭐라고 했었지?", CONVERSATION_TOOLS),
    ("대화RAG", "이전 대화들 중에 '회식' 얘기 나온 거 있어?", CONVERSATION_TOOLS),
    ("대화RAG", "과거 채팅에서 할 일 등록했던 내용 찾아줘.", CONVERSATION_TOOLS),
    ("대화RAG", "옛날 대화에서 치과 예약 얘기 했던 거 검색해줘.", CONVERSATION_TOOLS),

    # E. 혼합/복합 (여러 출처 판단)
    ("혼합", "내가 선호하는 회의 시간대에 맞춰, 저장된 회의 일정 중 겹치는 게 있는지 봐줘.", REFERENCE_TOOLS | SAVED_TOOLS),
    ("혼합", "내 점심시간 규칙이랑 저장된 일정 중 점심때 잡힌 거 같이 알려줘.", REFERENCE_TOOLS | SAVED_TOOLS),
    ("혼합", "예전 대화랑 참고자료 둘 다 뒤져서 '집중'에 대해 내가 한 말 정리해줘.", REFERENCE_TOOLS | CONVERSATION_TOOLS),
    ("혼합", "내가 회의를 짧게 선호한다고 했는데, 저장된 회의들 시간 좀 확인해줘.", REFERENCE_TOOLS | SAVED_TOOLS),
    ("혼합", "오후에 대한 내 규칙이랑 관련된 저장 일정 있으면 보여줘.", REFERENCE_TOOLS | SAVED_TOOLS),

    # F. week1~3 회귀 (오늘 코드가 이전 tool을 안 깨뜨렸는지)
    ("회귀", "오늘 오후 4시에 30분 산책 일정 만들어줘.", WEEK123_TOOLS),
    ("회귀", "저장된 일정 목록 보여줘.", WEEK123_TOOLS),
    ("회귀", "저장된 일정 중에 산책 일정 삭제해줘.", WEEK123_TOOLS),

    # G. 엣지 (근거 없음 / 모호 → 환각 없이 처리)
    ("엣지", "내가 우주정거장 견학을 예약해뒀다는 참고자료가 있어?", set()),
    ("엣지", "음, 그냥 아무거나 좀 정리해줘.", set()),
]


def _events_of(messages: list) -> list[dict]:
    """주어진 메시지 조각에서만 tool_call/tool_result 이벤트를 뽑습니다."""

    try:
        return extract_agent_events({"messages": messages})
    except Exception:
        return []


def turn(index: int, category: str, text: str, expect: set[str], agent, history: list) -> tuple[list, list[str]]:
    """이어지는 대화의 한 턴을 실행합니다.

    직전까지의 history에 이번 질문을 붙여 통째로 넘기므로 에이전트가 앞 대화를 기억합니다.
    반환: (갱신된 history, 이번 턴에 호출된 tool 이름 목록)
    """

    print("=" * 78)
    print(f"[{index:02d}] ({category}) {text}")
    if expect:
        print(f"     기대 tool 후보: {', '.join(sorted(expect))}")

    prev_len = len(history)
    next_history = history + [{"role": "user", "content": text}]
    try:
        res = agent.invoke({"messages": next_history})
    except Exception as exc:  # 한 턴이 실패해도 대화는 계속 이어갑니다(history는 유지).
        print(f"     ❌ 실행 오류: {type(exc).__name__}: {exc}")
        return history, []

    messages = res["messages"]
    # 이번 턴에 새로 생긴 메시지(질문+tool+답변)에서만 이벤트를 추출합니다.
    turn_events = _events_of(messages[prev_len:])
    called = [ev["tool_name"] for ev in turn_events if ev.get("event") == "tool_call"]

    if not called:
        print("     tool 호출 없음 (앞 대화/메모리로 답변)")
    for i, ev in enumerate(turn_events, 1):
        if ev.get("event") == "tool_call":
            args = json.dumps(ev.get("arguments", {}), ensure_ascii=False)
            print(f"       {i}. call   {ev['tool_name']}  args={args}")
        else:
            content = ev.get("content")
            preview = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            print(f"       {i}. result {ev['tool_name']}  -> {preview[:180]}")

    if expect:
        hit = expect.intersection(called)
        if hit:
            print(f"     ✅ 기대대로 라우팅: {', '.join(sorted(hit))}")
        elif called:
            print(f"     ⚠️ 다른 tool로 라우팅: {', '.join(called)}")
        else:
            print("     · tool 없이 답변 (앞 대화 기억으로 처리했을 수 있음)")

    print(f"     [답변] {extract_final_text(res)[:220].strip()}")
    print()
    return messages, called


def main() -> None:
    if not CONFIG.has_openai_key:
        print("⚠️ .env의 PROXY_TOKEN이 필요합니다. 키를 넣고 다시 실행하세요.")
        return

    agent = build_week04_agent()
    history: list = []          # 대화 전체가 여기 누적됩니다.
    tally: Counter[str] = Counter()
    no_tool_turns = 0
    routed_ok = 0
    routed_total = 0
    index = 0

    # 대본 전체를 하나의 대화 범위로 감쌉니다(= 하나의 "현재 대화").
    with conversation_session_scope(TRACE_SESSION_ID):
        print("\n########## SETUP: 저장 데이터 만들기 (search_saved_requests가 찾을 대상) ##########\n")
        for text in SETUP_INPUTS:
            index += 1
            history, _ = turn(index, "셋업저장", text, WEEK123_TOOLS, agent, history)

        print("\n########## 30개 예시 트레이스 (이어지는 대화) ##########\n")
        for category, text, expect in CASES:
            index += 1
            history, called = turn(index, category, text, expect, agent, history)
            tally.update(called)
            if not called:
                no_tool_turns += 1
            if expect:
                routed_total += 1
                if expect.intersection(called):
                    routed_ok += 1

    print("=" * 78)
    print("요약")
    print("-" * 78)
    print(f"누적 대화 메시지 수: {len(history)}")
    print("tool 호출 횟수:")
    for name, count in tally.most_common():
        print(f"  {count:>3}  {name}")
    print("-" * 78)
    print(f"기대 tool 후보가 있던 {routed_total}개 중 {routed_ok}개가 기대대로 라우팅됨.")
    print(f"tool 없이 답한 턴(앞 대화 기억으로 처리 가능): {no_tool_turns}개")
    print("(⚠️/· 표시는 오답이 아니라 라우팅이 갈리거나 대화 기억으로 답한 경우일 수 있으니,")
    print(" tool_call args와 답변을 함께 확인하세요.)")


if __name__ == "__main__":
    main()
