from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from fixed.app_store import AppSQLiteStore
from fixed.config import CONFIG
from fixed.external_mcp import call_external_tool_payload
from fixed.external_people_store import (
    external_schedule_summary,
    normalize_external_member_names,
    normalize_external_schedule_date_bounds,
)
from fixed.llm import chat_model
from fixed.mcp_client import (
    call_local_mcp_tool,
    call_local_mcp_tool_sync,
    load_local_mcp_tools,
    load_local_mcp_tools_sync,
)
from fixed.runtime_clock import current_app_date_iso
from fixed.session_scope import DEFAULT_SESSION_SCOPE, current_session_scope
from student_parts.week01_wake_up_nana import PERSONAL_SCHEDULES, join_system_prompt
from student_parts.week02_structure_natural_language_requests import StructuredRequest
from student_parts.week04_retrieve_nanas_memory import week04_prompt_parts, week04_tools


_WEEK05_AGENT: Any | None = None


call_mcp_tool = call_local_mcp_tool
call_mcp_tool_sync = call_local_mcp_tool_sync
load_langchain_mcp_tools = load_local_mcp_tools
load_langchain_mcp_tools_sync = load_local_mcp_tools_sync


def _schedule_scope(schedule: dict[str, Any]) -> str:
    return str(schedule.get("session_id") or DEFAULT_SESSION_SCOPE)


def _personal_schedules_for_current_scope() -> list[dict[str, Any]]:
    """SQLite 저장 일정과 현재 대화의 임시 일정만 group 조율 후보로 사용합니다."""

    stored = AppSQLiteStore(CONFIG.app_db_path).list_schedules(
        kind="personal_schedule", limit=200
    )

    stored_ids = {
        schedule.get("schedule_id") or schedule.get("id")
        for schedule in stored
    }

    session_id = current_session_scope()
    merged = list(stored)
    for schedule in PERSONAL_SCHEDULES:
        if _schedule_scope(schedule) != session_id:
            continue
        if (schedule.get("schedule_id") or schedule.get("id")) in stored_ids:
            continue
        merged.append(schedule)
    return merged


def json_payload(payload: dict[str, Any]) -> str:
    """도구 반환용 dict를 한글이 깨지지 않는 JSON 문자열로 변환합니다."""

    return json.dumps(payload, ensure_ascii=False)


class SearchPreviousConversationsInput(BaseModel):
    """외부 이전 대화 검색 입력입니다."""

    query: str = Field(
        description="이전 대화를 찾기 위한 핵심 검색어. LLM이 직접 고른 짧은 명사나 구를 넣습니다. 조사·불용어는 빼고 핵심 키워드만 넣습니다."
    )
    member_names: list[str] | None = Field(
        default=None,
        description="검색 대상 외부 멤버 이름 목록. 특정 멤버만 찾을 때 지정하고, 모든 멤버를 검색하려면 생략합니다.",
    )
    limit: int = Field(default=5, ge=1, le=50, description="반환할 최대 대화 메시지 수(1~50).")


class LoadConversationMessagesInput(BaseModel):
    """외부 대화 메시지 조회 입력입니다."""

    conversation_id: str = Field(
        description="메시지를 불러올 이전 대화의 고유 ID. search_previous_conversations 결과의 conversation_id 값을 사용합니다."
    )


class ExtractSchedulesFromHistoryInput(BaseModel):
    """외부 멤버 일정 추출 입력입니다."""

    member_names: list[str] = Field(description="일정(바쁜 시간)을 추출할 외부 멤버 이름 목록.")
    date_from: str = Field(description="조회 시작 날짜(YYYY-MM-DD). 이 날짜 이후의 일정만 추출합니다.")
    date_to: str = Field(description="조회 종료 날짜(YYYY-MM-DD). 이 날짜 이전의 일정만 추출합니다.")


