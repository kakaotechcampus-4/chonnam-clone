from __future__ import annotations

"""student_parts/week05_load_kanas_past_conversations.py 테스트.

이 파일은 tests/test_week03_build_nanas_logbook.py와 같은 방식으로,
프로젝트 루트의 software-testing-types.md에서 정리한 테스트 분류를 코드로 옮긴 것이다.
각 테스트 클래스의 docstring 앞에 붙은 [분류] 표시가 이론 문서와 코드를 이어준다.

---

## 1. Week 5 코드가 Week 3 코드와 다른 점

Week 3 대상 함수는 앱 SQLite 파일 하나만 읽고 썼다. Week 5 대상 함수는 두 개의
경계를 더 넘는다.

1. MCP 프로세스 경계
   call_mcp_tool_sync는 mcp_server/sqlite_mcp_server.py를 stdio subprocess로 새로
   기동한다. 실측하면 호출 1회당 약 5초가 걸린다.

2. 두 개의 SQLite 파일
   내 일정은 data/kanana_app.sqlite3(AppSQLiteStore)에서 읽고, 다른 사람의 대화와
   일정은 data/kanana_external_people.sqlite3(ExternalPeopleSQLiteStore)에서 읽는다.

그래서 이 파일의 테스트는 "어느 지점에서 실제 호출을 끊는가"를 기준으로 세 층으로
나뉜다. 아래 다이어그램의 `◀── 교체` 표시가 그 지점이다.

    [도형 범례]
      ┌──┐  함수/@tool                     ___
      └──┘                               /___/|   저장소(SQLite 파일)
                                         |___|/
       .-~-.
      ( ☁ )  프로세스 경계(MCP stdio subprocess)
       `-~-~-'
      ( {...}, {...}, ... )               rows 배열


    (A) 단위 테스트 — call_mcp_tool_sync를 MagicMock으로 교체

      ┌────────────────────────────┐     ┌───────────────────────┐
      │ week05 @tool wrapper       │────▶│ call_mcp_tool_sync    │ ◀── 교체
      └────────────────────────────┘     └───────────────────────┘


    (B) 통합 테스트 — subprocess 경계만 in-process 호출로 교체

      ┌────────────────────────────┐     ┌───────────────────────┐
      │ week05 @tool wrapper       │────▶│ call_mcp_tool_sync    │
      └────────────────────────────┘     └───────────┬───────────┘
                                             .-~-~-~-▼-~-~-~-.
                                            ( ☁ subprocess    ) ◀── 교체
                                             `-~-~-~-┬-~-~-~-'
                                                     ▼
                                         ┌───────────────────────┐
                                         │ @mcp.tool 함수 본문     │ mcp_server/
                                         └───────────┬───────────┘ sqlite_mcp_server.py
                                                     ▼
                                         ┌───────────────────────┐
                                         │ ExternalPeople         │ fixed/external_
                                         │ SQLiteStore            │ people_store.py
                                         └───────────┬───────────┘
                                                     ▼
                                                    ___
                                                   /___/|  tmp_path/external.sqlite3
                                                   |___|/


    (C) subprocess end-to-end 테스트 — 아무것도 교체하지 않는다

      환경 변수 KANANA_EXTERNAL_DB_PATH만 tmp_path로 바꿔서 실습용 DB를 보호하고,
      실제 subprocess를 기동한다. 호출 1회당 수 초가 걸리므로 기본 실행에서는
      건너뛰고 KANANA_TEST_MCP_SUBPROCESS=1일 때만 실행한다.

(B)에서 subprocess만 교체하고 @mcp.tool 함수 본문부터는 실제 코드를 쓰는 이유는,
반환 payload의 필드 구성(ok/tool_name/rows/schedule_summary)과 rows의 필드 이름이
mcp_server/sqlite_mcp_server.py에서 결정되기 때문이다. 이 payload 모양을 테스트
파일에서 다시 만들어 쓰면 서버 쪽 계약이 바뀌어도 테스트가 통과한다.

---

## 2. 테스트 클래스가 대응하는 5가지 분류

1. **화이트박스 테스트**
   함수 내부의 if 분기와 or 기본값 항을 하나씩 실행한다.

2. **블랙박스 테스트**
   구현 대신 가이드 주석에 적힌 입출력 규칙만 보고, 대표 입력(동등 분할)과
   경계 입력(경계값)으로 확인한다.

3. **오류 예측 검사**
   LLM이나 MCP 서버가 규칙에서 벗어난 값을 넘기는 상황을 가정하고 실패/무시
   경로가 명세대로 동작하는지 본다.

4. **Mock 기반 단위 테스트**
   MCP tool과 앱 SQLite store를 MagicMock으로 바꿔서, "wrapper가 의존성을 어떤
   인자로 몇 번 호출했는가"만 확인한다. Java Mockito의 verify(mock).method(...)와
   같은 목적이다.

5. **통합 테스트**
   위 (B), (C) 층이다. 실제 SQLite 파일과 실제 store/MCP tool 함수를 연달아
   호출해서 검색 → 대화 로드 → 일정 추출 → 일정 합치기가 하나의 흐름으로
   맞물리는지 본다.

---

## 3. 실제 앱 실행에서 출발한 테스트

일부 테스트는 이론 분류를 먼저 정한 것이 아니라, `./run.sh --week5`로 앱을 띄우고
채팅에서 요청을 넣어 trace를 읽는 과정에서 계약을 확인한 뒤 추가했다. 그런 테스트의
docstring에는 어떤 trace에서 확인했는지를 한 문장 덧붙여 표시한다.

1. TestCollectMemberSchedulesSpec.test_personal_rows_are_included_even_without_my_name
   member_names=["지훈"]으로 호출된 trace에 personal_row_count=3이 함께 담긴 것을
   확인하고 추가했다.

2. TestCollectMemberSchedulesSpec.test_both_sources_partition
   외부 store가 반환하는 row에 source_conversation_id가 함께 오는 것을 확인하고,
   계약 필드 6개를 "정확히 일치"에서 "포함"으로 나눴다.

---

## 4. 실행 방법

1. 기본 테스트 실행 (프로젝트 루트에서):

       uv run pytest tests/test_week05_load_kanas_past_conversations.py

   pyproject.toml에 pythonpath가 설정되어 있어서 PYTHONPATH를 따로 잡지 않아도
   student_parts/fixed를 import할 수 있다.

2. subprocess end-to-end 테스트까지 실행:

       KANANA_TEST_MCP_SUBPROCESS=1 uv run pytest tests/test_week05_load_kanas_past_conversations.py

   PowerShell에서는 `$env:KANANA_TEST_MCP_SUBPROCESS = "1"`로 설정한 뒤 실행한다.

3. 분기 커버리지 실측:

       uv run --with pytest-cov pytest tests/test_week05_load_kanas_past_conversations.py \\
           --cov=student_parts.week05_load_kanas_past_conversations \\
           --cov-branch --cov-report=term-missing
"""

import importlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import student_parts.week05_load_kanas_past_conversations as week05
from fixed.app_store import AppSQLiteStore
from fixed.external_people_store import (
    JULY_PRACTICE_MEMBER_NAMES,
    PERSONAL_SHARED_MEMBER_NAME,
)
from fixed.runtime_clock import current_app_date_iso
from fixed.session_scope import DEFAULT_SESSION_SCOPE, conversation_session_scope
from student_parts.week01_wake_up_nana import PERSONAL_SCHEDULES
from student_parts.week01_wake_up_nana import personal_create_schedule as week01_personal_create_schedule
from student_parts.week02_structure_natural_language_requests import StructuredRequest
from student_parts.week03_build_nanas_logbook import save_structured_request_payload
from student_parts.week04_retrieve_nanas_memory import week04_prompt_parts, week04_tools
from student_parts.week05_load_kanas_past_conversations import (
    APP_SCHEDULE_FETCH_LIMIT,
    WEEK05_EXTERNAL_HISTORY_PROMPT,
    WEEK05_SCHEDULE_COLLECTION_PROMPT,
    CollectMemberSchedulesInput,
    CreateSharedScheduleInput,
    DeleteSharedScheduleInput,
    ExtractSchedulesFromHistoryInput,
    ListSharedSchedulesInput,
    LoadConversationMessagesInput,
    SearchPreviousConversationsInput,
    _collect_member_schedules,
    _personal_schedule_row,
    _personal_schedules_for_current_scope,
    _row_in_date_range,
    _schedule_identifier,
    _schedule_scope,
    _structured_request_from_schedule_row,
    build_week05_agent,
    build_week_agent,
    collect_member_schedules,
    create_shared_schedule,
    delete_shared_schedule,
    extract_schedules_from_history,
    json_payload,
    list_shared_schedules,
    load_conversation_messages,
    search_previous_conversations,
    week05_prompt_parts,
    week05_system_prompt,
    week05_tools,
)


# --------------------------------------------------------------------------
# 테스트 데이터 helper
# --------------------------------------------------------------------------


def mcp_payload_text(tool_name: str, rows: list[dict[str, Any]], **extra: Any) -> str:
    """MCP tool이 반환하는 JSON 문자열과 같은 모양의 값을 만듭니다."""

    return json.dumps({"ok": True, "tool_name": tool_name, "rows": rows, **extra}, ensure_ascii=False)


def external_row(
    member_name: str,
    title: str,
    date: str,
    start_time: str = "10:00",
    end_time: str = "11:00",
    notes: str = "",
) -> dict[str, Any]:
    """외부 store가 반환하는 일정 row와 같은 필드 구성을 만듭니다."""

    return {
        "member_name": member_name,
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "notes": notes,
    }


def app_schedule_row(
    schedule_id: str = "sch_test0001",
    title: str = "앱 저장 일정",
    date: str = "2026-07-09",
    start_time: str = "09:00",
    end_time: str = "10:00",
    attendees: list[str] | None = None,
) -> dict[str, Any]:
    """AppSQLiteStore.list_schedules가 반환하는 row와 같은 필드 구성을 만듭니다."""

    return {
        "schedule_id": schedule_id,
        "request_id": "req_test0001",
        "owner": "me",
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "attendees": attendees if attendees is not None else [],
        "request_kind": "personal_schedule",
    }


def temporary_schedule_row(
    schedule_id: str = "personal_test0001",
    title: str = "임시 일정",
    date: str = "2026-07-10",
    start_time: str = "13:00",
    end_time: str = "14:00",
    session_id: str = DEFAULT_SESSION_SCOPE,
) -> dict[str, Any]:
    """Week 1 임시 일정 dict와 같은 필드 구성을 만듭니다. 식별자 키가 id인 점이 앱 row와 다릅니다."""

    return {
        "id": schedule_id,
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "attendees": [],
        "created_at": "2026-07-01T09:00:00",
        "session_id": session_id,
    }


