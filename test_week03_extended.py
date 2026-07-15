"""Week 3 확장 검증 대본 (추가 탐색용, 제출용 test_week03.py와 별개).

실행:
    KANANA_ACTIVE_WEEK=3 uv run python test_week03_extended.py

test_week03.py가 LLM agent로 "구조화→저장→조회/수정/삭제" 흐름을 보는 반면,
이 대본은 LLM 없이 Week3 도구를 직접 호출해 도구 레벨 엣지케이스를 결정적으로 점검합니다.
(매번 같은 결과, 프록시/네트워크 불필요, 몇 초)

점검 갈래
  A. 저장 라우팅 — kind별로 schedules / todos / reminders에 맞게 들어가는가
  B. source_schedule_id 멱등 — 같은 원본 ID 재저장 시 중복 생성 안 되는가
  C. 수정 — 일부 필드만 바꿔도 나머지는 유지되는가(None=변경 안 함)
  D. 조회 필터 — kind / 날짜범위, 그룹은 kind 지정 시에만 조회되는가
  E. 삭제 — 제목/시간미정 필터, delete_all, 조건 없으면 거부
  F. 레거시 정규화 — structured_request / payload wrapper를 풀어내는가
  G. 영속성 — 새 store 인스턴스(앱 재시작 가정)로 같은 DB를 읽어도 남아 있는가

각 검증은 격리된 임시 DB에서 실행하므로 실제 앱 DB(data/)를 건드리지 않습니다.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

os.environ.setdefault("KANANA_ACTIVE_WEEK", "3")

import student_parts.week03_build_nanas_logbook as w3
from fixed.app_store import AppSQLiteStore

# 격리된 임시 DB로 _store 교체 (실제 앱 DB 보호)
_DB = Path(tempfile.mkdtemp()) / "week03_extended.sqlite3"
_STORE = AppSQLiteStore(_DB)
w3._store = lambda: _STORE

_passed = 0
_failed: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed
    if cond:
        _passed += 1
        print(f"[OK]   {name}")
    else:
        _failed.append(name)
        print(f"[FAIL] {name}  {detail}")


def call(tool: Any, **kwargs: Any) -> dict[str, Any]:
    """@tool을 호출하고 JSON 문자열 결과를 dict로 돌려줍니다."""
    return json.loads(tool.invoke(kwargs))


def run() -> int:
    # A. 저장 라우팅
    call(w3.save_structured_request, kind="personal_schedule", title="개인A", date="2026-07-16", start_time="10:00", original_text="x")
    call(w3.save_structured_request, kind="group_schedule", title="회의B", date="2026-07-17", start_time="15:00", members=["철수"], original_text="x")
    call(w3.save_structured_request, kind="todo", title="보고서C", date="2026-07-18", original_text="x")
    call(w3.save_structured_request, kind="reminder", title="약D", start_time="17:00", original_text="x")
    check("A. schedules 2건(personal+group)", len(_STORE.list_schedules(limit=200)) == 2)
    check("A. structured_requests todo 1건", len(_STORE.list_saved_requests(kind="todo")) == 1)
    check("A. structured_requests reminder 1건", len(_STORE.list_saved_requests(kind="reminder")) == 1)

    # B. source_schedule_id 멱등
    call(w3.save_structured_request, kind="personal_schedule", title="멱등E", date="2026-07-19", start_time="09:00", source_schedule_id="sch_fixed1", original_text="x")
    before = len(_STORE.list_schedules(limit=200))
    r2 = call(w3.save_structured_request, kind="personal_schedule", title="멱등E", date="2026-07-19", start_time="09:00", source_schedule_id="sch_fixed1", original_text="x")
    check("B. 같은 source_schedule_id 재저장 → already_exists", r2.get("already_exists") is True, str(r2))
    check("B. 재저장해도 일정 개수 그대로", before == len(_STORE.list_schedules(limit=200)))

    # C. 수정: 일부 필드만(None=유지)
    sid = next(s["schedule_id"] for s in _STORE.list_schedules(limit=200) if s["title"] == "개인A")
    u = call(w3.personal_update_saved_schedule, schedule_id=sid, date="2026-07-20")
    row = next(s for s in _STORE.list_schedules(limit=200) if s["schedule_id"] == sid)
    check("C. date만 수정 성공", u["ok"] is True)
    check("C. date 반영", row["date"] == "2026-07-20", str(row["date"]))
    check("C. start_time은 유지(None=변경 안 함)", row["start_time"] == "10:00", str(row["start_time"]))
    call(w3.personal_update_saved_schedule, schedule_id=sid, attendees=["영희", "민수"])
    row = next(s for s in _STORE.list_schedules(limit=200) if s["schedule_id"] == sid)
    check("C. attendees만 수정 반영", row["attendees"] == ["영희", "민수"], str(row["attendees"]))
    check("C. 없는 id 수정 → ok=False", call(w3.personal_update_saved_schedule, schedule_id="sch_nope", title="z")["ok"] is False)

    # D. 조회 필터
    check("D. list_saved_requests kind=todo 1건", len(call(w3.list_saved_requests, kind="todo")["rows"]) == 1)
    check("D. list_saved_requests 전체(>=5건)", len(call(w3.list_saved_requests)["rows"]) >= 5)
    only20 = call(w3.personal_list_saved_schedules, date_from="2026-07-20", date_to="2026-07-20")["schedules"]
    check("D. 일정 날짜범위 필터", len(only20) >= 1 and all(s["date"] == "2026-07-20" for s in only20))
    check("D. 기본(personal) 조회엔 group 회의B 없음", all(s["title"] != "회의B" for s in call(w3.personal_list_saved_schedules)["schedules"]))
    check("D. kind=group_schedule 조회엔 회의B 있음", any(s["title"] == "회의B" for s in call(w3.personal_list_saved_schedules, kind="group_schedule")["schedules"]))

    # E. 삭제
    check("E. 제목 필터로 회의B 1건 삭제", call(w3.personal_delete_saved_schedules, title="회의B")["deleted_count"] == 1)
    d_none = call(w3.personal_delete_saved_schedules)
    check("E. 조건 없으면 ok=False, 0건", d_none["ok"] is False and d_none["deleted_count"] == 0)
    call(w3.save_structured_request, kind="personal_schedule", title="시간미정F", date="2026-07-25", original_text="x")
    check("E. time_unspecified로 시간없는 일정 삭제", call(w3.personal_delete_saved_schedules, time_unspecified=True)["deleted_count"] >= 1)
    call(w3.personal_delete_saved_schedules, delete_all=True)
    check("E. delete_all 후 일정 0건", len(_STORE.list_schedules(limit=200)) == 0)

    # F. 레거시 wrapper 정규화
    li_sr = w3._save_input_from({"structured_request": {"kind": "todo", "title": "wrapSR", "original_text": "x"}})
    li_pl = w3._save_input_from({"payload": {"kind": "reminder", "title": "wrapPL", "original_text": "x"}})
    check("F. structured_request wrapper 정규화", li_sr.kind == "todo" and li_sr.title == "wrapSR")
    check("F. payload wrapper 정규화", li_pl.kind == "reminder" and li_pl.title == "wrapPL")

    # G. 영속성: 새 store 인스턴스(앱 재시작 가정)로 같은 DB 읽기
    call(w3.save_structured_request, kind="personal_schedule", title="재시작G", date="2026-07-30", start_time="11:00", original_text="x")
    restarted = AppSQLiteStore(_DB)
    survived = [s for s in restarted.list_schedules(limit=200) if s["title"] == "재시작G"]
    check("G. 새 store 인스턴스에서도 저장 일정 조회됨", len(survived) == 1, str(len(survived)))
    rid = next(r["request_id"] for r in restarted.list_saved_requests(kind="personal_schedule", limit=200) if r["title"] == "재시작G")
    check("G. get: 있는 id는 row 반환", call(w3.get_saved_request, request_id=rid)["row"]["request_id"] == rid)
    check("G. get: 없는 id는 row=None", call(w3.get_saved_request, request_id="req_nope")["row"] is None)

    print(f"\n결과: {_passed}개 통과" + (f", 실패 {len(_failed)}개: {_failed}" if _failed else ", 실패 0개"))
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
