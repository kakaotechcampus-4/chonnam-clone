"""Week 5 측정 대본 — 조율 요청에서 LLM이 member_names에 "나"를 넣는 비율.

실행:
    KANANA_ACTIVE_WEEK=5 PYTHONNOUSERSITE=1 uv run python trace_week05_mine_inclusion.py
    KANANA_ACTIVE_WEEK=5 PYTHONNOUSERSITE=1 uv run python trace_week05_mine_inclusion.py 3

왜 이 대본이 따로 있나
    collect_member_schedules는 member_names에 "나"가 있을 때만 내 일정을 rows에 넣습니다.
    묻지 않은 내 일정까지 답하지 않기 위한 선택인데, 그 대가로 위험이 하나 남습니다 —
    Week 6 find_common_available_slots가 이 rows를 busy_rows 근거로 쓸 때 LLM이 "나"를
    빼먹으면 내가 이미 바쁜 시각이 조용히 추천됩니다. 결과만 봐서는 드러나지 않는 실패입니다.

    이 설계는 그 위험을 코드가 아니라 **호출 규약**으로 막습니다. week05_prompt_parts()에
    "조율 요청에는 '나'를 넣어 부른다"를 못박아 뒀습니다. 규약으로 막는다는 건 곧
    **LLM이 규약을 지킨다**는 가정 위에 서 있다는 뜻이라, 그 가정만 따로 반복 측정합니다.

    test_week05.py는 "나"가 들어왔을 때 내 일정이 rows에 담기는지를 결정적으로 확인할 뿐,
    LLM이 "나"를 넣는지는 확인할 수 없습니다. 그래서 별도 대본으로 뒀습니다.

    trace_week05.py의 SCRIPTS에는 넣지 않았습니다. 다른 대본이 시나리오 통과/실패를 보는
    반면 이건 같은 질문을 N회 반복하는 측정이고, 전체 실행 비용을 크게 올리기 때문입니다.

설계
    · 단일 변경점은 질문 문구뿐입니다. 내 일정·날짜·회차마다 새 대화는 모든 조건에서 같습니다.
    · 내 일정은 앱 DB에 직접 넣습니다. 저장을 LLM 턴에 맡기면 그 자체가 변동 요인이 됩니다.
    · 회차마다 대화를 새로 시작합니다(앞 대화 기억으로 답하면 측정이 무의미해집니다).
    · 내 일정은 철수가 실제로 일정을 가진 날(2026-07-09)에 둡니다. 그래야 "내 일정을
      빼먹으면 실제로 답이 틀어지는" 조건이 됩니다.

분모 정의 (중요)
    분모는 **조율 tool을 실제로 부른 회차**입니다. tool을 안 부르고 되묻기만 한 회차를
    분모에 넣으면 규약을 어긴 것처럼 보이고, 반대로 전체 회차를 분모로 쓰면 좋아 보입니다.
    둘 다 규약 준수율이 아닙니다.

조건
    A. 명시적 자기 지칭       "나랑 철수 ... 언제 겹치는지"        → "나" 포함이 정답
    B. 조사 붙은 자기 지칭     "내가 철수랑 ... 만날 수 있는 시간"   → "나" 포함이 정답
    C. 자기 지칭 없는 조율     "철수랑 언제 만날 수 있을까?"        → "나" 포함이 정답 (가장 빼먹기 쉬움)
    D. 대조군                 "철수랑 지훈 둘이 ... 나는 참석 안 해" → "나" 미포함이 정답

    D가 없으면 "항상 넣기"가 만점이 되어 측정이 의미를 잃습니다. 규약은 양방향입니다.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from fixed.app_store import AppSQLiteStore
from fixed.config import CONFIG
from fixed.external_people_store import PERSONAL_SHARED_MEMBER_NAME
from trace_week05_common import BUSY_TOOLS, TraceRun

MINE_TITLE = "포함검증 개인작업"
MINE_ID = "sch_mine_inclusion_check"
MINE_DATE = "2026-07-09"
DEFAULT_N = 5

# (라벨, 질문, 기대 tool, "나"가 들어가야 하는가)
CONDITIONS: list[tuple[str, str, set[str], bool]] = [
    ("A", "나랑 철수 2026년 7월 9일에 언제 겹치는지 일정 모아줘.", BUSY_TOOLS, True),
    ("B", "내가 철수랑 2026년 7월 9일에 만날 수 있는 시간 찾아줘.", BUSY_TOOLS, True),
    ("C", "철수랑 2026년 7월 9일에 언제 만날 수 있을까?", BUSY_TOOLS, True),
    ("D", "철수랑 지훈 둘이 2026년 7월 9일에 회의할 시간 찾아줘. 나는 참석 안 해.",
     BUSY_TOOLS, False),
]


def seed_my_schedule() -> None:
    """내 일정을 앱 DB에 직접 넣습니다 (LLM 저장 턴의 변동을 배제).

    save_structured_request 경로는 공유 저장소 동기화까지 하므로, 내 일정 사본이 외부
    조회에도 잡혀 측정이 흐려집니다. 여기서는 '이미 저장된 내 일정'이 입력일 뿐이라
    fixture row를 직접 넣습니다.
    """

    AppSQLiteStore(CONFIG.app_db_path).initialize()
    with sqlite3.connect(CONFIG.app_db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO schedules "
            "(schedule_id, request_id, owner, title, date, start_time, end_time, "
            " attendees_json, source, created_at) "
            "VALUES (?, ?, 'me', ?, ?, '10:00', '11:00', '[]', 'mine_inclusion_check', "
            "'2026-07-01T00:00:00+09:00')",
            (MINE_ID, f"req_{MINE_ID}", MINE_TITLE, MINE_DATE),
        )


def remove_my_schedule() -> None:
    with sqlite3.connect(CONFIG.app_db_path) as conn:
        conn.execute("DELETE FROM schedules WHERE schedule_id = ?", (MINE_ID,))


def run(n: int = DEFAULT_N) -> int:
    """조건마다 n회씩 측정하고, 규약 위반이 하나라도 있으면 1을 돌려줍니다."""

    seed_my_schedule()
    results: list[dict[str, Any]] = []
    try:
        for label, question, expect, should_include in CONDITIONS:
            for i in range(1, n + 1):
                t = TraceRun(f"\"나\" 포함 측정 {label}#{i}", f"mine_inclusion_{label}_{i}")
                turn = t.turn("측정", question, expect)

                # 조율 tool을 어떤 인자로 불렀는가. 두 tool 모두 member_names를 받습니다.
                calls = (turn.args_of("collect_member_schedules")
                         + turn.args_of("extract_schedules_from_history"))
                sent_names = [str(x) for a in calls for x in (a.get("member_names") or [])]
                asked_mine = PERSONAL_SHARED_MEMBER_NAME in sent_names
                mine_in_rows = any(
                    r.get("member_name") == PERSONAL_SHARED_MEMBER_NAME
                    for r in turn.rows("collect_member_schedules")
                )
                results.append({
                    "cond": label,
                    "run": i,
                    "should_include": should_include,
                    "called": turn.called,
                    # tool을 안 불렀으면 규약 준수 여부를 물을 수 없습니다(분모에서 뺍니다).
                    "counted": bool(calls),
                    "sent_names": sent_names,
                    "asked_mine": asked_mine,
                    "mine_in_rows": mine_in_rows,
                    "ok": bool(calls) and asked_mine == should_include,
                    "answer": turn.answer[:250],
                })
                t.cleanup(())
    finally:
        remove_my_schedule()

    return report(results)


def report(results: list[dict[str, Any]]) -> int:
    print("\n" + "=" * 78)
    print("\"나\" 포함 규약 준수 측정 요약")
    print("-" * 78)
    for r in results:
        if not r["counted"]:
            mark = "미집계"
        elif r["ok"]:
            mark = "준수"
        else:
            mark = "위반"
        want = "포함" if r["should_include"] else "미포함"
        print(f"  {r['cond']}#{r['run']}  {mark:<6} 기대={want} 보낸이름={r['sent_names']} "
              f"내row={r['mine_in_rows']} called={r['called']}")

    counted = [r for r in results if r["counted"]]
    violations = [r for r in counted if not r["ok"]]
    skipped = [r for r in results if not r["counted"]]
    print("-" * 78)
    print(f"전체 {len(results)}회 / 집계 {len(counted)}회 / 위반 {len(violations)}회 "
          f"/ tool 미호출로 제외 {len(skipped)}회")
    if counted:
        print(f"규약 준수율: {len(counted) - len(violations)}/{len(counted)} "
              f"({100 * (len(counted) - len(violations)) / len(counted):.0f}%)")
    else:
        print("집계 가능한 회차가 없음 — 문구를 다시 설계해야 합니다.")

    positive = [r for r in counted if r["should_include"]]
    negative = [r for r in counted if not r["should_include"]]
    if positive:
        hit = sum(1 for r in positive if r["asked_mine"])
        print(f"  포함해야 하는 회차: {hit}/{len(positive)} 포함")
    if negative:
        clean = sum(1 for r in negative if not r["asked_mine"])
        print(f"  포함하면 안 되는 회차: {clean}/{len(negative)} 정상")

    for r in violations:
        want = "포함" if r["should_include"] else "미포함"
        print(f"\n  [위반 {r['cond']}#{r['run']} 기대={want}] 보낸이름={r['sent_names']}"
              f"\n    {r['answer']}")

    out = Path(__file__).with_name("trace_week05_mine_inclusion_results.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n원자료: {out.name}")
    return 1 if violations else 0


def main(argv: list[str]) -> int:
    if not CONFIG.has_openai_key:
        print("⚠️ .env의 PROXY_TOKEN이 필요합니다. 키를 넣고 다시 실행하세요.")
        return 1
    n = int(argv[0]) if argv else DEFAULT_N
    return run(n)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
