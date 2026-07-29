"""'나' 중복 방지 회귀 테스트.

배경: Week3+ AppSQLiteStore.save_structured_request는 개인/그룹 일정을 저장할 때마다
fixed/external_mcp.py의 sync_personal_schedule_to_shared를 통해 그 사본을 외부 공유
일정 저장소에도 member_name="나"로 자동 동기화한다 (fixed/, 학생 구현 대상 아님).

그래서 _collect_member_schedules가 member_names에 "나"를 그대로 포함한 채 외부 MCP
extract_schedules_from_history를 호출하면, 이미 앱 SQLite/임시 일정에서 읽은 내 일정
(my_rows)과 외부에 동기화된 "나" 사본(external mirrored rows)이 겹쳐서 내 일정이
두 번 반환된다. 이 스크립트는 그 문제를 재현한 BEFORE(수정 전 로직)와 실제 구현된
AFTER(_collect_member_schedules, 외부 조회 시 "나" 제외)를 나란히 실행해 row 개수
차이로 보여준다.
"""

import json
from collections import Counter

from fixed.external_people_store import (
    PERSONAL_SHARED_MEMBER_NAME,
    external_schedule_summary,
    normalize_external_member_names,
    normalize_external_schedule_date_bounds,
)
from student_parts.week05_load_kanas_past_conversations import (
    _collect_member_schedules,
    _personal_schedules_for_current_scope,
    _structured_request_from_schedule_row,
    call_mcp_tool_sync,
)

MEMBER_NAMES = ["나", "철수"]
DATE_FROM = "2026-07-01"
DATE_TO = "2026-07-31"


def _buggy_collect_member_schedules(
    *, member_names: list[str], date_from: str, date_to: str, personal_schedules: list[dict]
) -> dict:
    """수정 전 로직 재현: 외부 조회에서 "나"를 빼지 않고 그대로 넘긴다."""

    normalized_members = normalize_external_member_names(member_names)
    normalized_date_from, normalized_date_to = normalize_external_schedule_date_bounds(
        member_names, date_from, date_to
    )

    my_rows = []
    for schedule in personal_schedules or []:
        request = _structured_request_from_schedule_row(schedule)
        schedule_date = str(request.date or "")
        if not schedule_date:
            continue
        if normalized_date_from and schedule_date < normalized_date_from:
            continue
        if normalized_date_to and schedule_date > normalized_date_to:
            continue
        my_rows.append(
            {"member_name": PERSONAL_SHARED_MEMBER_NAME, "title": request.title or "제목 없음", "date": schedule_date}
        )

    # BUG: "나"를 제외하지 않고 그대로 외부 MCP에 넘김 -> "나" 사본이 my_rows와 겹침
    raw = call_mcp_tool_sync(
        "extract_schedules_from_history",
        {"member_names": normalized_members, "date_from": normalized_date_from, "date_to": normalized_date_to},
    )
    external_rows = json.loads(raw).get("rows") or []

    rows = [*my_rows, *external_rows]
    return {"rows": rows, "my_rows": my_rows, "external_rows": external_rows}


personal_schedules = _personal_schedules_for_current_scope()

fixed_result = _collect_member_schedules(
    member_names=MEMBER_NAMES, date_from=DATE_FROM, date_to=DATE_TO, personal_schedules=personal_schedules
)
buggy_result = _buggy_collect_member_schedules(
    member_names=MEMBER_NAMES, date_from=DATE_FROM, date_to=DATE_TO, personal_schedules=personal_schedules
)

# my_rows는 항상 앱 SQLite/임시 일정에서만 나온 "내" 일정 목록이다 (겹칠 상대가 없는 원본).
# external_rows는 BEFORE 버전이 "나"를 제외하지 않고 외부 MCP에 넘겨서 받아온 결과다.
# 이 둘의 (title, date) 교집합이 있다면, 그건 곧 "내 일정이 외부 동기화 사본으로도 다시 조회됐다"는 증거다.
my_keys = Counter((row["title"], row["date"]) for row in buggy_result["my_rows"])
external_na_keys = Counter(
    (row["title"], row["date"]) for row in buggy_result["external_rows"] if row["member_name"] == "나"
)
overlap = sorted(set(my_keys) & set(external_na_keys))

print(f"[AFTER  fix] 전체 row 수: {len(fixed_result['rows'])}")
print(
    f"[BEFORE fix] 전체 row 수: {len(buggy_result['rows'])} "
    f"(내 일정 {len(buggy_result['my_rows'])} + 외부 조회 결과 {len(buggy_result['external_rows'])})"
)
print(f"[BEFORE fix] 내 일정과 외부 조회 결과가 겹치는 항목 수: {len(overlap)}")
if overlap:
    print(f"[BEFORE fix] 겹치는 예시: {overlap[0]} (내 일정에도 있고, 외부 동기화 사본으로도 또 조회됨)")

assert my_keys, "비교하려면 실제 '나' 일정 데이터가 SQLite에 저장돼 있어야 함"
assert len(fixed_result["rows"]) < len(buggy_result["rows"]), "AFTER fix가 BEFORE보다 row 수가 적어야 함(중복 제거)"
assert overlap, "BEFORE fix 로직에서 내 일정과 외부 동기화 사본이 겹치는 항목이 재현돼야 함"

print("\n중복 확인: 수정 전 로직에서는 내 일정이 (SQLite 원본 + 외부 동기화 사본으로) 두 번 잡힙니다.")
print('→ _collect_member_schedules가 외부 조회 시 "나"를 제외하는 이유입니다.')
