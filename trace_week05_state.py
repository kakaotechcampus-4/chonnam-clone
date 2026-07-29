"""Week 5 트레이스 ⑤ 상태 변화·주차 연결.

실행:
    KANANA_ACTIVE_WEEK=5 PYTHONNOUSERSITE=1 uv run python trace_week05_state.py

다른 대본과 무엇이 다른가
    다른 대본은 "어떤 요청이 어떤 tool로 가는가"와 그 결과를 봅니다.
    이 대본은 **앞 턴이 만든 상태가 뒤 턴의 결과를 바꾸는지**를 봅니다.
    그래서 각 시나리오는 "바꾼다 → 다시 조회한다 → 반영됐는지 본다" 구조입니다.

무엇을 검증하나요
    ① 이중집계  : week3 personal_create_schedule 은 임시 일정을 같은 id로 SQLite에도 저장한다.
                  collect_member_schedules rows 에 그 일정이 정확히 1건만 있어야 한다.
    ② 수정 반영  : 내 일정 시간을 바꾸면 collect 결과의 start_time 도 바뀌어야 한다.
                  앱 DB만 바뀌고 공유 저장소 사본이 남으면 여기서 드러난다.
    ③ 삭제 반영  : 내 일정을 지우면 공유 저장소의 "나" 사본도 사라져야 한다.
    ④ 주차 연결  : 개인 참고자료(week4 RAG)를 근거로 외부 멤버 일정(week5 MCP)을 조회하는,
                  두 출처를 잇는 요청이 실제로 두 tool을 순서대로 쓰는지 본다.

주의
    앱 DB와 외부 공유 저장소를 **실제로 변경**합니다. 마지막에 정리합니다.
"""

from __future__ import annotations

from trace_week05_common import (
    BUSY_TOOLS,
    SHARED_LIST_TOOLS,
    WEEK1234_TOOLS,
    TraceRun,
    shared_rows,
)

COFFEE_TITLE = "커피 약속"
# '회의'라는 말이 들어가면 agent가 group_schedule로 분류하고, 참석자가 없으면
# 공유 저장소 동기화가 skip 되어 시나리오 ③이 검증 없이 통과해 버립니다.
# 그래서 개인 일정으로 분류되도록 제목과 문장에서 '회의'를 뺍니다.
FOCUS_TITLE = "상태검증 집중작업"


def _stored(title: str) -> list[dict]:
    """공유 저장소를 직접 읽어 해당 제목 row를 셉니다."""

    return [row for row in shared_rows() if str(row.get("title") or "").startswith(title)]


