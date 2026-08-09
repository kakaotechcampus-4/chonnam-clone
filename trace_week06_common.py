"""Week 6 트레이스 대본들이 공유하는 DB 기준선·뒷정리 helper.

왜 공용 모듈인가
    correctness·delegation 대본은 앱 DB/공유 저장소에 일정을 만들고 끝에서 되돌립니다.
    그 "실행 전 id 스냅샷 → 실행 후 새로 생긴 것만 삭제" 로직이 두 대본에 똑같이 들어가므로,
    복제해 두면 한쪽만 고쳐 정리가 새는 사고가 나기 쉽습니다. 그 부분만 여기 모읍니다.
    (trace_week05_common.py의 TraceRun은 week5 agent에 묶여 있어 week6에는 맞지 않습니다.)
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fixed.app_store import AppSQLiteStore
from fixed.config import CONFIG
from fixed.external_people_store import ExternalPeopleSQLiteStore, external_db_path_from_env
from fixed.langchain_trace import extract_agent_events
from fixed.schedule_decision import parse_time_minutes


def app_ids() -> set[str]:
    """앱 DB에 저장된 일정 id 집합 — 실행 중 새로 생긴 row를 구분하는 기준선입니다."""

    store = AppSQLiteStore(CONFIG.app_db_path)
    return {str(r.get("schedule_id")) for r in store.list_schedules(limit=1000)}


def shared_ids() -> set[str]:
    """공유 저장소 row id 집합. 넓은 날짜 범위를 명시해 앱에서 동기화된 row까지 봅니다."""

    store = ExternalPeopleSQLiteStore(external_db_path_from_env())
    rows = store.list_shared_schedules(date_from="2000-01-01", date_to="2100-01-01", limit=1000)
    return {str(r.get("schedule_id")) for r in rows}


def kana_inner_content(result: dict[str, Any], tool_name: str) -> list[dict[str, Any]]:
    """kana_agent 하위 trace에서 특정 tool이 돌려준 content dict들을 모읍니다.

    supervisor 결과 → kana_agent tool_result → 그 안의 trace(하위 events)에서
    tool_name이 일치하는 tool_result의 content(dict)만 추립니다. 호출부는 여기서
    rows/candidate_slots 등 필요한 필드를 골라 씁니다.
    """

    out: list[dict[str, Any]] = []
    for ev in extract_agent_events(result):
        if ev.get("event") != "tool_result" or ev.get("tool_name") != "kana_agent":
            continue
        content = ev.get("content")
        if not isinstance(content, dict):
            continue
        for inner in content.get("trace", []):
            if inner.get("event") == "tool_result" and inner.get("tool_name") == tool_name:
                c = inner.get("content")
                if isinstance(c, dict):
                    out.append(c)
    return out


def overlaps(slot_start: str, slot_end: str, busy_start: str, busy_end: str) -> bool:
    """두 [start, end) 시간 구간이 겹치는지 판정합니다(HH:MM 문자열)."""

    a0 = parse_time_minutes(slot_start, -1)
    a1 = parse_time_minutes(slot_end, 24 * 60)
    b0 = parse_time_minutes(busy_start, 0)
    b1 = parse_time_minutes(busy_end, 24 * 60)
    return a0 < b1 and b0 < a1


def cleanup_new_rows(app_before: set[str], shared_before: set[str]) -> None:
    """실행 전 기준선과 비교해 새로 생긴 앱/공유 row만 지웁니다.

    기준선에 없던 id만 삭제하므로 실습 seed 데이터는 건드리지 않습니다.
    """

    print("=" * 78)
    print("뒷정리")
    new_app = app_ids() - app_before
    with sqlite3.connect(CONFIG.app_db_path) as conn:
        for sid in new_app:
            conn.execute("DELETE FROM schedules WHERE schedule_id = ?", (sid,))
    print(f"  앱 DB: {len(new_app)}건 삭제 ({', '.join(sorted(new_app)) or '없음'})")

    ext_store = ExternalPeopleSQLiteStore(external_db_path_from_env())
    new_shared = shared_ids() - shared_before
    for sid in new_shared:
        ext_store.delete_shared_schedules(schedule_id=sid)
    print(f"  공유 저장소: {len(new_shared)}건 정리 ({', '.join(sorted(new_shared)) or '없음'})")