RUN_MCP_SUBPROCESS_TESTS = bool(os.getenv("KANANA_TEST_MCP_SUBPROCESS"))
requires_mcp_subprocess = pytest.mark.skipif(
    not RUN_MCP_SUBPROCESS_TESTS,
    reason=(
        "실제 MCP stdio subprocess 호출은 1회당 약 5초가 걸린다. "
        "KANANA_TEST_MCP_SUBPROCESS=1을 설정하면 실행된다."
    ),
)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_week01_memory():
    """Week 1의 PERSONAL_SCHEDULES는 프로세스 전역 리스트라 테스트끼리 오염될 수 있다.

    _personal_schedules_for_current_scope()가 이 리스트를 직접 읽으므로, 각 테스트
    전후로 비워 둔다.
    """

    PERSONAL_SCHEDULES.clear()
    yield
    PERSONAL_SCHEDULES.clear()


@pytest.fixture
def fake_mcp(mocker):
    """week05 모듈이 참조하는 call_mcp_tool_sync 이름을 MagicMock으로 교체한다.

    이 파일은 `call_mcp_tool_sync = call_local_mcp_tool_sync`로 이름만 가져왔으므로,
    patch 대상은 fixed.mcp_client가 아니라 그 이름을 참조하는 week05 모듈이어야 한다
    (파이썬 import 바인딩 규칙). 기본 반환값은 rows가 빈 payload이고, 각 테스트에서
    return_value를 덮어 쓴다.
    """

    return mocker.patch.object(
        week05,
        "call_mcp_tool_sync",
        return_value=mcp_payload_text("extract_schedules_from_history", []),
    )


@pytest.fixture
def fake_external_payload(mocker):
    """load_conversation_messages만 쓰는 call_external_tool_payload를 MagicMock으로 교체한다."""

    return mocker.patch.object(
        week05,
        "call_external_tool_payload",
        return_value={"ok": True, "tool_name": "load_conversation_messages", "rows": []},
    )


@pytest.fixture
def fake_app_store(mocker):
    """_personal_schedules_for_current_scope()가 실제 앱 DB 대신 MagicMock store를 읽게 한다.

    week05 코드는 `AppSQLiteStore(CONFIG.app_db_path)`를 함수 안에서 직접 만들기
    때문에, store 주입 지점이 따로 없다. 그래서 클래스 이름 자체를 교체한다.
    """

    store = mocker.MagicMock()
    store.list_schedules.return_value = []
    mocker.patch.object(week05, "AppSQLiteStore", return_value=store)
    return store


@pytest.fixture
def app_store(tmp_path: Path) -> AppSQLiteStore:
    """테스트마다 새 앱 SQLite 파일에 스키마를 만든다. 실제 앱 DB(data/kanana_app.sqlite3)는 건드리지 않는다."""

    return AppSQLiteStore(tmp_path / "app.sqlite3")


@pytest.fixture
def use_app_store(mocker, app_store: AppSQLiteStore) -> AppSQLiteStore:
    """week05 tool이 임시 앱 SQLite 파일을 읽게 한다."""

    mocker.patch.object(week05, "AppSQLiteStore", return_value=app_store)
    return app_store


@pytest.fixture
def in_process_mcp(mocker, monkeypatch, tmp_path: Path):
    """MCP subprocess 경계만 in-process 호출로 바꾸고 그 아래는 실제 코드를 쓴다.

    처리 순서

    1. 환경 변수를 임시 DB로 바꾼다.
       mcp_server/sqlite_mcp_server.py는 import 시점에 KANANA_EXTERNAL_DB_PATH를
       읽어 STORE를 만든다. 그래서 reload 전에 환경 변수를 바꿔야 실습용
       data/kanana_external_people.sqlite3가 아니라 tmp_path를 쓴다.

    2. 서버 모듈을 reload한다.
       reload가 모듈 본문을 다시 실행하면서 ExternalPeopleSQLiteStore가 임시 파일에
       스키마를 만들고 7월 실습 fixture(대화 6건, 일정 18건)를 seed한다.
       @mcp.tool 데코레이터는 원래 함수를 그대로 반환하므로, 서버의 tool 함수를
       일반 함수처럼 직접 호출할 수 있다.

    3. 두 경계 함수를 같은 dispatch 함수로 교체한다.
       (1) week05.call_mcp_tool_sync — wrapper 4개와 _collect_member_schedules가 쓴다.
       (2) fixed.external_mcp.call_local_mcp_tool_sync — load_conversation_messages가
           쓰는 call_external_tool_payload와, 앱 일정 저장 시 공유 저장소를 맞추는
           sync_personal_schedule_to_shared가 내부에서 이 이름을 호출한다.

    이 fixture가 끝나도 서버 모듈은 임시 DB에 연결된 상태로 남는다. 이 모듈을
    쓰는 곳은 이 fixture뿐이고 매번 reload하므로 다른 테스트에 영향을 주지 않는다.
    """

    monkeypatch.setenv("KANANA_EXTERNAL_DB_PATH", str(tmp_path / "external.sqlite3"))
    server = importlib.reload(importlib.import_module("mcp_server.sqlite_mcp_server"))

    def dispatch(tool_name: str, args: dict[str, Any], db_path: Any = None) -> str:
        """MCP subprocess 대신 서버 모듈의 tool 함수를 같은 프로세스에서 호출합니다."""

        return getattr(server, tool_name)(**args)

    mocker.patch.object(week05, "call_mcp_tool_sync", side_effect=dispatch)
    mocker.patch("fixed.external_mcp.call_local_mcp_tool_sync", side_effect=dispatch)
    return server


@pytest.fixture
def external_db_env(monkeypatch, tmp_path: Path) -> Path:
    """실제 MCP subprocess가 실습용 외부 DB 대신 임시 DB를 쓰게 환경 변수를 바꾼다.

    fixed/mcp_client.py의 load_local_mcp_tools는 os.environ.copy()를 subprocess env로
    넘기므로, 이 환경 변수만 바꾸면 subprocess가 임시 파일을 연다.
    """

    external_path = tmp_path / "external_subprocess.sqlite3"
    monkeypatch.setenv("KANANA_EXTERNAL_DB_PATH", str(external_path))
    return external_path


# --------------------------------------------------------------------------
# 1. 화이트박스 테스트 (구조 기반) - 분기 커버리지
# --------------------------------------------------------------------------


class TestScheduleScopeBranches:
    """[화이트박스 / 구조 기반] _schedule_scope의 `session_id or DEFAULT_SESSION_SCOPE` 두 분기를 실행한다."""

    def test_existing_session_id_is_returned(self):
        """session_id가 있으면 그 값을 그대로 반환하는 참쪽 분기를 실행한다."""

        assert _schedule_scope({"session_id": "conv_a1b2"}) == "conv_a1b2"

    @pytest.mark.parametrize("schedule", [{}, {"session_id": None}, {"session_id": ""}])
    def test_missing_session_id_falls_back_to_default_scope(self, schedule):
        """session_id가 없거나 None/빈 문자열이면 DEFAULT_SESSION_SCOPE로 대체되는 거짓쪽 분기를 실행한다.
        키 자체가 없는 경우는 Week 1 이전에 직접 tool을 호출해 만든 row에서 나타난다."""

        assert _schedule_scope(schedule) == DEFAULT_SESSION_SCOPE


class TestScheduleIdentifierBranches:
    """[화이트박스 / 구조 기반] _schedule_identifier의 `schedule_id or id or ""` 세 항을 각각 실행한다.

    앱 SQLite 일정 row는 schedule_id를, Week 1 임시 일정 row는 id를 식별자로 쓴다.
    두 목록을 합칠 때 중복 판정 기준이 되는 함수다.
    """

    def test_schedule_id_is_preferred_when_both_keys_exist(self):
        """schedule_id와 id가 둘 다 있으면 첫 항인 schedule_id를 쓰는지 확인한다."""

        assert _schedule_identifier({"schedule_id": "sch_1", "id": "personal_1"}) == "sch_1"

    def test_falls_back_to_id_when_schedule_id_missing(self):
        """schedule_id가 없으면 두 번째 항인 id로 넘어가는 분기를 실행한다."""

        assert _schedule_identifier({"id": "personal_1"}) == "personal_1"

    def test_returns_empty_string_when_no_identifier_key(self):
        """두 키가 모두 없으면 마지막 항인 빈 문자열이 되는 분기를 실행한다.
        이 값이 반환되면 중복 판정에서 서로 같은 row로 취급되므로, 아래
        test_untitled_rows_without_identifier_collide가 그 결과를 따로 확인한다."""

        assert _schedule_identifier({"title": "식별자 없는 일정"}) == ""


class TestRowInDateRangeBranches:
    """[화이트박스 / 구조 기반] _row_in_date_range의 3개 if 분기를 각각 실행한다.

    분기: (1) 날짜 값이 없음 (2) date_from보다 이전 (3) date_to보다 이후.
    경계값(범위의 양 끝과 정확히 같은 날짜)은 블랙박스 절의
    TestRowInDateRangeBoundaries가 담당한다.
    """

    @pytest.mark.parametrize("empty_date", [None, "", 0])
    def test_missing_date_is_out_of_range(self, empty_date):
        """날짜가 없는 일정은 첫 if에서 False로 처리되는지 확인한다.
        Week 2 StructuredRequest와 앱 일정 row는 date를 None으로 둘 수 있고, 이때는
        어느 날 바쁜지 판단할 수 없으므로 조율 근거로 쓰지 않는다."""

        assert _row_in_date_range(empty_date, "2026-07-07", "2026-07-17") is False

    def test_date_before_lower_bound_is_excluded(self):
        """date_from보다 이전 날짜가 두 번째 if로 걸러지는지 확인한다."""

        assert _row_in_date_range("2026-07-06", "2026-07-07", "2026-07-17") is False

    def test_date_after_upper_bound_is_excluded(self):
        """date_to보다 이후 날짜가 세 번째 if로 걸러지는지 확인한다."""

        assert _row_in_date_range("2026-07-18", "2026-07-07", "2026-07-17") is False

    @pytest.mark.parametrize(
        "date_from, date_to",
        [("", "2026-07-17"), ("2026-07-07", ""), ("", "")],
    )
    def test_empty_bound_does_not_restrict_that_direction(self, date_from, date_to):
        """범위 경계가 빈 문자열이면 그 방향 조건을 건너뛰는지 확인한다.
        normalize_external_schedule_date_bounds는 인자가 None이면 빈 문자열을 반환하므로,
        이 분기가 "범위 제한 없음"을 뜻하게 된다."""

        assert _row_in_date_range("2026-07-09", date_from, date_to) is True

    def test_non_string_date_is_converted_before_comparison(self):
        """date가 문자열이 아니어도 str()로 변환한 뒤 비교하는 경로를 확인한다.
        날짜 문자열 비교는 자릿수가 고정된 YYYY-MM-DD를 전제로 하므로, 변환 결과가
        그 형식이면 그대로 판정된다."""

        class DateLike:
            def __str__(self) -> str:
                return "2026-07-09"

        assert _row_in_date_range(DateLike(), "2026-07-07", "2026-07-17") is True


