"""Week 5 트레이스 ② 외부 멤버 busy-time + 내 일정 병합.

실행:
    KANANA_ACTIVE_WEEK=5 PYTHONNOUSERSITE=1 uv run python trace_week05_schedules.py

무엇을 보나요
    - extract_schedules_from_history : 외부 멤버가 언제 바쁜지
    - collect_member_schedules       : 내 일정 + 외부 멤버 busy-time을 한 rows로 합치기

    라우팅뿐 아니라 rows 내용을 직접 판정합니다.
    · 묻지 않은 내 일정이 섞이지 않는가 (member_names에 "나"가 없으면 내 일정은 넣지 않는다)
    · 사용자가 자신을 포함해 물으면 "나"가 member_names에 들어가는가
      (이 규약이 지켜지는 비율은 trace_week05_mine_inclusion.py가 반복 측정합니다)
    · 멤버가 늘어도 배열 하나로 한 번만 호출하는가
    · 두 출처 row 의 스키마와 end_time 표기가 같은가

주의
    SETUP에서 내 일정을 저장하므로 앱 DB와 공유 저장소가 변경됩니다.
    마지막에 이 대본이 만든 일정을 정리합니다.
"""

from __future__ import annotations

from trace_week05_common import (
    BUSY_TOOLS,
    EXTRACT_TOOLS,
    WEEK1234_TOOLS,
    TraceRun,
)

# 이 대본이 만드는 일정 제목 — 뒷정리 대상입니다.
MINE_0708 = "병합검증 오후작업"
MINE_0715 = "병합검증 회고"


def run() -> int:
    t = TraceRun("② 외부 busy-time + 내 일정 병합", "trace_week05_schedules")

    # ── SETUP: 내 일정이 있어야 '섞임/누락'을 볼 수 있습니다.
    #    '회의'라는 말을 피해 개인 일정으로 분류되게 합니다(그룹+참석자0이면 공유 동기화가 skip).
    t.turn("셋업", f"2026년 7월 8일 오후 2시에 '{MINE_0708}' 일정으로 저장해줘. 나 혼자 하는 일이야.",
           WEEK1234_TOOLS)
    t.turn("셋업", f"2026년 7월 15일 오전 9시에 '{MINE_0715}' 일정으로 저장해줘. 나 혼자 하는 일이야.",
           WEEK1234_TOOLS)

    # ── 외부 멤버만 묻기
    single = t.turn("외부일정", "지훈이 2026년 7월 14일부터 7월 16일까지 언제 바쁜지 알려줘.", EXTRACT_TOOLS)
    t.check("지훈 일정을 받아옴", len(single.rows("extract_schedules_from_history")
                                 + single.rows("collect_member_schedules")) >= 1)

    two = t.turn("외부일정", "철수랑 영희 둘 다 2026년 7월 7일에 무슨 일정이 있어?", EXTRACT_TOOLS)
    # collect 로 가도 결과는 맞지만, 그 경우 내 일정이 섞이지 않았는지 확인합니다.
    mixed_names = {r.get("member_name") for r in two.rows("collect_member_schedules")}
    t.check("묻지 않은 내 일정이 섞이지 않음", "나" not in mixed_names, f"멤버={sorted(mixed_names)}")

    # 있는 멤버 + 없는 멤버 혼합 — 철수만 나오고 홍길동은 없다고 해야 합니다.
    mix = t.turn("외부일정", "철수랑 홍길동 둘 다 2026년 7월 7일부터 7월 9일까지 일정 알려줘.", EXTRACT_TOOLS)
    all_rows = mix.rows("extract_schedules_from_history") + mix.rows("collect_member_schedules")
    names = {r.get("member_name") for r in all_rows}
    t.check("철수 일정은 있음", "철수" in names, f"멤버={sorted(names)}")
    t.check("없는 사람 일정을 만들지 않음", "홍길동" not in names, f"멤버={sorted(names)}")
    # 이 구간(7/7~7/9)에는 내 일정 MINE_0708이 있으므로, 섞였다면 여기서 잡힙니다.
    t.check("혼합 조회에도 내 일정 안 섞임", "나" not in names, f"멤버={sorted(names)}")

    # ── 나를 포함해 합치기
    both = t.turn("합치기", "나랑 철수, 지훈이 2026년 7월 7일부터 7월 15일까지 각각 언제 바쁜지 정리해줘.",
                  BUSY_TOOLS)
    collect_args = both.args_of("collect_member_schedules")
    t.check("member_names에 \"나\"를 포함해 호출",
            any("나" in (a.get("member_names") or []) for a in collect_args),
            str([a.get("member_names") for a in collect_args]))
    rows = both.rows("collect_member_schedules")
    if rows:
        keysets = {tuple(sorted(r.keys())) for r in rows}
        t.check("내 row와 외부 row의 스키마가 동일", len(keysets) == 1, str(keysets))
        t.check("end_time 표기가 통일됨 (None 없음)",
                all(r.get("end_time") is not None for r in rows),
                str(sorted({str(r.get("end_time")) for r in rows})))
        t.check("내 일정이 member_name='나'로 들어감",
                any(r.get("member_name") == "나" for r in rows),
                f"멤버={sorted({r.get('member_name') for r in rows})}")

    # 멤버가 늘어도 배열 하나로 한 번만 호출하는지
    many = t.turn("합치기", "철수, 영희, 민준, 지훈 네 명 2026년 7월 7일부터 7월 10일까지 일정 모아줘.",
                  BUSY_TOOLS)
    busy_calls = many.args_of("collect_member_schedules") + many.args_of("extract_schedules_from_history")
    t.check("사람 수만큼 쪼개 부르지 않음 (1회 호출)", len(busy_calls) <= 1, f"{len(busy_calls)}회")

    # "저"처럼 자신을 다르게 가리켰을 때도 내 일정이 함께 모이는지
    self_ref = t.turn("합치기", "저랑 하린이 2026년 7월 8일에 겹치는 시간 있는지 일정 모아줘.", BUSY_TOOLS)
    self_rows = self_ref.rows("collect_member_schedules")
    t.check("'저'로 물어도 내 일정이 rows에 있음",
            any(r.get("member_name") == "나" for r in self_rows),
            f"멤버={sorted({r.get('member_name') for r in self_rows})}")

    # ── 이전 주차 회귀 (week1~4 tool이 여전히 살아있는지)
    t.turn("회귀", "내가 저장해둔 일정 목록 보여줘.", WEEK1234_TOOLS)
    t.turn("회귀", "나는 오전에 집중이 잘 된다고 기억해둬.", WEEK1234_TOOLS)

    t.cleanup((MINE_0708, MINE_0715))
    return t.summary()


if __name__ == "__main__":
    raise SystemExit(run())