class CreateSharedScheduleInput(BaseModel):
    """공유 일정 생성 입력입니다."""

    member_name: str = Field(description="공유 일정 주인의 이름. 내 일정이면 '나'를 사용합니다.")
    title: str = Field(description="일정 제목.")
    date: str = Field(description="일정 날짜(YYYY-MM-DD).")
    start_time: str = Field(description="시작 시각(HH:MM). 시간을 모르면 '미정'을 넣습니다.")
    end_time: str = Field(default="미정", description="종료 시각(HH:MM). 모르면 '미정'으로 둡니다.")
    notes: str | None = Field(default=None, description="일정에 대한 추가 메모. 없으면 생략합니다.")
    source_conversation_id: str | None = Field(
        default=None,
        description="이 일정을 만든 원본 대화/요청 ID. 나중에 같은 복사본을 찾아 수정·삭제할 때 사용합니다.",
    )
    schedule_id: str | None = Field(
        default=None,
        description="갱신할 기존 공유 일정 ID. 새로 만들 때는 생략하면 자동으로 발급됩니다.",
    )


class DeleteSharedScheduleInput(BaseModel):
    """공유 일정 삭제 입력입니다."""

    schedule_id: str | None = Field(default=None, description="삭제할 공유 일정의 ID. schedule_id 또는 source_conversation_id 중 하나는 있어야 합니다.")
    source_conversation_id: str | None = Field(
        default=None,
        description="삭제할 일정의 원본 대화/요청 ID. schedule_id를 모를 때 이 값으로 찾아 삭제합니다.",
    )


class ListSharedSchedulesInput(BaseModel):
    """공유 일정 조회 입력입니다."""

    member_names: list[str] | None = Field(
        default=None,
        description="조회할 멤버 이름 목록. 특정 멤버만 필터할 때 지정하고, 생략하면 기본 공유 일정을 반환합니다.",
    )
    date_from: str | None = Field(default=None, description="조회 시작 날짜(YYYY-MM-DD). 생략하면 시작 제한이 없습니다.")
    date_to: str | None = Field(default=None, description="조회 종료 날짜(YYYY-MM-DD). 생략하면 종료 제한이 없습니다.")
    source_conversation_id: str | None = Field(
        default=None,
        description="특정 원본 대화/요청에서 만든 공유 일정만 필터할 때 사용합니다.",
    )
    limit: int = Field(default=50, ge=1, le=200, description="반환할 최대 일정 수(1~200).")


class CollectMemberSchedulesInput(BaseModel):
    """내 일정과 외부 멤버 busy-time 수집 입력입니다."""

    member_names: list[str] = Field(
        description="busy-time을 모을 외부 멤버 이름 목록. 내 일정(\"나\")은 자동으로 함께 포함됩니다."
    )
    date_from: str = Field(description="조회 시작 날짜(YYYY-MM-DD).")
    date_to: str = Field(description="조회 종료 날짜(YYYY-MM-DD).")


def _structured_request_from_schedule_row(row: dict[str, Any]) -> StructuredRequest:
    """앱 일정 row를 Week 2 StructuredRequest 기준으로 읽습니다."""

    return StructuredRequest(
        kind="personal_schedule",
        title=row.get("title"),
        date=row.get("date"),
        start_time=row.get("start_time"),
        end_time=row.get("end_time"),
        members=row.get("attendees") or row.get("members") or [],
        original_text=str(row.get("title") or ""),
    )


def _collect_member_schedules(
    *,
    member_names: list[str],
    date_from: str,
    date_to: str,
    personal_schedules: list[dict[str, Any]],
) -> dict[str, Any]:
    """내 일정과 외부 멤버 일정을 같은 row 구조로 합칩니다."""

    normalized_members = normalize_external_member_names(member_names)
    normalized_from, normalized_to = normalize_external_schedule_date_bounds(
        member_names, date_from, date_to
    )

    rows: list[dict[str, Any]] = []

    for schedule in personal_schedules:
        request = _structured_request_from_schedule_row(schedule)
        if request.date and normalized_from and request.date < normalized_from:
            continue
        if request.date and normalized_to and request.date > normalized_to:
            continue
        rows.append(
            {
                "member_name": "나",
                "title": request.title,
                "date": request.date,
                "start_time": request.start_time,
                "end_time": request.end_time,
                "notes": None,
            }
        )

    payload = call_external_tool_payload(
        "extract_schedules_from_history",
        {
            "member_names": normalized_members,
            "date_from": normalized_from,
            "date_to": normalized_to,
        },
    )
    rows.extend(payload.get("rows", []))

    return {
        "ok": True,
        "tool_name": "collect_member_schedules",
        "rows": rows,
        "schedule_summary": external_schedule_summary(rows),
    }