class TestStructuredRequestFromScheduleRowBranches:
    """[화이트박스 / 구조 기반] _structured_request_from_schedule_row의 members 후보 3항과 original_text 기본값을 실행한다."""

    def test_attendees_field_is_used_first(self):
        """attendees가 있으면 `attendees or members or []`의 첫 항이 선택되는지 확인한다."""

        row = app_schedule_row(attendees=["나", "철수"])
        assert _structured_request_from_schedule_row(row).members == ["나", "철수"]

    def test_members_field_is_used_when_attendees_is_empty(self):
        """attendees가 빈 리스트면 두 번째 항인 members로 넘어가는 분기를 실행한다.
        앱 일정 row는 attendees를, Week 2 StructuredRequest는 members를 쓰기 때문에
        두 키를 모두 읽어야 한다."""

        row = {"title": "회의", "date": "2026-07-09", "attendees": [], "members": ["영희"]}
        assert _structured_request_from_schedule_row(row).members == ["영희"]

    def test_no_member_key_becomes_empty_list(self):
        """attendees와 members가 모두 없으면 마지막 항인 빈 리스트가 되는 분기를 실행한다."""

        row = {"title": "회의", "date": "2026-07-09"}
        assert _structured_request_from_schedule_row(row).members == []

    def test_kind_is_fixed_to_personal_schedule(self):
        """내 일정 row는 항상 kind="personal_schedule"로 읽는지 확인한다.
        이 값이 RequestKind Literal에 없으면 StructuredRequest 생성 자체가 실패한다."""

        assert _structured_request_from_schedule_row(app_schedule_row()).kind == "personal_schedule"

    @pytest.mark.parametrize("raw_title", [None, ""])
    def test_missing_title_becomes_empty_original_text(self, raw_title):
        """title이 없으면 `str(title or "")` 분기가 original_text를 빈 문자열로 만드는지 확인한다."""

        row = {"title": raw_title, "date": "2026-07-09"}
        result = _structured_request_from_schedule_row(row)
        assert result.original_text == ""
        assert result.title == raw_title or result.title is None


class TestPersonalScheduleRowBranches:
    """[화이트박스 / 구조 기반] _personal_schedule_row의 기본값 대체와 notes 출처 분기를 실행한다."""

    def test_saved_schedule_gets_sqlite_source_note(self):
        """schedule_id가 있으면 notes가 "앱 SQLite 저장 일정"이 되는 참쪽 분기를 실행한다."""

        assert _personal_schedule_row(app_schedule_row())["notes"] == "앱 SQLite 저장 일정"

    def test_temporary_schedule_gets_conversation_source_note(self):
        """schedule_id가 없으면 notes가 "현재 대화 임시 일정"이 되는 거짓쪽 분기를 실행한다.
        Week 1 임시 일정 row는 식별자 키가 id뿐이므로 이 분기를 타게 된다."""

        assert _personal_schedule_row(temporary_schedule_row())["notes"] == "현재 대화 임시 일정"

    def test_member_name_is_fixed_to_shared_personal_name(self):
        """내 일정 row의 member_name이 공유 저장소와 같은 상수("나")로 고정되는지 확인한다.
        Week 6이 두 출처의 row를 같은 사람으로 인식하려면 이 값이 일치해야 한다."""

        row = _personal_schedule_row(app_schedule_row())
        assert row["member_name"] == PERSONAL_SHARED_MEMBER_NAME

    @pytest.mark.parametrize("raw_title", [None, ""])
    def test_missing_title_falls_back_to_default(self, raw_title):
        """title이 비어 있으면 `title or "제목 없음"` 분기가 기본값으로 대체하는지 확인한다."""

        row = _personal_schedule_row({"schedule_id": "sch_1", "title": raw_title, "date": "2026-07-09"})
        assert row["title"] == "제목 없음"

    @pytest.mark.parametrize("raw_time", [None, ""])
    def test_missing_times_fall_back_to_undecided_text(self, raw_time):
        """start_time/end_time이 비어 있으면 "미정"으로 대체되는 분기를 실행한다.
        외부 store가 반환하는 row도 시간이 없을 때 "미정"을 쓰므로 두 출처의 표기가 같아진다."""

        row = _personal_schedule_row(
            {"schedule_id": "sch_1", "title": "회의", "date": "2026-07-09", "start_time": raw_time, "end_time": raw_time}
        )
        assert row["start_time"] == "미정"
        assert row["end_time"] == "미정"

    def test_real_times_are_preserved(self):
        """시간이 실제로 있으면 대체 분기를 타지 않고 값이 보존되는 반대 경로를 확인한다."""

        row = _personal_schedule_row(app_schedule_row(start_time="09:00", end_time="10:00"))
        assert (row["start_time"], row["end_time"]) == ("09:00", "10:00")

    def test_row_has_only_external_row_fields(self):
        """반환 row의 키가 외부 멤버 row와 같은 6개로 맞춰지는지 확인한다.
        owner/attendees 같은 앱 전용 필드가 남으면 두 출처를 한 rows 배열로 합칠 수 없다."""

        row = _personal_schedule_row(app_schedule_row())
        assert set(row) == {"member_name", "title", "date", "start_time", "end_time", "notes"}


class TestPersonalSchedulesForCurrentScopeBranches:
    """[화이트박스 / 구조 기반] _personal_schedules_for_current_scope의 scope 필터와 중복 제거 분기를 실행한다."""

    def test_saved_schedules_come_first_then_temporary(self, fake_app_store):
        """저장 일정 뒤에 임시 일정을 이어 붙이는 반환 순서를 확인한다."""

        fake_app_store.list_schedules.return_value = [app_schedule_row(schedule_id="sch_saved")]
        PERSONAL_SCHEDULES.append(temporary_schedule_row(schedule_id="personal_temp"))

        result = _personal_schedules_for_current_scope()

        assert [_schedule_identifier(row) for row in result] == ["sch_saved", "personal_temp"]

    def test_temporary_schedule_from_other_conversation_is_excluded(self, fake_app_store):
        """다른 대화 범위의 임시 일정이 scope 조건에서 걸러지는지 확인한다.
        _personal_schedules_for_current_scope를 직접 호출하면 현재 범위는
        DEFAULT_SESSION_SCOPE이므로, session_id가 다른 row는 제외되어야 한다."""

        PERSONAL_SCHEDULES.append(temporary_schedule_row(session_id="conv_other"))

        assert _personal_schedules_for_current_scope() == []

    def test_temporary_schedule_duplicating_saved_identifier_is_excluded(self, fake_app_store):
        """저장 일정과 식별자가 같은 임시 일정이 중복 제거 조건에서 걸러지는지 확인한다."""

        fake_app_store.list_schedules.return_value = [app_schedule_row(schedule_id="sch_dup")]
        PERSONAL_SCHEDULES.append(temporary_schedule_row(schedule_id="sch_dup"))

        result = _personal_schedules_for_current_scope()

        assert len(result) == 1
        assert result[0]["schedule_id"] == "sch_dup"

    def test_temporary_schedule_with_distinct_id_is_kept(self, fake_app_store):
        """식별자가 다르면 중복 제거 조건의 반대쪽을 타고 임시 일정이 유지되는지 확인한다.
        앱 일정 id는 "sch_" 접두어, 임시 일정 id는 "personal_" 접두어를 쓰므로 실제
        실행에서는 이쪽이 기본 경로다."""

        fake_app_store.list_schedules.return_value = [app_schedule_row(schedule_id="sch_a")]
        PERSONAL_SCHEDULES.append(temporary_schedule_row(schedule_id="personal_b"))

        assert len(_personal_schedules_for_current_scope()) == 2

    def test_untitled_rows_without_identifier_collide(self, fake_app_store):
        """식별자 키가 없는 row는 _schedule_identifier가 모두 빈 문자열을 반환해 같은 row로 취급되는 결과를 확인한다.
        _schedule_identifier의 빈 문자열 분기가 중복 제거에 미치는 영향을 고정해 둔다."""

        fake_app_store.list_schedules.return_value = [{"title": "식별자 없는 저장 일정", "date": "2026-07-09"}]
        PERSONAL_SCHEDULES.append({"title": "식별자 없는 임시 일정", "date": "2026-07-10"})

        result = _personal_schedules_for_current_scope()

        assert [row["title"] for row in result] == ["식별자 없는 저장 일정"]


class TestCollectMemberSchedulesBranches:
    """[화이트박스 / 구조 기반] _collect_member_schedules의 외부 조회 생략 분기와 rows 병합 분기를 실행한다."""

    def test_personal_only_request_skips_mcp_call(self, fake_mcp):
        """member_names에 "나"만 있으면 외부 조회 대상이 비어 MCP 호출 자체를 건너뛰는 분기를 실행한다.
        MCP 호출 1회는 subprocess를 새로 기동하므로, 이 생략이 응답 시간에 직접 영향을 준다."""

        result = _collect_member_schedules(
            member_names=[PERSONAL_SHARED_MEMBER_NAME],
            date_from="2026-07-07",
            date_to="2026-07-17",
            personal_schedules=[app_schedule_row()],
        )

        fake_mcp.assert_not_called()
        assert result["external_member_names"] == []
        assert result["external_row_count"] == 0

    def test_empty_member_names_skips_mcp_call(self, fake_mcp):
        """member_names가 빈 리스트여도 같은 생략 분기를 타는지 확인한다."""

        result = _collect_member_schedules(
            member_names=[],
            date_from="2026-07-07",
            date_to="2026-07-17",
            personal_schedules=[],
        )

        fake_mcp.assert_not_called()
        assert result["rows"] == []

    def test_external_member_triggers_mcp_call(self, fake_mcp):
        """외부 멤버가 하나라도 있으면 MCP 호출 분기로 들어가는지 확인한다."""

        fake_mcp.return_value = mcp_payload_text(
            "extract_schedules_from_history",
            [external_row("철수", "QA 리뷰", "2026-07-15", "16:00", "17:00")],
        )

        result = _collect_member_schedules(
            member_names=["철수"],
            date_from="2026-07-07",
            date_to="2026-07-17",
            personal_schedules=[],
        )

        fake_mcp.assert_called_once()
        assert result["external_row_count"] == 1

    def test_personal_name_is_removed_from_external_lookup(self, fake_mcp):
        """member_names에 "나"와 외부 멤버가 함께 있으면 "나"만 외부 조회 대상에서 빠지는 분기를 실행한다.
        앱 개인 일정 저장 시 공유 저장소에 member_name="나" 복사본이 생기므로, 이 제외가
        없으면 같은 일정이 rows에 두 번 들어간다."""

        result = _collect_member_schedules(
            member_names=[PERSONAL_SHARED_MEMBER_NAME, "철수"],
            date_from="2026-07-07",
            date_to="2026-07-17",
            personal_schedules=[],
        )

        assert result["member_names"] == [PERSONAL_SHARED_MEMBER_NAME, "철수"]
        assert result["external_member_names"] == ["철수"]

    def test_personal_rows_are_filtered_by_date_range(self, fake_mcp):
        """내 일정에만 _row_in_date_range 필터가 적용되는 분기를 실행한다.
        외부 row는 store가 이미 범위로 좁혀 반환하므로 다시 걸러내지 않는다."""

        result = _collect_member_schedules(
            member_names=[PERSONAL_SHARED_MEMBER_NAME],
            date_from="2026-07-07",
            date_to="2026-07-17",
            personal_schedules=[
                app_schedule_row(schedule_id="sch_in", title="범위 안", date="2026-07-09"),
                app_schedule_row(schedule_id="sch_out", title="범위 밖", date="2026-08-09"),
            ],
        )

        assert [row["title"] for row in result["rows"]] == ["범위 안"]
        assert result["personal_row_count"] == 1

    def test_rows_are_sorted_by_date_start_time_member_name(self, fake_mcp):
        """두 출처를 합친 뒤 (date, start_time, member_name) 순으로 정렬하는 분기를 실행한다.
        정렬 전에는 내 일정이 앞, 외부 일정이 뒤에 놓이므로 정렬이 실제로 실행되지
        않으면 날짜 순서가 뒤섞인다."""

        fake_mcp.return_value = mcp_payload_text(
            "extract_schedules_from_history",
            [
                external_row("철수", "QA 리뷰", "2026-07-15", "16:00", "17:00"),
                external_row("영희", "디자인 피드백", "2026-07-07", "13:00", "14:00"),
            ],
        )

        result = _collect_member_schedules(
            member_names=["철수", "영희"],
            date_from="2026-07-07",
            date_to="2026-07-17",
            personal_schedules=[app_schedule_row(title="내 일정", date="2026-07-09", start_time="09:00")],
        )

        sort_keys = [(row["date"], row["start_time"], row["member_name"]) for row in result["rows"]]
        assert sort_keys == sorted(sort_keys)
        assert [row["date"] for row in result["rows"]] == ["2026-07-07", "2026-07-09", "2026-07-15"]


