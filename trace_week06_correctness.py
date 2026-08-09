"""Week 6 트레이스 — 기능 정확성 대본 (라우팅이 아니라 '결과가 맞는가').

실행:
    KANANA_ACTIVE_WEEK=6 PYTHONNOUSERSITE=1 uv run python trace_week06_correctness.py

무엇을 보나요
    이 프로젝트의 최종 기능은 "이미 잡힌 시간을 빈 시간으로 추천하지 않는 것"입니다.
    (Week 5 버그 ①의 수정이 Week 6까지 이어지는지가 핵심)

    ① 내 일정이 실제로 busy-time으로 반영되는가
       - 앱 DB에 내 오전 일정을 심어두고, "나랑 철수" 조율을 시키면
         · 그 일정이 collect 결과 busy_rows에 member '나'로 들어오고
         · 최종 추천 시간이 그 일정(과 철수 일정)과 겹치지 않아야 합니다.
    ② 사용자가 빠지는 요청이면 내 일정은 섞이지 않는가
       - 같은 seed 상태에서 "나는 빼고 철수랑 민준만" 조율을 시키면
         · 내 일정이 busy_rows에 들어오면 안 됩니다("묻지 않은 내 일정은 안 넣는다").

    각 케이스는 대화를 새로 시작합니다. seed는 앱 DB에 있으므로 두 케이스가 함께 봅니다.

주의
    앱 DB에 일정을 직접 심고, 끝에서 이 대본이 만든 것(과 실행 중 새로 생긴 것)을 정리합니다.
"""

from __future__ import annotations

import sqlite3

from fixed.config import CONFIG
from fixed.schedule_decision import parse_time_minutes
from fixed.session_scope import conversation_session_scope
from student_parts.week06_kanamate_decides_schedule import (
    build_week_agent,
    extract_langchain_trace,
)
from trace_week06_common import app_ids, cleanup_new_rows, kana_inner_content, overlaps, shared_ids

# 이 대본이 앱 DB에 직접 심는 내 일정 — 2026-07-09 오전을 통째로 막습니다.
MINE_ID = "wk6trace_mine_0709"
MINE_TITLE = "집중근무_대본검증"
MINE_DATE = "2026-07-09"
MINE_START = "09:00"
MINE_END = "13:00"
# 같은 날 외부 seed: 철수 14:00-15:30 (고객 인터뷰), 민준 11:00-12:00 (백엔드 리뷰)


def _seed_my_schedule() -> None:
    with sqlite3.connect(CONFIG.app_db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO schedules "
            "(schedule_id, request_id, owner, title, date, start_time, end_time, "
            " attendees_json, source, created_at) "
            "VALUES (?, ?, 'me', ?, ?, ?, ?, '[]', 'trace_week06', '2026-07-01T00:00:00+09:00')",
            (MINE_ID, f"req_{MINE_ID}", MINE_TITLE, MINE_DATE, MINE_START, MINE_END),
        )


def _run(agent: object, session_id: str, text: str) -> tuple[dict, dict]:
    """supervisor에게 한 요청을 던지고 (정리된 trace, 원본 result)를 돌려줍니다."""

    with conversation_session_scope(session_id):
        result = agent.invoke({"messages": [{"role": "user", "content": text}]})
    return extract_langchain_trace(result), result


def _kana_inner_rows(result: dict, tool_name: str) -> list[dict]:
    """kana_agent 하위 trace에서 특정 tool이 돌려준 rows를 모읍니다(공용 walker 재사용)."""

    return [row for content in kana_inner_content(result, tool_name) for row in content.get("rows", [])]


