"""Week 5 트레이스 ③ 공유 일정 저장소 조회·등록·갱신·삭제 (추가 과제 포함).

실행:
    KANANA_ACTIVE_WEEK=5 PYTHONNOUSERSITE=1 uv run python trace_week05_shared.py

무엇을 보나요
    - list_shared_schedules   : 공유 저장소 row 조회 (메인 과제)
    - create_shared_schedule  : row 등록/갱신 (추가 과제)
    - delete_shared_schedule  : row 삭제 (추가 과제)

    등록 → 갱신 → 조회 → 삭제를 한 흐름으로 보면서 저장소를 직접 확인합니다.
    · 필터 없이 부르면 실습용 기본 공유 일정이 우선 반환된다
    · 갱신 후 같은 제목 row가 여러 건으로 늘지 않는가 (schedule_id 갱신 또는 삭제+재생성 모두 허용)
    · 삭제 후 저장소에서 실제로 사라졌는가

주의
    공유 저장소를 실제로 변경합니다. 마지막에 실행 중 생긴 row를 정리합니다.
"""

from __future__ import annotations

from trace_week05_common import (
    SHARED_DELETE_TOOLS,
    SHARED_LIST_TOOLS,
    SHARED_WRITE_TOOLS,
    TraceRun,
    shared_rows,
)

SYNC_TITLE = "주간 싱크"
SYNC_DATE = "2026-07-16"
SYNC_DATE_TEXT = "2026년 7월 16일"
SYNC_MEMBER = "하린"


def _stored(title: str, member: str) -> list[dict]:
    """저장소를 직접 읽어 해당 제목/멤버 row를 셉니다(LLM 응답에 판정을 맡기지 않습니다)."""

    return [
        row for row in shared_rows()
        if str(row.get("title") or "").startswith(title) and row.get("member_name") == member
    ]


def run() -> int:
    t = TraceRun("③ 공유 일정 저장소 (조회·등록·갱신·삭제)", "trace_week05_shared")

    # ── 조회
    default = t.turn("공유조회", "공유 일정 저장소에 등록된 일정들을 보여줘.", SHARED_LIST_TOOLS)
    t.check("기본 공유 일정이 조회됨", len(default.rows("list_shared_schedules")) >= 1)

    mine = t.turn("공유조회", "공유 저장소에 내 이름으로 등록된 일정이 있어?", SHARED_LIST_TOOLS)
    args = mine.args_of("list_shared_schedules")
    t.check("\"나\"로 필터해 조회", any("나" in (a.get("member_names") or []) for a in args),
            str([a.get("member_names") for a in args]))

    # ── 등록
    created = t.turn(
        "공유등록",
        f"{SYNC_DATE_TEXT} 오후 3시에 '{SYNC_TITLE}' 회의를 {SYNC_MEMBER} 이름으로 공유 일정에 등록해줘.",
        SHARED_WRITE_TOOLS,
    )
    payloads = created.payloads("create_shared_schedule")
    saved_id = ""
    if payloads:
        saved = payloads[-1].get("shared_schedule", {})
        saved_id = str(saved.get("schedule_id") or "")
        t.check("등록 결과에 schedule_id가 있음 (나중에 갱신·삭제 근거)", bool(saved_id), str(saved))
    t.check("저장소에 1건 등록됨", len(_stored(SYNC_TITLE, SYNC_MEMBER)) == 1,
            f"{len(_stored(SYNC_TITLE, SYNC_MEMBER))}건")

    # ── 갱신: 같은 id를 갱신하거나 삭제+재생성 — 어느 쪽이든 최종 1건이어야 합니다.
    t.turn("공유갱신", f"그 {SYNC_TITLE} 일정을 오후 4시로 바꿔줘.",
           SHARED_WRITE_TOOLS | SHARED_DELETE_TOOLS | SHARED_LIST_TOOLS)
    after_update = _stored(SYNC_TITLE, SYNC_MEMBER)
    t.check("갱신 후에도 1건 (중복 생성 아님)", len(after_update) == 1, f"{len(after_update)}건")
    if after_update:
        t.check("시작 시간이 16:00으로 반영됨",
                str(after_update[0].get("start_time")) == "16:00",
                str(after_update[0].get("start_time")))

    # ── 조회로 확인
    listed = t.turn("공유조회", f"공유 저장소에서 {SYNC_MEMBER} 일정만 보여줘.", SHARED_LIST_TOOLS)
    t.check(f"{SYNC_MEMBER} 일정이 조회됨",
            any(r.get("member_name") == SYNC_MEMBER for r in listed.rows("list_shared_schedules")))

    # ── 삭제
    t.turn("공유삭제", f"방금 등록한 그 {SYNC_MEMBER} {SYNC_TITLE} 공유 일정을 삭제해줘.",
           SHARED_DELETE_TOOLS)
    t.check("저장소에서 실제로 사라짐", len(_stored(SYNC_TITLE, SYNC_MEMBER)) == 0,
            f"{len(_stored(SYNC_TITLE, SYNC_MEMBER))}건 남음")

    t.cleanup()
    return t.summary()


if __name__ == "__main__":
    raise SystemExit(run())
