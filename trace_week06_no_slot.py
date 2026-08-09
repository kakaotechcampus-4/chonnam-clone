"""Week 6 트레이스 — 공통 가능 시간이 없을 때 정직하게 보류하는가 (부정 경로).

실행:
    KANANA_ACTIVE_WEEK=6 PYTHONNOUSERSITE=1 uv run python trace_week06_no_slot.py

무엇을 보나요
    correctness 대본은 "바쁜 시간을 피해 슬롯을 찾는" 긍정 경로를 봅니다.
    이 대본은 그 짝인 부정 경로 — 아무 슬롯도 없을 때 시간을 지어내지 않는가 — 를 봅니다.

    내 일정을 그날(2026-08-20) 09:00~18:00 통째로 막아두고 "나랑 철수 그날 회의 시간 찾아줘"를
    시키면, 업무시간 안에 공통으로 비는 60분이 없습니다. 기대 동작:
      · 내 종일 일정이 busy_rows에 반영되고,
      · 겹침 검증이 후보를 전부 걷어내 candidate_slots가 비고,
      · 최종적으로 final_slot을 지어내지 않고 needs_agent_selection=true로 보류한다.
    (가이드: selected_index/selected_slot이 없으면 final_slot을 자동으로 고르지 않는다.)

주의
    앱 DB에 종일 일정을 직접 심고, 끝에서 이 대본이 만든 row를 정리합니다.
"""

from __future__ import annotations

import sqlite3

from fixed.config import CONFIG
from fixed.session_scope import conversation_session_scope
from student_parts.week06_kanamate_decides_schedule import (
    build_week_agent,
    extract_langchain_trace,
)
from trace_week06_common import app_ids, cleanup_new_rows, kana_inner_content, overlaps, shared_ids

MINE_ID = "wk6noslot_fullday_0820"
MINE_TITLE = "종일근무_대본검증"
MINE_DATE = "2026-08-20"
MINE_START = "09:00"
MINE_END = "18:00"  # 업무시간 전체를 막습니다.


def _seed_full_day() -> None:
    with sqlite3.connect(CONFIG.app_db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO schedules "
            "(schedule_id, request_id, owner, title, date, start_time, end_time, "
            " attendees_json, source, created_at) "
            "VALUES (?, ?, 'me', ?, ?, ?, ?, '[]', 'trace_week06', '2026-07-01T00:00:00+09:00')",
            (MINE_ID, f"req_{MINE_ID}", MINE_TITLE, MINE_DATE, MINE_START, MINE_END),
        )


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
        mark = "✅(관찰)" if ok else "➖(관찰)"
        print(f"     {mark} {label}" + (f"  ({detail})" if detail else ""))

    print("#" * 78)
    print("# Week 6 부정 경로 대본 — 공통 시간이 없으면 지어내지 않는다")
    print("#" * 78)

    app_before = app_ids()
    shared_before = shared_ids()
    _seed_full_day()
    print(f"\nseed: 내 종일 일정 '{MINE_TITLE}' {MINE_DATE} {MINE_START}-{MINE_END} (앱 DB)")

    agent = build_week_agent()
    try:
        print("\n" + "=" * 78)
        q = "나랑 철수랑 2026년 8월 20일에 같이 회의할 수 있는 시간을 찾아줘."
        print(f"[01] (슬롯 없음) {q}")
        with conversation_session_scope("trace_week06_no_slot"):
            result = agent.invoke({"messages": [{"role": "user", "content": q}]})
        trace = extract_langchain_trace(result)
        inner = trace.get("inner_tool_names") or []
        print(f"     위임: {trace.get('supervisor_selected_agent')} | 하위: {' → '.join(inner)}")

        # 내 종일 일정이 busy_rows에 반영됐는가
        collect_contents = kana_inner_content(result, "collect_member_schedules")
        my_busy = [
            r for c in collect_contents for r in c.get("rows", [])
            if r.get("member_name") == "나" and str(r.get("title") or "").startswith(MINE_TITLE)
        ]
        check("그룹 조율은 kana_agent로 위임", trace.get("supervisor_selected_agent") == "kana_agent",
              str(trace.get("supervisor_selected_agent")))
        check("내 종일 일정이 busy_rows에 반영됨", bool(my_busy),
              f"나 busy={[(r.get('start_time'), r.get('end_time')) for r in my_busy]}")

        # find 후보가 내 종일 일정과 겹치지 않도록 전부 걸러졌는가
        find_contents = kana_inner_content(result, "find_common_available_slots")
        find_candidates = [s for c in find_contents for s in c.get("candidate_slots", [])]
        overlapping = [
            s for s in find_candidates
            if s.get("date") == MINE_DATE
            and overlaps(s.get("start_time"), s.get("end_time"), MINE_START, MINE_END)
        ]
        if find_contents:
            check("find가 내 종일 일정과 겹치는 후보를 남기지 않음 (겹침 검증)",
                  not overlapping, f"겹치는 후보={overlapping}")
            check("공통 가능 후보가 없음 (candidate_slots 비어 있음)",
                  not find_candidates, f"후보={find_candidates}")
        else:
            observe("find_common_available_slots가 호출되지 않음 (모델이 조회만으로 판단했을 수 있음)", True)

        # ★ 핵심: 없는 시간을 지어내지 않았는가
        fs = trace.get("final_slot_payload")
        if fs is not None:
            print(f"     최종 payload: final_slot={fs.get('final_slot')!r} "
                  f"needs_agent_selection={fs.get('needs_agent_selection')}")
            check("없는 시간을 지어내지 않음 (final_slot=null)", fs.get("final_slot") is None,
                  str(fs.get("final_slot")))
            check("보류 상태 유지 (needs_agent_selection=true)",
                  fs.get("needs_agent_selection") is True, str(fs.get("needs_agent_selection")))
        else:
            # decide_final_slot을 아예 부르지 않았다면 그것도 '지어내지 않음'의 한 형태입니다.
            check("없는 시간을 지어내지 않음 (최종 시간 payload 없음)", True)

        # 답변이 '가능한 시간 없음'을 사용자에게 알리는가 (문구는 모델마다 달라 관찰)
        answer = ""
        for message in reversed(result.get("messages", [])):
            content = getattr(message, "content", "")
            if isinstance(content, str) and content.strip():
                answer = content.strip()
                break
        print(f"     [답변] {answer[:220]}")
        no_slot_words = ("없", "찾지 못", "어렵", "불가", "겹치", "종일", "하루 종일", "가능한 시간")
        observe("답변이 '가능한 공통 시간 없음'을 알림",
                any(w in answer for w in no_slot_words), answer[:80])

    finally:
        cleanup_new_rows(app_before, shared_before)

    print("\n" + "=" * 78)
    print("요약 — Week 6 부정 경로 대본")
    print("-" * 78)
    print(f"내용 판정: {passed}개 통과" + (f", 실패 {len(failed)}개" if failed else ", 실패 0개"))
    for label in failed:
        print(f"  ❌ {label}")
    print("(라우팅/최종 판단은 LLM이지만, 겹침 검증과 final_slot 보류는 Python 계약이라 안정적입니다.)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
