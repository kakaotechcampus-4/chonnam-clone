from __future__ import annotations

"""student_parts/week03_build_nanas_logbook.py 테스트.

이 파일은 프로젝트 루트의 software-testing-types.md에서 정리한 테스트 분류를
코드로 옮긴 것이다. 각 테스트 클래스의 docstring에는 [분류] 표시가 붙어 있고,
그 표시는 "이 테스트가 어떤 관점에서 검증하는가"를 이론 문서와 코드 사이에
그대로 이어준다.

---

## 1. 테스트 클래스가 대응하는 5가지 분류

1. **화이트박스 테스트**
   함수 내부의 if/elif 분기를 하나씩 실행한다. 구현이 바뀌어도
   "이 분기가 실제로 존재하고 실행된다"는 사실 자체를 검증한다.

2. **블랙박스 테스트**
   함수 내부 구조는 보지 않는다. docstring에 적힌 대로 "이 입력을 넣으면 이 출력이
   나와야 한다"는 규칙만 보고, 대표 입력(동등 분할)과 경계 입력(경계값)으로 확인한다.

3. **오류 예측 검사**
   "사용자가 이렇게 실수하면 어떻게 되지?"를 가정하고,
   실패/거부 경로가 명세대로 동작하는지 본다.

4. **Mock 기반 단위 테스트**
   진짜 SQLite나 외부 MCP 대신 가짜 객체를 주입해서,
   "이 함수가 의존성을 올바른 인자로 호출했는가"만 확인한다.
   Java Mockito의 verify(mock).method(...)와 같은 목적이다.

5. **통합 테스트**
   실제 SQLite 파일(tmp_path, 상향식으로 진짜 AppSQLiteStore 사용)에
   여러 함수를 연달아 호출해서, 저장 → 조회 → 수정 → 삭제가
   하나의 흐름으로 맞물리는지 본다.

위 5가지는 전부 "이론 분류를 먼저 정하고, 그 분류에 맞는 코드를 찾아서" 짠
테스트라는 공통점이 있다. 즉 출발점이 이론 쪽에 있다.

---

## 2. 이론이 아니라 실측에서 출발한 테스트

일부 테스트는 출발점 자체가 다르다. 이론 분류를 먼저 정한 게 아니라,
아래 두 가지 도구/실험을 먼저 돌려서 실제 코드에 남아있던 사각지대를
찾아냈고, 그 자리를 나중에 이론 분류로 되짚어 채운 테스트다.

- **커버리지 실측**: `coverage.py --branch`를 돌려서 나온 미실행 분기
  (예: unwrap_legacy_payload의 non-dict 입력, _save_input_from의 raise 경로)
- **수동 mutation**: has_filter처럼 `a or b or c` 하나로 압축된 조건에서,
  개별 항(date만 있을 때 / start_time만 있을 때)을 코드에서 지워보고
  그래도 테스트가 통과하는지 확인하는 방식

이런 테스트의 docstring은 "~하는지 확인한다" 뒤에 "어떻게 그 갭을 찾았는지
(실측/mutation)"를 한 문장 덧붙여 표시해 둔다. 1번과 나누는 기준은 순서다:
1번은 이론 분류가 먼저 있었고, 2번은 도구가 낸 숫자(혹은 실험 결과)가 먼저
있었고 분류는 그 다음에 붙었다.

---

## 3. 실행 방법

1. 기본 테스트 실행 (프로젝트 루트에서):

       uv run pytest

   pyproject.toml에 pythonpath가 설정되어 있어서, PYTHONPATH를 따로
   잡지 않아도 student_parts/fixed를 바로 import할 수 있다.

2. 분기 커버리지 실측:

       uv run --with pytest-cov pytest tests/test_week03_build_nanas_logbook.py \\
           --cov=student_parts.week03_build_nanas_logbook \\
           --cov-branch --cov-report=term-missing

   단, 이 도구도 한 줄짜리 `A or B` 기본값이나 압축조건의 개별 항은
   분기로 잡지 않는다(서로 다른 소스 라인으로 갈라지는 경우만 추적).
   그 부분은 2번처럼 수동 mutation으로 보완해야 한다.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from fixed.app_store import AppSQLiteStore
from student_parts.week01_wake_up_nana import PERSONAL_SCHEDULES
from student_parts.week01_wake_up_nana import personal_create_schedule as week01_personal_create_schedule
from student_parts.week02_structure_natural_language_requests import StructuredRequest
from student_parts.week03_build_nanas_logbook import (
    SavedScheduleListInput,
    SaveStructuredRequestInput,
    _delete_saved_schedules,
    _save_input_from,
    delete_saved_schedules_dict,
    get_saved_request,
    list_saved_requests,
    personal_create_schedule,
    personal_delete_saved_schedules,
    personal_list_saved_schedules,
    personal_update_saved_schedule,
    save_structured_request,
    save_structured_request_payload,
    structured_request_from_week01_schedule,
    week03_tools,
)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_week01_memory():
    """Week 1의 PERSONAL_SCHEDULES는 프로세스 전역 리스트라 테스트끼리 오염될 수 있다.

    personal_create_schedule 테스트가 다른 테스트의 잔여 데이터를 보지 않도록
    각 테스트 전후로 비워 둔다. (테스트 격리 = 화이트박스/블랙박스 여부와 무관하게
    모든 동적 테스트가 지켜야 하는 전제 조건이다.)
    """

    PERSONAL_SCHEDULES.clear()
    yield
    PERSONAL_SCHEDULES.clear()


@pytest.fixture
def store(tmp_path: Path) -> AppSQLiteStore:
    """테스트마다 새 SQLite 파일에 스키마를 만든다. 실제 앱 DB(data/kanana_app.sqlite3)는 절대 건드리지 않는다."""

    return AppSQLiteStore(tmp_path / "app.db")


@pytest.fixture
def no_external_sync(mocker):
    """personal_schedule/group_schedule 저장 시 진짜 MCP subprocess가 뜨지 않게 막는다.

    fixed/app_store.py는 `from fixed.external_mcp import sync_personal_schedule_to_shared, ...`로
    이름만 가져왔으므로, patch 대상은 fixed.external_mcp가 아니라 그 이름을 참조하는
    fixed.app_store 쪽이어야 한다(파이썬 import 바인딩 규칙).
    """

    mocker.patch(
        "fixed.app_store.sync_personal_schedule_to_shared",
        return_value={"ok": True, "status": "synced (mocked)"},
    )
    mocker.patch(
        "fixed.app_store.sync_group_schedule_to_shared",
        return_value={"ok": True, "status": "synced (mocked)"},
    )
    mocker.patch("fixed.app_store.delete_personal_schedule_from_shared", return_value=None)
    mocker.patch("fixed.app_store.delete_group_schedule_from_shared", return_value=None)


@pytest.fixture
def use_test_store(mocker, store):
    """@tool 함수 내부의 _store()가 CONFIG.app_db_path 대신 테스트용 임시 DB를 보게 한다."""

    mocker.patch("student_parts.week03_build_nanas_logbook._store", return_value=store)
    return store


# --------------------------------------------------------------------------
# 1. 화이트박스 테스트 (구조 기반) - 분기 커버리지
# --------------------------------------------------------------------------


class TestUnwrapLegacyPayloadBranches:
    """[화이트박스 / 구조 기반] unwrap_legacy_payload의 3가지 분기를 각각 실행한다.

    분기: (1) structured_request wrapper (2) payload wrapper (3) wrapper 없는 일반 dict.
    """

    def test_structured_request_wrapper_branch(self):
        """unwrap_legacy_payload가 "structured_request" wrapper 키를 만나 안쪽 dict를 반환하는 분기를 실행한다.
        extract_schedule_request가 돌려주는 {ok, tool_name, base_date, structured_request:{...}} 전체를 model_validate에 넣어도 안쪽 kind/title로 검증되는지 확인한다."""

        wrapped = {
            "ok": True,
            "tool_name": "extract_schedule_request",
            "base_date": "2026-07-17",
            "structured_request": {"kind": "todo", "title": "보고서"},
        }
        result = SaveStructuredRequestInput.model_validate(wrapped)
        assert result.kind == "todo"
        assert result.title == "보고서"

    def test_payload_wrapper_branch(self):
        """같은 unwrap_legacy_payload가 "payload" 키에서도 안쪽 dict를 반환하는 두 번째 분기를 실행한다.
        예전 저장 helper가 쓰던 {"payload":{...}} 형태를 넣어 kind/reason이 안쪽 값으로 채워지는지 확인한다."""

        wrapped = {"payload": {"kind": "reminder", "title": "약", "reason": "건강"}}
        result = SaveStructuredRequestInput.model_validate(wrapped)
        assert result.kind == "reminder"
        assert result.reason == "건강"

    def test_no_wrapper_passthrough_branch(self):
        """wrapper 키가 없는 dict는 unwrap_legacy_payload가 변형 없이 그대로 반환하는 세 번째 분기를 실행한다.
        {kind, title}만 있는 입력이 그대로 model_validate를 통과하는지 확인한다."""

        plain = {"kind": "todo", "title": "청소"}
        result = SaveStructuredRequestInput.model_validate(plain)
        assert result.title == "청소"

    def test_non_dict_value_skips_unwrap(self):
        """value가 dict가 아니면 unwrap_legacy_payload의 isinstance(value, dict) 분기가 False가 되어 값을 그대로 반환하는 경로를 확인한다.
        이 분기(line 342)의 False쪽은 이 테스트가 생기기 전까지 어떤 테스트에서도 실행된 적이 없었는데, coverage.py로 실제로 확인했다."""

        with pytest.raises(ValidationError):
            SaveStructuredRequestInput.model_validate("그냥 문자열")


class TestDeleteGuardBranches:
    """[화이트박스 / 구조 기반] _delete_saved_schedules의 guard·delete_all·필터 분기를 각각 실행한다."""

    def test_no_condition_branch_is_rejected(self, store):
        """_delete_saved_schedules를 조건 없이(schedule_ids/date/title/start_time/delete_all 모두 없음) 호출해 guard가 ok=False, deleted_count=0으로 거부하는지 확인한다.
        같은 시나리오의 tool(.invoke) 층 검증은 TestErrorGuessing.test_delete_without_any_condition_is_rejected가 맡고, 여기서는 함수 자체의 guard만 직접 호출로 확인한다."""

        result = _delete_saved_schedules(store=store)
        assert result["ok"] is False
        assert result["deleted_count"] == 0

    def test_delete_all_branch(self, store, no_external_sync):
        """personal_schedule 한 건을 저장한 뒤 delete_all=True로 호출해 store.delete_all_schedules 분기가 실행되는지 확인한다.
        deleted_count=1이고 이후 list_schedules가 빈 목록이 되어야 한다."""

        save_structured_request_payload(
            {"kind": "personal_schedule", "title": "회의", "date": "2026-08-01"}, store=store
        )
        result = _delete_saved_schedules(store=store, delete_all=True)
        assert result["ok"] is True
        assert result["deleted_count"] == 1
        assert store.list_schedules() == []

    def test_filter_branch(self, store, no_external_sync):
        """title="치과" 하나만 넘겨 has_filter 분기로 store.delete_schedules_by_filter가 호출되는지 확인한다.
        조건이 하나라도 있으면 삭제가 성립하는 경로다."""

        save_structured_request_payload(
            {"kind": "personal_schedule", "title": "치과", "date": "2026-08-05"}, store=store
        )
        result = _delete_saved_schedules(store=store, title="치과")
        assert result["ok"] is True
        assert result["deleted_count"] == 1

    def test_time_unspecified_only_branch(self, store, no_external_sync):
        """time_unspecified=True 하나만 넘긴 경우도 has_filter가 True가 되어 삭제가 성립하는 분기를 실행한다.
        title/date 없이 "시간 미정" 조건만으로도 deleted_count=1이 되는지 확인한다."""

        save_structured_request_payload(
            {"kind": "personal_schedule", "title": "미정 일정", "date": "2026-08-06"}, store=store
        )
        result = _delete_saved_schedules(store=store, time_unspecified=True)
        assert result["ok"] is True
        assert result["deleted_count"] == 1
        assert store.list_schedules() == []

    def test_date_only_branch(self, store, no_external_sync):
        """date=만 필터로 준 경우도 has_filter의 bool(date) 항이 단독으로 True를 만들어 삭제가 성립하는지 확인한다.
        이 항(date)은 코드에서 실제로 지워봐도(mutation) 기존 테스트가 전부 그대로 통과했는데, 그건 이 항목만 따로 검증하는 테스트가 없었기 때문이다 — title/time_unspecified만 단독으로 검증되고 있었다."""

        save_structured_request_payload(
            {"kind": "personal_schedule", "title": "무제", "date": "2026-08-07"}, store=store
        )
        result = _delete_saved_schedules(store=store, date="2026-08-07")
        assert result["ok"] is True
        assert result["deleted_count"] == 1

    def test_start_time_only_branch(self, store, no_external_sync):
        """start_time=만 필터로 준 경우도 has_filter의 bool(start_time) 항이 단독으로 True를 만들어 삭제가 성립하는지 확인한다."""

        save_structured_request_payload(
            {"kind": "personal_schedule", "title": "무제", "date": "2026-08-08", "start_time": "09:00"},
            store=store,
        )
        result = _delete_saved_schedules(store=store, start_time="09:00")
        assert result["ok"] is True
        assert result["deleted_count"] == 1


class TestSaveInputFromBranches:
    """[화이트박스 / 구조 기반] _save_input_from의 4가지 입력 형태 분기를 각각 실행한다.

    분기: (1) SaveStructuredRequestInput 인스턴스 그대로 통과 (2) StructuredRequest 인스턴스
    변환 (3) dict/JSON 문자열 검증 (4) JSON이 아닌 자연어 문자열은 extract_structured_request로
    먼저 구조화한다. (1)은 structured_request_from_week01_schedule 경유로 다른 테스트에서
    이미 지나가므로 여기서는 (2)~(4)만 새로 다룬다.
    """

    def test_structured_request_instance_branch(self):
        """_save_input_from에 StructuredRequest 인스턴스를 넘겨 model_dump 후 SaveStructuredRequestInput으로 다시 검증하는 분기를 실행한다.
        반환 타입이 SaveStructuredRequestInput이고 kind/title이 보존되는지 확인한다."""

        instance = StructuredRequest(kind="todo", title="장보기", original_text="장보기 해야지")
        result = _save_input_from(instance)
        assert isinstance(result, SaveStructuredRequestInput)
        assert result.kind == "todo"
        assert result.title == "장보기"

    def test_valid_json_string_branch(self):
        """JSON으로 파싱되는 문자열은 json.loads 성공 분기를 타고 dict로 model_validate되는지 확인한다.
        '{"kind":"todo","title":"청소"}' 문자열이 kind/title 필드로 풀려야 한다."""

        result = _save_input_from('{"kind": "todo", "title": "청소"}')
        assert result.kind == "todo"
        assert result.title == "청소"

    def test_natural_language_string_falls_through_to_extract_structured_request(self, mocker):
        """JSON 파싱에 실패하는 자연어 문자열은 json.loads 실패 분기를 지나 extract_structured_request로 넘어가는지 확인한다.
        이 함수는 실제로 chat_model()로 LLM을 호출하므로 mocker.patch로 대체하고, "회의 준비해줘"가 그 함수로 전달됐는지 assert_called_once_with로 본다."""

        fake_structured = StructuredRequest(kind="todo", title="회의 준비", original_text="회의 준비해줘")
        mock_extract = mocker.patch(
            "student_parts.week03_build_nanas_logbook.extract_structured_request",
            return_value=fake_structured,
        )

        result = _save_input_from("회의 준비해줘")

        mock_extract.assert_called_once_with("회의 준비해줘")
        assert result.kind == "todo"
        assert result.title == "회의 준비"

    def test_unsupported_type_raises_runtime_error(self):
        """SaveStructuredRequestInput/StructuredRequest/dict/str 어느 것도 아닌 값(int)을 넣으면 _save_input_from 마지막의 raise RuntimeError 분기가 실행되는지 확인한다.
        line 364의 False쪽(모든 isinstance를 통과 못 하는 경우)은 이 테스트가 생기기 전까지 실행된 적이 없었는데, coverage.py로 실제로 확인했다."""

        with pytest.raises(RuntimeError):
            _save_input_from(123)


class TestWeek01ScheduleConversionBranches:
    """[화이트박스 / 구조 기반] structured_request_from_week01_schedule의 end_time 정규화 분기를 확인한다."""

    @pytest.mark.parametrize("raw_end_time", [None, "", "미정"])
    def test_missing_end_time_variants_become_none(self, raw_end_time):
        """end_time이 None/""/"미정" 중 무엇이든 structured_request_from_week01_schedule이 None으로 정규화하는 분기를 실행한다.
        Week 1이 넣는 "미정" 값을 DB에는 값 없음(None)으로 남기는 규칙을 세 입력으로 확인한다."""

        schedule = {
            "id": "personal_x",
            "title": "코칭",
            "date": "2026-07-18",
            "start_time": "10:00",
            "end_time": raw_end_time,
            "attendees": [],
        }
        result = structured_request_from_week01_schedule(schedule)
        assert result.end_time is None

    def test_real_end_time_is_kept(self):
        """실제 시각 "11:00"이 들어오면 정규화 분기를 타지 않고 end_time이 그대로 보존되는 반대 경로를 확인한다."""

        schedule = {
            "id": "personal_y",
            "title": "코칭",
            "date": "2026-07-18",
            "start_time": "10:00",
            "end_time": "11:00",
            "attendees": ["나"],
        }
        result = structured_request_from_week01_schedule(schedule)
        assert result.end_time == "11:00"

    @pytest.mark.parametrize("raw_title", [None, ""])
    def test_missing_title_becomes_empty_original_text(self, raw_title):
        """title이 없거나 빈 문자열이면 structured_request_from_week01_schedule의 title or "" 분기(line 526)가 original_text를 ""로 대체하는지 확인한다.
        이 분기의 거짓쪽(title이 비어 있는 경우)은 이 테스트가 생기기 전까지 실행된 적이 없었는데, 그건 지금까지의 모든 테스트가 title을 항상 채워서 호출했기 때문이다."""

        schedule = {
            "id": "personal_w",
            "title": raw_title,
            "date": "2026-07-20",
            "start_time": "09:00",
            "end_time": "10:00",
            "attendees": [],
        }
        result = structured_request_from_week01_schedule(schedule)
        assert result.original_text == ""


# --------------------------------------------------------------------------
# 2. 블랙박스 테스트 (명세 기반) - 동등 분할 / 경계값 분석
# --------------------------------------------------------------------------


class TestSaveStructuredRequestKindRouting:
    """[블랙박스 / 명세 기반 - 동등 분할] kind별 저장 테이블 라우팅을 확인한다.

    week03_build_nanas_logbook.py의 _KIND_TABLE_MAP 문서화 명세:
    personal_schedule/group_schedule -> schedules, todo -> todos, reminder -> reminders,
    그 외(unknown)는 structured_requests에만 남는다. 내부 구현이 아니라
    "이 kind를 넣으면 이 테이블에 남는다"는, docstring에 적힌 입출력 규칙만 검증한다.
    """

    @pytest.mark.parametrize(
        "kind, expected_table",
        [
            ("personal_schedule", "schedules"),
            ("group_schedule", "schedules"),
            ("todo", "todos"),
            ("reminder", "reminders"),
        ],
    )
    def test_known_kind_creates_projection_row(self, store, no_external_sync, kind, expected_table):
        """kind별로 structured_requests 외에 정규화 테이블(schedules/todos/reminders) 한 줄이 더 생기는지 saved_rows의 table 목록으로 확인한다.
        내부 SQL이 아니라 "이 kind를 넣으면 이 테이블에 남는다"는, 문서화된 입출력 규칙만 본다."""

        payload = {
            "kind": kind,
            "title": "제목",
            "date": "2026-08-10",
            "members": ["철수"] if kind == "group_schedule" else [],
        }
        result = save_structured_request_payload(payload, store=store)
        tables = [row["table"] for row in result["saved_rows"]]
        assert "structured_requests" in tables
        assert expected_table in tables

    def test_unknown_kind_has_no_projection_row(self, store):
        """매핑에 정의되지 않은 kind="unknown"을 넣으면, 정규화 테이블에는 남지 않고 structured_requests에만 남는 예외적인 경우를 확인한다.
        saved_rows의 table이 ["structured_requests"] 하나뿐이어야 한다."""

        result = save_structured_request_payload({"kind": "unknown", "title": "분류 불가"}, store=store)
        tables = [row["table"] for row in result["saved_rows"]]
        assert tables == ["structured_requests"]

    @pytest.mark.parametrize("kind", ["personal_schedule", "group_schedule"])
    def test_schedule_kinds_trigger_shared_sync(self, store, no_external_sync, kind):
        """personal_schedule/group_schedule만 외부 공유 저장소 동기화를 일으켜 shared_sync가 채워지는지 확인한다.
        no_external_sync fixture로 실제 MCP 호출은 mock하고, 반환된 shared_sync.ok가 True인지만 본다."""

        payload = {
            "kind": kind,
            "title": "일정",
            "date": "2026-08-11",
            "members": ["철수"] if kind == "group_schedule" else [],
        }
        result = save_structured_request_payload(payload, store=store)
        assert result["shared_sync"] is not None
        assert result["shared_sync"]["ok"] is True

    @pytest.mark.parametrize("kind", ["todo", "reminder", "unknown"])
    def test_non_schedule_kinds_skip_shared_sync(self, store, kind):
        """todo/reminder/unknown은 다른 사람과 일정이 겹칠 수 있는 종류가 아니라서 동기화가 일어나지 않고 shared_sync가 None으로 남는, 앞 테스트와 반대되는 경우를 확인한다."""

        result = save_structured_request_payload({"kind": kind, "title": "x"}, store=store)
        assert result["shared_sync"] is None


class TestSaveStructuredRequestBoundaries:
    """[블랙박스 / 명세 기반 - 경계값 분석] 필드가 비어 있거나 없는 경계 상황을 확인한다."""

    def test_missing_title_falls_back_to_default(self, store):
        """title을 아예 주지 않은 경계 입력에서 저장 row의 title이 "제목 없음" 기본값으로 채워지는지 확인한다.
        store.get_saved_request로 실제 저장된 값을 되읽어 본다."""

        result = save_structured_request_payload({"kind": "todo"}, store=store)
        row = store.get_saved_request(result["request_id"])
        assert row["title"] == "제목 없음"

    def test_empty_members_list_is_valid(self, store):
        """members=[]라는 빈 리스트 경계가 오류 없이 ok=True로 저장되는지 확인한다."""

        result = save_structured_request_payload({"kind": "todo", "title": "a", "members": []}, store=store)
        assert result["ok"] is True


class TestPersonalListSavedSchedules:
    """[블랙박스 / 명세 기반 - 동등 분할] personal_list_saved_schedules가 필터 조건에 따라 정해진 대로 동작하는지 확인한다.

    이 tool은 메인과제의 핵심 조회 기능인데, 이 테스트들이 생기기 전까지는 기존
    테스트 파일 어디에서도 호출된 적이 없었다. kind 기본값, 명시적 kind 필터,
    date 범위(동등 분할: 범위 안/밖), limit 상한을 각각 확인한다.
    """

    def test_lists_only_personal_schedule_kind_by_default(self, store, no_external_sync, use_test_store):
        """kind 인자를 비우면 personal_list_saved_schedules가 기본값 personal_schedule로 조회하는지 확인한다.
        personal_schedule과 todo를 함께 저장해 두고, 목록에 personal_schedule만 나오는지 본다."""

        save_structured_request_payload({"kind": "personal_schedule", "title": "코칭", "date": "2026-08-12"}, store=store)
        save_structured_request_payload({"kind": "todo", "title": "보고서"}, store=store)

        result = json.loads(personal_list_saved_schedules.invoke({}))

        assert result["filters"]["kind"] == "personal_schedule"
        titles = [row["title"] for row in result["schedules"]]
        assert titles == ["코칭"]

    def test_kind_filter_overrides_default(self, store, no_external_sync, use_test_store):
        """kind="group_schedule"을 명시하면 기본값 personal_schedule 대신 그 kind로 조회하는지 확인한다."""

        save_structured_request_payload(
            {"kind": "group_schedule", "title": "팀 회의", "date": "2026-08-13", "members": ["철수"]}, store=store
        )

        result = json.loads(personal_list_saved_schedules.invoke({"kind": "group_schedule"}))

        assert result["filters"]["kind"] == "group_schedule"
        assert [row["title"] for row in result["schedules"]] == ["팀 회의"]

    def test_date_range_filters_schedules(self, store, no_external_sync, use_test_store):
        """date_from/date_to 범위 안(8월)과 밖(9월) 일정을 함께 저장해 범위 안 일정만 반환되는지 확인한다."""

        save_structured_request_payload({"kind": "personal_schedule", "title": "8월 일정", "date": "2026-08-15"}, store=store)
        save_structured_request_payload({"kind": "personal_schedule", "title": "9월 일정", "date": "2026-09-15"}, store=store)

        result = json.loads(
            personal_list_saved_schedules.invoke({"date_from": "2026-08-01", "date_to": "2026-08-31"})
        )

        assert [row["title"] for row in result["schedules"]] == ["8월 일정"]

    def test_limit_caps_number_of_rows(self, store, no_external_sync, use_test_store):
        """일정 3건을 저장하고 limit=2로 조회해 반환 개수가 상한에서 잘리는지 확인한다."""

        for day in ("10", "11", "12"):
            save_structured_request_payload(
                {"kind": "personal_schedule", "title": f"일정{day}", "date": f"2026-08-{day}"}, store=store
            )

        result = json.loads(personal_list_saved_schedules.invoke({"limit": 2}))

        assert len(result["schedules"]) == 2


class TestSavedScheduleListInputBoundaries:
    """[블랙박스 / 명세 기반 - 경계값 분석] SavedScheduleListInput.limit의 ge=1, le=200 경계를 확인한다."""

    @pytest.mark.parametrize("invalid_limit", [0, -1, 201])
    def test_out_of_range_limit_is_rejected(self, invalid_limit):
        """limit의 ge=1/le=200 밖 값(0, -1, 201)을 SavedScheduleListInput에 넣으면 Pydantic이 ValidationError로 거부하는지 확인한다."""

        with pytest.raises(ValidationError):
            SavedScheduleListInput(limit=invalid_limit)

    @pytest.mark.parametrize("boundary_limit", [1, 200])
    def test_boundary_limit_values_are_accepted(self, boundary_limit):
        """경계값 1과 200은 거부되지 않고 그대로 limit에 저장되는지 확인한다."""

        result = SavedScheduleListInput(limit=boundary_limit)
        assert result.limit == boundary_limit


class TestListAndGetSavedRequestFiltering:
    """[블랙박스 / 명세 기반 - 동등 분할/경계값] list_saved_requests/get_saved_request가 조회 조건에 따라 정해진 대로 동작하는지 확인한다."""

    def test_list_saved_requests_date_range_filters_rows(self, store, use_test_store):
        """8월 두 건과 9월 한 건을 저장해 date_from/date_to 범위 안 두 건만 list_saved_requests가 반환하는지 확인한다."""

        for date in ("2026-08-01", "2026-08-15", "2026-09-01"):
            save_structured_request_payload({"kind": "todo", "title": f"할일-{date}", "date": date}, store=store)

        result = json.loads(list_saved_requests.invoke({"date_from": "2026-08-01", "date_to": "2026-08-31"}))

        returned_dates = {row["date"] for row in result["rows"]}
        assert returned_dates == {"2026-08-01", "2026-08-15"}

    def test_get_saved_request_returns_full_row_by_id(self, use_test_store):
        """저장 후 받은 request_id로 get_saved_request가 그 원본 row(title/kind)를 그대로 되돌려주는지 확인한다."""

        saved = save_structured_request_payload({"kind": "todo", "title": "정기 보고"}, store=use_test_store)

        result = json.loads(get_saved_request.invoke({"request_id": saved["request_id"]}))

        assert result["row"]["title"] == "정기 보고"
        assert result["row"]["kind"] == "todo"


# --------------------------------------------------------------------------
# 3. 오류 예측 검사 (경험 기반 블랙박스)
# --------------------------------------------------------------------------


class TestErrorGuessing:
    """[블랙박스 / 경험 기반 - 오류 예측 검사] 사용자가 하기 쉬운 실수를 흉내내 실패 경로를 확인한다."""

    def test_invalid_kind_is_rejected_by_pydantic(self):
        """kind가 RequestKind Literal에 없는 "존재하지않는종류"이면 SaveStructuredRequestInput.model_validate가 ValidationError로 거부하는지 확인한다."""

        with pytest.raises(ValidationError):
            SaveStructuredRequestInput.model_validate({"kind": "존재하지않는종류", "title": "x"})

    def test_get_unknown_request_id_returns_none_not_error(self, use_test_store):
        """없는 request_id를 조회했을 때 예외가 아니라 ok=True, row=None으로 돌아오는지 확인한다.
        "조회 결과 없음은 오류가 아니다"라는 가이드 규칙을 지키는 경로다."""

        result = json.loads(get_saved_request.invoke({"request_id": "req_없는id"}))
        assert result["ok"] is True
        assert result["row"] is None

    def test_update_unknown_schedule_id_fails_gracefully(self, use_test_store):
        """없는 schedule_id로 수정을 시도하면 예외를 던지지 않고 ok=False로 실패를 알리는지 확인한다."""

        result = json.loads(
            personal_update_saved_schedule.invoke({"schedule_id": "sch_없는id", "title": "새 제목"})
        )
        assert result["ok"] is False

    def test_delete_without_any_condition_is_rejected(self, use_test_store):
        """personal_delete_saved_schedules.invoke({})로 아무 조건 없이 삭제를 호출해 ok=False, deleted_count=0으로 거부되는지 확인한다.
        .invoke는 SavedScheduleDeleteInput 기본값(delete_all=False 등)을 실제로 거치므로, 내부 함수 직접 호출(TestDeleteGuardBranches)로는 못 잡는 스키마 기본값 오류까지 잡는다."""

        result = json.loads(personal_delete_saved_schedules.invoke({}))
        assert result["ok"] is False
        assert result["deleted_count"] == 0


# --------------------------------------------------------------------------
# 4. Mock 기반 단위 테스트 (검증(Verification) 테스트)
# --------------------------------------------------------------------------


class TestSaveStructuredRequestCallsStoreCorrectly:
    """[Mock 기반 단위 테스트 / 검증(Verification) 테스트]

    진짜 SQLite 대신 store를 MagicMock으로 바꿔서, "무엇이 저장됐는가"가 아니라
    "store.save_structured_request가 정확히 어떤 인자로 호출됐는가"만 검증한다.
    Java Mockito의 `verify(mock).method(eq(...))`와 같은 접근이다.
    """

    def test_save_structured_request_forwards_exact_payload_to_store(self, mocker):
        """store를 MagicMock으로 바꿔, save_structured_request가 store.save_structured_request에 넘긴 payload를 call_args로 되짚어 검증한다.
        kind/title/priority는 그대로 전달되고, tool 응답 wrapper 필드(ok/tool_name)는 저장 payload에 섞이지 않아야 한다."""

        fake_store = mocker.MagicMock()
        fake_store.save_structured_request.return_value = {
            "request_id": "req_fake",
            "kind": "todo",
            "saved_rows": [
                {"table": "structured_requests", "id": "req_fake"},
                {"table": "todos", "id": "todo_fake"},
            ],
            "shared_sync": None,
        }
        mocker.patch("student_parts.week03_build_nanas_logbook._store", return_value=fake_store)

        result = json.loads(
            save_structured_request.invoke(
                {"kind": "todo", "title": "보고서", "date": "2026-08-01", "priority": "high"}
            )
        )

        fake_store.save_structured_request.assert_called_once()
        (called_payload,), _ = fake_store.save_structured_request.call_args
        assert called_payload["kind"] == "todo"
        assert called_payload["title"] == "보고서"
        assert called_payload["priority"] == "high"
        assert "ok" not in called_payload
        assert "tool_name" not in called_payload
        assert result["request_id"] == "req_fake"

    def test_personal_create_schedule_wires_week01_result_into_sqlite_save(self, mocker):
        """personal_create_schedule이 Week 1 tool 결과를 SQLite 저장 경로로 넘기는 연결만 확인한다(실제 저장은 mock).
        call_args로 kind="personal_schedule"·title이 전달되고, source_schedule_id가 created_schedule.id와 같은지 본다."""

        fake_store = mocker.MagicMock()
        fake_store.save_structured_request.return_value = {
            "request_id": "req_fake2",
            "kind": "personal_schedule",
            "saved_rows": [
                {"table": "structured_requests", "id": "req_fake2"},
                {"table": "schedules", "id": "sch_fake2"},
            ],
            "shared_sync": {"ok": True, "status": "synced"},
        }
        mocker.patch("student_parts.week03_build_nanas_logbook._store", return_value=fake_store)

        result = json.loads(
            personal_create_schedule.invoke(
                {"title": "코칭", "date": "2026-07-18", "start_time": "10:00", "attendees": ["나"]}
            )
        )

        fake_store.save_structured_request.assert_called_once()
        (called_payload,), _ = fake_store.save_structured_request.call_args
        assert called_payload["kind"] == "personal_schedule"
        assert called_payload["title"] == "코칭"
        assert called_payload["source_schedule_id"] == result["created_schedule"]["id"]
        assert result["sqlite_save"]["request_id"] == "req_fake2"

    def test_personal_create_schedule_forwards_none_attendees_as_empty_list_to_week01(self, mocker):
        """personal_create_schedule을 attendees 없이 호출하면 line 551의 attendees or [] 분기가 None을 []로 바꿔 week01_personal_create_schedule.invoke에 넘기는지 call_args로 확인한다.
        week01 쪽에도 같은 or [] 기본값이 있어 최종 결과만 보면 이 분기가 실제로 실행됐는지 구분되지 않는다.
        그래서 mock이 실제 함수를 그대로 호출하도록 해 두고(side_effect), 그 mock이 어떤 인자로 불렸는지만 따로 기록해서 확인한다."""

        fake_store = mocker.MagicMock()
        fake_store.save_structured_request.return_value = {
            "request_id": "req_fake3",
            "kind": "personal_schedule",
            "saved_rows": [
                {"table": "structured_requests", "id": "req_fake3"},
                {"table": "schedules", "id": "sch_fake3"},
            ],
            "shared_sync": None,
        }
        mocker.patch("student_parts.week03_build_nanas_logbook._store", return_value=fake_store)
        mock_week01 = mocker.MagicMock()
        mock_week01.invoke.side_effect = week01_personal_create_schedule.invoke
        mocker.patch("student_parts.week03_build_nanas_logbook.week01_personal_create_schedule", mock_week01)

        personal_create_schedule.invoke({"title": "코칭", "date": "2026-07-18", "start_time": "10:00"})

        called_args, _ = mock_week01.invoke.call_args
        assert called_args[0]["attendees"] == []

    def test_save_structured_request_forwards_explicit_members(self, mocker):
        """save_structured_request(tool)에 members를 직접 넘기면 line 645의 members or [] 분기가 참쪽(그대로 사용)을 타는지 call_args로 확인한다.
        지금까지 이 tool을 부르는 다른 모든 테스트는 members를 생략해 거짓쪽(빈 리스트 대체)만 지나갔다."""

        fake_store = mocker.MagicMock()
        fake_store.save_structured_request.return_value = {
            "request_id": "req_fake4",
            "kind": "group_schedule",
            "saved_rows": [
                {"table": "structured_requests", "id": "req_fake4"},
                {"table": "schedules", "id": "sch_fake4"},
            ],
            "shared_sync": {"ok": True, "status": "synced"},
        }
        mocker.patch("student_parts.week03_build_nanas_logbook._store", return_value=fake_store)

        save_structured_request.invoke(
            {"kind": "group_schedule", "title": "팀 회의", "date": "2026-08-20", "members": ["철수", "영희"]}
        )

        (called_payload,), _ = fake_store.save_structured_request.call_args
        assert called_payload["members"] == ["철수", "영희"]

    def test_personal_list_saved_schedules_forwards_filters_to_store(self, mocker):
        """personal_list_saved_schedules가 _store().list_schedules를 정확한 인자(limit/kind/date_from/date_to)로 호출하는지 assert_called_once_with로 본다.
        결과 row 모양은 TestPersonalListSavedSchedules가 실제 SQLite로 확인하므로, 여기서는 "store에 무엇을 물어봤는가"만 검증한다."""

        fake_store = mocker.MagicMock()
        fake_store.list_schedules.return_value = []
        mocker.patch("student_parts.week03_build_nanas_logbook._store", return_value=fake_store)

        personal_list_saved_schedules.invoke(
            {"limit": 5, "kind": "todo", "date_from": "2026-08-01", "date_to": "2026-08-31"}
        )

        fake_store.list_schedules.assert_called_once_with(
            limit=5, kind="todo", date_from="2026-08-01", date_to="2026-08-31"
        )


class TestWeek03ToolsAssembly:
    """[화이트박스 / 구조 기반] week03_tools()의 tool 교체·집합 로직을 확인한다.

    이 함수의 핵심 분기는 "week01 tool 목록 중 personal_create_schedule 이름을 가진
    항목만 이 파일의 버전으로 교체한다"는 list comprehension이다. 그 분기가 실제로
    올바른 객체를 골라내는지, 그리고 Week 2/3에서 추가한 tool들이 누락 없이
    포함되는지를 확인한다.
    """

    def test_replaces_week01_personal_create_schedule_with_week03_version(self):
        """week03_tools()가 week01 tool 목록 중 personal_create_schedule만 이 파일 버전으로 교체하는 분기를 확인한다.
        이름이 같은 tool이 정확히 하나이고, 그게 week03 객체(is 비교)이며 week01 객체가 아닌지 본다."""

        tools = week03_tools()
        matching = [tool for tool in tools if getattr(tool, "name", None) == "personal_create_schedule"]

        assert len(matching) == 1
        assert matching[0] is personal_create_schedule
        assert matching[0] is not week01_personal_create_schedule

    def test_includes_all_expected_sqlite_tools(self):
        """week03_tools()가 Week 1~3 tool을 누락 없이 담는지, 기대하는 tool 이름 집합이 부분집합으로 들어 있는지 확인한다."""

        tools = week03_tools()
        names = {getattr(tool, "name", getattr(tool, "__name__", None)) for tool in tools}

        assert {
            "personal_create_schedule",
            "personal_list_schedules",
            "personal_delete_schedule",
            "extract_schedule_request",
            "save_structured_request",
            "list_saved_requests",
            "get_saved_request",
            "personal_list_saved_schedules",
            "personal_update_saved_schedule",
            "personal_delete_saved_schedules",
        }.issubset(names)


class TestDeleteSavedSchedulesDictHelper:
    """delete_saved_schedules_dict는 이 테스트들이 생기기 전까지 어떤 테스트에서도 호출된 적이 없었다(커버리지 0).
    app_store or _store() 분기(line 746)의 두 갈래를 각각 실행한다."""

    def test_forwards_to_delete_saved_schedules_with_given_store(self, store, no_external_sync):
        """app_store를 명시적으로 넘기면 line 746의 참쪽을 타고 _delete_saved_schedules에 그대로 위임하는지 확인한다."""

        save_structured_request_payload(
            {"kind": "personal_schedule", "title": "약속", "date": "2026-08-21"}, store=store
        )
        result = delete_saved_schedules_dict(title="약속", app_store=store)
        assert result["ok"] is True
        assert result["deleted_count"] == 1

    def test_falls_back_to_store_when_app_store_omitted(self, mocker):
        """app_store 없이 호출하면 line 746의 거짓쪽이 _store()를 호출해 그 결과를 쓰는지 확인한다."""

        fake_store = mocker.MagicMock()
        fake_store.delete_schedules_by_filter.return_value = []
        mocker.patch("student_parts.week03_build_nanas_logbook._store", return_value=fake_store)

        result = delete_saved_schedules_dict(title="아무거나")

        fake_store.delete_schedules_by_filter.assert_called_once()
        assert result["ok"] is True


# --------------------------------------------------------------------------
# 5. 통합 테스트
# --------------------------------------------------------------------------


class TestScheduleLifecycleIntegration:
    """[통합 테스트] 실제 SQLite 파일에 저장 -> 조회 -> 수정 -> 삭제를 연달아 호출해
    각 함수가 서로 맞물려 동작하는지 확인한다(개별 함수 하나의 정확성이 아니라 흐름 전체를 본다).
    """

    def test_full_personal_schedule_lifecycle(self, store, no_external_sync):
        """실제 SQLite에 personal_schedule을 저장한 뒤 list→update→delete를 store 메서드로 연달아 호출해 흐름이 맞물리는지 확인한다.
        저장이 만든 schedule_id가 조회에 보이고, 수정한 start_time이 반영되며, 삭제 후 목록이 비는지 하나의 시나리오로 본다."""

        saved = save_structured_request_payload(
            {"kind": "personal_schedule", "title": "치과", "date": "2026-07-25", "start_time": "14:00"},
            store=store,
        )
        schedule_id = next(row["id"] for row in saved["saved_rows"] if row["table"] == "schedules")

        listed = store.list_schedules(kind="personal_schedule")
        assert any(row["schedule_id"] == schedule_id for row in listed)

        updated = store.update_schedule(schedule_id, start_time="16:00")
        assert updated["schedule"]["start_time"] == "16:00"

        deleted = _delete_saved_schedules(store=store, schedule_ids=[schedule_id])
        assert deleted["deleted_count"] == 1
        assert store.list_schedules(kind="personal_schedule") == []

    def test_duplicate_source_schedule_id_is_not_saved_twice(self, store, no_external_sync):
        """같은 source_schedule_id를 두 번 저장하면 두 번째는 새로 만들지 않고 already_exists=True와 같은 request_id를 돌려주는지 확인한다.
        Week 1 호환 저장이 중복 저장을 막는 실제 SQLite 경로다."""

        week1_schedule = {
            "id": "personal_dup1",
            "title": "회의",
            "date": "2026-07-30",
            "start_time": "09:00",
            "end_time": "미정",
            "attendees": ["나"],
        }
        save_input = structured_request_from_week01_schedule(week1_schedule)
        first = save_structured_request_payload(save_input, store=store)
        second = save_structured_request_payload(save_input, store=store)
        assert second.get("already_exists") is True
        assert first["request_id"] == second["request_id"]

    def test_tool_layer_end_to_end_via_agent_style_invoke(self, use_test_store, no_external_sync):
        """agent가 실제로 쓰는 것과 같은 @tool.invoke 방식으로 save→list→get을 이어 호출해, tool이 감싸고 있는 인터페이스 층까지 포함해서 실제 SQLite와 맞물려 정상 동작하는지 확인한다.
        저장한 request_id가 목록과 단건 조회에 그대로 나타나야 한다."""

        save_result = json.loads(
            save_structured_request.invoke({"kind": "todo", "title": "보고서 작성", "date": "2026-08-01"})
        )
        assert save_result["ok"] is True

        listed = json.loads(list_saved_requests.invoke({"kind": "todo"}))
        assert any(row["request_id"] == save_result["request_id"] for row in listed["rows"])

        fetched = json.loads(get_saved_request.invoke({"request_id": save_result["request_id"]}))
        assert fetched["row"]["title"] == "보고서 작성"

    def test_full_lifecycle_via_tool_invoke_including_update_and_delete(self, use_test_store, no_external_sync):
        """save→list→update→delete→list를 전부 .invoke로만 호출해, update가 성공하는 경로와 delete가 tool의 .invoke 인터페이스를 통해 정상 동작하는 경로를 함께 메운다.
        기존 test_full_personal_schedule_lifecycle이 store/내부 helper로 직접 호출한 것과 달리, 여기서는 tool 자체를 agent 방식으로 검증한다."""

        save_structured_request.invoke(
            {"kind": "personal_schedule", "title": "치과", "date": "2026-08-05", "start_time": "14:00"}
        )

        listed = json.loads(personal_list_saved_schedules.invoke({}))
        schedule_id = listed["schedules"][0]["schedule_id"]

        updated = json.loads(
            personal_update_saved_schedule.invoke(
                {"schedule_id": schedule_id, "start_time": "16:00", "title": "치과 (변경)"}
            )
        )
        assert updated["ok"] is True
        assert updated["updated_schedule"]["start_time"] == "16:00"
        assert updated["updated_schedule"]["title"] == "치과 (변경)"
        assert updated["shared_sync"] is not None
        assert updated["shared_sync"]["ok"] is True

        deleted = json.loads(personal_delete_saved_schedules.invoke({"schedule_ids": [schedule_id]}))
        assert deleted["ok"] is True
        assert deleted["deleted_count"] == 1

        final_listed = json.loads(personal_list_saved_schedules.invoke({}))
        assert final_listed["schedules"] == []
