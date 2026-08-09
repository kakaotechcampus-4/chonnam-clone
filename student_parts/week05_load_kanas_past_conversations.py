from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from fixed.app_store import AppSQLiteStore
from fixed.config import CONFIG
from fixed.external_mcp import call_external_tool_payload
from fixed.external_people_store import (
    PERSONAL_SHARED_MEMBER_NAME,
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
# 공유 일정 저장소가 한 번에 200건까지만 돌려준다. 아래에서는 "받은 건수가 이 값과 같으면
# 뒤에 더 있다"고 보고 누락 경고를 띄우는데, 이 값을 200보다 크게 잡으면 그 조건이 영원히
# 참이 되지 않는다. 그러면 실제로 명단이 잘려도 경고 없이 넘어간다.
_ROSTER_LIMIT = 200
EXTERNAL_LOOKUP_FAILURE_NOTICE = "외부 일정 조회에 실패해, 외부 구성원의 일정이 빠진 채로 계산됐습니다."


# [5주차 수강생 구현 가이드]
#
# 목표
#   외부 SQLite/MCP 서버에 있는 Kana의 이전 대화와 공유 일정을 LangChain agent가 사용할 수 있게 감쌉니다.
#   학생이 직접 SQL을 작성하는 주차가 아니라, MCP tool을 호출하고 그 결과를 agent용 JSON으로 전달하는
#   wrapper tool을 만드는 주차입니다.
#
# 과제 구성
#   - 메인과제: 외부 SQLite/MCP 서버의 이전 대화를 검색·로드하고 그 대화에서 일정을 추출하는
#     MCP wrapper 세로 슬라이스에 더해, 공유 일정 조회(list_shared_schedules)와
#     내 일정·외부 멤버 busy-time을 한 rows로 합치는 collect_member_schedules까지 완성합니다.
#     이 두 tool은 Week 6 Kana 하위 agent가 그대로 재사용하는 연결 지점이라 메인과제입니다.
#   - 추가 과제: 공유 일정 저장소에 row를 직접 등록·삭제하는 create_shared_schedule/delete_shared_schedule
#     wrapper를 확장합니다. 구현하지 않으려면 week05_tools() 목록에서 이 두 tool을 빼면 됩니다.
#
# 구현 위치와 사용할 코드
#   - 이 파일(student_parts/week05_load_kanas_past_conversations.py)의 @tool wrapper 함수들을 구현합니다.
#   - 실제 외부 SQLite/MCP tool 구현은 mcp_server/sqlite_mcp_server.py에 있으며, 학생은 이 파일을 직접 수정하지 않습니다.
#   - MCP 호출은 fixed/mcp_client.py의 call_local_mcp_tool_sync를 이 파일에서 별칭으로 둔
#     call_mcp_tool_sync(tool_name, args)를 사용합니다.
#   - load_conversation_messages는 fixed/external_mcp.py의 call_external_tool_payload(...)를 사용해
#     외부 tool payload를 dict로 받은 뒤 json_payload()로 감쌉니다.
#   - 멤버 이름/날짜 정규화와 요약은 fixed/external_people_store.py의
#     normalize_external_member_names(), normalize_external_schedule_date_bounds(),
#     external_schedule_summary()를 사용합니다.
#   - 내 일정 수집은 _personal_schedules_for_current_scope()에서 처리합니다. 이 helper는
#     fixed/app_store.py의 AppSQLiteStore(CONFIG.app_db_path).list_schedules(...)와
#     student_parts/week01_wake_up_nana.py의 PERSONAL_SCHEDULES 중 현재 대화 범위 row를 합칩니다.
#   - Week 3+ AppSQLiteStore는 개인/그룹 일정을 저장할 때 공유 일정 저장소에 자동 동기화할 수 있습니다.
#     list_shared_schedules wrapper(메인)는 공유 저장소 row를 직접 확인할 때,
#     create/delete_shared_schedule wrapper(추가)는 row를 직접 등록/삭제해 보정할 때 사용합니다.
#   - week05_tools()는 student_parts/week04_retrieve_nanas_memory.py의 week04_tools() 위에
#     Week 5 MCP wrapper tool들을 누적해 Week 5 단일 agent에 공개합니다.
#     추가 과제(create/delete_shared_schedule)를 구현하지 않으려면 week05_tools() 목록에서 해당 tool을 빼면 됩니다.
#
# 메인과제 구현 대상
#   1. search_previous_conversations
#      - query, member_names, limit를 받습니다.
#      - 이 파일의 call_mcp_tool_sync("search_previous_conversations", args)를 호출하고 결과 문자열을 그대로 반환합니다.
#      - 멤버 이름 정규화는 외부 SQLite store/MCP 경계에서 한 번만 처리하므로 wrapper에서 중복 변환하지 않습니다.
#
#   2. load_conversation_messages
#      - conversation_id로 외부 SQLite/MCP helper에서 이전 대화 메시지를 조회합니다.
#      - call_external_tool_payload("load_conversation_messages", {"conversation_id": conversation_id})를 사용합니다.
#      - 대화 메시지의 sender/content/created_at 순서가 보존되도록 결과를 가공하지 않습니다.
#
#   3. extract_schedules_from_history
#      - member_names, date_from, date_to를 받습니다.
#      - call_mcp_tool_sync("extract_schedules_from_history", args)를 호출합니다.
#      - 날짜 형식 정리는 외부 SQLite store/MCP 경계에서 한 번만 처리합니다.
#      - 결과 rows는 member_name/title/date/start_time/end_time/notes 필드를 유지해야 합니다.
#
#   4. list_shared_schedules
#      - call_mcp_tool_sync("list_shared_schedules", args)를 호출해 공유 일정 저장소 row를 조회합니다.
#      - 공유 저장소 자체를 확인할 때는 "나"를 포함한 등록 row를 조회합니다.
#      - 필터 없이 호출하면 외부 실습용 기본 공유 일정 row가 우선 반환될 수 있습니다.
#      - Week 6 Kana 하위 agent가 공유 저장소 row 조회에 그대로 사용하는 tool입니다.
#
#   5. collect_member_schedules
#      - 3주차 이후 저장된 내 일정은 앱 SQLite에서 읽고, 현재 대화의 임시 일정만 추가로 합칩니다.
#      - 외부 멤버 일정은 call_mcp_tool_sync("extract_schedules_from_history", args) 결과를 이 tool 안에서 읽습니다.
#      - 두 출처를 member_name/title/date/start_time/end_time/notes가 있는 rows 배열로 직접 합칩니다.
#      - schedule_summary도 함께 반환해 LLM이 바쁜 시간을 자연어로 설명할 수 있게 합니다.
#      - PERSONAL_SCHEDULES는 현재 대화 범위의 아직 DB에 없는 임시 일정만 합치고, SQLite에 이미 저장된 일정과 중복하지 않습니다.
#      - Week 6 추가 과제(find_common_available_slots)가 이 tool의 rows를 busy_rows 근거로 사용합니다.
#
# 추가 과제 구현 대상 (구현하지 않으려면 week05_tools() 목록에서 해당 tool을 제거)
#   1. create_shared_schedule / delete_shared_schedule
#      - 각각 call_mcp_tool_sync("create_shared_schedule" / "delete_shared_schedule", args)를 호출합니다.
#      - 공유 일정 저장소 row를 생성/삭제할 때 MCP tool 결과를 그대로 전달합니다.
#      - schedule_id 또는 source_conversation_id를 보존해야 나중에 수정/삭제 동기화가 가능합니다.
#
# 책임 경계
#   mcp_server/sqlite_mcp_server.py의 @mcp.tool 구현은 학생 구현 대상이 아닙니다.
#   이 파일의 wrapper tool은 직접 SQL이나 중복 정규화 helper를 두지 않고 store/MCP helper의 결과 JSON을 전달합니다.
#   week05_tools()는 Week 1-4 도구에 외부 SQLite/MCP 일정 도구를 누적합니다.
#   외부 멤버 busy-time 조회와 공유 저장소 row 조회는 Week 5 범위지만, 여러 사람의 최종 회의 시간 선택은 Week 6 범위입니다.
#
# 검증 방법
#   - 메인과제: ./run.sh --week5에서 외부 팀원 일정 조회 요청을 입력하고, trace에서
#     search_previous_conversations, load_conversation_messages, extract_schedules_from_history 중
#     어떤 tool이 어떤 순서로 호출됐는지 확인합니다.
#     collect_member_schedules 결과 rows에 "나"와 외부 멤버 일정이 같은 구조로 들어 있고,
#     list_shared_schedules 결과에 rows와 schedule_summary가 유지되는지 확인합니다.
#   - 추가 과제: create_shared_schedule로 등록한 row가 list_shared_schedules 조회에 나타나고
#     delete_shared_schedule로 삭제되는지 확인합니다.
#
# 함수별 동작 설명 ([메인]/[추가]/[공통]은 각 함수가 속한 과제 티어입니다)
#   - [메인] _schedule_scope(schedule)
#     Week 1 임시 일정이 어느 대화 범위에 속하는지 읽습니다. session_id가 없으면 기본 scope로 처리합니다.
#
#   - [메인] _personal_schedules_for_current_scope()
#     Week 3 이후 SQLite에 저장된 내 일정과 현재 대화에만 남아 있는 Week 1 임시 일정을 합칩니다.
#     이미 SQLite에 저장된 일정과 임시 일정이 중복되지 않도록 schedule_id/id를 기준으로 한 번 걸러냅니다.
#
#   - [공통] json_payload(payload)
#     외부 MCP 결과나 내부 helper 결과 dict를 한글이 보존되는 JSON 문자열로 바꿉니다.
#
#   - [메인] SearchPreviousConversationsInput / LoadConversationMessagesInput / ExtractSchedulesFromHistoryInput
#     외부 이전 대화 검색, 대화 메시지 로드, 외부 대화에서 일정 추출 tool의 입력 스키마입니다.
#
#   - [메인] ListSharedSchedulesInput / CollectMemberSchedulesInput
#     공유 일정 저장소 row 조회와, 내 일정·외부 멤버 busy-time을 같은 rows 배열로 합치는 tool의 입력 스키마입니다.
#
#   - [추가] CreateSharedScheduleInput / DeleteSharedScheduleInput
#     외부 공유 일정 저장소에 row를 생성, 삭제할 때 쓰는 입력 스키마입니다.
#
#   - [메인] _structured_request_from_schedule_row(row)
#     SQLite schedule row나 Week 1 임시 schedule row를 Week 2 StructuredRequest 모양으로 읽습니다.
#     뒤에서 내 일정 row를 외부 멤버 row와 같은 구조로 맞출 때 사용합니다.
#
#   - [메인] _collect_member_schedules(...)
#     내 일정과 외부 멤버 일정을 같은 member_name/title/date/start_time/end_time/notes row 구조로 합칩니다.
#     외부 멤버 이름과 날짜 범위는 fixed/external_people_store.py helper로 정규화합니다.
#
#   - [메인] search_previous_conversations(...)
#     외부 SQLite/MCP 서버에 저장된 과거 대화를 검색합니다. wrapper는 query/member_names/limit를 넘기고 결과 문자열을 그대로 반환합니다.
#
#   - [메인] load_conversation_messages(conversation_id)
#     검색으로 찾은 특정 외부 대화의 전체 메시지를 불러옵니다. sender/content/created_at 순서를 보존합니다.
#
#   - [메인] extract_schedules_from_history(...)
#     외부 멤버의 이전 대화에서 일정 또는 바쁜 시간 row를 추출합니다.
#
#   - [메인] list_shared_schedules(...)
#     공유 일정 저장소 row를 조회하는 MCP wrapper입니다. Week 6 Kana 하위 agent도 그대로 사용합니다.
#
#   - [메인] collect_member_schedules(...)
#     내 일정과 외부 멤버 busy-time을 한 번에 모으는 Week 5 핵심 tool입니다.
#     Week 6의 공통 가능 시간 결정 tool(추가 과제)이 이 rows를 busy_rows 근거로 사용합니다.
#
#   - [추가] create_shared_schedule(...) / delete_shared_schedule(...)
#     공유 일정 저장소에 row를 등록/삭제하는 MCP wrapper입니다. source_conversation_id와 schedule_id를 보존해 동기화 근거로 씁니다.
#
#   - [공통] week05_tools()
#     Week 4까지의 tool에 외부 대화/MCP/공유 일정 tool을 누적합니다.
#
#   - [공통] week05_system_prompt() / week05_prompt_parts()
#     개인 저장/RAG는 이전 주차 도구로, 외부 멤버 대화와 일정은 MCP wrapper로 처리하도록 agent 역할을 설명합니다.
#
#   - [공통] build_week05_agent() / build_week_agent()
#     Week 1~5 tool을 가진 agent를 한 번만 만들고 재사용합니다.


call_mcp_tool = call_local_mcp_tool
call_mcp_tool_sync = call_local_mcp_tool_sync
load_langchain_mcp_tools = load_local_mcp_tools
load_langchain_mcp_tools_sync = load_local_mcp_tools_sync


def _schedule_scope(schedule: dict[str, Any]) -> str:
    return str(schedule.get("session_id") or DEFAULT_SESSION_SCOPE)


def _personal_schedules_for_current_scope() -> list[dict[str, Any]]:
    """SQLite 저장 일정과 현재 대화의 임시 일정만 group 조율 후보로 사용합니다."""

    # 기본 limit 12로는 조율 대상 일정이 잘린다. SQL 날짜 필터는 일부러 안 쓴다 — 아래 임시분이
    # SQL을 안 타 날짜 의미가 두 층이 되므로, 날짜 거르기는 _collect_member_schedules가 맡는다.
    stored = AppSQLiteStore(CONFIG.app_db_path).list_schedules(limit=200)
    # 저장된 일정의 schedule_id와 임시 일정의 id는 같은 값일 수 있다. week03에서 저장할 때
    # 임시 id를 그대로 물려주기 때문이다(fixed/app_store.py의 save_structured_request).
    # 그래서 아래에서 이 id 집합으로 임시분 중 이미 저장된 것을 걸러 중복을 막는다.
    stored_ids = {str(row["schedule_id"]) for row in stored if row.get("schedule_id")}
    scope = current_session_scope()
    pending = [
        schedule
        for schedule in PERSONAL_SCHEDULES
        if _schedule_scope(schedule) == scope
        and str(schedule.get("id") or "") not in stored_ids
    ]
    return [*stored, *pending]


def json_payload(payload: dict[str, Any]) -> str:
    """도구 반환용 dict를 한글이 깨지지 않는 JSON 문자열로 변환합니다."""

    return json.dumps(payload, ensure_ascii=False)


class SearchPreviousConversationsInput(BaseModel):
    """외부 이전 대화 검색 입력입니다."""

    query: str
    member_names: list[str] | None = None
    limit: int = Field(default=5, ge=1, le=50)


class LoadConversationMessagesInput(BaseModel):
    """외부 대화 메시지 조회 입력입니다."""

    conversation_id: str


class ExtractSchedulesFromHistoryInput(BaseModel):
    """외부 멤버 일정 추출 입력입니다."""

    member_names: list[str]
    date_from: str
    date_to: str


class CreateSharedScheduleInput(BaseModel):
    """공유 일정 생성 입력입니다."""

    member_name: str
    title: str
    date: str
    start_time: str
    end_time: str = "미정"
    notes: str | None = None
    source_conversation_id: str | None = None
    schedule_id: str | None = None


class DeleteSharedScheduleInput(BaseModel):
    """공유 일정 삭제 입력입니다."""

    schedule_id: str | None = None
    source_conversation_id: str | None = None


class ListSharedSchedulesInput(BaseModel):
    """공유 일정 조회 입력입니다."""

    member_names: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None
    source_conversation_id: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class CollectMemberSchedulesInput(BaseModel):
    """내 일정과 외부 멤버 busy-time 수집 입력입니다."""

    # 필수로 두면 LLM이 "전원"을 말할 자리가 없어 ["나"] 같은 값으로 슬롯을 채운다.
    member_names: list[str] | None = None
    date_from: str
    date_to: str


def _structured_request_from_schedule_row(row: dict[str, Any]) -> StructuredRequest:
    """앱 일정 row를 Week 2 StructuredRequest 기준으로 읽습니다.

    SQLite row는 `request_kind`로 개인/그룹을 구분합니다. Week 1 임시 일정 row에는
    이 값이 없으므로 개인 일정으로 봅니다.
    """

    return StructuredRequest(
        kind=(
            "group_schedule"
            if row.get("request_kind") == "group_schedule"
            else "personal_schedule"
        ),
        title=row.get("title"),
        date=row.get("date"),
        start_time=row.get("start_time"),
        end_time=row.get("end_time"),
        members=row.get("attendees") or row.get("members") or [],
        original_text=str(row.get("title") or ""),
    )


def _my_schedule_notes(request: StructuredRequest) -> str:
    """내 일정 row가 개인 일정인지, 참석자가 있는 그룹 일정인지 설명합니다."""

    if request.kind != "group_schedule":
        return "Nana 개인 일정"
    members = [str(member).strip() for member in (request.members or []) if str(member).strip()]
    return f"Nana 그룹 일정 · 참석자: {', '.join(members)}" if members else "Nana 그룹 일정"


def unique_member_names(member_names: list[Any] | None) -> list[str]:
    """이름을 정규화한 뒤 중복을 없애고, 처음 나온 순서를 지킵니다.

    "나"는 빼지 않습니다. "나"까지 뺀 목록이 필요하면 external_member_names를 씁니다.
    같은 사람이 두 번 들어오면 그 사람 일정을 두 번 세게 되므로 여기서 걸러 둡니다.
    """

    return list(dict.fromkeys(normalize_external_member_names(member_names)))


def external_member_names(member_names: list[Any] | None) -> list[str]:
    """외부 멤버 이름만 남깁니다. "나"는 사용자 자신이라 외부 멤버가 아니므로 뺍니다.

    외부 저장소를 조회할 이름 목록을 만들 때 씁니다. "나"의 일정은 외부가 아니라
    앱 DB에서 따로 읽으므로, 이 목록에 "나"가 섞이면 같은 일정을 두 번 세게 됩니다.
    """

    return [
        name
        for name in unique_member_names(member_names)
        if name != PERSONAL_SHARED_MEMBER_NAME
    ]


def _external_member_roster(date_from: str, date_to: str) -> tuple[list[str], bool]:
    """조회 구간에 일정이 있는 외부 멤버 이름을 등장 순서대로 모읍니다."""

    # 여기서는 이름 명단만 얻는다. 일정 자체는 extract_schedules_from_history가 계속 맡는다
    # (이 파일 맨 위 구현 가이드 "외부 멤버 일정은 ... extract_schedules_from_history 결과를
    #  이 tool 안에서 읽습니다").
    # 저장소는 날짜가 이른 것부터 줄 세운 뒤 앞에서 _ROSTER_LIMIT건만 잘라 준다. 전체가 몇 건이었는지는
    # 안 알려주므로, 꽉 채워 오면 뒤가 더 있다고 보고 구간을 반으로 쪼개 다시 부른다. 그래야 뒤쪽
    # 날짜에만 나오는 사람이 명단에서 빠지지 않는다.
    # 하루까지 쪼갰는데도 꽉 차면 그 하루는 정말 다 못 담은 것이므로, 두 번째 반환값으로 알린다.
    def _lookup_once(start: str, end: str) -> tuple[list[dict[str, Any]], bool]:
        payload = json.loads(
            call_mcp_tool_sync(
                "list_shared_schedules",
                {"date_from": start, "date_to": end, "limit": _ROSTER_LIMIT},
            )
        )
        rows = payload.get("rows") or []
        return rows, len(rows) >= _ROSTER_LIMIT

    def _lookup_range(start: date, end: date) -> tuple[list[dict[str, Any]], bool]:
        if start > end:
            return [], False

        rows, limit_reached = _lookup_once(start.isoformat(), end.isoformat())
        if not limit_reached or start == end:
            return rows, limit_reached

        midpoint = start + (end - start) // 2
        left_rows, left_limit_reached = _lookup_range(start, midpoint)
        right_rows, right_limit_reached = _lookup_range(
            midpoint + timedelta(days=1), end
        )
        return [*left_rows, *right_rows], left_limit_reached or right_limit_reached

    try:
        start_date = date.fromisoformat(date_from)
        end_date = date.fromisoformat(date_to)
    except (TypeError, ValueError):
        # 날짜를 못 읽으면 구간을 쪼갤 수 없다. 쪼개기 이전처럼 받은 문자열 그대로 한 번만 조회한다.
        # 여기서 빈 명단([])을 돌려주는 쪽이 안전해 보이지만 그러면 안 된다. 빈 명단은 "전원"이
        # 아니라 "아무도 없음"으로 읽히고, 뒤이은 일정 조회(fixed/external_people_store.py의
        # extract_schedules_from_history)는 찾을 이름이 없다며 곧바로 빈 목록을 돌려준다.
        # 그러면 오류 메시지 하나 없이 "일정이 하나도 없다"는 답이 사용자에게 나가 버린다.
        rows, limit_reached = _lookup_once(date_from, date_to)
    else:
        rows, limit_reached = _lookup_range(start_date, end_date)
    return external_member_names([row.get("member_name") for row in rows]), limit_reached


def _collect_member_schedules(
    *,
    member_names: list[str] | None,
    date_from: str,
    date_to: str,
    personal_schedules: list[dict[str, Any]],
) -> dict[str, Any]:
    """내 일정과 외부 멤버 일정을 같은 row 구조로 합칩니다."""

    # agent가 "2026-07-07T00:00:00"을 넘기면 아래 내 일정 필터에서 그날이 통째로 잘린다.
    normalized_from, normalized_to = normalize_external_schedule_date_bounds(
        member_names, date_from, date_to
    )
    # 아래 try는 예외 종류를 가리지 않고 전부 "외부 조회 실패" 하나로 묶는다.
    # 외부 조회는 MCP 서버를 별도 프로세스로 띄워 주고받는 일이라 실패 모양이 여럿이다 —
    # 프로세스를 못 띄우는 경우, 응답이 JSON이 아닌 경우, JSON이 dict가 아니라 .get이 터지는 경우.
    # 종류를 좁혀 잡으면 미처 예상 못 한 실패 하나가 그대로 올라와 채팅 턴 전체를 죽인다.
    # 외부 멤버 명단 조회를 이 try 안에 같이 둔 것도 같은 이유다.
    external_members: list[str] = []
    roster_payload: dict[str, Any] | None = None
    try:
        if not member_names:
            # 비어 있으면 전원. 지목했다가 필터로 비는 경우(["나"])는 아래로 가서 안 넓어진다.
            external_members, limit_reached = _external_member_roster(normalized_from, normalized_to)
            # limit_reached는 이름을 안 준 이 경우에만 생긴다. 아래에서 읽을 때 같은 조건을 다시 본다.
        else:
            # 정규화 뒤에 거른다 — 공백·별칭으로 "나"가 되는 이름을 놓치면 내 일정이 두 번 온다.
            external_members = external_member_names(member_names)
        external_payload = json.loads(
            call_mcp_tool_sync(
                "extract_schedules_from_history",
                {
                    "member_names": external_members,
                    "date_from": normalized_from,
                    "date_to": normalized_to,
                },
            )
        )
        # 읽기까지 try 안이다. dict가 아닌 JSON이 오면 .get이 AttributeError를 낸다.
        # or []인 것은 키가 null로 실려 오면 .get이 [] 대신 None을 주기 때문이다.
        external_ok = external_payload.get("ok", False)
        external_rows = external_payload.get("rows") or []
        if not member_names and external_ok:
            roster_payload = {
                "limit_reached": limit_reached,
                "limit": _ROSTER_LIMIT,
            }
            if limit_reached:
                # "하루"라고 쓰지 않는다. 날짜를 못 읽어 구간을 못 쪼갠 경우(_external_member_roster의
                # except 갈래)에도 이 경고가 나가는데, 그때는 하루가 아니라 받은 구간 전체다.
                roster_payload["notice"] = (
                    f"명단 조회가 {_ROSTER_LIMIT}건 상한에 닿아, 일부 구성원이 이번 조회 전체에서 빠졌을 수 있습니다."
                )
    except Exception:
        external_ok = False
        external_rows = []

    my_rows: list[dict[str, Any]] = []
    for row in personal_schedules:
        request = _structured_request_from_schedule_row(row)
        if not request.date or not request.start_time:
            continue
        if normalized_from and request.date < normalized_from:
            continue
        if normalized_to and request.date > normalized_to:
            continue
        my_rows.append(
            {
                "member_name": "나",
                "title": request.title or "제목 없음",
                "date": request.date,
                "start_time": request.start_time,
                "end_time": request.end_time or "미정",
                "notes": _my_schedule_notes(request),
            }
        )

    # 공지 (D)의 _dedupe_schedule_rows는 두지 않는다. 그 중복은 "나"가 외부 조회에 섞여야
    # 생기는데, 이 구현은 조회 전에 "나"를 뺀다 (이름을 준 경우 external_member_names,
    # 전원인 경우 _external_member_roster). 그래서 같은 일정이 두 경로로 들어오지 않는다.
    rows = [*my_rows, *external_rows]
    payload = {
        # 외부 조회가 실패하면 rows에는 내 일정만 남는다. 그런데도 ok=True로 고정해 두면
        # 읽는 쪽은 "전원 일정을 다 모았다"고 믿고 답을 만든다. 그래서 실패를 그대로 싣는다.
        "ok": external_ok,
        "tool_name": "collect_member_schedules",
        # 실제로 MCP에 보낸 값이다. LLM이 보낸 원본은 같은 trace의 tool_call에 이미 있다.
        "filters": {
            "member_names": external_members,
            "date_from": normalized_from,
            "date_to": normalized_to,
        },
        "rows": rows,
        "schedule_summary": external_schedule_summary(rows),
    }
    if roster_payload is not None:
        payload["roster"] = roster_payload
    if not external_ok:
        payload["external_lookup"] = {
            "ok": False,
            "notice": EXTERNAL_LOOKUP_FAILURE_NOTICE,
        }
    return payload


@tool(args_schema=SearchPreviousConversationsInput)
def search_previous_conversations(
    query: str,
    member_names: list[str] | None = None,
    limit: int = 5,
) -> str:
    """외부 SQLite 데이터베이스에 저장된 이전 대화를 검색합니다. query에는 LLM이 고른 짧은 핵심 명사나 구를 넣습니다."""

    return call_mcp_tool_sync(
        "search_previous_conversations",
        {"query": query, "member_names": member_names, "limit": limit},
    )


@tool(args_schema=LoadConversationMessagesInput)
def load_conversation_messages(conversation_id: str) -> str:
    """외부 SQLite 데이터베이스에서 특정 이전 대화의 모든 메시지를 불러옵니다."""

    return json_payload(
        call_external_tool_payload(
            "load_conversation_messages", {"conversation_id": conversation_id}
        )
    )


@tool(args_schema=ExtractSchedulesFromHistoryInput)
def extract_schedules_from_history(member_names: list[str], date_from: str, date_to: str) -> str:
    """외부 SQLite 이전 대화에서 멤버별 일정을 추출합니다."""

    return call_mcp_tool_sync(
        "extract_schedules_from_history",
        {"member_names": member_names, "date_from": date_from, "date_to": date_to},
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
    """외부 MCP 공유 일정 저장소에 일정을 등록하거나 갱신합니다."""

    # 이 파일 맨 위 구현 가이드의 "MCP tool 결과를 그대로 전달합니다"에서 벗어난다.
    # 전달할 payload 자체가 없는 실패다.
    try:
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
    except Exception:
        return json_payload({"ok": False, "tool_name": "create_shared_schedule"})


@tool(args_schema=DeleteSharedScheduleInput)
def delete_shared_schedule(
    schedule_id: str | None = None,
    source_conversation_id: str | None = None,
) -> str:
    """외부 MCP 공유 일정 저장소에서 일정을 삭제합니다."""

    # 이 파일 맨 위 구현 가이드의 "MCP tool 결과를 그대로 전달합니다"에서 벗어난다.
    # 서버는 실제로 지운 건수와 무관하게 ok=true를 싣는데(mcp_server/sqlite_mcp_server.py의
    # delete_shared_schedule), ok는 "요청한 효과가 일어났다"는 뜻이어야 한다.
    try:
        payload = json.loads(
            call_mcp_tool_sync(
                "delete_shared_schedule",
                {"schedule_id": schedule_id, "source_conversation_id": source_conversation_id},
            )
        )
        payload["ok"] = (payload.get("deleted_count") or 0) > 0
    except Exception:
        payload = {"ok": False, "tool_name": "delete_shared_schedule"}
    return json_payload(payload)


@tool(args_schema=ListSharedSchedulesInput)
def list_shared_schedules(
    member_names: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    source_conversation_id: str | None = None,
    limit: int = 50,
) -> str:
    """외부 MCP 공유 일정 저장소에 등록된 일정을 조회합니다. 필터가 없으면 기본 공유 일정을 반환합니다."""

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
def collect_member_schedules(
    *, member_names: list[str] | None = None, date_from: str, date_to: str
) -> str:
    """내 일정과 다른 사람들의 일정을 MCP SQLite 기록에서 모읍니다."""

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
        "## Week 5 외부 대화·공유 일정 — 도구 구분\n"
        "- 내 개인 일정(일정·할 일·알림)은 Week 1/3/4 도구로 처리한다. 외부 멤버의 일정은 "
        "이 주차 도구로만 조회하고, 두 출처를 섞어서 부르지 않는다.\n"
        "- 내 일정과 외부 멤버 일정이 같은 rows로 함께 나와야 하면 collect_member_schedules를 쓴다. "
        "이 도구가 내 일정을 앱 저장소에서 직접 읽어 합쳐 주므로, member_names에는 외부 멤버 "
        "이름만 넣고 \"나\"는 넣지 않는다.\n"
        "- collect_member_schedules 결과의 roster.limit_reached가 true이면 최종 답변에 명단 조회 상한 때문에 일부 멤버가 빠졌을 수 있다는 주의 문장을 반드시 한 줄 적는다.\n"
        "- \"다들\"·\"모두\"·\"팀원들\"처럼 전원을 가리키는 요청이면 member_names를 비운다.\n"
        "- 공유 일정 저장소에 어떤 row가 등록돼 있는지 자체를 확인할 때는 list_shared_schedules를 쓴다. "
        "이 도구의 member_names는 위와 반대로 \"나\"를 포함한다 — 내 일정도 \"나\" row로 이 저장소에 "
        "동기화돼 있기 때문이다. 내 것과 남의 것을 함께 보려면 \"나\"와 멤버 이름을 같이 넣는다.\n"
        "- 공유 저장소 row를 직접 고쳐야 할 때만 create_shared_schedule/delete_shared_schedule을 쓴다. "
        "shared_로 시작하는 일정 id는 이 저장소의 것이므로 개인 일정 도구로 지우지 말고 "
        "delete_shared_schedule에 그 id를 그대로 넣는다.",
        "## Week 5 외부 대화 탐색과 범위 경계\n"
        "- 외부 멤버의 바쁜 시간만 물었다면 대화 탐색을 건너뛰고 extract_schedules_from_history를 "
        "바로 부른다. 일정의 근거가 된 대화 내용까지 확인해야 할 때만 search_previous_conversations로 "
        "대화를 먼저 찾는다.\n"
        "- load_conversation_messages는 대화 원문을 직접 확인해야 할 때만 선택적으로 부른다. "
        "search 결과에 이미 필요한 내용이 있으면 부르지 않는다.\n"
        "- 조회 결과에 없는 일정을 지어내지 않는다. 없으면 없다고 답한다.\n"
        "- 이 주차의 책임은 바쁜 시간을 모아 보여 주는 데까지다. 여러 사람의 최종 회의 시간을 "
        "확정하지 말고, 비어 있는 후보 시간대까지만 제시한 뒤 사용자에게 선택을 맡긴다.\n"
        "- 후보 시간대를 답할 때는 도구 결과의 24시간제 표기(14:00-16:00)를 그대로 쓰고 오전/오후로 "
        "바꾸지 않는다.\n"
        # 답변을 보기 좋게 만들려는 줄이 아니라, 다음 턴이 날짜를 다시 맞히게 하려는 줄이다.
        # 다음 턴에는 도구를 부른 기록과 그 결과가 안 넘어가고 주고받은 글만 넘어간다
        # (fixed/agent_runtime.py의 previous_messages). 그래서 어느 기간을 조회했는지 알 수 있는 건
        # 이 답변 글뿐이고, 연도를 안 적으면 다음 턴이 엉뚱한 해로 다시 계산한다.
        "- 조회 결과를 답할 때는 답변 첫 줄에 조회한 기간을 YYYY-MM-DD ~ YYYY-MM-DD 꼴로 반드시 "
        "적고 시작한다. 날짜별 목록은 그다음 줄부터 월·일만 적어도 된다.\n"
        "- 답변에는 바쁜 시간이 아니라 비어 있는 구간을 적는다. 날짜마다 비어 있는 구간을 "
        "HH:MM-HH:MM 꼴로 계산해 적고, 여집합을 말로 설명해 사용자에게 넘기지 않는다.",
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
