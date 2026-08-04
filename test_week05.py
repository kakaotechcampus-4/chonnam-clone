"""Week 5 확장 검증 대본 (LLM 없이 결정적).

실행:
    KANANA_ACTIVE_WEEK=5 PYTHONIOENCODING=utf-8 uv run python test_week05.py

trace_week05_*.py가 LLM 라우팅(변동적)을 보는 반면, 이 대본은 Week5 helper/tool을
직접 호출해 계약과 가드를 결정적으로 점검합니다. 매번 같은 결과이고 프록시/네트워크가
필요 없습니다. (C 갈래는 MCP subprocess를 띄우므로 전체 30초 내외)

데이터 격리
    앱 DB      : AppSQLiteStore 팩토리를 임시 경로용으로 바꿔 끼웁니다.
                 (CONFIG는 frozen dataclass이고 DB 경로에 env 오버라이드가 없습니다)
    외부 DB/MCP: KANANA_EXTERNAL_DB_PATH를 임시 파일로 지정하고 seed 합니다.
    → data/ 의 실제 실습 데이터와 네트워크를 건드리지 않고, 끝나면 임시 폴더를 지웁니다.

점검 갈래
  A. _personal_schedules_for_current_scope — 두 출처 병합, 중복 제거, 대화 범위, DB 날짜 필터
  B. _collect_member_schedules — include_mine, 자기 지칭(조사 포함), 이중집계 방지,
     날짜 경계, end_time 표기, 스키마 일치, MCP 실패 처리
     (fake MCP로 분기를 결정적으로 확인)
  C. 위임 wrapper 계약 — 실제 MCP subprocess로 rows/필터/보존 필드/삭제 가드 확인
  D. tool·prompt 계약 — week05_tools() 구성과 prompt 누적

설계 결정의 근거 (실행으로 남기는 목적)
  · "나"를 외부 조회에서 제외 → B4 (제외하지 않으면 같은 일정이 두 번 집계된다)
  · include_mine → B1/B2 (묻지 않은 내 일정이 rows에 섞이지 않는다)
    이 선택이 남기는 Week 6 누락 위험은 호출 규약으로 막고, 규약이 실제로 지켜지는지는
    trace_week05_mine_inclusion.py가 LLM을 태워 반복 측정한다.
  · 조사 붙은 자기 지칭 → B3b (LLM이 "내가"로 넘겨도 같은 사람으로 본다 — include_mine의 전제)
  · 오탐 방지 → B3c ("나은"·"제니" 같은 실제 이름은 자기 지칭이 아니다)
  · 외부 실패 vs 내 버그 구분 → B17 (내 코드의 버그는 external_error로 삼키지 않는다)
  · member_names 선택 필드 → B19/C8c ("다들 언제 바쁜지"처럼 이름 없는 요청을 표현할 수 있어야 한다.
    MCP tool의 member_names는 필수 list라 None을 그대로 넘기면 경계에서 거부되므로,
    등록 멤버 이름으로 풀어서 넘긴다)
                          → B20 (빈 목록은 전체로 넓히지 않고 '대상 없음'으로 남긴다)
  · extract는 내 일정을 못 본다 → C7d (외부 저장소만 보므로 "나"를 넣어도 앱 일정은 안 나온다.
    rows만 비면 '내 일정 없음'과 구분되지 않으므로 그 사실을 payload에 남긴다)
  · end_time "미정" 통일 → B7 (병합 rows에 None과 "미정"이 섞이지 않는다)
  · 중복 제거 → A4 (week3 personal_create_schedule은 같은 id로 두 저장소에 쓴다)
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

# import 시 참고자료 store가 embedding 네트워크를 호출하지 않도록 has_openai_key를 꺼둔다.
# load_dotenv(override=False)라 미리 넣은 값이 이긴다.
os.environ["PROXY_TOKEN"] = "여기에 api key 입력"  # config.PROXY_TOKEN_PLACEHOLDER
os.environ.setdefault("KANANA_ACTIVE_WEEK", "5")

# 외부 DB/MCP가 실제 data/ 를 건드리지 않도록 import 전에 임시 경로로 돌린다.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="wk5test_"))
_TMP_APP_DB = _TMP_DIR / "app.sqlite3"
_TMP_EXTERNAL_DB = _TMP_DIR / "external.sqlite3"
os.environ["KANANA_EXTERNAL_DB_PATH"] = str(_TMP_EXTERNAL_DB)

import json  # noqa: E402
from typing import Any  # noqa: E402

import student_parts.week05_load_kanas_past_conversations as w5  # noqa: E402
from fixed.app_store import AppSQLiteStore  # noqa: E402
from fixed.external_people_store import (  # noqa: E402
    JULY_PRACTICE_DATE_FROM,
    JULY_PRACTICE_DATE_TO,
    ExternalPeopleSQLiteStore,
)
from fixed.session_scope import conversation_session_scope  # noqa: E402
from student_parts.week01_wake_up_nana import PERSONAL_SCHEDULES  # noqa: E402
from student_parts.week04_retrieve_nanas_memory import week04_prompt_parts, week04_tools  # noqa: E402

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


# ── 격리 준비 ────────────────────────────────────────────────────────────────
def _prepare_stores() -> AppSQLiteStore:
    """임시 앱 DB와 임시 외부 DB(seed 포함)를 만들고, 앱 store를 바꿔 끼웁니다."""

    app_store = AppSQLiteStore(_TMP_APP_DB)
    app_store.initialize()

    external = ExternalPeopleSQLiteStore(_TMP_EXTERNAL_DB)
    external.initialize()
    external.seed()

    # week05 모듈은 호출 시점에 AppSQLiteStore 를 전역에서 찾으므로, 경로를 무시하고
    # 임시 store 를 돌려주는 팩토리로 바꿔 끼운다.
    w5.AppSQLiteStore = lambda _path: app_store  # type: ignore[assignment]
    return app_store


def _insert_app_schedule(
    schedule_id: str,
    title: str,
    date: str | None,
    start_time: str | None = "09:00",
    end_time: str | None = None,
    attendees: list[str] | None = None,
    created_at: str = "2026-07-01T00:00:00+09:00",
) -> None:
    """검증용 앱 일정 row를 임시 DB에 직접 넣습니다.

    저장 경로(save_structured_request)는 공유 저장소 동기화까지 하므로 MCP subprocess를
    띄웁니다. 여기서는 '이미 저장된 일정'이 입력일 뿐이라 fixture row를 직접 넣습니다.
    (저장 흐름 자체는 Week 3 테스트가 검증합니다)
    """

    with sqlite3.connect(_TMP_APP_DB) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO schedules "
            "(schedule_id, request_id, owner, title, date, start_time, end_time, "
            " attendees_json, source, created_at) "
            "VALUES (?, ?, 'me', ?, ?, ?, ?, ?, 'test', ?)",
            (
                schedule_id,
                f"req_{schedule_id}",
                title,
                date,
                start_time,
                end_time,
                json.dumps(attendees or [], ensure_ascii=False),
                created_at,
            ),
        )


def _clear_app_schedules() -> None:
    with sqlite3.connect(_TMP_APP_DB) as conn:
        conn.execute("DELETE FROM schedules")


# ── A. _personal_schedules_for_current_scope ────────────────────────────────
def section_a() -> None:
    print("\n== A. _personal_schedules_for_current_scope ==")
    _clear_app_schedules()
    PERSONAL_SCHEDULES.clear()

    _insert_app_schedule("sch_a1", "저장 일정1", "2026-07-08", "14:00")
    _insert_app_schedule("sch_a2", "저장 일정2", "2026-07-15", "09:00")

    titles = lambda rows: sorted(str(r.get("title")) for r in rows)  # noqa: E731

    got = w5._personal_schedules_for_current_scope()
    check("A1. SQLite 저장 일정을 반환", titles(got) == ["저장 일정1", "저장 일정2"], str(titles(got)))

    # 현재 대화 임시 일정은 합치고, 다른 대화 것은 제외한다.
    PERSONAL_SCHEDULES.append({"id": "personal_now", "title": "임시 현재", "date": "2026-07-09",
                               "start_time": "15:00", "attendees": [], "session_id": "conv_A"})
    PERSONAL_SCHEDULES.append({"id": "personal_other", "title": "임시 다른대화", "date": "2026-07-09",
                               "start_time": "16:00", "attendees": [], "session_id": "conv_B"})
    with conversation_session_scope("conv_A"):
        merged = w5._personal_schedules_for_current_scope()
    check("A2. 현재 대화 임시 일정이 합쳐짐", "임시 현재" in titles(merged), str(titles(merged)))
    check("A3. 다른 대화 임시 일정은 제외", "임시 다른대화" not in titles(merged), str(titles(merged)))

    # ★ week3 personal_create_schedule 은 임시 일정을 같은 id로 SQLite에도 저장한다.
    #   그래서 식별자로 걸러내지 않으면 같은 일정이 두 번 들어간다.
    PERSONAL_SCHEDULES.clear()
    _insert_app_schedule("personal_dup", "이중기록 일정", "2026-07-10", "11:00")
    PERSONAL_SCHEDULES.append({"id": "personal_dup", "title": "이중기록 일정", "date": "2026-07-10",
                               "start_time": "11:00", "attendees": [], "session_id": "conv_A"})
    with conversation_session_scope("conv_A"):
        dedup = w5._personal_schedules_for_current_scope()
    same = [r for r in dedup if str(r.get("title")) == "이중기록 일정"]
    check("A4. 같은 식별자는 1건으로 합쳐짐 (week3 이중기록)", len(same) == 1, f"{len(same)}건")

    # id를 못 읽는 임시 row는 중복이라 단정하지 않고 남긴다(유실 방지).
    PERSONAL_SCHEDULES.clear()
    PERSONAL_SCHEDULES.append({"title": "id 없음", "date": "2026-07-11",
                               "start_time": "10:00", "attendees": [], "session_id": "conv_A"})
    with conversation_session_scope("conv_A"):
        noid = w5._personal_schedules_for_current_scope()
    check("A5. id 없는 임시 row는 유지", "id 없음" in titles(noid), str(titles(noid)))

    # 날짜 범위를 주면 DB 단계에서 좁힌다(limit로 늦은 날짜가 잘리는 것 방지).
    PERSONAL_SCHEDULES.clear()
    narrowed = w5._personal_schedules_for_current_scope("2026-07-08", "2026-07-08")
    check("A6. 날짜 범위를 주면 DB에서 좁혀짐", titles(narrowed) == ["저장 일정1"], str(titles(narrowed)))

    blank = w5._personal_schedules_for_current_scope("", "")
    check("A7. 빈 경계는 필터 없음과 같음", len(blank) == len(w5._personal_schedules_for_current_scope()),
          f"{len(blank)}건")


# ── B. _collect_member_schedules (fake MCP) ─────────────────────────────────
class FakeMCP:
    """call_mcp_tool_sync 를 대신해 호출 인자를 기록하고 정해진 rows를 돌려줍니다."""

    def __init__(self, rows: list[dict[str, Any]] | None = None, fail: bool = False):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.rows = rows if rows is not None else [{
            "member_name": "철수", "title": "고객 인터뷰", "date": "2026-07-09",
            "start_time": "14:00", "end_time": "15:30", "notes": "",
            "source_conversation_id": "ext_cs",
        }]
        self.fail = fail

    def __call__(self, tool_name: str, args: dict[str, Any]) -> str:
        self.calls.append((tool_name, args))
        if self.fail:
            raise RuntimeError("MCP subprocess 기동 실패(모의)")
        return json.dumps({"ok": True, "tool_name": tool_name, "rows": self.rows},
                          ensure_ascii=False)


def _collect(members: list[str] | None, date_from: str, date_to: str,
             mine: list[dict[str, Any]], fake: FakeMCP) -> dict[str, Any]:
    original = w5.call_mcp_tool_sync
    w5.call_mcp_tool_sync = fake
    try:
        return w5._collect_member_schedules(
            member_names=members, date_from=date_from, date_to=date_to, personal_schedules=mine)
    finally:
        w5.call_mcp_tool_sync = original


def section_b() -> None:
    print("\n== B. _collect_member_schedules (fake MCP) ==")
    MINE = [
        {"schedule_id": "m1", "title": "내 일정", "date": "2026-07-09",
         "start_time": "10:00", "end_time": "11:00", "attendees": ["철수"]},
        {"schedule_id": "m2", "title": "범위 밖", "date": "2026-07-30",
         "start_time": "10:00", "end_time": None, "attendees": []},
        {"schedule_id": "m3", "title": "날짜 없음", "date": None,
         "start_time": None, "end_time": None, "attendees": []},
        {"schedule_id": "m4", "title": "종료 없음", "date": "2026-07-09",
         "start_time": "16:00", "end_time": None, "attendees": []},
    ]
    names = lambda r: sorted({str(x.get("member_name")) for x in r["rows"]})  # noqa: E731

    with_me = _collect(["나", "철수"], "2026-07-09", "2026-07-09", MINE, FakeMCP())
    check("B1. \"나\" 포함 → 내 일정이 rows에 있음", "나" in names(with_me), str(names(with_me)))

    without_me = _collect(["철수"], "2026-07-09", "2026-07-09", MINE, FakeMCP())
    check("B2. \"나\" 미포함 → 내 일정이 섞이지 않음", "나" not in names(without_me), str(names(without_me)))

    self_ref = _collect(["저", "철수"], "2026-07-09", "2026-07-09", MINE, FakeMCP())
    check("B3. '저'도 자기 지칭으로 처리", "나" in names(self_ref), str(names(self_ref)))

    # 조사가 붙어 오는 경우까지 같은 사람으로 본다 (LLM이 "내가 언제 바빠"를 그대로 넘길 수 있다).
    # 자기 지칭 판정이 빗나가면 내 일정이 조용히 빠지므로, 이 정규화가 include_mine의 전제다.
    for token in ("내가", "제가", "나는", "저는", "본인은", "나도"):
        with_particle = _collect([token, "철수"], "2026-07-09", "2026-07-09", MINE, FakeMCP())
        check(f"B3b. 조사 붙은 자기 지칭 '{token}'을 \"나\"로 정규화",
              "나" in names(with_particle), str(with_particle.get("member_names")))

    # 반대로 접두어만 같은 실제 이름을 자기 지칭으로 오인하면 남의 일정 조회가 통째로 사라진다.
    # ("나은"은 받침 없는 "나"에 "은"이 붙을 수 없으므로 조사 결합이 아니다)
    for name in ("나은", "나연", "제니", "저스틴", "내털리", "본인철"):
        other = FakeMCP()
        result = _collect([name], "2026-07-09", "2026-07-09", MINE, other)
        sent = other.calls[0][1].get("member_names") if other.calls else None
        check(f"B3c. 실제 이름 '{name}'은 자기 지칭이 아님",
              "나" not in names(result) and sent == [name],
              f"members={names(result)} sent={sent}")

    # ★ 외부 조회 대상에서 "나"를 빼야 한다. 공유 저장소로 동기화된 "나" 사본이
    #   외부 일정으로 또 잡히면 같은 일정이 두 번 집계된다.
    fake = FakeMCP()
    _collect(["나", "철수"], "2026-07-09", "2026-07-09", MINE, fake)
    sent = fake.calls[0][1].get("member_names") if fake.calls else None
    check("B4. 외부 조회 인자에 \"나\"가 없음 (이중집계 방지)",
          sent is not None and "나" not in sent, str(sent))

    # 외부 대상이 없으면 MCP를 아예 부르지 않는다.
    # (빈 목록을 None으로 바꿔 넘기면 store가 멤버 전체를 반환해 남의 일정이 딸려온다)
    only_me = FakeMCP()
    solo = _collect(["나"], "2026-07-09", "2026-07-09", MINE, only_me)
    check("B5. 외부 대상 없으면 MCP 호출 0회", len(only_me.calls) == 0, f"{len(only_me.calls)}회")
    check("B5b. 그때 rows는 내 일정만", names(solo) == ["나"], str(names(solo)))

    empty = FakeMCP()
    none_asked = _collect([], "2026-07-09", "2026-07-09", MINE, empty)
    check("B6. member_names 빈 목록 → 외부 조회 없음", len(empty.calls) == 0, f"{len(empty.calls)}회")
    check("B6b. 그때 rows도 비어 있음", none_asked["rows"] == [], str(none_asked["rows"]))

    # 스키마 일치와 값 표기
    rows = with_me["rows"]
    keysets = {tuple(sorted(r.keys())) for r in rows}
    check("B7. 내 row와 외부 row의 키 집합이 동일", len(keysets) == 1, str(keysets))
    expected = ("date", "end_time", "member_name", "notes", "start_time", "title")
    check("B7b. busy-time 6개 필드를 유지", keysets == {expected}, str(keysets))

    mine_rows = [r for r in rows if r.get("member_name") == "나"]
    ends = {str(r.get("end_time")) for r in rows}
    check("B8. end_time에 None이 섞이지 않음 (\"미정\"으로 통일)",
          all(r.get("end_time") is not None for r in rows), str(ends))
    check("B8b. 종료 시간 없는 일정은 \"미정\"",
          any(r.get("title") == "종료 없음" and r.get("end_time") == "미정" for r in mine_rows), str(ends))
    check("B8c. 실제 종료 시간은 보존",
          any(r.get("title") == "내 일정" and r.get("end_time") == "11:00" for r in mine_rows), str(ends))
    check("B9. 참석자는 notes에 남김",
          any(r.get("notes") == "참석자: 철수" for r in mine_rows),
          str([r.get("notes") for r in mine_rows]))

    my_titles = sorted(str(r.get("title")) for r in mine_rows)
    check("B10. 날짜 없는 일정은 제외", "날짜 없음" not in my_titles, str(my_titles))
    check("B11. 범위 밖 일정은 제외", "범위 밖" not in my_titles, str(my_titles))

    iso = _collect(["나", "철수"], "2026-07-09T00:00:00", "2026-07-09T23:59:59", MINE, FakeMCP())
    check("B12. ISO datetime 경계를 날짜로 정규화",
          iso["date_from"] == "2026-07-09" and iso["date_to"] == "2026-07-09",
          f"{iso['date_from']}~{iso['date_to']}")

    # 빈 date_to 는 store의 date <= '' 와 같은 판정(아무것도 통과하지 않음)이어야 한다.
    blank_to = _collect(["나"], "2026-07-09", "", MINE, FakeMCP())
    check("B13. 빈 date_to는 store와 같은 판정 (내 rows 0건)",
          blank_to["rows"] == [], str(len(blank_to["rows"])))
    reversed_range = _collect(["나"], "2026-07-15", "2026-07-07", MINE, FakeMCP())
    check("B14. 뒤집힌 범위는 0건", reversed_range["rows"] == [], str(len(reversed_range["rows"])))

    # 정상/실패 payload 계약
    check("B15. 정상 payload에 ok=True, 실패 필드 없음",
          with_me.get("ok") is True and "external_error" not in with_me and "warning" not in with_me,
          str(sorted(with_me.keys())))
    check("B15b. schedule_summary를 함께 반환", isinstance(with_me.get("schedule_summary"), str))

    failed = _collect(["나", "철수"], "2026-07-09", "2026-07-09", MINE, FakeMCP(fail=True))
    check("B16. MCP 실패가 예외로 전파되지 않음", isinstance(failed, dict))
    check("B16b. 실패 시 ok=False", failed.get("ok") is False, str(failed.get("ok")))
    check("B16c. 실패 시 external_error/warning 표시",
          bool(failed.get("external_error")) and bool(failed.get("warning")),
          str(failed.get("external_error")))
    check("B16d. 실패해도 내 일정은 보존",
          any(r.get("member_name") == "나" for r in failed["rows"]), str(len(failed["rows"])))

    # ★ "외부 호출이 실패한 것"과 "이 함수에 버그가 있는 것"은 다르게 다뤄야 한다.
    #   버그까지 external_error에 담으면 '외부 시스템 탓' warning 뒤에 숨어 조용히 넘어간다.
    def _bug(tool_name: str, args: dict[str, Any]) -> str:
        raise KeyError("collect 블록 안의 오타(모의)")

    raised: BaseException | None = None
    try:
        _collect(["나", "철수"], "2026-07-09", "2026-07-09", MINE, _bug)  # type: ignore[arg-type]
    except KeyError as exc:
        raised = exc
    check("B17. 내 코드 버그(KeyError)는 삼키지 않고 그대로 전파",
          isinstance(raised, KeyError), type(raised).__name__)

    # 반대로 경계 너머의 실패는 예외로 올리지 않고 external_error로 표시한다.
    def _broken_json(tool_name: str, args: dict[str, Any]) -> str:
        return "이건 JSON이 아니다"

    broken = _collect(["나", "철수"], "2026-07-09", "2026-07-09", MINE, _broken_json)  # type: ignore[arg-type]
    check("B17b. JSON 파싱 실패는 외부 실패로 표시",
          broken.get("ok") is False and "JSONDecodeError" in str(broken.get("external_error")),
          str(broken.get("external_error")))

    def _list_payload(tool_name: str, args: dict[str, Any]) -> str:
        return "[]"

    odd = _collect(["나", "철수"], "2026-07-09", "2026-07-09", MINE, _list_payload)  # type: ignore[arg-type]
    check("B17c. dict가 아닌 payload도 외부 실패로 표시",
          odd.get("ok") is False and "UnexpectedPayload" in str(odd.get("external_error")),
          str(odd.get("external_error")))
    check("B17d. 그 경우에도 내 일정은 보존",
          any(r.get("member_name") == "나" for r in odd["rows"]), str(len(odd["rows"])))

    # TypeError는 내 버그 목록에서 뺐다. fixed/mcp_client.py의 _mcp_result_to_text가
    # json.dumps(result)로 끝나므로, 어댑터가 직렬화 불가능한 객체를 주면 경계 너머에서
    # TypeError가 올라온다. 이걸 내 버그로 분류하면 외부 실패에 내 일정까지 못 쓰게 된다.
    def _boundary_type_error(tool_name: str, args: dict[str, Any]) -> str:
        raise TypeError("Object of type object is not JSON serializable")

    boundary = _collect(["나", "철수"], "2026-07-09", "2026-07-09", MINE,
                        _boundary_type_error)  # type: ignore[arg-type]
    check("B17e. 경계에서 온 TypeError는 외부 실패로 표시(전파 아님)",
          boundary.get("ok") is False and "TypeError" in str(boundary.get("external_error")),
          str(boundary.get("external_error")))
    check("B17f. 그 경우에도 내 일정은 보존",
          any(r.get("member_name") == "나" for r in boundary["rows"]), str(len(boundary["rows"])))

    # ★ include_mine을 유지하면 "나"를 빼먹은 호출이 흔적 없이 지나간다. rows는 그대로 두고
    #   무엇이 빠졌는지만 payload에 남겨, 규약 위반이 사후에 확인되게 한다.
    check("B18. \"나\" 미포함 + 범위 내 내 일정 있음 → 제외 사실을 기록",
          bool(without_me.get("mine_excluded_note")), str(sorted(without_me.keys())))
    # MINE 중 2026-07-09 범위에 드는 것은 m1, m4 두 건이다 (m2는 범위 밖, m3은 날짜 없음).
    check("B18b. 제외 건수가 실제 건수와 일치",
          without_me.get("mine_excluded_count") == 2, str(without_me.get("mine_excluded_count")))
    # 기록은 사실만 남기고 데이터는 오염시키지 않는다 — 답할 수단 자체를 주지 않는다.
    check("B18c. 기록해도 rows에는 내 일정이 없음",
          "나" not in names(without_me), str(names(without_me)))
    check("B18d. \"나\"를 포함해 부르면 제외 표시가 없음",
          "mine_excluded_note" not in with_me and "mine_excluded_count" not in with_me,
          str(sorted(with_me.keys())))

    # 빠진 게 없으면 표시하지 않는다. 매번 붙는 잡음은 곧 무시된다.
    out_of_range = _collect(["철수"], "2026-07-20", "2026-07-21", MINE, FakeMCP())
    check("B18e. 범위 내 내 일정이 없으면 표시하지 않음",
          "mine_excluded_note" not in out_of_range, str(sorted(out_of_range.keys())))
    no_mine = _collect(["철수"], "2026-07-09", "2026-07-09", [], FakeMCP())
    check("B18f. 내 일정 자체가 없어도 표시하지 않음",
          "mine_excluded_note" not in no_mine, str(sorted(no_mine.keys())))

    # ★ "다들 언제 바쁜지 모아줘"처럼 이름이 안 나오는 요청 — member_names를 넘기지 않는 경로.
    #   MCP tool의 member_names는 필수 list라 None을 그대로 넘길 수 없으므로,
    #   공유 저장소에 등록된 멤버 이름으로 풀어서 넘겨야 한다.
    everyone_mcp = FakeMCP()
    everyone = _collect(None, "2026-07-09", "2026-07-09", MINE, everyone_mcp)
    called = [name for name, _ in everyone_mcp.calls]
    check("B19. 대상 미지정 → 등록 멤버를 먼저 조회",
          called[:1] == ["list_shared_schedules"], str(called))
    sent_all = next((a.get("member_names") for n, a in everyone_mcp.calls
                     if n == "extract_schedules_from_history"), None)
    check("B19b. 등록 멤버 이름으로 풀어서 외부 조회 (None을 그대로 넘기지 않음)",
          sent_all == ["철수"], str(sent_all))
    check("B19c. member_scope에 전체 조회 근거가 남음",
          everyone.get("member_scope") == w5.MEMBER_SCOPE_ALL_REGISTERED,
          str(everyone.get("member_scope")))
    # 전체를 물었으면 나도 대상이다. 특정 이름을 물은 게 아니므로 "묻지 않은 내 일정"이 아니다.
    check("B19d. 전체 조회에는 \"나\"도 포함됨",
          "나" in names(everyone) and "mine_excluded_note" not in everyone, str(names(everyone)))
    check("B19e. payload member_names에 실제 조회 대상이 남음",
          everyone.get("member_names") == ["나", "철수"], str(everyone.get("member_names")))

    # ★ 빈 목록은 전체로 넓히지 않는다 — "철수 일정"을 물었는데 이름 전달만 실패한 경우까지
    #   전체 조회로 바뀌면 묻지 않은 사람들의 일정을 답하게 된다(include_mine과 같은 이유).
    none_mcp = FakeMCP()
    none_asked = _collect([], "2026-07-09", "2026-07-09", MINE, none_mcp)
    check("B20. 빈 목록은 전체로 확대되지 않음 (MCP 호출 0회)", len(none_mcp.calls) == 0,
          str([n for n, _ in none_mcp.calls]))
    check("B20b. member_scope가 '대상 없음'",
          none_asked.get("member_scope") == w5.MEMBER_SCOPE_NONE_REQUESTED,
          str(none_asked.get("member_scope")))
    check("B20c. 빈 rows를 '아무도 안 바쁘다'로 읽지 않도록 members_note를 남김",
          bool(none_asked.get("members_note")), str(none_asked.get("members_note")))
    blank_names = _collect(["  "], "2026-07-09", "2026-07-09", MINE, FakeMCP())
    check("B20d. 공백만 있는 이름도 '대상 없음' (전체로 넓히지 않음)",
          blank_names.get("member_scope") == w5.MEMBER_SCOPE_NONE_REQUESTED,
          str(blank_names.get("member_scope")))

    # 등록 멤버 목록 조회가 실패하면 누구에게 물어야 할지 모른다. 예외로 터뜨리지 않고
    # 실패를 표시하되 내 일정은 지킨다(B16과 같은 원칙).
    class NoMemberListMCP(FakeMCP):
        def __call__(self, tool_name: str, args: dict[str, Any]) -> str:
            self.calls.append((tool_name, args))
            if tool_name == "list_shared_schedules":
                raise RuntimeError("등록 멤버 조회 실패(모의)")
            return json.dumps({"ok": True, "tool_name": tool_name, "rows": self.rows},
                              ensure_ascii=False)

    lost = _collect(None, "2026-07-09", "2026-07-09", MINE, NoMemberListMCP())
    check("B21. 등록 멤버 조회 실패는 예외 대신 실패 표시",
          lost.get("ok") is False and bool(lost.get("external_error")),
          str(lost.get("external_error")))
    check("B21b. 그때도 warning으로 '한가하다'고 읽히지 않게 안내", bool(lost.get("warning")),
          str(lost.get("warning")))
    check("B21c. 실패해도 내 일정은 보존", names(lost) == ["나"], str(names(lost)))


# ── C. 위임 wrapper 계약 (실제 MCP) ──────────────────────────────────────────
def section_c() -> None:
    print("\n== C. 위임 wrapper 계약 (실제 MCP subprocess) ==")

    found = call(w5.search_previous_conversations, query="QA 리뷰", member_names=["철수"], limit=5)
    check("C1. search: ok/rows 구조", found.get("ok") is True and isinstance(found.get("rows"), list))
    row_keys = set(found["rows"][0]) if found["rows"] else set()
    check("C1b. search rows에 conversation_id/member_name/content",
          {"conversation_id", "member_name", "content"} <= row_keys, str(sorted(row_keys)))
    check("C2. search 멤버 필터가 적용됨",
          {r["member_name"] for r in found["rows"]} <= {"철수"},
          str({r["member_name"] for r in found["rows"]}))

    blank_q = call(w5.search_previous_conversations, query="", member_names=["철수"], limit=3)
    check("C3. search 빈 query에도 안전(오류 없이 rows)",
          blank_q.get("ok") is True and isinstance(blank_q.get("rows"), list))
    no_member = call(w5.search_previous_conversations, query="회의", member_names=[], limit=3)
    check("C4. search member_names=[] → 0건 (None과 뜻이 다름)", no_member["rows"] == [],
          str(len(no_member["rows"])))

    conv_id = found["rows"][0]["conversation_id"] if found["rows"] else "ext_cs"
    loaded = call(w5.load_conversation_messages, conversation_id=conv_id)
    times = [r.get("created_at") for r in loaded["rows"]]
    check("C5. load: created_at 오름차순 보존", times == sorted(times), str(times))
    check("C5b. load rows에 sender/content/created_at",
          all({"sender", "content", "created_at"} <= set(r) for r in loaded["rows"]),
          str(sorted(loaded["rows"][0])) if loaded["rows"] else "rows 없음")
    missing = call(w5.load_conversation_messages, conversation_id="ext_zzz")
    check("C6. load 없는 대화 id → 0건", missing["rows"] == [], str(len(missing["rows"])))

    extracted = call(w5.extract_schedules_from_history, member_names=["철수", "영희"],
                     date_from=JULY_PRACTICE_DATE_FROM, date_to=JULY_PRACTICE_DATE_TO)
    need = {"member_name", "title", "date", "start_time", "end_time", "notes"}
    check("C7. extract rows가 6개 필수 필드 유지",
          bool(extracted["rows"]) and all(need <= set(r) for r in extracted["rows"]),
          str(sorted(extracted["rows"][0])) if extracted["rows"] else "rows 없음")
    check("C7b. extract가 schedule_summary 포함", isinstance(extracted.get("schedule_summary"), str))
    check("C7c. 남만 물으면 mine_note를 붙이지 않음", "mine_note" not in extracted,
          str(sorted(extracted.keys())))

    # ★ 이 도구는 외부 저장소만 본다. "나"를 넣어 부르면 앱 DB의 내 일정은 조회되지 않는데
    #   결과는 ok=true에 rows만 비어 "내 일정이 없다"와 구분되지 않는다(엣지 트레이스에서
    #   실제로 이 경로를 탔다). rows는 그대로 두고 그 사실만 남기는지 본다.
    for token in ("나", "내가"):
        mine_ask = call(w5.extract_schedules_from_history, member_names=[token],
                        date_from=JULY_PRACTICE_DATE_FROM, date_to=JULY_PRACTICE_DATE_TO)
        check(f"C7d. extract에 '{token}'을 넣으면 내 일정을 못 본다는 표시가 붙음",
              bool(mine_ask.get("mine_note")), str(sorted(mine_ask.keys())))
    mixed_ask = call(w5.extract_schedules_from_history, member_names=["나", "철수"],
                     date_from=JULY_PRACTICE_DATE_FROM, date_to=JULY_PRACTICE_DATE_TO)
    check("C7e. 표시를 붙여도 남의 rows는 그대로 보존",
          bool(mixed_ask.get("mine_note"))
          and "철수" in {r.get("member_name") for r in mixed_ask["rows"]},
          str(sorted({r.get("member_name") for r in mixed_ask["rows"]})))
    empty_ask = call(w5.extract_schedules_from_history, member_names=[],
                     date_from=JULY_PRACTICE_DATE_FROM, date_to=JULY_PRACTICE_DATE_TO)
    check("C8. extract member_names=[] → 0건", empty_ask["rows"] == [], str(len(empty_ask["rows"])))
    check("C8b. 그때 '대상 없음'과 안내가 남음",
          empty_ask.get("member_scope") == w5.MEMBER_SCOPE_NONE_REQUESTED
          and bool(empty_ask.get("members_note")), str(empty_ask.get("member_scope")))

    # ★ "다들 언제 바쁜지" — member_names를 넘기지 않는 실제 경로.
    #   MCP tool은 member_names가 필수 list라 None/생략을 거부하므로, wrapper가 이름으로 풀어야
    #   여기서 rows가 나온다. (풀지 않고 그대로 넘기면 ToolException으로 실패한다)
    everyone = call(w5.extract_schedules_from_history,
                    date_from=JULY_PRACTICE_DATE_FROM, date_to=JULY_PRACTICE_DATE_TO)
    everyone_names = {r.get("member_name") for r in everyone["rows"]}
    check("C8c. extract 대상 미지정 → 등록 멤버 전체 rows", len(everyone_names) >= 2,
          str(sorted(everyone_names)))
    one_member = call(w5.extract_schedules_from_history, member_names=["철수"],
                      date_from=JULY_PRACTICE_DATE_FROM, date_to=JULY_PRACTICE_DATE_TO)
    check("C8d. 전체 조회가 한 명 조회보다 많은 rows", len(everyone["rows"]) > len(one_member["rows"]),
          f"{len(everyone['rows'])} vs {len(one_member['rows'])}")

    # collect 도 같은 경로를 지원해야 한다 (Week 6이 이 rows를 busy_rows로 쓰는 tool).
    _clear_app_schedules()
    PERSONAL_SCHEDULES.clear()
    collected_all = call(w5.collect_member_schedules,
                         date_from=JULY_PRACTICE_DATE_FROM, date_to=JULY_PRACTICE_DATE_TO)
    check("C8e. collect 대상 미지정 → 전체 조회 근거와 여러 멤버 rows",
          collected_all.get("member_scope") == w5.MEMBER_SCOPE_ALL_REGISTERED
          and len({r.get("member_name") for r in collected_all["rows"]}) >= 2,
          str(sorted({r.get("member_name") for r in collected_all["rows"]})))
    check("C8f. 그때 \"나\"가 조회 대상에 들어감",
          "나" in (collected_all.get("member_names") or []),
          str(collected_all.get("member_names")))

    default_list = call(w5.list_shared_schedules, member_names=None, date_from=None,
                        date_to=None, source_conversation_id=None, limit=50)
    check("C9. list_shared 필터 없음 → 기본 실습 일정", len(default_list["rows"]) >= 1,
          str(len(default_list["rows"])))
    check("C9b. list_shared가 rows/schedule_summary 유지",
          "rows" in default_list and isinstance(default_list.get("schedule_summary"), str))
    check("C10. list_shared member_names=[] → 0건",
          call(w5.list_shared_schedules, member_names=[], date_from=None, date_to=None,
               source_conversation_id=None, limit=50)["rows"] == [])

    # 등록 → 조회 → 갱신 → 삭제 왕복 (추가 과제)
    sid, src = "shared_test_wk5", "test:wk5"
    created = call(w5.create_shared_schedule, member_name="테스트멤버", title="검증 일정",
                   date="2026-08-11", start_time="14:00", end_time="15:00",
                   notes="wk5 검증", source_conversation_id=src, schedule_id=sid)
    shared = created.get("shared_schedule", {})
    check("C11. create: schedule_id 보존", shared.get("schedule_id") == sid, str(shared.get("schedule_id")))
    check("C11b. create: source_conversation_id 보존",
          shared.get("source_conversation_id") == src, str(shared.get("source_conversation_id")))
    by_src = call(w5.list_shared_schedules, member_names=None, date_from=None, date_to=None,
                  source_conversation_id=src, limit=50)
    check("C11c. 등록한 row가 조회됨", len(by_src["rows"]) == 1, str(len(by_src["rows"])))

    updated = call(w5.create_shared_schedule, member_name="테스트멤버", title="검증 일정(수정)",
                   date="2026-08-11", start_time="16:00", end_time="17:00",
                   notes="wk5 검증2", source_conversation_id=src, schedule_id=sid)
    check("C12. 같은 schedule_id 재등록은 갱신(updated)",
          updated.get("shared_schedule", {}).get("sync_status") == "updated",
          str(updated.get("shared_schedule", {}).get("sync_status")))
    check("C12b. 갱신이 row를 늘리지 않음",
          len(call(w5.list_shared_schedules, member_names=None, date_from=None, date_to=None,
                   source_conversation_id=src, limit=50)["rows"]) == 1)

    nothing = call(w5.delete_shared_schedule, schedule_id=None, source_conversation_id=None)
    check("C13. 인자 없는 삭제는 아무것도 지우지 않음", nothing.get("deleted_count") == 0,
          str(nothing.get("deleted_count")))

    removed = call(w5.delete_shared_schedule, schedule_id=sid, source_conversation_id=None)
    check("C14. delete로 삭제됨", removed.get("deleted_count") == 1, str(removed.get("deleted_count")))
    check("C14b. 삭제 후 조회에서 사라짐",
          call(w5.list_shared_schedules, member_names=None, date_from=None, date_to=None,
               source_conversation_id=src, limit=50)["rows"] == [])


# ── D. tool·prompt 계약 ─────────────────────────────────────────────────────
def section_d() -> None:
    print("\n== D. tool·prompt 계약 ==")
    tools = w5.week05_tools()
    names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools]
    week5_names = [
        "search_previous_conversations",
        "load_conversation_messages",
        "extract_schedules_from_history",
        "create_shared_schedule",
        "delete_shared_schedule",
        "list_shared_schedules",
        "collect_member_schedules",
    ]
    check("D1. week05_tools()에 Week5 tool 7개가 모두 있음",
          all(n in names for n in week5_names),
          str([n for n in week5_names if n not in names]))
    check("D2. Week4 도구 위에 7개를 누적", len(tools) == len(week04_tools()) + 7,
          f"{len(tools)} vs {len(week04_tools())}+7")
    check("D3. tool 이름이 중복되지 않음", len(names) == len(set(names)),
          str([n for n in set(names) if names.count(n) > 1]))
    check("D4. Week5 tool이 모두 args_schema를 가짐",
          all(getattr(t, "args_schema", None) is not None
              for t in tools if getattr(t, "name", "") in week5_names))

    # ★ 프롬프트가 "대상을 지정하지 않을 때는 아예 넘기지 않는다"고 지시하므로,
    #   스키마에서도 실제로 생략할 수 있어야 한다(필수 필드면 LLM이 지킬 방법이 없다).
    for schema_cls in (w5.ExtractSchedulesFromHistoryInput, w5.CollectMemberSchedulesInput):
        required = schema_cls.model_json_schema().get("required", [])
        check(f"D4b. {schema_cls.__name__}.member_names가 선택 필드",
              "member_names" not in required, str(required))
        check(f"D4c. {schema_cls.__name__}의 날짜 범위는 여전히 필수",
              {"date_from", "date_to"} <= set(required), str(required))

    parts = w5.week05_prompt_parts()
    base = week04_prompt_parts()
    check("D5. Week4 prompt 조각을 그대로 누적", parts[:len(base)] == base)
    check("D6. Week5 prompt 조각이 추가됨", len(parts) > len(base), f"{len(parts)} vs {len(base)}")
    check("D7. prompt 조각이 모두 비어있지 않은 문자열",
          all(isinstance(p, str) and p.strip() for p in parts))
    system_prompt = w5.week05_system_prompt()
    check("D8. system prompt에 공유 일정 구분 안내가 들어감",
          "create_shared_schedule" in system_prompt and "collect_member_schedules" in system_prompt)
    check("D9. prompt가 '대상 미지정'과 member_scope 읽는 법을 함께 안내",
          "member_scope" in system_prompt and w5.MEMBER_SCOPE_NONE_REQUESTED in system_prompt,
          "member_scope 안내 없음")


def run() -> int:
    print("Week 5 결정적 검증 (LLM 없음)")
    print(f"임시 데이터: {_TMP_DIR}")
    try:
        _prepare_stores()
        section_a()
        section_b()
        section_c()
        section_d()
    finally:
        PERSONAL_SCHEDULES.clear()
        shutil.rmtree(_TMP_DIR, ignore_errors=True)

    print(f"\n결과: {_passed}개 통과" + (f", 실패 {len(_failed)}개: {_failed}" if _failed else ", 실패 0개"))
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