def run() -> int:
    t = TraceRun("⑤ 상태 변화·주차 연결", "trace_week05_state")

    # ── ① 이중집계: 임시 일정이 collect rows 에 1건만 들어오는가
    print("\n--- ① 이중집계 ---\n")
    created = t.turn("일정생성", f"2026년 7월 9일 오후 3시에 '{COFFEE_TITLE}' 일정 하나 만들어줘.",
                     WEEK1234_TOOLS)
    t.check("일정 생성 tool이 호출됨", bool(created.called), f"called={created.called}")

    merged = t.turn("합치기", "나랑 철수가 2026년 7월 9일에 각각 언제 바쁜지 일정 모아줘.", BUSY_TOOLS)
    t.check("collect_member_schedules 호출됨", merged.used("collect_member_schedules"),
            f"called={merged.called}")
    payloads = merged.payloads("collect_member_schedules")
    t.check("collect 결과 payload를 읽음", bool(payloads), "payload 파싱 실패")
    if payloads:
        coffee = merged.rows_titled("collect_member_schedules", COFFEE_TITLE)
        t.check(f"'{COFFEE_TITLE}'가 rows에 정확히 1건 (중복 제거)", len(coffee) == 1, f"{len(coffee)}건")
        t.check("내 일정이 member_name='나'로 들어감",
                any(r.get("member_name") == "나" for r in merged.rows("collect_member_schedules")))

    # ── ② 수정 반영: 시간을 바꾸면 collect 결과도 바뀌는가
    print("\n--- ② 수정 반영 ---\n")
    t.turn("일정저장", f"2026년 7월 8일 오후 2시에 '{FOCUS_TITLE}' 일정으로 저장해줘. 나 혼자 하는 일이야.",
           WEEK1234_TOOLS)

    before = t.turn("합치기(전)", "나랑 민준이 2026년 7월 8일에 언제 바쁜지 일정 모아줘.", BUSY_TOOLS)
    before_rows = before.rows_titled("collect_member_schedules", FOCUS_TITLE)
    before_start = before_rows[0].get("start_time") if before_rows else None
    t.check("수정 전 start_time이 14:00", before_start == "14:00", repr(before_start))

    updated = t.turn("일정수정", f"그 '{FOCUS_TITLE}' 일정을 오전 10시로 바꿔줘.", WEEK1234_TOOLS)
    t.check("수정 tool이 호출됨", bool(updated.called), f"called={updated.called}")

    after = t.turn("합치기(후)", "나랑 민준이 2026년 7월 8일에 언제 바쁜지 다시 모아줘.", BUSY_TOOLS)
    after_rows = after.rows_titled("collect_member_schedules", FOCUS_TITLE)
    after_start = after_rows[0].get("start_time") if after_rows else None
    t.check("수정 후 collect 결과가 10:00으로 바뀜", after_start == "10:00", repr(after_start))
    t.check(f"'{FOCUS_TITLE}'가 여전히 1건", len(after_rows) == 1, f"{len(after_rows)}건")

    # ── ③ 삭제 반영: 앱에서 지우면 공유 사본도 사라지는가
    print("\n--- ③ 삭제 반영 ---\n")
    shared_before = t.turn("공유확인(전)", "공유 저장소에 내 이름으로 등록된 2026년 7월 8일 일정이 있어?",
                           SHARED_LIST_TOOLS)
    t.check("list_shared_schedules 호출됨", shared_before.used("list_shared_schedules"),
            f"called={shared_before.called}")
    # LLM이 어떤 필터로 조회했는지에 판정을 맡기지 않고 저장소를 직접 확인합니다.
    # 공유 사본이 애초에 없으면 아래 삭제 검증이 '검증 없이 통과'하므로 여기서 먼저 막습니다.
    t.check("삭제 전 공유 사본이 존재함 (시나리오 성립 조건)", len(_stored(FOCUS_TITLE)) >= 1,
            f"{len(_stored(FOCUS_TITLE))}건 — 개인 일정으로 저장되지 않아 동기화가 skip됐을 수 있음")

    deleted = t.turn("일정삭제", f"'{FOCUS_TITLE}' 일정을 삭제해줘.", WEEK1234_TOOLS)
    t.check("삭제 tool이 호출됨", bool(deleted.called), f"called={deleted.called}")

    t.turn("공유확인(후)", f"공유 저장소에 '{FOCUS_TITLE}' 일정이 아직 남아 있어?", SHARED_LIST_TOOLS)
    t.check("공유 저장소에서도 사라짐", len(_stored(FOCUS_TITLE)) == 0,
            f"{len(_stored(FOCUS_TITLE))}건 남음")

    # ── ④ 주차 연결: 참고자료(week4) → 외부 일정(week5)
    print("\n--- ④ 주차 연결 ---\n")
    ref = t.turn("참고자료저장", "나는 오전 10시~12시에 집중이 가장 잘 된다고 기억해둬.", WEEK1234_TOOLS)
    t.check("add_personal_reference 호출됨", ref.used("add_personal_reference"), f"called={ref.called}")

    linked = t.turn(
        "연결",
        "내가 저장해둔 집중 시간 선호를 확인해서 반영하고, 철수랑 2026년 7월 9일에 회의 시간 잡아줘.",
    )
    used_reference = linked.used("search_personal_references")
    used_external = linked.used("extract_schedules_from_history", "collect_member_schedules")
    t.check("참고자료를 실제로 조회함(week4)", used_reference, f"called={linked.called}")
    t.check("외부 멤버 일정도 조회함(week5)", used_external, f"called={linked.called}")
    t.check("두 출처를 한 요청에서 함께 사용", used_reference and used_external, f"called={linked.called}")

    t.cleanup((COFFEE_TITLE, FOCUS_TITLE))
    return t.summary()


if __name__ == "__main__":
    raise SystemExit(run())
