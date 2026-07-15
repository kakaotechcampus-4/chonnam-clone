from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from pydantic import BaseModel, Field, ValidationError, model_validator

from fixed.config import CONFIG
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from fixed.app_store import AppSQLiteStore
from student_parts.week01_wake_up_nana import (
    join_system_prompt,
    personal_create_schedule as week01_personal_create_schedule,
    week01_tools,
)
from student_parts.week02_structure_natural_language_requests import (
    RequestKind,
    StructuredRequest,
    extract_schedule_request,
    extract_structured_request,
    week02_prompt_parts,
)


_WEEK03_AGENT: Any | None = None

# TODO: 새 대화에서도 SQLite 일정/할 일/알림을 조회할 수 있도록 Week 3 영속 메모리 규칙을 작성하세요.
SQLITE_MEMORY_PROMPT = ""

# TODO: 자연어 구조화 → SQLite 저장과 조회/수정/삭제 tool 호출 순서를 안내하는 규칙을 작성하세요.
WEEK03_TOOL_CALL_PROMPT = ""


def _store() -> AppSQLiteStore:
    return AppSQLiteStore(CONFIG.app_db_path)


def _tool_name(item: Any) -> str:
    return getattr(item, "name", getattr(item, "__name__", str(item)))


def json_payload(payload: dict[str, Any]) -> str:
    """도구 반환용 dict를 한글이 깨지지 않는 JSON 문자열로 변환합니다."""

    return json.dumps(payload, ensure_ascii=False)


def tool_result(tool_name: str, *, ok: bool = True, **payload: Any) -> dict[str, Any]:
    """Week 3 tool들이 공통으로 쓰는 JSON payload 껍데기를 만듭니다."""

    return {"ok": ok, "tool_name": tool_name, **payload}


class SaveStructuredRequestInput(StructuredRequest):
    """SQLite 저장 직전에 검증하는 Week 3 입력 스키마입니다."""

    kind: RequestKind = Field(default="unknown", description="분류된 요청 종류")
    source_schedule_id: str | None = Field(default=None, description="Week 1 임시 일정에서 넘어온 원본 일정 ID")

    @model_validator(mode="before")
    @classmethod
    def unwrap_legacy_payload(cls, value: Any) -> Any:
        """예전 trace의 payload wrapper만 짧게 풀고 실제 검증은 필드 스키마에 맡깁니다."""

        if isinstance(value, StructuredRequest):
            return value.model_dump()
        while isinstance(value, dict):
            inner = value.get("structured_request") or value.get("payload")
            if not isinstance(inner, dict):
                break
            value = inner
        return value


