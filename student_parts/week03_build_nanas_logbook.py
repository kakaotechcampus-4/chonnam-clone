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
SQLITE_MEMORY_PROMPT = """
[Week 3 영속 메모리]
- Week 3부터 일정/할 일/알림은 앱 SQLite DB에 저장되어 새 대화와 앱 재시작 후에도 유지된다.
- 저장된 일정 조회는 personal_list_saved_schedules를 사용한다.
- Week 1 personal_list_schedules는 현재 대화의 임시 일정만 보여주므로 저장된 일정 질문에 쓰지 않는다.
- 저장된 구조화 요청 원본은 list_saved_requests / get_saved_request로 조회한다.
- 저장 여부와 일정 상태는 대화 기억이 아니라 SQLite 조회 tool 결과를 근거로 답한다.
"""
WEEK03_TOOL_CALL_PROMPT = """
[Week 3 tool 호출 순서]
- 저장: 일정/할 일/알림 요청은 먼저 extract_schedule_request로 구조화한 뒤 반환된 필드를
save_structured_request로 저장한다. 단, 시간이 '10시'처럼 오전/오후가 모호하면
구조화하기 전에 먼저 사용자에게 오전/오후를 물어 확정하고, 확정된 시간이 반영된 전체 요청 문장으로
extract_schedule_request를 호출한다.
- extract_schedule_request에는 요청 원문 전체를 그대로 넣고, 필드 값을 요약하거나 임의로 바꾸지 않는다.
- personal_create_schedule은 일정 생성과 SQLite 저장을 함께 수행하므로,
이 tool로 만든 일정에 save_structured_request를 다시 호출하지 않는다.
- 조회: 저장된 일정은 personal_list_saved_schedules, 요청 기록은 list_saved_requests를 쓴다.
- 수정: 먼저 personal_list_saved_schedules로 대상 schedule_id를 확인한 뒤
personal_update_saved_schedule을 호출한다. 바꿀 필드만 전달하고 나머지는 생략한다.
- 전체 삭제: 사용자가 '모두 삭제', '전부 지워줘'처럼 저장된 일정 전체 삭제를 명확히 요청하면,
schedule_ids를 하나씩 모으지 말고 personal_delete_saved_schedules를 delete_all=True로 한 번만 호출한다.
- 일부 삭제: 먼저 personal_list_saved_schedules로 후보를 확인하고,
personal_delete_saved_schedules에 schedule_ids 또는 날짜/제목/시간 필터를 명시한다.
- 조건 없는 삭제는 하지 않는다. delete_all=True는 사용자가 전체 삭제를 명확히 요청할 때만 쓴다.
- 수정/삭제 대상이 여러 개로 일치하면 실행 전에 사용자에게 확인한다.
"""


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

    kind: RequestKind | None = Field(default=None, description="필터할 요청 종류. 생략하면 모든 종류를 조회")
    date_from: str | None = Field(default=None, description="조회 시작 날짜(YYYY-MM-DD, 포함)")
    date_to: str | None = Field(default=None, description="조회 종료 날짜(YYYY-MM-DD, 포함)")


class SavedRequestGetInput(BaseModel):
    """저장 요청 단건 조회 입력입니다."""

    request_id: str = Field(description="조회할 구조화 요청의 ID. list_saved_requests 결과의 request_id 값")


class SavedScheduleListInput(BaseModel):
    """저장 일정 목록 조회 입력입니다."""

    limit: int = Field(default=50, ge=1, le=200, description="최대 반환 개수(1~200)")
    kind: RequestKind | None = Field(default=None, description="일정 종류 필터. 생략하면 personal_schedule 기준으로 조회")
    date_from: str | None = Field(default=None, description="조회 시작 날짜(YYYY-MM-DD, 포함)")
    date_to: str | None = Field(default=None, description="조회 종료 날짜(YYYY-MM-DD, 포함)")


class SavedScheduleUpdateInput(BaseModel):
    """저장 일정 수정 입력입니다."""

    schedule_id: str = Field(description="수정할 일정의 ID. personal_list_saved_schedules 결과의 schedule_id 값")
    title: str | None = Field(default=None, description="새 제목. 바꾸지 않으면 생략")
    date: str | None = Field(default=None, description="새 날짜(YYYY-MM-DD). 바꾸지 않으면 생략")
    start_time: str | None = Field(default=None, description="새 시작 시간(HH:MM). 바꾸지 않으면 생략")
    end_time: str | None = Field(default=None, description="새 종료 시간(HH:MM). 바꾸지 않으면 생략")
    attendees: list[str] | None = Field(default=None, description="새 참석자 목록 전체. 바꾸지 않으면 생략")


