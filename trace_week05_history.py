"""Week 5 트레이스 ① 외부 과거 대화 (검색 → 로드).

실행:
    KANANA_ACTIVE_WEEK=5 PYTHONNOUSERSITE=1 uv run python trace_week05_history.py

무엇을 보나요
    외부 SQLite/MCP에 있는 Kana의 이전 대화를 찾고 불러오는 세로 슬라이스입니다.
    - search_previous_conversations : 핵심어로 과거 대화 검색 (conversation_id를 얻는다)
    - load_conversation_messages    : 그 id로 대화 전체를 불러온다

    함께 확인하는 경계
    · 검색어를 좁힐 단어가 없는 요청 → store가 빈 query면 LIKE 절을 빼므로 그대로 넘겨야 한다
    · limit 스키마 상한(50)을 넘는 요청 → 도구 오류를 읽고 값을 고쳐 다시 부르거나 되물어야 한다
    · 없는 conversation_id → 빈 rows 를 받고 내용을 지어내지 않아야 한다

    내 일정에 의존하지 않으므로 이 대본은 DB를 변경하지 않습니다.
"""

from __future__ import annotations

from trace_week05_common import (
    COLLECT_TOOLS,
    EXTRACT_TOOLS,
    LOAD_TOOLS,
    SEARCH_TOOLS,
    TraceRun,
)


def run() -> int:
    t = TraceRun("① 외부 과거 대화 (검색 → 로드)", "trace_week05_history")

    t.turn("외부검색", "철수가 예전 대화에서 QA 리뷰 얘기한 적 있어?", SEARCH_TOOLS)

    # 앞 턴에서 얻은 conversation_id를 물려받아 불러오는지 (세로 슬라이스 연결)
    loaded = t.turn("외부로드", "방금 찾은 그 대화 전체 내용을 그대로 보여줘.", LOAD_TOOLS)
    ids = [str(a.get("conversation_id") or "") for a in loaded.args_of("load_conversation_messages")]
    t.check("앞 턴 검색으로 찾은 conversation_id를 사용", any(i.startswith("ext_") for i in ids), str(ids))
    t.check("대화 메시지를 실제로 받아옴", len(loaded.rows("load_conversation_messages")) >= 1)

    t.turn("외부검색", "영희랑 나눈 이전 대화 중에 디자인 관련된 게 있는지 찾아줘.", SEARCH_TOOLS)

    # 좁힐 단어가 없는 요청 — 앞 턴에서 id를 아는 철수 대신 처음 언급하는 민준으로 물어 검색을 강제한다.
    broad = t.turn("외부검색", "민준이랑 나눈 이전 대화 전체를 그냥 보여줘.", SEARCH_TOOLS)
    t.check("빈/광범위 query로도 결과를 받음", len(broad.rows("search_previous_conversations")) >= 1)

    # limit 상한 초과 — 도구가 ValidationError 를 돌려준다. 되묻거나 값을 고쳐 다시 불러야 한다.
    over = t.turn("외부검색", "철수랑 나눈 대화를 100개까지 찾아서 보여줘.", SEARCH_TOOLS)
    limits = [a.get("limit") for a in over.args_of("search_previous_conversations")]
    recovered = any(isinstance(v, int) and v <= 50 for v in limits) or not over.called
    t.check("상한을 넘긴 뒤 복구(허용 값 재호출 또는 되묻기)", recovered, f"limit={limits}")

    # 없는 대화 id — 빈 rows 를 받고 지어내지 않아야 한다.
    missing = t.turn("외부로드", "'ext_zzz' 대화의 내용을 보여줘.", LOAD_TOOLS)
    t.check("없는 대화는 빈 rows", len(missing.rows("load_conversation_messages")) == 0)

    # 검색 → 일정 조회를 한 요청에서 이어서 하는지 (외부 tool 두 개 연결)
    chained = t.turn(
        "연결",
        "민준이 이전 대화에서 뭐라고 했는지 찾아보고, 그 사람 2026년 7월 8일 일정도 알려줘.",
        SEARCH_TOOLS | EXTRACT_TOOLS | COLLECT_TOOLS,
    )
    t.check(
        "한 요청에서 대화 검색과 일정 조회를 모두 사용",
        chained.used("search_previous_conversations")
        and chained.used("extract_schedules_from_history", "collect_member_schedules"),
        f"called={chained.called}",
    )

    t.cleanup()
    return t.summary()


if __name__ == "__main__":
    raise SystemExit(run())