class TestWeek05ToolsAssembly:
    """[화이트박스 / 구조 기반] week05_tools()의 누적 목록과 미구현 tool 제외를 확인한다."""

    def test_accumulates_all_week04_tools(self):
        """week04_tools()의 tool 이름이 하나도 빠지지 않고 포함되는지 확인한다."""

        week04_names = {tool.name for tool in week04_tools()}
        week05_names = {tool.name for tool in week05_tools()}

        assert week04_names.issubset(week05_names)

    def test_adds_five_week05_mcp_tools(self):
        """이번 주차 메인과제 tool 5개가 추가되는지 확인한다."""

        names = {tool.name for tool in week05_tools()}

        assert {
            "search_previous_conversations",
            "load_conversation_messages",
            "extract_schedules_from_history",
            "list_shared_schedules",
            "collect_member_schedules",
        }.issubset(names)

    def test_excludes_unimplemented_shared_schedule_writers(self):
        """구현하지 않은 추가 과제 tool 2개가 목록에서 제외되는지 확인한다.
        두 함수는 본문이 TODO 상태라 호출하면 None을 반환하고, LangChain tool은 문자열
        반환을 기대하므로 목록에 남기면 LLM이 선택했을 때 오류가 발생한다."""

        names = {tool.name for tool in week05_tools()}

        assert "create_shared_schedule" not in names
        assert "delete_shared_schedule" not in names

    def test_tool_names_are_unique(self):
        """누적 과정에서 같은 이름의 tool이 두 번 들어가지 않는지 확인한다.
        Week 3이 week01의 personal_create_schedule을 같은 이름의 다른 객체로 교체하므로,
        누적 목록에서 이름 중복이 생기기 쉬운 구조다."""

        names = [tool.name for tool in week05_tools()]

        assert len(names) == len(set(names))


# --------------------------------------------------------------------------
# 2. 블랙박스 테스트 (명세 기반) - 동등 분할 / 경계값 분석
# --------------------------------------------------------------------------


class TestRowInDateRangeBoundaries:
    """[블랙박스 / 명세 기반 - 경계값 분석] _row_in_date_range의 범위 양 끝 날짜를 확인한다."""

    @pytest.mark.parametrize(
        "date_text, expected",
        [
            ("2026-07-06", False),
            ("2026-07-07", True),
            ("2026-07-17", True),
            ("2026-07-18", False),
        ],
    )
    def test_range_bounds_are_inclusive(self, date_text, expected):
        """범위 경계와 정확히 같은 날짜는 포함되고, 하루 벗어나면 제외되는지 확인한다.
        범위는 2026-07-07 ~ 2026-07-17이고, 이는 외부 store의 SQL 조건
        `date >= ? AND date <= ?`와 같은 판정이어야 한다."""

        assert _row_in_date_range(date_text, "2026-07-07", "2026-07-17") is expected


class TestJsonPayloadSpec:
    """[블랙박스 / 명세 기반] json_payload가 dict를 한글이 보존되는 JSON 문자열로 바꾸는 규칙을 확인한다."""

    def test_korean_text_is_not_escaped(self):
        """ensure_ascii=False 규칙에 따라 한글이 \\uXXXX로 escape되지 않는지 확인한다."""

        result = json_payload({"title": "회의 준비"})

        assert "회의 준비" in result
        assert "\\u" not in result

    def test_payload_round_trips_without_loss(self):
        """직렬화한 문자열을 다시 파싱하면 원래 dict와 같은지 확인한다.
        rows 안의 중첩 dict와 정수/불리언 타입도 유지되어야 한다."""

        payload = {
            "ok": True,
            "tool_name": "collect_member_schedules",
            "personal_row_count": 2,
            "rows": [external_row("철수", "QA 리뷰", "2026-07-15")],
        }

        assert json.loads(json_payload(payload)) == payload


class TestInputSchemaEquivalencePartitions:
    """[블랙박스 / 명세 기반 - 동등 분할] 각 tool 입력 스키마의 필수/선택 필드 구분을 확인한다."""

    def test_search_input_requires_only_query(self):
        """SearchPreviousConversationsInput은 query만 필수이고 나머지는 기본값이 있는지 확인한다."""

        result = SearchPreviousConversationsInput(query="일정")

        assert result.member_names is None
        assert result.limit == 5

    def test_extract_input_requires_all_three_fields(self):
        """ExtractSchedulesFromHistoryInput은 member_names/date_from/date_to가 모두 필수인지 확인한다."""

        with pytest.raises(ValidationError):
            ExtractSchedulesFromHistoryInput(member_names=["철수"])

    def test_collect_input_requires_all_three_fields(self):
        """CollectMemberSchedulesInput도 같은 3개 필드를 모두 요구하는지 확인한다."""

        with pytest.raises(ValidationError):
            CollectMemberSchedulesInput(member_names=["철수"], date_from="2026-07-07")

    def test_load_input_requires_conversation_id(self):
        """LoadConversationMessagesInput은 conversation_id가 없으면 거부되는지 확인한다."""

        with pytest.raises(ValidationError):
            LoadConversationMessagesInput()

    def test_list_shared_input_accepts_no_filter(self):
        """ListSharedSchedulesInput은 필터를 모두 생략할 수 있고 limit 기본값이 50인지 확인한다.
        필터가 없는 조회는 외부 store에서 실습용 기본 조건으로 대체된다."""

        result = ListSharedSchedulesInput()

        assert (result.member_names, result.date_from, result.date_to, result.source_conversation_id) == (
            None,
            None,
            None,
            None,
        )
        assert result.limit == 50

    def test_create_shared_input_defaults_end_time_to_undecided(self):
        """CreateSharedScheduleInput의 end_time 기본값이 "미정"인지 확인한다.
        구현하지 않은 추가 과제 tool이지만, 스키마는 공유 저장소 계약의 일부이므로
        기본값이 외부 store의 표기와 같아야 한다."""

        result = CreateSharedScheduleInput(
            member_name="철수", title="QA 리뷰", date="2026-07-15", start_time="16:00"
        )

        assert result.end_time == "미정"
        assert result.notes is None
        assert result.schedule_id is None

    def test_delete_shared_input_allows_both_keys_empty(self):
        """DeleteSharedScheduleInput은 두 식별자가 모두 없어도 스키마 단계에서는 통과하는지 확인한다.
        조건 없는 삭제 요청은 스키마가 아니라 외부 store가 빈 목록으로 거부한다."""

        result = DeleteSharedScheduleInput()

        assert (result.schedule_id, result.source_conversation_id) == (None, None)


class TestInputSchemaBoundaries:
    """[블랙박스 / 명세 기반 - 경계값 분석] limit 필드의 ge/le 경계를 확인한다."""

    @pytest.mark.parametrize("invalid_limit", [0, -1, 51])
    def test_search_limit_outside_range_is_rejected(self, invalid_limit):
        """SearchPreviousConversationsInput.limit의 ge=1/le=50 밖 값이 거부되는지 확인한다."""

        with pytest.raises(ValidationError):
            SearchPreviousConversationsInput(query="일정", limit=invalid_limit)

    @pytest.mark.parametrize("boundary_limit", [1, 50])
    def test_search_limit_boundaries_are_accepted(self, boundary_limit):
        """경계값 1과 50은 그대로 통과하는지 확인한다."""

        assert SearchPreviousConversationsInput(query="일정", limit=boundary_limit).limit == boundary_limit

    @pytest.mark.parametrize("invalid_limit", [0, -1, 201])
    def test_list_shared_limit_outside_range_is_rejected(self, invalid_limit):
        """ListSharedSchedulesInput.limit의 ge=1/le=200 밖 값이 거부되는지 확인한다.
        외부 store도 조회 시 max(1, min(limit, 200))으로 범위를 제한하므로 두 층의
        상한이 같아야 한다."""

        with pytest.raises(ValidationError):
            ListSharedSchedulesInput(limit=invalid_limit)

    @pytest.mark.parametrize("boundary_limit", [1, 200])
    def test_list_shared_limit_boundaries_are_accepted(self, boundary_limit):
        """경계값 1과 200은 그대로 통과하는지 확인한다."""

        assert ListSharedSchedulesInput(limit=boundary_limit).limit == boundary_limit