class SavedScheduleDeleteInput(BaseModel):
    """저장 일정 삭제 입력입니다."""

    schedule_ids: list[str] | None = Field(default=None, description="삭제할 일정 ID 목록. personal_list_saved_schedules로 확인한 schedule_id 값")
    date: str | None = Field(default=None, description="이 날짜의 일정만 삭제(YYYY-MM-DD)")
    title: str | None = Field(default=None, description="제목에 이 문자열이 포함된 일정만 삭제(부분 일치)")
    start_time: str | None = Field(default=None, description="이 시작 시간의 일정만 삭제(HH:MM)")
    time_unspecified: bool = Field(default=False, description="True면 시작 시간이 비어 있거나 '미정'인 일정을 삭제")
    delete_all: bool = Field(default=False, description="True면 저장된 일정 전체를 삭제. 사용자가 전체 삭제를 명확히 요청했을 때만 사용")


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

    filters = {
        "schedule_ids": schedule_ids,
        "date": date,
        "title": title,
        "start_time": start_time,
        "time_unspecified": time_unspecified,
    }
    has_filter = (
        bool(schedule_ids)
        or bool(date)
        or bool(title)
        or bool(start_time)
        or time_unspecified
    )
    
    if not has_filter and not delete_all:
        return tool_result(
            "personal_delete_saved_schedules",
            ok=False,
            error="삭제 조건이 없습니다. schedule_ids나 날짜/제목/시간 필터를 지정하거나 delete_all=True를 명시하세요.",
            deleted_count=0,
            filters=filters,
            deleted=[],
        )
    
    if delete_all:
        deleted = store.delete_all_schedules()
    else:
        deleted = store.delete_schedules_by_filter(
            schedule_ids=schedule_ids,
            date=date,
            title=title,
            start_time=start_time,
            time_unspecified=time_unspecified,
        )
    
    return tool_result(
        "personal_delete_saved_schedules",
        deleted_count=len(deleted),
        filters=filters,
        deleted=deleted,
        delete_all=delete_all,
    )


def structured_request_from_week01_schedule(schedule: dict[str, Any]) -> SaveStructuredRequestInput:
    """Week 1 임시 일정 dict를 Week 3 저장 입력으로 변환합니다."""

    return SaveStructuredRequestInput(
        kind="personal_schedule",
        title=schedule.get("title"),
        date=schedule.get("date"),
        start_time=schedule.get("start_time"),
        end_time=schedule.get("end_time"),
        members=list(schedule.get("attendees") or []),
        original_text=json.dumps(schedule, ensure_ascii=False),
        source_schedule_id=schedule.get("schedule_id"),
    )

@tool
def personal_create_schedule(
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    attendees: list[str] | None = None,
) -> str:
    """Nana의 개인 일정을 생성하고 Week 3+ 앱 SQLite DB에도 저장합니다.

    title, date, start_time은 필수입니다. date는 YYYY-MM-DD, 시간은 HH:MM 형식을 사용합니다.
    현재 대화의 임시 일정 생성과 SQLite 저장을 한 번에 수행하므로,
    이 tool로 만든 일정에 save_structured_request를 다시 호출하지 않습니다.
    created_schedule(생성된 일정), structured_request(저장 입력), sqlite_save(저장 결과)를
    담은 JSON 문자열을 반환합니다.
    """

    raw = week01_personal_create_schedule.invoke({
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "attendees": attendees,
    })

    created = json.loads(raw)
    schedule = created.get("created_schedule") or {}
    request = structured_request_from_week01_schedule(schedule)
    
    sqlite_save = save_structured_request_payload(request)
    return json_payload({
        **created,
        "structured_request": request.model_dump(),
        "sqlite_save": sqlite_save,
    })


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
    """Week 2 구조화 결과를 SQLite에 저장하는 Week 3 핵심 tool입니다.

    extract_schedule_request가 반환한 structured_request의 필드 값을 그대로 인자로
    전달합니다. 값을 요약하거나 임의로 바꾸지 않습니다.
    kind에 따라 일정/할 일/알림 테이블에 정규화 저장되고, 개인/그룹 일정은
    외부 공유 저장소에도 복사됩니다.
    request_id와 saved_rows(저장된 테이블/ID 목록)를 담은 JSON 문자열을 반환합니다.
    """

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
        key: value
        for key, value in payload.items()
        if value is not None
    }

    saved = _store().save_structured_request(payload)
    return json_payload(tool_result("save_structured_request", **saved))