@tool(args_schema=SearchPreviousConversationsInput)
def search_previous_conversations(
    query: str,
    member_names: list[str] | None = None,
    limit: int = 5,
) -> str:
    """외부 팀원(철수, 영희 등)이 과거에 남긴 대화 기록을 검색합니다.

    앱 안에 저장된 내 대화가 아니라 외부 팀원의 이전 대화를 찾을 때 사용합니다.
    (내 앱 대화 검색은 search_conversation_messages를 씁니다.)
    query에는 LLM이 직접 고른 짧은 핵심 명사나 구를 넣고, member_names로 특정 팀원만
    좁힐 수 있습니다. 특정 대화의 전체 내용을 보려면 반환된 conversation_id로
    load_conversation_messages를 이어서 호출합니다.
    ok와 rows(conversation_id/member_name/title/content 포함)를 담은 JSON 문자열을 반환합니다.
    """

    return call_mcp_tool_sync(
        "search_previous_conversations",
        {
            "query": query,
            "member_names": member_names,
            "limit": limit,
        },
    )


@tool(args_schema=LoadConversationMessagesInput)
def load_conversation_messages(conversation_id: str) -> str:
    """특정 외부 대화 하나의 전체 메시지를 시간순으로 불러옵니다.

    먼저 search_previous_conversations로 conversation_id를 확보한 뒤에 사용합니다.
    sender/content/created_at 순서가 그대로 보존된 rows를 반환하므로 대화 맥락을 읽을 때 씁니다.
    ok와 rows를 담은 JSON 문자열을 반환합니다.
    """

    return json_payload(
        call_external_tool_payload(
            "load_conversation_messages",
            {"conversation_id": conversation_id},
        )
    )