class TestWrapperResultPassthroughSpec:
    """[블랙박스 / 명세 기반] MCP 결과를 가공하지 않고 전달하는 규칙을 확인한다.

    가이드 주석의 규칙은 세 가지다. (1) MCP tool이 이미 계약에 맞는 JSON 문자열을
    반환하므로 다시 파싱/직렬화하지 않는다. (2) 멤버 이름과 날짜 정규화는 store 경계에서
    한 번만 한다. (3) rows의 필드 이름과 순서를 바꾸지 않는다.
    """

    def test_search_returns_mcp_text_object_unchanged(self, fake_mcp):
        """search_previous_conversations가 MCP 결과 문자열 객체를 그대로 반환하는지 is 비교로 확인한다.
        문자열 내용 비교로는 파싱 후 재직렬화한 값과 구분되지 않으므로, 같은 객체인지까지 본다."""

        expected = mcp_payload_text("search_previous_conversations", [{"conversation_id": "ext_cs"}])
        fake_mcp.return_value = expected

        assert search_previous_conversations.func(query="일정") is expected

    def test_extract_returns_mcp_text_object_unchanged(self, fake_mcp):
        """extract_schedules_from_history도 같은 규칙으로 결과 문자열을 그대로 반환하는지 확인한다."""

        expected = mcp_payload_text("extract_schedules_from_history", [], schedule_summary="요약")
        fake_mcp.return_value = expected

        result = extract_schedules_from_history.func(
            member_names=["철수"], date_from="2026-07-07", date_to="2026-07-17"
        )

        assert result is expected

    def test_list_shared_returns_mcp_text_object_unchanged(self, fake_mcp):
        """list_shared_schedules도 결과 문자열을 그대로 반환하는지 확인한다."""

        expected = mcp_payload_text("list_shared_schedules", [], schedule_summary="요약")
        fake_mcp.return_value = expected

        assert list_shared_schedules.func() is expected

    def test_tool_invoke_layer_returns_same_text(self, fake_mcp):
        """agent가 실제로 쓰는 .invoke 경로에서도 문자열 내용이 유지되는지 확인한다.
        위 세 테스트는 함수 본문(.func)을 직접 호출하므로, 스키마 검증과 tool wrapper를
        통과하는 경로는 여기서 따로 본다."""

        expected = mcp_payload_text("search_previous_conversations", [{"conversation_id": "ext_cs"}])
        fake_mcp.return_value = expected

        assert search_previous_conversations.invoke({"query": "일정"}) == expected

    def test_load_conversation_messages_preserves_message_field_order(self, fake_external_payload):
        """load_conversation_messages가 메시지 rows의 필드와 순서를 그대로 유지하는지 확인한다.
        rows는 외부 store가 created_at 기준으로 정렬한 결과이므로, wrapper가 dict를
        다시 만들거나 정렬하면 그 순서가 보존되지 않는다."""

        rows = [
            {"role": "user", "sender": "철수", "content": "첫 메시지", "created_at": "2026-07-01T09:00:00"},
            {"role": "user", "sender": "철수", "content": "두 번째 메시지", "created_at": "2026-07-01T09:05:00"},
        ]
        fake_external_payload.return_value = {
            "ok": True,
            "tool_name": "load_conversation_messages",
            "rows": rows,
        }

        payload = json.loads(load_conversation_messages.invoke({"conversation_id": "ext_cs"}))

        assert payload["rows"] == rows
        assert [row["content"] for row in payload["rows"]] == ["첫 메시지", "두 번째 메시지"]

    def test_load_conversation_messages_keeps_extra_payload_fields(self, fake_external_payload):
        """payload에서 rows만 골라 담지 않고 받은 dict 전체를 전달하는지 확인한다."""

        fake_external_payload.return_value = {
            "ok": True,
            "tool_name": "load_conversation_messages",
            "rows": [],
            "conversation_id": "ext_cs",
        }

        payload = json.loads(load_conversation_messages.invoke({"conversation_id": "ext_cs"}))

        assert payload["conversation_id"] == "ext_cs"
        assert payload["tool_name"] == "load_conversation_messages"


class TestCollectMemberSchedulesSpec:
    """[블랙박스 / 명세 기반 - 동등 분할] collect_member_schedules 반환 payload의 규칙을 확인한다.

    동등 분할 기준은 rows의 출처 조합이다. (1) 내 일정만 (2) 외부 일정만
    (3) 두 출처 모두 (4) 어느 쪽도 없음.
    """

    def test_payload_has_documented_contract_fields(self, fake_mcp, fake_app_store):
        """반환 payload에 rows와 schedule_summary를 포함한 계약 필드가 모두 있는지 확인한다.
        Week 6의 공통 가능 시간 결정 tool이 이 필드 이름을 그대로 읽는다."""

        payload = json.loads(
            collect_member_schedules.invoke(
                {"member_names": ["철수"], "date_from": "2026-07-07", "date_to": "2026-07-17"}
            )
        )

        assert set(payload) == {
            "ok",
            "tool_name",
            "member_names",
            "external_member_names",
            "date_from",
            "date_to",
            "personal_row_count",
            "external_row_count",
            "rows",
            "schedule_summary",
        }
        assert payload["ok"] is True
        assert payload["tool_name"] == "collect_member_schedules"

    def test_personal_only_partition(self, fake_mcp, fake_app_store):
        """내 일정만 있는 경우 rows가 "나" row로만 채워지는지 확인한다."""

        fake_app_store.list_schedules.return_value = [app_schedule_row(title="내 일정")]

        payload = json.loads(
            collect_member_schedules.invoke(
                {
                    "member_names": [PERSONAL_SHARED_MEMBER_NAME],
                    "date_from": "2026-07-07",
                    "date_to": "2026-07-17",
                }
            )
        )

        assert [row["member_name"] for row in payload["rows"]] == [PERSONAL_SHARED_MEMBER_NAME]
        assert (payload["personal_row_count"], payload["external_row_count"]) == (1, 0)

    def test_external_only_partition(self, fake_mcp, fake_app_store):
        """외부 일정만 있는 경우 rows가 외부 멤버 row로만 채워지는지 확인한다."""

        fake_mcp.return_value = mcp_payload_text(
            "extract_schedules_from_history", [external_row("철수", "QA 리뷰", "2026-07-15")]
        )

        payload = json.loads(
            collect_member_schedules.invoke(
                {"member_names": ["철수"], "date_from": "2026-07-07", "date_to": "2026-07-17"}
            )
        )

        assert [row["member_name"] for row in payload["rows"]] == ["철수"]
        assert (payload["personal_row_count"], payload["external_row_count"]) == (0, 1)

    def test_both_sources_partition(self, fake_mcp, fake_app_store):
        """두 출처가 모두 있는 경우 rows가 같은 계약 필드를 갖추는지 확인한다.

        내 일정 row는 계약 필드 6개만 갖고, 외부 row는 store가 붙이는
        source_conversation_id 같은 필드를 더 가질 수 있다. 그래서 내 일정 row는
        정확히 6개인지, 모든 row는 6개를 포함하는지를 나눠서 본다. 이 구분은 실제 앱
        실행 trace에서 외부 row에 source_conversation_id가 함께 오는 것을 확인하고
        나눴다.
        """

        fake_app_store.list_schedules.return_value = [app_schedule_row(title="내 일정", date="2026-07-09")]
        fake_mcp.return_value = mcp_payload_text(
            "extract_schedules_from_history",
            [{**external_row("철수", "QA 리뷰", "2026-07-15"), "source_conversation_id": "ext_cs"}],
        )

        payload = json.loads(
            collect_member_schedules.invoke(
                {
                    "member_names": [PERSONAL_SHARED_MEMBER_NAME, "철수"],
                    "date_from": "2026-07-07",
                    "date_to": "2026-07-17",
                }
            )
        )

        contract_fields = {"member_name", "title", "date", "start_time", "end_time", "notes"}
        personal_row, external_row_result = payload["rows"]
        assert [row["member_name"] for row in payload["rows"]] == [PERSONAL_SHARED_MEMBER_NAME, "철수"]
        assert set(personal_row) == contract_fields
        assert contract_fields.issubset(external_row_result)

    def test_personal_rows_are_included_even_without_my_name(self, fake_mcp, fake_app_store):
        """member_names에 "나"가 없어도 내 일정 row가 rows에 포함되는 계약을 확인한다.

        이 동작이 있어야 "나"를 외부 조회 대상에서 제외해도 내 일정이 누락되지 않는다.
        반대로, 다른 사람 한 명만 물어본 요청에도 범위 안의 내 일정이 함께 들어오므로
        답변 단계에서 걸러내야 한다.

        실제 앱 채팅에서 member_names=["지훈"]으로 호출된 trace에
        personal_row_count=3이 함께 담긴 것을 확인하고 추가한 테스트다.
        """

        fake_app_store.list_schedules.return_value = [app_schedule_row(title="내 일정", date="2026-07-09")]
        fake_mcp.return_value = mcp_payload_text(
            "extract_schedules_from_history", [external_row("지훈", "보안 점검", "2026-07-14")]
        )

        payload = json.loads(
            collect_member_schedules.invoke(
                {"member_names": ["지훈"], "date_from": "2026-07-07", "date_to": "2026-07-17"}
            )
        )

        assert payload["member_names"] == ["지훈"]
        assert payload["personal_row_count"] == 1
        assert [(row["member_name"], row["title"]) for row in payload["rows"]] == [
            (PERSONAL_SHARED_MEMBER_NAME, "내 일정"),
            ("지훈", "보안 점검"),
        ]

    def test_empty_partition_returns_no_schedule_message(self, fake_mcp, fake_app_store):
        """양쪽 모두 없으면 rows가 비고 schedule_summary가 없음 안내 문장이 되는지 확인한다.
        LLM은 이 문장을 근거로 "조회 결과 없음"을 답해야 하며, 없는 시간을 추측하면 안 된다."""

        payload = json.loads(
            collect_member_schedules.invoke(
                {"member_names": ["철수"], "date_from": "2026-07-07", "date_to": "2026-07-17"}
            )
        )

        assert payload["rows"] == []
        assert payload["schedule_summary"] == "조회된 외부 일정이 없습니다."

    def test_summary_has_one_line_per_row(self, fake_mcp, fake_app_store):
        """schedule_summary가 rows 개수와 같은 줄 수로 만들어지는지 확인한다."""

        fake_app_store.list_schedules.return_value = [app_schedule_row(date="2026-07-09")]
        fake_mcp.return_value = mcp_payload_text(
            "extract_schedules_from_history",
            [
                external_row("철수", "QA 리뷰", "2026-07-15"),
                external_row("영희", "발표 리허설", "2026-07-16"),
            ],
        )

        payload = json.loads(
            collect_member_schedules.invoke(
                {
                    "member_names": [PERSONAL_SHARED_MEMBER_NAME, "철수", "영희"],
                    "date_from": "2026-07-07",
                    "date_to": "2026-07-17",
                }
            )
        )

        assert len(payload["schedule_summary"].splitlines()) == len(payload["rows"]) == 3

    def test_member_names_are_normalized_in_payload(self, fake_mcp, fake_app_store):
        """공백이 섞인 이름은 정규화되고 빈 이름은 제거된 결과가 payload에 담기는지 확인한다."""

        payload = json.loads(
            collect_member_schedules.invoke(
                {
                    "member_names": [" 철수 ", "", "영희"],
                    "date_from": "2026-07-07",
                    "date_to": "2026-07-17",
                }
            )
        )

        assert payload["member_names"] == ["철수", "영희"]

    def test_iso_datetime_bounds_are_reduced_to_date(self, fake_mcp, fake_app_store):
        """ISO datetime 형식의 날짜 범위가 날짜 부분만 남기고 정규화되는지 확인한다.
        LLM이 "2026-07-07T00:00:00"처럼 시간까지 붙여 넘기는 경우를 store 경계와 같은
        기준으로 정리해야 문자열 비교 판정이 성립한다."""

        payload = json.loads(
            collect_member_schedules.invoke(
                {
                    "member_names": ["철수"],
                    "date_from": "2026-07-07T00:00:00",
                    "date_to": "2026-07-17T23:59:59",
                }
            )
        )

        assert (payload["date_from"], payload["date_to"]) == ("2026-07-07", "2026-07-17")