def _parse_final_slot(final_slot: str | None) -> tuple[str, str, str] | None:
    """'YYYY-MM-DD HH:MM-HH:MM' → (date, start, end). 형식이 아니면 None."""

    if not final_slot or " " not in final_slot or "-" not in final_slot:
        return None
    date_part, time_part = final_slot.split(" ", 1)
    if "-" not in time_part:
        return None
    start, end = time_part.split("-", 1)
    return date_part.strip(), start.strip(), end.strip()


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

    print("#" * 78)
    print("# Week 6 정확성 대본 — 이미 잡힌 시간은 빈 시간으로 추천되지 않는다")
    print("#" * 78)

    app_before = app_ids()
    shared_before = shared_ids()
    _seed_my_schedule()
    print(f"\nseed: 내 일정 '{MINE_TITLE}' {MINE_DATE} {MINE_START}-{MINE_END} (앱 DB)")

    agent = build_week_agent()

    try:
        # ── ① 나를 포함한 조율 → 내 일정이 busy-time으로 반영되고 추천에서 빠진다
        print("\n" + "=" * 78)
        q1 = "나랑 철수랑 2026년 7월 9일에 같이 회의할 수 있는 시간을 찾아줘."
        print(f"[01] (나 포함) {q1}")
        t1, r1 = _run(agent, "trace_week06_corr_include", q1)
        print(f"     위임: {t1.get('supervisor_selected_agent')} | 하위: "
              f"{' → '.join(t1.get('inner_tool_names') or [])}")
        collect_rows = _kana_inner_rows(r1, "collect_member_schedules")
        mine_rows = [r for r in collect_rows if r.get("member_name") == "나"]
        my_seed_in_busy = any(str(r.get("title") or "").startswith(MINE_TITLE) for r in mine_rows)
        print(f"     collect busy_rows(나): {[(r.get('title'), r.get('start_time'), r.get('end_time')) for r in mine_rows]}")

        check("나 포함 조율은 kana_agent로 위임", t1.get("supervisor_selected_agent") == "kana_agent",
              str(t1.get("supervisor_selected_agent")))
        check("내 일정이 busy_rows에 member '나'로 반영됨 (Week5 버그① 수정이 이어짐)",
              my_seed_in_busy, f"나 rows={[r.get('title') for r in mine_rows]}")

        fs = t1.get("final_slot_payload") or {}
        parsed = _parse_final_slot(fs.get("final_slot"))
        print(f"     최종 시간: {fs.get('final_slot')!r} (needs_agent_selection={fs.get('needs_agent_selection')})")
        if parsed:
            d, s, e = parsed
            check("추천 시간이 내 오전 일정(09:00-13:00)과 겹치지 않음",
                  not (d == MINE_DATE and overlaps(s, e, MINE_START, MINE_END)),
                  f"{fs.get('final_slot')} vs 내 {MINE_START}-{MINE_END}")
            check("추천 시간이 철수 일정(14:00-15:30)과도 겹치지 않음",
                  not (d == MINE_DATE and overlaps(s, e, "14:00", "15:30")),
                  f"{fs.get('final_slot')} vs 철수 14:00-15:30")
            check("추천 시간이 업무시간(09:00-18:00) 안",
                  parse_time_minutes(s, -1) >= 9 * 60 and parse_time_minutes(e, 24 * 60) <= 18 * 60,
                  fs.get("final_slot"))
        else:
            # 최종 시간을 확정하지 못했다면(후보 부족 등) 최소한 후보들은 내 일정과 겹치지 않아야 한다.
            cands = fs.get("candidate_slots") or []
            no_overlap = all(
                not (c.get("date") == MINE_DATE
                     and overlaps(c.get("start_time"), c.get("end_time"), MINE_START, MINE_END))
                for c in cands
            )
            check("최종 미확정이면 후보라도 내 일정과 겹치지 않음", no_overlap, str(cands))

        # ── ② 나를 빼는 조율 → 내 일정은 섞이지 않는다
        print("\n" + "=" * 78)
        q2 = "나는 빼고, 철수랑 민준만 2026년 7월 9일에 겹치는 시간이 있는지 정리해줘."
        print(f"[02] (나 제외) {q2}")
        t2, r2 = _run(agent, "trace_week06_corr_exclude", q2)
        print(f"     위임: {t2.get('supervisor_selected_agent')} | 하위: "
              f"{' → '.join(t2.get('inner_tool_names') or [])}")
        collect_rows2 = _kana_inner_rows(r2, "collect_member_schedules")
        members2 = {r.get("member_name") for r in collect_rows2}
        my_seed_leaked = any(str(r.get("title") or "").startswith(MINE_TITLE) for r in collect_rows2)
        print(f"     collect 대상 멤버: {sorted(m for m in members2 if m)}")
        check("나를 뺀 요청에는 내 일정이 busy_rows에 들어오지 않음",
              not my_seed_leaked, f"멤버={sorted(m for m in members2 if m)}")

    finally:
        # 뒷정리: 이 대본이 심은 내 일정 + 실행 중 새로 생긴 앱/공유 row (기준선과 diff)
        cleanup_new_rows(app_before, shared_before)

    print("\n" + "=" * 78)
    print("요약 — Week 6 정확성 대본")
    print("-" * 78)
    print(f"내용 판정: {passed}개 통과" + (f", 실패 {len(failed)}개" if failed else ", 실패 0개"))
    for label in failed:
        print(f"  ❌ {label}")
    print("(라우팅/최종 시간 선택은 LLM 판단이라 실행마다 갈릴 수 있습니다.)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