@tool(args_schema=ExtractSchedulesFromHistoryInput)
def extract_schedules_from_history(member_names: list[str], date_from: str, date_to: str) -> str:
    """외부 팀원들이 언제 바쁜지(busy time)를 날짜 범위로 조회합니다.

    특정 팀원 몇 명의 일정만 필요할 때 사용합니다. 나와 팀원을 함께 모아
    회의 시간을 잡는 것이 목적이라면 대신 collect_member_schedules를 사용합니다.
    member_name/title/date/start_time/end_time/notes 필드를 가진 rows와
    자연어 schedule_summary를 담은 JSON 문자열을 반환합니다.
    """

    return call_mcp_tool_sync(
        "extract_schedules_from_history",
        {
            "member_names": member_names,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@tool(args_schema=CreateSharedScheduleInput)
def create_shared_schedule(
    member_name: str,
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    notes: str | None = None,
    source_conversation_id: str | None = None,
    schedule_id: str | None = None,
) -> str:
    """외부 공유 일정 저장소에 일정 row를 직접 등록하거나 같은 schedule_id의 일정을 갱신합니다.

    내 개인 일정 저장은 보통 personal_create_schedule을 쓰며, 이 도구는 공유 저장소 row를
    직접 보정해야 할 때만 사용합니다. 나중에 수정·삭제 동기화가 가능하도록
    source_conversation_id나 schedule_id를 보존합니다.
    등록/갱신된 shared_schedule을 담은 JSON 문자열을 반환합니다.
    """

    return call_mcp_tool_sync(
        "create_shared_schedule",
        {
            "member_name": member_name,
            "title": title,
            "date": date,
            "start_time": start_time,
            "end_time": end_time,
            "notes": notes,
            "source_conversation_id": source_conversation_id,
            "schedule_id": schedule_id,
        },
    )


@tool(args_schema=DeleteSharedScheduleInput)
def delete_shared_schedule(
    schedule_id: str | None = None,
    source_conversation_id: str | None = None,
) -> str:
    """외부 공유 일정 저장소에서 schedule_id 또는 source_conversation_id로 일정 row를 삭제합니다.

    두 값 중 최소 하나는 있어야 하며, schedule_id를 모르면 source_conversation_id로 찾아 지웁니다.
    삭제된 row 목록 deleted와 개수 deleted_count를 담은 JSON 문자열을 반환합니다.
    """

    return call_mcp_tool_sync(
        "delete_shared_schedule",
        {
            "schedule_id": schedule_id,
            "source_conversation_id": source_conversation_id,
        },
    )


@tool(args_schema=ListSharedSchedulesInput)
def list_shared_schedules(
    member_names: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    source_conversation_id: str | None = None,
    limit: int = 50,
) -> str:
    """외부 공유 일정 저장소에 등록된 row를 멤버/날짜/source 기준으로 조회합니다.

    공유 저장소 자체의 내용을 확인할 때 사용합니다. 회의 시간을 조율하려고 나와 팀원의
    바쁜 시간을 모으는 것이 목적이라면 대신 collect_member_schedules를 사용합니다.
    필터를 하나도 주지 않으면 실습용 기본 공유 일정을 반환합니다.
    rows와 자연어 schedule_summary를 담은 JSON 문자열을 반환합니다.
    """

    return call_mcp_tool_sync(
        "list_shared_schedules",
        {
            "member_names": member_names,
            "date_from": date_from,
            "date_to": date_to,
            "source_conversation_id": source_conversation_id,
            "limit": limit,
        },
    )


@tool(args_schema=CollectMemberSchedulesInput)
def collect_member_schedules(member_names: list[str], date_from: str, date_to: str) -> str:
    """회의 시간 조율을 위해 나와 외부 팀원의 일정(바쁜 시간)을 한 번에 모읍니다.

    '나랑 철수 언제 만날까', '팀 회의 시간 잡아줘'처럼 여러 사람의 빈 시간을 찾아야 할 때
    가장 먼저 쓰는 도구입니다. 내 일정("나")은 자동으로 포함되므로 member_names에는
    외부 팀원 이름만 넣습니다. 내 일정(앱 SQLite+현재 대화)과 외부 팀원 busy time을
    member_name/title/date/start_time/end_time/notes로 통일한 rows와
    자연어 schedule_summary를 담은 JSON 문자열을 반환합니다.
    """

    return json_payload(
        _collect_member_schedules(
            member_names=member_names,
            date_from=date_from,
            date_to=date_to,
            personal_schedules=_personal_schedules_for_current_scope(),
        )
    )


def week05_tools() -> list[Any]:
    """4주차까지의 도구에 외부 SQLite/MCP 일정 도구를 누적한 목록입니다."""

    return [
        *week04_tools(),
        search_previous_conversations,
        load_conversation_messages,
        extract_schedules_from_history,
        create_shared_schedule,
        delete_shared_schedule,
        list_shared_schedules,
        collect_member_schedules,
    ]


def week05_system_prompt() -> str:
    """5주차 단일 agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt(week05_prompt_parts())


def week05_prompt_parts() -> list[str]:
    """1~5주차 system prompt 조각을 누적합니다."""

    return [
        *week04_prompt_parts(),
        """이제 너는 외부 팀원들의 이전 대화와 공유 일정에도 접근할 수 있다.
- 내 개인 일정 저장/조회와 개인 참고자료 검색은 기존 주차 도구(personal_*, *_reference 등)를 그대로 쓴다.
- 외부 팀원(철수, 영희, 민준 등)의 과거 대화를 찾을 때는 search_previous_conversations로 검색하고, 특정 대화의 전체 내용이 필요하면 load_conversation_messages로 그 대화의 메시지를 불러온다.
- 외부 팀원이 언제 바쁜지(busy time)는 extract_schedules_from_history로 조회한다.
- '나와 팀원들의 일정을 모아 회의 시간을 잡아줘' 같은 요청은 collect_member_schedules로 내 일정과 외부 멤버 일정을 한 번에 모은 뒤, 그 rows와 schedule_summary를 근거로 답한다.
- 공유 일정 저장소를 직접 확인·등록·삭제할 때만 list_shared_schedules, create_shared_schedule, delete_shared_schedule을 쓴다.
- 도구가 돌려준 일정 데이터를 지어내지 말고 그대로 근거로 삼아 한국어로 답한다.""",
    ]


def build_week05_agent() -> object:
    """Week 1-5 누적 tool 목록을 노출하는 단일 LangChain agent를 만듭니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK05_AGENT
    if _WEEK05_AGENT is None:
        _WEEK05_AGENT = create_agent(
            model=chat_model(),
            tools=week05_tools(),
            system_prompt=week05_system_prompt(),
        )
    return _WEEK05_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week05_agent()