class TestWeek05PromptSpec:
    """[블랙박스 / 명세 기반] week05_prompt_parts()/week05_system_prompt()의 누적 규칙을 확인한다."""

    def test_week04_parts_come_first(self):
        """Week 4까지의 prompt 조각이 앞쪽에 그대로 유지되는지 확인한다.
        join_system_prompt는 뒤에 오는 지시를 우선한다고 안내하므로, 이번 주차 지시가
        앞으로 오면 우선순위가 뒤바뀐다."""

        parts = week05_prompt_parts()
        week04_parts = week04_prompt_parts()

        assert parts[: len(week04_parts)] == week04_parts

    def test_week05_parts_are_appended_in_documented_order(self):
        """Week 5 조각 3개가 출처 구분 → 호출 규칙 → 실행 시점 값 순으로 붙는지 확인한다."""

        parts = week05_prompt_parts()
        week05_only = parts[len(week04_prompt_parts()) :]

        assert len(week05_only) == 3
        assert week05_only[0] == WEEK05_EXTERNAL_HISTORY_PROMPT
        assert week05_only[1] == WEEK05_SCHEDULE_COLLECTION_PROMPT

    def test_last_part_contains_current_app_date(self):
        """마지막 조각에 실행 시점의 앱 기준 날짜가 들어가는지 확인한다.
        이 값은 호출 시점에 결정되므로 상수로 둘 수 없다."""

        assert current_app_date_iso() in week05_prompt_parts()[-1]

    def test_system_prompt_contains_every_part(self):
        """week05_system_prompt()가 모든 조각을 누락 없이 합치는지 확인한다."""

        prompt = week05_system_prompt()

        for part in week05_prompt_parts():
            assert part.strip() in prompt

    def test_shared_store_lookup_rule_keeps_date_range_optional(self):
        """공유 저장소 조회 지시가 member_names는 요구하고 날짜 범위는 비워 두게 하는지 확인한다.

        이전 문구는 "member_names나 날짜 범위 같은 조건을 반드시 명시한다"였다. 실제 앱
        실행에서 LLM이 이 문구를 날짜도 채우라는 뜻으로 읽고 date_from/date_to를 실행
        시점 날짜 하루로 채워, "나" row가 9건 있는데 0건이 조회된 적이 있다. 그래서
        날짜 범위는 사용자가 기간을 지정한 경우에만 넣도록 문구를 나눴고, 이 테스트가
        그 조건이 prompt에 남아 있는지 고정한다.
        """

        prompt = WEEK05_SCHEDULE_COLLECTION_PROMPT

        assert "member_names는 반드시 지정한다" in prompt
        assert "date_from과 date_to를 비워 둔다" in prompt
        assert "날짜 범위 같은 조건을 반드시 명시한다" not in prompt

    def test_prompt_names_the_tools_agent_must_choose(self):
        """prompt에 이번 주차 tool 이름이 들어가 LLM이 tool을 고를 근거가 되는지 확인한다."""

        prompt = week05_system_prompt()

        for tool_name in (
            "search_previous_conversations",
            "load_conversation_messages",
            "extract_schedules_from_history",
            "collect_member_schedules",
            "list_shared_schedules",
        ):
            assert tool_name in prompt


# --------------------------------------------------------------------------
# 3. 오류 예측 검사 (경험 기반 블랙박스)
# --------------------------------------------------------------------------


class TestErrorGuessing:
    """[블랙박스 / 경험 기반 - 오류 예측 검사] LLM과 MCP 서버가 규칙에서 벗어난 값을 넘기는 상황을 확인한다."""

    def test_limit_above_maximum_is_rejected_at_tool_layer(self, fake_mcp):
        """LLM이 limit=100처럼 상한을 넘는 값을 고르면 .invoke 단계에서 거부되는지 확인한다.
        스키마 인스턴스 직접 생성(TestInputSchemaBoundaries)과 달리, tool wrapper를
        통과하는 실제 호출 경로에서도 검증이 걸리는지 본다."""

        with pytest.raises(ValidationError):
            search_previous_conversations.invoke({"query": "일정", "limit": 100})

        fake_mcp.assert_not_called()

    def test_collect_member_schedules_rejects_missing_date_range(self, fake_mcp, fake_app_store):
        """LLM이 날짜 범위를 빼고 호출하면 거부되는지 확인한다."""

        with pytest.raises(ValidationError):
            collect_member_schedules.invoke({"member_names": ["철수"]})

        fake_mcp.assert_not_called()

    def test_none_member_names_is_forwarded_as_none(self, fake_mcp):
        """member_names를 생략하면 빈 리스트로 바꾸지 않고 None을 그대로 넘기는지 확인한다.
        외부 store는 None이면 모든 멤버를 검색하고 빈 리스트면 빈 rows를 반환하므로,
        wrapper가 None을 []로 바꾸면 조회 대상이 달라진다."""

        search_previous_conversations.invoke({"query": "일정"})

        (_, args), _ = fake_mcp.call_args
        assert args["member_names"] is None

    def test_empty_member_names_is_forwarded_as_empty_list(self, fake_mcp):
        """빈 리스트를 넘기면 None으로 바꾸지 않고 빈 리스트를 그대로 넘기는지 확인한다."""

        search_previous_conversations.invoke({"query": "일정", "member_names": []})

        (_, args), _ = fake_mcp.call_args
        assert args["member_names"] == []

    @pytest.mark.parametrize("broken_payload", [{"ok": True}, {"ok": True, "rows": None}])
    def test_mcp_payload_without_usable_rows_is_treated_as_empty(self, fake_mcp, broken_payload):
        """MCP 결과에 rows 키가 없거나 값이 None이면 `get("rows") or []`가 빈 목록으로 처리하는지 확인한다.
        이 경우 예외가 아니라 "외부 일정 없음"으로 이어져야 내 일정만이라도 답변 근거로 쓸 수 있다."""

        fake_mcp.return_value = json.dumps(broken_payload, ensure_ascii=False)

        result = _collect_member_schedules(
            member_names=["철수"],
            date_from="2026-07-07",
            date_to="2026-07-17",
            personal_schedules=[app_schedule_row(title="내 일정")],
        )

        assert result["external_row_count"] == 0
        assert [row["title"] for row in result["rows"]] == ["내 일정"]

    def test_non_json_mcp_result_raises_json_decode_error(self, fake_mcp):
        """MCP 결과가 JSON이 아니면 _collect_member_schedules가 예외를 감추지 않고 전파하는지 확인한다.
        wrapper가 빈 결과로 바꿔 버리면 MCP 서버 오류가 "일정 없음"으로 보고되어 원인을
        찾을 수 없으므로, 현재 동작을 그대로 고정해 둔다."""

        fake_mcp.return_value = "서버 오류: tool not found"

        with pytest.raises(json.JSONDecodeError):
            _collect_member_schedules(
                member_names=["철수"],
                date_from="2026-07-07",
                date_to="2026-07-17",
                personal_schedules=[],
            )

    def test_unimplemented_shared_schedule_writers_return_none(self):
        """구현하지 않은 추가 과제 tool 2개가 None을 반환하는 현재 상태를 확인한다.
        LangChain tool은 문자열 반환을 기대하므로, 이 두 함수가 week05_tools() 목록에서
        제외되어 있어야 한다(TestWeek05ToolsAssembly에서 함께 확인한다)."""

        created = create_shared_schedule.func(
            member_name="철수", title="QA 리뷰", date="2026-07-15", start_time="16:00"
        )
        deleted = delete_shared_schedule.func(schedule_id="shared_1")

        assert created is None
        assert deleted is None

    def test_schedule_without_date_is_dropped_from_personal_rows(self, fake_mcp):
        """날짜가 없는 내 일정이 rows에 들어가지 않는지 확인한다.
        Week 1 임시 일정과 앱 일정 row는 date가 None일 수 있고, 날짜가 없으면 바쁜
        시간을 판단할 수 없어 조율 근거로 쓸 수 없다."""

        result = _collect_member_schedules(
            member_names=[PERSONAL_SHARED_MEMBER_NAME],
            date_from="2026-07-07",
            date_to="2026-07-17",
            personal_schedules=[app_schedule_row(title="날짜 없는 일정", date=None)],
        )

        assert result["rows"] == []
        assert result["personal_row_count"] == 0


# --------------------------------------------------------------------------
# 4. Mock 기반 단위 테스트 (검증(Verification) 테스트)
# --------------------------------------------------------------------------