def _save_input_from(
    value: SaveStructuredRequestInput | StructuredRequest | dict[str, Any] | str,
) -> SaveStructuredRequestInput:
    """저장 입력을 SaveStructuredRequestInput 하나로 모읍니다."""

    if isinstance(value, SaveStructuredRequestInput):
        return value
    if isinstance(value, StructuredRequest | dict):
        return SaveStructuredRequestInput.model_validate(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return SaveStructuredRequestInput.model_validate(parsed)
        extracted = extract_structured_request(value).model_dump()
        return SaveStructuredRequestInput.model_validate(extracted)
    raise TypeError(f"지원하지 않는 저장 입력 타입: {type(value)}")


def save_structured_request_payload(
    request: SaveStructuredRequestInput | StructuredRequest | dict[str, Any] | str,
    *,
    store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    """검증된 structured request를 앱 DB에 저장합니다."""

    try:
        validated = _save_input_from(request)
    except ValidationError as exc:
        return tool_result(
            "save_structured_request", ok=False, error=exc.errors()
        )
    payload = {
        key: value
        for key, value in validated.model_dump().items()
        if value is not None
    }
    saved = (store or _store()).save_structured_request(payload)
    return tool_result("save_structured_request", **saved)


class SavedRequestListInput(BaseModel):
    """저장 요청 목록 조회 입력입니다."""

    kind: RequestKind | None = None
    date_from: str | None = None
    date_to: str | None = None


class SavedRequestGetInput(BaseModel):
    """저장 요청 단건 조회 입력입니다."""

    request_id: str


class SavedScheduleListInput(BaseModel):
    """저장 일정 목록 조회 입력입니다."""

    limit: int = Field(default=50, ge=1, le=200)
    kind: RequestKind | None = None
    date_from: str | None = None
    date_to: str | None = None


class SavedScheduleUpdateInput(BaseModel):
    """저장 일정 수정 입력입니다."""

    schedule_id: str
    title: str | None = None
    date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    attendees: list[str] | None = None


class SavedScheduleDeleteInput(BaseModel):
    """저장 일정 삭제 입력입니다."""

    schedule_ids: list[str] | None = None
    date: str | None = None
    title: str | None = None
    start_time: str | None = None
    time_unspecified: bool = False
    delete_all: bool = False


def _delete_saved_schedules(
    *,
    store: AppSQLiteStore,
    schedule_ids: list[str] | None = None,
    date: str | None = None,
    title: str | None = None,
    start_time: str | None = None,
    time_unspecified: bool = False,
    delete_all: bool = False,
) -> dict[str, Any]:
    """삭제 guard와 DB 호출을 한 곳에 둡니다."""

    # TODO: 삭제 조건이 없으면 거부하고, delete_all 또는 명시 필터에 맞는 store 메서드를 호출하세요.
    # TODO: deleted_count, filters, deleted가 포함된 tool 결과 dict를 반환하세요.
    ...


def structured_request_from_week01_schedule(schedule: dict[str, Any]) -> SaveStructuredRequestInput:
    """Week 1 임시 일정 dict를 Week 3 저장 입력으로 변환합니다."""

    # TODO: Week 1 schedule의 attendees/id를 Week 3 members/source_schedule_id에 맞춰 변환하세요.
    ...


@tool("personal_create_schedule")
def personal_create_schedule(
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    attendees: list[str] | None = None,
) -> str:
    """Nana의 개인 일정을 생성하고 Week 3+ 앱 SQLite DB에도 저장합니다."""

    # TODO: Week 1 임시 일정 tool을 호출한 뒤 결과를 StructuredRequest로 바꿔 SQLite에도 저장하세요.
    # TODO: created 결과에 structured_request와 sqlite_save를 합쳐 JSON 문자열로 반환하세요.
    ...


@tool(args_schema=SaveStructuredRequestInput)
def save_structured_request(
    kind: RequestKind = "unknown",
    title: str | None = None,
    date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    members: list[str] | None = None,
    priority: str | None = None,
    reason: str | None = None,
    original_text: str = "",
    source_schedule_id: str | None = None,
) -> str:
    """Week 2 structured_request 필드를 검증한 뒤 SQLite에 저장합니다."""

    # TODO: 검증된 함수 인자를 저장 dict로 만들고 None 값을 제외한 뒤 SQLite에 저장하세요.
    payload = {
        "kind": kind,
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "members": members or [],
        "priority": priority,
        "reason": reason,
        "original_text": original_text,
        "source_schedule_id": source_schedule_id,
    }
    payload = {
        key: value for key, value in payload.items() if value is not None
    }
    saved = _store().save_structured_request(payload)
    return json_payload(tool_result("save_structured_request", **saved))


@tool(args_schema=SavedRequestListInput)
def list_saved_requests(
    kind: RequestKind | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """SQLite에 저장된 구조화 요청 목록을 조회합니다."""

    # TODO: kind/date_from/date_to 필터로 저장 요청을 조회하고 rows를 JSON 문자열로 반환하세요.
    rows = _store().list_saved_requests(
        kind=kind,
        date_from=date_from,
        date_to=date_to,
    )
    return json_payload(tool_result("list_saved_requests", rows=rows))


@tool(args_schema=SavedRequestGetInput)
def get_saved_request(request_id: str) -> str:
    """request_id로 구조화 요청 행 하나를 조회합니다."""

    row = _store().get_saved_request(request_id=request_id)
    return json_payload(tool_result("get_saved_request", row=row))


@tool(args_schema=SavedScheduleListInput)
def personal_list_saved_schedules(
    limit: int = 50,
    kind: RequestKind | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """앱 DB에 저장된 일정 목록을 날짜/종류 필터로 반환합니다. Nana가 조회/수정/삭제 후보를 볼 때 사용합니다."""

    # TODO: 기본 kind를 personal_schedule로 정하고 날짜/종류/limit 필터로 저장 일정을 조회하세요.
    kind = kind or "personal_schedule"
    schedules = _store().list_schedules(
        limit=limit,
        kind=kind,
        date_from=date_from,
        date_to=date_to,
    )
    filters = {
        "kind": kind,
        "date_from": date_from,
        "date_to": date_to,
        "limit": limit,
    }
    # TODO: filters와 schedules를 포함한 JSON 문자열을 반환하세요.
    payload = tool_result(
        "personal_list_saved_schedules",
        filters=filters,
        schedules=schedules,
    )
    return json_payload(payload)


def delete_saved_schedules_dict(
    schedule_ids: list[str] | None = None,
    date: str | None = None,
    title: str | None = None,
    start_time: str | None = None,
    time_unspecified: bool = False,
    delete_all: bool = False,
    app_store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    """tool invoke 없이 저장 일정 삭제 로직을 직접 호출합니다."""

    # TODO: 전달받은 store 또는 기본 store로 _delete_saved_schedules(...)를 호출하세요.
    ...


@tool(args_schema=SavedScheduleUpdateInput)
def personal_update_saved_schedule(
    schedule_id: str,
    title: str | None = None,
    date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    attendees: list[str] | None = None,
) -> str:
    """앱 DB에 저장된 내 일정 원본을 수정하고 공유 일정 복사본을 같은 값으로 갱신합니다."""

    # TODO: None이 아닌 수정 필드를 AppSQLiteStore.update_schedule(...)에 전달하세요.
    # TODO: ID가 없으면 ok=False, 있으면 updated_schedule/shared_sync를 담아 JSON 문자열로 반환하세요.
    ...


@tool(args_schema=SavedScheduleDeleteInput)
def personal_delete_saved_schedules(
    schedule_ids: list[str] | None = None,
    date: str | None = None,
    title: str | None = None,
    start_time: str | None = None,
    time_unspecified: bool = False,
    delete_all: bool = False,
) -> str:
    """Nana가 고른 일정 ID나 날짜/제목/시간 필터로 저장 일정을 삭제합니다."""

    # TODO: _delete_saved_schedules(...)에 삭제 조건을 전달하고 결과를 JSON 문자열로 반환하세요.
    ...


def week03_tools() -> list[Any]:
    """Week 1 도구, Week 2 구조화 helper, SQLite 저장/조회/삭제 도구를 조립합니다."""

    base_tools = [
        personal_create_schedule if _tool_name(item) == "personal_create_schedule" else item for item in week01_tools()
    ]
    return [
        *base_tools,
        extract_schedule_request,
        save_structured_request,
        list_saved_requests,
        get_saved_request,
        personal_list_saved_schedules,
        personal_update_saved_schedule,
        personal_delete_saved_schedules,
    ]


def week03_system_prompt() -> str:
    """3주차 단일 agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt(week03_prompt_parts())


def week03_prompt_parts() -> list[str]:
    """1~3주차 system prompt 조각을 누적합니다."""

    return [
        *week02_prompt_parts(),
        # TODO: Week 2 구조화 결과를 Week 3 SQLite 저장 흐름으로 연결하는 지시를 추가하세요.
        SQLITE_MEMORY_PROMPT,
        WEEK03_TOOL_CALL_PROMPT,
        # TODO: 현재 날짜, Week 3 tool 선택 기준, 이번 주차의 범위를 설명하는 agent 지시를 추가하세요.
    ]


def build_week03_agent() -> object:
    """Week 1-3 누적 tool 목록을 노출하는 단일 LangChain agent를 만듭니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK03_AGENT
    if _WEEK03_AGENT is None:
        _WEEK03_AGENT = create_agent(
            model=chat_model(),
            tools=week03_tools(),
            system_prompt=week03_system_prompt(),
        )
    return _WEEK03_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week03_agent()