@tool(args_schema=SavedRequestListInput)
def list_saved_requests(
    kind: RequestKind | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """SQLite에 저장된 구조화 요청 원본 기록을 조회합니다.

    "지금까지 저장한 요청 보여줘"처럼 요청 이력을 물을 때 사용합니다.
    결과가 없어도 오류가 아니며, rows가 빈 목록인 JSON 문자열을 반환합니다.
    """

    rows = _store().list_saved_requests(
        kind=kind,
        date_from=date_from,
        date_to=date_to,
    )
    return json_payload(tool_result("list_saved_requests", rows=rows))


@tool(args_schema=SavedRequestGetInput)
def get_saved_request(request_id: str) -> str:
    """request_id로 저장된 구조화 요청 하나를 조회합니다.

    list_saved_requests로 얻은 request_id의 상세 내용을 확인할 때 사용합니다.
    해당 ID가 없으면 row가 null인 JSON 문자열을 반환합니다.
    """

    row = _store().get_saved_request(request_id=request_id)
    return json_payload(tool_result("get_saved_request", row=row))


@tool(args_schema=SavedScheduleListInput)
def personal_list_saved_schedules(
    limit: int = 50,
    kind: RequestKind | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """앱 DB에 저장된 일정 목록을 날짜/종류 필터로 반환합니다.

    "내 일정 보여줘" 같은 조회 질문과, 수정/삭제 전에 대상 schedule_id를 확인할 때
    사용합니다. 날짜가 명확하면 date_from/date_to로 범위를 좁힙니다.
    Week 1 personal_list_schedules와 달리 새 대화에서도 유지되는 저장 일정을 조회합니다.
    filters와 schedules를 담은 JSON 문자열을 반환합니다.
    """

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

    return _delete_saved_schedules(
        store=app_store or _store(),
        schedule_ids=schedule_ids,
        date=date,
        title=title,
        start_time=start_time,
        time_unspecified=time_unspecified,
        delete_all=delete_all,
    )


@tool(args_schema=SavedScheduleUpdateInput)
def personal_update_saved_schedule(
    schedule_id: str,
    title: str | None = None,
    date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    attendees: list[str] | None = None,
) -> str:
    """앱 DB에 저장된 일정을 수정하고 공유 일정 복사본도 같은 값으로 갱신합니다.

    먼저 personal_list_saved_schedules로 대상 schedule_id를 확인한 뒤 호출합니다.
    바꿀 필드만 전달하고 나머지는 생략합니다.
    schedule_id가 없으면 ok=false를, 성공하면 updated_schedule과 shared_sync를
    담은 JSON 문자열을 반환합니다.
    """

    result = _store().update_schedule(
        schedule_id=schedule_id,
        title=title,
        date=date,
        start_time=start_time,
        end_time=end_time,
        attendees=attendees,
    )

    if result is None:
        return json_payload(tool_result(
            "personal_update_saved_schedule",
            ok=False,
            error=f"schedule_id '{schedule_id}'를 찾을 수 없습니다.",
            schedule_id=schedule_id,
        ))
    else:
        return json_payload(tool_result(
            "personal_update_saved_schedule",
            updated_schedule=result["schedule"],
            shared_sync=result["shared_sync"],
        ))




@tool(args_schema=SavedScheduleDeleteInput)
def personal_delete_saved_schedules(
    schedule_ids: list[str] | None = None,
    date: str | None = None,
    title: str | None = None,
    start_time: str | None = None,
    time_unspecified: bool = False,
    delete_all: bool = False,
) -> str:
    """일정 ID 목록이나 날짜/제목/시간 필터로 저장 일정을 삭제합니다.

    먼저 personal_list_saved_schedules로 후보를 확인한 뒤 호출합니다.
    조건 없이 호출하면 ok=false로 거부됩니다. delete_all=True는 사용자가
    전체 삭제를 명확히 요청했을 때만 사용합니다.
    deleted_count, filters, deleted를 담은 JSON 문자열을 반환합니다.
    """

    return json_payload(_delete_saved_schedules(
        store=_store(),
        schedule_ids=schedule_ids,
        date=date,
        title=title,
        start_time=start_time,
        time_unspecified=time_unspecified,
        delete_all=delete_all,
    ))



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
        "Week 2의 '저장하지 않는다' 제한은 Week 3에서 해제된다. 구조화 결과는 save_structured_request로 SQLite에 저장한다.",
        SQLITE_MEMORY_PROMPT,
        WEEK03_TOOL_CALL_PROMPT,
        f"오늘 날짜는 {current_app_date_iso()}이다. ",
        """[일정 저장 전 확인 절차]
        일정을 저장할 때는 아래 순서를 반드시 따른다.
        1. 시간 확정: '10시'처럼 오전/오후가 명시되지 않은 시간은 반드시 모호한 시간으로 취급한다.
        '아침', '저녁', '퇴근 후'처럼 사용자가 요청 문장에 쓴 표현만 확정 근거가 된다.
        기존에 같은 시간대 일정이 있다는 사실이나 일반적인 관례는 확정 근거가 아니다.
        모호하면 어떤 tool도 호출하기 전에 먼저 질문한다.
        예: 사용자 "내일 10시 엄마랑 약속" → tool 호출 없이 "오전 10시인가요, 오후 10시인가요?"라고 먼저 묻는다
        2. 겹침 조회: personal_list_saved_schedules를 date_from/date_to에 같은 날짜로 지정해
        그 날짜의 저장된 일정을 조회한다. 저장 여부를 묻는 응답도 이 조회를 마친 뒤에만 한다.
        3. 저장 결정: 같은 날짜의 같은 시작 시간에 일정이 없으면 바로 저장한다.
        이미 일정이 있으면 저장하지 않고, 겹치는 일정의 제목과 시간을 알리며 진행 여부를 확인한다.
        예: "내일 10:00에는 이미 '개인 코칭' 일정이 있습니다. 그래도 저장할까요, 아니면 다른 시간으로 잡을까요?"
        겹침 여부를 알리지 않은 채 '저장할까요?'라고만 묻지 않는다.
        사용자가 그래도 저장하겠다고 확인하면 그때 저장한다.
        """,
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