class TestMcpCallArguments:
    """[Mock 기반 단위 테스트 / 검증(Verification) 테스트]

    실제 MCP subprocess 대신 MagicMock을 주입해서, "무엇이 조회됐는가"가 아니라
    "call_mcp_tool_sync가 어떤 tool 이름과 어떤 args로 호출됐는가"만 검증한다.
    Java Mockito의 `verify(mock).method(eq(...))`와 같은 접근이다.
    """

    def test_search_forwards_exact_tool_name_and_args(self, fake_mcp):
        """search_previous_conversations가 query/member_names/limit를 그대로 넘기는지 assert_called_once_with로 확인한다."""

        search_previous_conversations.invoke(
            {"query": "일정 공유", "member_names": ["철수", "영희"], "limit": 3}
        )

        fake_mcp.assert_called_once_with(
            "search_previous_conversations",
            {"query": "일정 공유", "member_names": ["철수", "영희"], "limit": 3},
        )

    def test_search_does_not_normalize_member_names(self, fake_mcp):
        """공백이 섞인 멤버 이름을 wrapper에서 정규화하지 않고 그대로 넘기는지 확인한다.
        정규화는 외부 store가 조회 직전에 수행하므로, wrapper에서 한 번 더 하면 정규화
        지점이 두 곳으로 늘어난다."""

        search_previous_conversations.invoke({"query": "일정", "member_names": [" 철수 "]})

        (_, args), _ = fake_mcp.call_args
        assert args["member_names"] == [" 철수 "]

    def test_extract_forwards_exact_tool_name_and_args(self, fake_mcp):
        """extract_schedules_from_history가 member_names와 날짜 범위를 그대로 넘기는지 확인한다."""

        extract_schedules_from_history.invoke(
            {"member_names": ["철수"], "date_from": "2026-07-07T09:00:00", "date_to": "2026-07-17"}
        )

        fake_mcp.assert_called_once_with(
            "extract_schedules_from_history",
            {"member_names": ["철수"], "date_from": "2026-07-07T09:00:00", "date_to": "2026-07-17"},
        )

    def test_list_shared_forwards_all_filters_including_none(self, fake_mcp):
        """list_shared_schedules가 지정하지 않은 필터를 None 그대로 넘기는지 확인한다.
        필터를 모두 비운 조회는 외부 store에서 실습용 기본 조건으로 대체되므로, wrapper가
        None을 빈 값으로 바꾸면 그 대체 판정이 달라진다."""

        list_shared_schedules.invoke({"member_names": [PERSONAL_SHARED_MEMBER_NAME]})

        fake_mcp.assert_called_once_with(
            "list_shared_schedules",
            {
                "member_names": [PERSONAL_SHARED_MEMBER_NAME],
                "date_from": None,
                "date_to": None,
                "source_conversation_id": None,
                "limit": 50,
            },
        )

    def test_load_conversation_messages_calls_external_payload_helper(self, fake_external_payload):
        """load_conversation_messages가 call_external_tool_payload를 conversation_id 하나로 호출하는지 확인한다.
        이 tool만 결과를 dict로 받는 helper를 쓰므로, 호출 대상이 다른 wrapper와 다르다."""

        load_conversation_messages.invoke({"conversation_id": "ext_cs"})

        fake_external_payload.assert_called_once_with(
            "load_conversation_messages", {"conversation_id": "ext_cs"}
        )

    def test_collect_calls_extract_tool_with_normalized_args(self, fake_mcp, fake_app_store):
        """collect_member_schedules가 내부에서 extract_schedules_from_history를 정규화된 인자로 호출하는지 확인한다.
        "나"는 외부 조회 대상에서 빠지고, 이름 공백과 ISO datetime은 정리된 값이 넘어가야 한다."""

        collect_member_schedules.invoke(
            {
                "member_names": [PERSONAL_SHARED_MEMBER_NAME, " 철수 "],
                "date_from": "2026-07-07T00:00:00",
                "date_to": "2026-07-17T23:59:59",
            }
        )

        fake_mcp.assert_called_once_with(
            "extract_schedules_from_history",
            {"member_names": ["철수"], "date_from": "2026-07-07", "date_to": "2026-07-17"},
        )

    def test_collect_calls_mcp_once_for_multiple_members(self, fake_mcp, fake_app_store):
        """멤버가 여러 명이어도 MCP 호출이 한 번인지 확인한다.
        prompt에서 같은 조회를 반복하지 않도록 지시하는 근거가 이 구조다. 멤버별로
        나눠 호출하면 호출 수만큼 subprocess 기동 시간이 늘어난다."""

        collect_member_schedules.invoke(
            {
                "member_names": ["철수", "영희", "민준"],
                "date_from": "2026-07-07",
                "date_to": "2026-07-17",
            }
        )

        assert fake_mcp.call_count == 1

    def test_personal_schedules_are_fetched_with_widened_limit(self, fake_app_store):
        """_personal_schedules_for_current_scope가 list_schedules를 APP_SCHEDULE_FETCH_LIMIT으로 호출하는지 확인한다.
        list_schedules의 기본 limit은 12라서 기본값을 그대로 쓰면 같은 날짜에 일정이
        여러 건일 때 조회 결과가 잘리고 바쁜 시간이 누락된다."""

        _personal_schedules_for_current_scope()

        fake_app_store.list_schedules.assert_called_once_with(limit=APP_SCHEDULE_FETCH_LIMIT)
        assert APP_SCHEDULE_FETCH_LIMIT == 200


class TestCollectMemberSchedulesReadOrder:
    """[Mock 기반 단위 테스트 / 검증(Verification) 테스트] 내 일정 조회가 MCP 호출보다 먼저 실행되는지 확인한다.

    이 순서가 고정되어야 하는 이유는 대화 범위 값의 전달 방식이다. 현재 대화 범위는
    ContextVar로 관리되고, MCP 호출은 별도 thread에서 실행되므로 ContextVar가 그
    thread로 전파되지 않는다. 그래서 내 일정은 tool 본문(메인 thread)에서 먼저 읽어
    인자로 넘겨야 한다.
    """

    def test_app_sqlite_is_read_before_mcp_call(self, mocker):
        """앱 SQLite 조회가 MCP 호출보다 먼저 일어나는지 호출 순서 기록으로 확인한다."""

        call_order: list[str] = []

        def record_app_query(**kwargs: Any) -> list[dict[str, Any]]:
            """list_schedules 호출 시점을 기록하고 빈 목록을 반환합니다."""

            call_order.append("app_sqlite")
            return []

        def record_mcp_call(tool_name: str, args: dict[str, Any]) -> str:
            """MCP 호출 시점을 기록하고 빈 rows payload를 반환합니다."""

            call_order.append("mcp")
            return mcp_payload_text(tool_name, [])

        store = mocker.MagicMock()
        store.list_schedules.side_effect = record_app_query
        mocker.patch.object(week05, "AppSQLiteStore", return_value=store)
        mocker.patch.object(week05, "call_mcp_tool_sync", side_effect=record_mcp_call)

        collect_member_schedules.invoke(
            {"member_names": ["철수"], "date_from": "2026-07-07", "date_to": "2026-07-17"}
        )

        assert call_order == ["app_sqlite", "mcp"]

    def test_temporary_schedule_of_current_conversation_is_included(self, fake_mcp, fake_app_store):
        """현재 대화에서 만든 임시 일정이 rows에 포함되는지 확인한다.
        conversation_session_scope로 대화 범위를 설정한 뒤 Week 1 tool로 임시 일정을
        만들고, 같은 범위에서 collect_member_schedules를 호출한다."""

        with conversation_session_scope("conv_now"):
            week01_personal_create_schedule.invoke(
                {"title": "임시 회의", "date": "2026-07-09", "start_time": "13:00", "end_time": "14:00"}
            )
            payload = json.loads(
                collect_member_schedules.invoke(
                    {
                        "member_names": [PERSONAL_SHARED_MEMBER_NAME],
                        "date_from": "2026-07-07",
                        "date_to": "2026-07-17",
                    }
                )
            )

        assert [(row["title"], row["notes"]) for row in payload["rows"]] == [
            ("임시 회의", "현재 대화 임시 일정")
        ]

    def test_temporary_schedule_of_other_conversation_is_excluded(self, fake_mcp, fake_app_store):
        """다른 대화에서 만든 임시 일정은 rows에서 제외되는지 확인한다.
        앞 테스트와 같은 구성이지만 일정 생성과 조회의 대화 범위를 다르게 둔다."""

        with conversation_session_scope("conv_past"):
            week01_personal_create_schedule.invoke(
                {"title": "지난 대화 일정", "date": "2026-07-09", "start_time": "13:00"}
            )

        with conversation_session_scope("conv_now"):
            payload = json.loads(
                collect_member_schedules.invoke(
                    {
                        "member_names": [PERSONAL_SHARED_MEMBER_NAME],
                        "date_from": "2026-07-07",
                        "date_to": "2026-07-17",
                    }
                )
            )

        assert payload["rows"] == []


class TestBuildWeek05Agent:
    """[Mock 기반 단위 테스트 / 검증(Verification) 테스트] agent builder의 키 검사와 재사용 규칙을 확인한다."""

    def test_missing_api_key_raises_runtime_error(self, mocker):
        """PROXY_TOKEN이 없으면 create_agent를 부르기 전에 RuntimeError를 발생시키는지 확인한다.
        CONFIG는 frozen dataclass라 속성을 바꿀 수 없으므로, week05 모듈이 참조하는
        CONFIG 이름 자체를 has_openai_key=False인 MagicMock으로 교체한다."""

        mocker.patch.object(week05, "CONFIG", mocker.MagicMock(has_openai_key=False))
        mocker.patch.object(week05, "_WEEK05_AGENT", None)
        mock_create_agent = mocker.patch.object(week05, "create_agent")

        with pytest.raises(RuntimeError):
            build_week05_agent()

        mock_create_agent.assert_not_called()

    def test_agent_is_created_once_and_reused(self, mocker):
        """build_week05_agent를 두 번 호출해도 create_agent는 한 번만 실행되고 같은 객체가 반환되는지 확인한다."""

        mocker.patch.object(week05, "CONFIG", mocker.MagicMock(has_openai_key=True))
        mocker.patch.object(week05, "_WEEK05_AGENT", None)
        mocker.patch.object(week05, "chat_model", return_value=mocker.sentinel.chat_model)
        mock_create_agent = mocker.patch.object(
            week05, "create_agent", return_value=mocker.sentinel.agent
        )

        first = build_week05_agent()
        second = build_week05_agent()

        mock_create_agent.assert_called_once()
        assert first is second is mocker.sentinel.agent

    def test_create_agent_receives_week05_tools_and_prompt(self, mocker):
        """create_agent에 이번 주차 tool 목록과 system prompt가 전달되는지 call_args로 확인한다."""

        mocker.patch.object(week05, "CONFIG", mocker.MagicMock(has_openai_key=True))
        mocker.patch.object(week05, "_WEEK05_AGENT", None)
        mocker.patch.object(week05, "chat_model", return_value=mocker.sentinel.chat_model)
        mock_create_agent = mocker.patch.object(
            week05, "create_agent", return_value=mocker.sentinel.agent
        )

        build_week05_agent()

        _, kwargs = mock_create_agent.call_args
        tool_names = {tool.name for tool in kwargs["tools"]}
        assert kwargs["model"] is mocker.sentinel.chat_model
        assert "collect_member_schedules" in tool_names
        assert WEEK05_SCHEDULE_COLLECTION_PROMPT in kwargs["system_prompt"]

    def test_build_week_agent_delegates_to_week05_builder(self, mocker):
        """실행기가 호출하는 표준 이름 build_week_agent가 build_week05_agent에 위임하는지 확인한다."""

        mock_builder = mocker.patch.object(
            week05, "build_week05_agent", return_value=mocker.sentinel.week05_agent
        )

        assert build_week_agent() is mocker.sentinel.week05_agent
        mock_builder.assert_called_once_with()


# --------------------------------------------------------------------------
# 5. 통합 테스트
# --------------------------------------------------------------------------


class TestExternalHistoryVerticalSliceIntegration:
    """[통합 테스트 / 상향식] 실제 외부 SQLite 파일과 실제 MCP tool 함수로 검색 → 로드 → 추출 흐름을 확인한다.

    in_process_mcp fixture가 subprocess 경계만 in-process 호출로 바꾸므로, 이 아래의
    @mcp.tool 함수 본문과 ExternalPeopleSQLiteStore, SQLite 파일은 모두 실제 코드다.
    개별 wrapper 하나의 정확성이 아니라 세 tool이 conversation_id로 이어지는지를 본다.
    """

    def test_search_then_load_then_extract_flow(self, in_process_mcp):
        """검색으로 얻은 conversation_id로 대화를 로드하고, 같은 멤버의 일정을 추출하는 흐름이 맞물리는지 확인한다."""

        search_payload = json.loads(
            search_previous_conversations.invoke({"query": "일정", "member_names": ["철수"], "limit": 5})
        )
        assert search_payload["ok"] is True
        conversation_id = search_payload["rows"][0]["conversation_id"]
        assert conversation_id == "ext_cs"

        load_payload = json.loads(load_conversation_messages.invoke({"conversation_id": conversation_id}))
        assert [set(row) for row in load_payload["rows"]] == [{"role", "sender", "content", "created_at"}]
        assert "7월 7일 10시" in load_payload["rows"][0]["content"]

        extract_payload = json.loads(
            extract_schedules_from_history.invoke(
                {"member_names": ["철수"], "date_from": "2026-07-07", "date_to": "2026-07-17"}
            )
        )
        assert [row["title"] for row in extract_payload["rows"]] == ["API 연동 실습", "고객 인터뷰", "QA 리뷰"]
        assert len(extract_payload["schedule_summary"].splitlines()) == 3

    def test_extract_narrows_rows_by_date_range(self, in_process_mcp):
        """날짜 범위를 좁히면 외부 store의 SQL 조건으로 rows가 줄어드는지 확인한다."""

        payload = json.loads(
            extract_schedules_from_history.invoke(
                {"member_names": ["철수"], "date_from": "2026-07-08", "date_to": "2026-07-14"}
            )
        )

        assert [row["title"] for row in payload["rows"]] == ["고객 인터뷰"]

    def test_search_with_empty_member_list_returns_no_rows(self, in_process_mcp):
        """member_names를 빈 리스트로 넘기면 외부 store가 빈 rows를 반환하는지 확인한다.
        wrapper가 None과 빈 리스트를 구분해 전달해야 이 동작 차이가 유지된다."""

        empty_filter = json.loads(search_previous_conversations.invoke({"query": "일정", "member_names": []}))
        all_members = json.loads(search_previous_conversations.invoke({"query": "일정", "limit": 50}))

        assert empty_filter["rows"] == []
        assert len(all_members["rows"]) == len(JULY_PRACTICE_MEMBER_NAMES)

    def test_list_shared_schedules_without_filter_returns_practice_rows(self, in_process_mcp):
        """필터 없이 조회하면 실습용 기본 공유 일정만 나오고 "나" row는 없는지 확인한다.
        가이드 주석이 적어 둔 실측값(18건, "나" 없음)을 테스트로 고정한다."""

        payload = json.loads(list_shared_schedules.invoke({}))

        assert len(payload["rows"]) == 18
        assert PERSONAL_SHARED_MEMBER_NAME not in {row["member_name"] for row in payload["rows"]}

    def test_list_shared_schedules_with_member_filter(self, in_process_mcp):
        """member_names를 명시하면 그 멤버 row만 조회되는지 확인한다."""

        payload = json.loads(list_shared_schedules.invoke({"member_names": ["영희"]}))

        assert {row["member_name"] for row in payload["rows"]} == {"영희"}
        assert len(payload["rows"]) == 3


class TestCollectMemberSchedulesIntegration:
    """[통합 테스트 / 상향식] 실제 앱 SQLite와 실제 외부 SQLite를 함께 써서 rows 병합을 확인한다.

    앱 일정 저장과 공유 저장소 동기화, 외부 멤버 일정 조회가 하나의 흐름으로
    맞물리는지 본다. 두 SQLite 파일은 모두 tmp_path에 새로 만든다.
    """

    def test_app_saved_schedule_and_external_rows_are_merged(self, in_process_mcp, use_app_store):
        """앱에 저장한 내 일정과 외부 멤버 일정이 같은 rows 배열로 합쳐지는지 확인한다."""

        save_structured_request_payload(
            {
                "kind": "personal_schedule",
                "title": "개인 집중 작업",
                "date": "2026-07-09",
                "start_time": "08:00",
                "end_time": "09:00",
            },
            store=use_app_store,
        )

        payload = json.loads(
            collect_member_schedules.invoke(
                {
                    "member_names": [PERSONAL_SHARED_MEMBER_NAME, "철수"],
                    "date_from": "2026-07-07",
                    "date_to": "2026-07-17",
                }
            )
        )

        assert payload["personal_row_count"] == 1
        assert payload["external_row_count"] == 3
        assert [(row["member_name"], row["date"], row["start_time"]) for row in payload["rows"]] == [
            ("철수", "2026-07-07", "10:00"),
            ("나", "2026-07-09", "08:00"),
            ("철수", "2026-07-09", "14:00"),
            ("철수", "2026-07-15", "16:00"),
        ]
        assert len(payload["schedule_summary"].splitlines()) == 4

    def test_shared_copy_of_my_schedule_is_not_counted_twice(self, in_process_mcp, use_app_store):
        """공유 저장소에 "나" 복사본이 있어도 rows에 내 일정이 한 번만 들어가는지 확인한다.

        처리 순서

        1. 앱에 개인 일정을 저장하면 sync_personal_schedule_to_shared가 공유 저장소에
           member_name="나" 복사본을 만든다. 그 복사본이 실제로 생겼는지
           list_shared_schedules로 먼저 확인한다.

        2. 그 상태에서 member_names에 "나"를 포함해 collect_member_schedules를 호출한다.
           "나"를 외부 조회 대상에서 제외하지 않으면 앱 SQLite에서 읽은 row와 공유
           저장소 복사본이 모두 들어가 같은 일정이 두 번 나타난다.
        """

        save_structured_request_payload(
            {
                "kind": "personal_schedule",
                "title": "치과",
                "date": "2026-07-13",
                "start_time": "14:00",
                "end_time": "15:00",
            },
            store=use_app_store,
        )

        shared_payload = json.loads(
            list_shared_schedules.invoke({"member_names": [PERSONAL_SHARED_MEMBER_NAME]})
        )
        assert [row["title"] for row in shared_payload["rows"]] == ["치과"]

        collected = json.loads(
            collect_member_schedules.invoke(
                {
                    "member_names": [PERSONAL_SHARED_MEMBER_NAME],
                    "date_from": "2026-07-07",
                    "date_to": "2026-07-17",
                }
            )
        )

        assert [(row["member_name"], row["title"]) for row in collected["rows"]] == [
            (PERSONAL_SHARED_MEMBER_NAME, "치과")
        ]
        assert collected["rows"][0]["notes"] == "앱 SQLite 저장 일정"

    def test_saved_and_temporary_schedules_are_merged_with_source_notes(self, in_process_mcp, use_app_store):
        """앱 저장 일정과 현재 대화 임시 일정이 notes로 구분되면서 함께 합쳐지는지 확인한다."""

        with conversation_session_scope("conv_integration"):
            save_structured_request_payload(
                {
                    "kind": "personal_schedule",
                    "title": "저장된 일정",
                    "date": "2026-07-09",
                    "start_time": "09:00",
                },
                store=use_app_store,
            )
            week01_personal_create_schedule.invoke(
                {"title": "임시 일정", "date": "2026-07-10", "start_time": "11:00"}
            )

            payload = json.loads(
                collect_member_schedules.invoke(
                    {
                        "member_names": [PERSONAL_SHARED_MEMBER_NAME],
                        "date_from": "2026-07-07",
                        "date_to": "2026-07-17",
                    }
                )
            )

        assert [(row["title"], row["notes"]) for row in payload["rows"]] == [
            ("저장된 일정", "앱 SQLite 저장 일정"),
            ("임시 일정", "현재 대화 임시 일정"),
        ]

    def test_rows_outside_date_range_are_excluded_from_both_sources(self, in_process_mcp, use_app_store):
        """두 출처 모두 조회 날짜 범위 밖의 일정은 rows에서 빠지는지 확인한다.
        내 일정은 _row_in_date_range가, 외부 일정은 외부 store의 SQL 조건이 각각
        걸러내므로 두 경로가 같은 범위 판정을 내리는지 함께 본다."""

        save_structured_request_payload(
            {"kind": "personal_schedule", "title": "8월 일정", "date": "2026-08-09", "start_time": "09:00"},
            store=use_app_store,
        )

        payload = json.loads(
            collect_member_schedules.invoke(
                {
                    "member_names": [PERSONAL_SHARED_MEMBER_NAME, "철수"],
                    "date_from": "2026-07-07",
                    "date_to": "2026-07-08",
                }
            )
        )

        assert payload["personal_row_count"] == 0
        assert [row["title"] for row in payload["rows"]] == ["API 연동 실습"]

    def test_collect_calls_mcp_boundary_once_per_invocation(self, in_process_mcp, use_app_store):
        """tool 한 번 호출에 MCP 경계도 한 번만 통과하는지 확인한다.
        in_process_mcp fixture가 교체한 함수는 MagicMock이므로 호출 횟수를 그대로 셀 수 있다."""

        collect_member_schedules.invoke(
            {"member_names": ["철수", "영희"], "date_from": "2026-07-07", "date_to": "2026-07-17"}
        )

        assert week05.call_mcp_tool_sync.call_count == 1


@requires_mcp_subprocess
class TestMcpSubprocessEndToEnd:
    """[통합 테스트 / 빅뱅] 실제 MCP stdio subprocess를 기동해서 전체 경로를 확인한다.

    이 클래스만 아무 함수도 교체하지 않는다. 환경 변수 KANANA_EXTERNAL_DB_PATH만
    tmp_path로 바꿔서 실습용 DB를 보호하고, fixed/mcp_client.py가 실제로
    mcp_server/sqlite_mcp_server.py를 subprocess로 띄우게 한다.

    호출 1회당 약 5초가 걸려서 기본 실행에서는 건너뛴다. 실행 방법은 이 파일
    맨 위 docstring의 "4. 실행 방법"에 있다.
    """

    def test_extract_schedules_through_real_subprocess(self, external_db_env):
        """실제 subprocess 경로로 외부 일정을 조회하고 한글 필드가 그대로 전달되는지 확인한다.
        stdio 전송 구간에서 인코딩이 바뀌면 member_name/title 비교가 실패한다."""

        payload = json.loads(
            extract_schedules_from_history.invoke(
                {"member_names": ["철수"], "date_from": "2026-07-07", "date_to": "2026-07-17"}
            )
        )

        assert payload["ok"] is True
        assert {row["member_name"] for row in payload["rows"]} == {"철수"}
        assert [row["title"] for row in payload["rows"]] == ["API 연동 실습", "고객 인터뷰", "QA 리뷰"]
        assert external_db_env.exists()

    def test_collect_member_schedules_through_real_subprocess(self, external_db_env, use_app_store):
        """실제 subprocess 경로에서도 내 일정과 외부 일정이 한 rows로 합쳐지는지 확인한다.
        앱 SQLite는 tmp_path 파일을 쓰고, 외부 조회만 subprocess를 통과한다."""

        with conversation_session_scope("conv_subprocess"):
            week01_personal_create_schedule.invoke(
                {"title": "임시 회의", "date": "2026-07-09", "start_time": "08:00", "end_time": "09:00"}
            )
            payload = json.loads(
                collect_member_schedules.invoke(
                    {
                        "member_names": [PERSONAL_SHARED_MEMBER_NAME, "철수"],
                        "date_from": "2026-07-07",
                        "date_to": "2026-07-17",
                    }
                )
            )

        assert payload["personal_row_count"] == 1
        assert payload["external_row_count"] == 3
        assert [(row["member_name"], row["date"]) for row in payload["rows"]] == [
            ("철수", "2026-07-07"),
            (PERSONAL_SHARED_MEMBER_NAME, "2026-07-09"),
            ("철수", "2026-07-09"),
            ("철수", "2026-07-15"),
        ]
