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
#     내 일정은 member_names에 "나"가 있을 때만 넣습니다. 묻지 않은 내 일정을 답하지 않기
#     위한 선택이고, Week 6 busy_rows 누락 위험은 호출 규약(프롬프트)으로 막습니다.
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


# LLM이 사용자를 가리킬 때 쓰는 표현들 — 공유 저장소의 "나"와 같은 사람으로 봅니다.
SELF_REFERENCE_NAMES = {"나", "저", "제", "내", "본인", "나 자신"}

# LLM이 member_names에 조사를 붙여 넘기는 경우("내가", "저는")까지 같은 사람으로 봅니다.
# 접두어 매칭(startswith)만 쓰면 "나연"·"제니" 같은 실제 이름을 자기 지칭으로 오인하므로,
# 붙을 수 있는 조사를 목록으로 한정합니다. 조사는 앞 글자 받침에 따라 형태가 갈리므로
# 받침 유무로 나눠 둡니다 — 이렇게 해야 "나은"(받침 없는 "나" + "은")처럼
# 실제로는 성립하지 않는 결합이 이름을 잡아채는 일이 없습니다.
_PARTICLES_AFTER_VOWEL = frozenset({"는", "가", "를", "랑", "와", "도", "의", "에게", "한테", "만"})
_PARTICLES_AFTER_CONSONANT = frozenset({"은", "이", "을", "이랑", "과", "도", "의", "에게", "한테", "만"})


def _ends_with_consonant(text: str) -> bool:
    """한글 마지막 글자에 받침이 있는지 봅니다. 한글이 아니면 받침 없음으로 둡니다."""

    last = text[-1:]
    if not ("가" <= last <= "힣"):
        return False
    return (ord(last) - 0xAC00) % 28 != 0


def _is_self_reference(name: str) -> bool:
    """공유 저장소의 "나"와 같은 사람을 가리키는 표현인지 판정합니다."""

    text = name.strip()
    for stem in SELF_REFERENCE_NAMES:
        if text == stem:
            return True
        if not text.startswith(stem):
            continue
        particles = (
            _PARTICLES_AFTER_CONSONANT if _ends_with_consonant(stem)
            else _PARTICLES_AFTER_VOWEL
        )
        if text[len(stem):] in particles:
            return True
    return False


call_mcp_tool = call_local_mcp_tool
call_mcp_tool_sync = call_local_mcp_tool_sync
load_langchain_mcp_tools = load_local_mcp_tools
load_langchain_mcp_tools_sync = load_local_mcp_tools_sync


# 외부 호출 실패가 아니라 이 파일의 버그를 뜻하는 예외들. external_error로 삼키지 않고
# 그대로 올려서 '외부 시스템이 실패했다'는 warning 뒤에 숨지 않게 합니다.
#
# TypeError는 일부러 뺐습니다. fixed/mcp_client.py의 _mcp_result_to_text가 마지막에
# json.dumps(result)를 하므로, 어댑터가 직렬화 불가능한 객체를 돌려주면 경계 너머에서
# TypeError가 올라옵니다. 명백한 외부 실패인데 이걸 내 버그로 분류하면 내 일정까지
# 못 쓰게 됩니다. 아래 try는 경계 호출 한 줄뿐이라 우리 코드가 TypeError를 낼 여지가
# 거의 없어, 넣어서 얻는 것보다 오분류 위험이 큽니다.
_INTERNAL_BUG_ERRORS = (NameError, AttributeError, KeyError, IndexError)


def _schedule_scope(schedule: dict[str, Any]) -> str:
    return str(schedule.get("session_id") or DEFAULT_SESSION_SCOPE)


def _schedule_identity(schedule: dict[str, Any]) -> str:
    """같은 일정을 SQLite row는 schedule_id로, Week 1 임시 row는 id로 가리킵니다."""

    return str(schedule.get("schedule_id") or schedule.get("id") or "")


def _personal_schedules_for_current_scope(
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """SQLite 저장 일정과 현재 대화의 임시 일정만 group 조율 후보로 사용합니다."""

    # 조율 후보에서 내 일정이 조용히 빠지면 남의 일정만 보고 시간을 고르게 되므로
    # list_schedules 기본값(12)보다 넉넉히 읽습니다. 다만 limit만으로 자르면
    # list_schedules가 date ASC 정렬이라 하필 늦은 날짜부터 버려지므로,
    # 조회 범위를 알 때는 DB에서 먼저 좁혀 그 위험을 없앱니다.
    # kind로 좁히지 않습니다 — 개인 일정과 확정된 그룹 일정 모두 내 busy-time입니다.
    saved = AppSQLiteStore(CONFIG.app_db_path).list_schedules(
        limit=200,
        date_from=date_from or None,
        date_to=date_to or None,
    )

    # Week 3 personal_create_schedule은 임시 일정을 같은 id로 SQLite에도 저장하므로
    # 식별자로 한 번 걸러내지 않으면 현재 대화의 일정이 두 번 들어갑니다.
    session_id = current_session_scope()
    saved_ids = {_schedule_identity(row) for row in saved} - {""}

    # 아직 DB에 없는 임시 일정만 더합니다. id를 못 읽는 row는 중복이라고 단정하지 않고 남깁니다.
    pending = [
        schedule
        for schedule in PERSONAL_SCHEDULES
        if _schedule_scope(schedule) == session_id
        and _schedule_identity(schedule) not in saved_ids
    ]
    return [*saved, *pending]


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

    member_names: list[str]
    date_from: str
    date_to: str


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


def _personal_schedules_in_window(
    personal_schedules: list[dict[str, Any]],
    date_from: str,
    date_to: str,
) -> list[dict[str, Any]]:
    """조회 범위 안에서 busy-time 후보가 되는 내 일정만 고릅니다.

    rows를 만드는 쪽과 "몇 건이 빠졌는지" 세는 쪽이 같은 판정을 쓰도록 한 곳에 둡니다.
    둘이 갈라지면 제외 건수가 사실과 달라져, 기록이 오히려 잘못된 근거가 됩니다.
    """

    picked: list[dict[str, Any]] = []
    for schedule in personal_schedules:
        # 날짜 없는 일정은 시간대를 막지 못하므로 busy-time 후보에서 제외합니다.
        date_value = str(schedule.get("date") or "").split("T", 1)[0].strip()
        if not date_value:
            continue
        # 경계가 비어 있어도 store의 date >= ? AND date <= ? 와 같은 판정이 되도록
        # 조건부로 건너뛰지 않고 그대로 비교합니다. 한쪽만 필터링되면 내 일정과
        # 외부 일정의 범위가 어긋납니다.
        if date_value < date_from or date_value > date_to:
            continue
        picked.append(schedule)
    return picked


def _collect_member_schedules(
    *,
    member_names: list[str],
    date_from: str,
    date_to: str,
    personal_schedules: list[dict[str, Any]],
) -> dict[str, Any]:
    """내 일정과 외부 멤버 일정을 같은 row 구조로 합칩니다."""

    # 사용자를 가리키는 말은 공유 저장소의 "나"로 맞춥니다. 이 처리가 없으면 '저랑 철수 일정'처럼
    # 물었을 때 아래 include_mine 판정이 빗나가 내 일정이 조용히 빠집니다.
    normalized_members = [
        PERSONAL_SHARED_MEMBER_NAME if _is_self_reference(name) else name
        for name in normalize_external_member_names(member_names)
    ]
    bounded_date_from, bounded_date_to = normalize_external_schedule_date_bounds(
        member_names, date_from, date_to
    )
    # 내 일정은 앱 DB에서 이미 읽으므로 외부 조회 대상에서는 "나"를 뺍니다. 공유 저장소로 동기화된
    # "나" 사본이 외부 일정으로 또 잡히면 같은 일정이 두 번 집계됩니다.
    external_members = [
        name for name in normalized_members if name != PERSONAL_SHARED_MEMBER_NAME
    ]
    # 조회 대상에 내가 없으면 내 일정을 섞지 않습니다. 묻지 않은 내 일정이 rows에 들어가면
    # "철수 일정 알려줘"에 내 일정까지 함께 답하게 됩니다.
    #
    # 트레이드오프를 알고 택한 것입니다. 가이드 118번 줄은 rows에 "나"와 외부 멤버가 같은
    # 구조로 들어 있는 것을 전제하고, Week 6 find_common_available_slots가 이 rows를
    # busy_rows 근거로 쓸 때 LLM이 "나"를 빼먹으면 내 일정이 조용히 후보에서 빠집니다.
    # 그 위험은 rows를 오염시켜 막지 않고 호출 규약으로 막습니다.
    #   · 사용자를 포함한 조율 맥락이면 member_names에 "나"를 반드시 넣도록
    #     week05_prompt_parts()에 못박아 둡니다.
    #   · 자기 지칭 표현("저", "내가")은 _is_self_reference()로 "나"에 맞춰,
    #     표현이 달라 판정이 빗나가는 경로를 없앱니다.
    # rows에 항상 넣는 쪽은 누락은 막지만 "묻지 않은 내 일정을 답한다"는 오답을 새로
    # 만듭니다. 후자는 사용자가 매번 보는 오답이고 전자는 Week 6 호출부에서 규약으로
    # 막을 수 있는 것이라, 오답을 만들지 않는 쪽을 택했습니다.
    include_mine = PERSONAL_SHARED_MEMBER_NAME in normalized_members

    # 조회 범위 안의 내 일정. include_mine이면 rows가 되고, 아니면 "몇 건을 빼고
    # 답했는지" 기록하는 근거가 됩니다.
    mine_in_window = _personal_schedules_in_window(
        personal_schedules, bounded_date_from, bounded_date_to
    )

    rows: list[dict[str, Any]] = []
    for schedule in (mine_in_window if include_mine else []):
        request = _structured_request_from_schedule_row(schedule)
        members = [str(member).strip() for member in request.members if str(member).strip()]
        rows.append({
            "member_name": PERSONAL_SHARED_MEMBER_NAME,
            "title": request.title or "제목 없음",
            "date": request.date,
            "start_time": request.start_time,
            # 공유 저장소는 종료 시간이 없을 때 "미정"으로 넣으므로 같은 표기로 맞춥니다.
            # 여기서 None을 그대로 두면 병합된 rows에 "미정"과 None이 섞여
            # Week 6이 종료 시간 없는 일정을 두 가지 방식으로 걸러야 합니다.
            "end_time": request.end_time or "미정",
            # 참석자는 fixed/external_mcp.py 공유 동기화와 같은 표기로 남깁니다.
            "notes": f"참석자: {', '.join(members)}" if members else None,
        })

    # 외부 조회 대상이 없으면 MCP subprocess를 띄우지 않습니다.
    # member_names를 None으로 넘기면 store가 멤버 전체를 반환하므로 빈 목록을 그대로 넘기지 않습니다.
    external_error: str | None = None
    if external_members:
        # MCP는 subprocess로 뜨므로 실패할 수 있다. 예외를 그대로 올리면 내 일정까지 못 쓰고,
        # 조용히 빈 rows를 주면 '아무도 안 바쁘다'로 읽혀 더 위험하므로 실패를 표시해 돌려준다.
        #
        # 다만 "외부 호출이 실패한 것"과 "이 함수에 버그가 있는 것"은 다르게 다뤄야 한다.
        # 후자를 external_error에 담아 warning으로 내보내면, 버그가 '외부 시스템 탓'으로
        # 위장돼 조용히 넘어간다. 그래서 (1) try 안에는 경계 호출 한 줄만 두어 내 코드가
        # 예외를 낼 여지를 없애고, (2) 그래도 새어 들어올 수 있는 프로그래밍 오류는
        # 다시 던져서 테스트·트레이스에서 바로 드러나게 한다.
        payload: dict[str, Any] = {}
        try:
            parsed = json.loads(
                call_mcp_tool_sync(
                    "extract_schedules_from_history",
                    {
                        "member_names": external_members,
                        "date_from": bounded_date_from,
                        "date_to": bounded_date_to,
                    },
                )
            )
        except _INTERNAL_BUG_ERRORS:
            # 오타·잘못된 이름 참조 같은 내 실수다. 외부 실패로 위장하지 않고 그대로 올린다.
            raise
        except Exception as exc:
            # subprocess 기동 실패, 프로토콜 오류, JSON 파싱 실패 등 경계 너머의 실패.
            external_error = f"{type(exc).__name__}: {exc}"
        else:
            # 경계에서 온 값은 신뢰하지 않는다. 모양이 다르면 rows 없는 응답으로 취급한다.
            if isinstance(parsed, dict):
                payload = parsed
            else:
                external_error = f"UnexpectedPayload: dict가 아닌 {type(parsed).__name__} 응답"

        external_rows = payload.get("rows")
        # 외부 row에서 busy-time 판단에 쓰는 필드만 내 row와 같은 순서로 남깁니다.
        rows.extend(
            {
                "member_name": row.get("member_name"),
                "title": row.get("title"),
                "date": row.get("date"),
                "start_time": row.get("start_time"),
                "end_time": row.get("end_time"),
                "notes": row.get("notes"),
            }
            for row in (external_rows if isinstance(external_rows, list) else [])
            if isinstance(row, dict)
        )

    result = {
        "ok": external_error is None,
        "tool_name": "collect_member_schedules",
        "member_names": normalized_members,
        "date_from": bounded_date_from,
        "date_to": bounded_date_to,
        "rows": rows,
        "schedule_summary": external_schedule_summary(rows),
    }
    # "나"를 빼고 부른 탓에 실제로 빠진 일정이 있으면 그 사실을 남깁니다. rows는 건드리지
    # 않으므로 묻지 않은 내 일정을 답할 수단은 여전히 없고, 남는 건 "몇 건이 빠졌다"는
    # 사실과 재호출 안내뿐입니다.
    #
    # 이 기록이 없으면 규약 위반이 흔적조차 남기지 않습니다. 결과만 보면 정상이라
    # 트레이스를 뒤져도 못 찾고, Week 6 하위 agent도 rows가 완전한지 알 길이 없습니다.
    # 빠진 게 없으면(0건) 필드를 달지 않습니다 — 매번 붙는 잡음은 곧 무시됩니다.
    if not include_mine and mine_in_window:
        result["mine_excluded_count"] = len(mine_in_window)
        result["mine_excluded_note"] = (
            f"member_names에 \"나\"가 없어 이 기간의 내 일정 {len(mine_in_window)}건을 "
            "제외했습니다. 사용자가 함께 포함되는 조율이라면 \"나\"를 넣어 다시 호출하세요. "
            "사용자가 빠지는 요청이면 이대로 두면 됩니다."
        )
    if external_error:
        result["external_error"] = external_error
        result["warning"] = (
            f"외부 멤버({', '.join(external_members)}) 일정 조회가 실패했습니다. "
            "rows에서 그 사람들의 일정이 빠져 있으니 한가하다고 판단하지 마세요."
        )
    return result


@tool(args_schema=SearchPreviousConversationsInput)
def search_previous_conversations(
    query: str,
    member_names: list[str] | None = None,
    limit: int = 5,
) -> str:
    """외부 SQLite 데이터베이스에 저장된 이전 대화를 검색합니다. query에는 LLM이 고른 짧은 핵심 명사나 구를 넣습니다."""

    # 이름 정규화와 빈 query 처리는 store 경계에서 이미 하므로 인자를 그대로 넘깁니다.
    return call_mcp_tool_sync("search_previous_conversations", {
        "query": query,
        "member_names": member_names,
        "limit": limit,
    })


@tool(args_schema=LoadConversationMessagesInput)
def load_conversation_messages(conversation_id: str) -> str:
    """외부 SQLite 데이터베이스에서 특정 이전 대화의 모든 메시지를 불러옵니다."""

    # sender/content/created_at 순서가 근거가 되므로 payload를 가공하지 않고 그대로 감쌉니다.
    return json_payload(call_external_tool_payload(
        "load_conversation_messages",
        {"conversation_id": conversation_id},
    ))


@tool(args_schema=ExtractSchedulesFromHistoryInput)
def extract_schedules_from_history(member_names: list[str], date_from: str, date_to: str) -> str:
    """외부 SQLite 이전 대화에서 멤버별 일정을 추출합니다."""

    # 날짜 형식 정리도 store 경계에서 한 번만 하므로 여기서 다시 손대지 않습니다.
    return call_mcp_tool_sync("extract_schedules_from_history", {
        "member_names": member_names,
        "date_from": date_from,
        "date_to": date_to,
    })


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

    # schedule_id / source_conversation_id를 그대로 넘겨야 나중에 같은 row를 찾아 갱신·삭제할 수 있습니다.
    return call_mcp_tool_sync("create_shared_schedule", {
        "member_name": member_name,
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "notes": notes,
        "source_conversation_id": source_conversation_id,
        "schedule_id": schedule_id,
    })


@tool(args_schema=DeleteSharedScheduleInput)
def delete_shared_schedule(
    schedule_id: str | None = None,
    source_conversation_id: str | None = None,
) -> str:
    """외부 MCP 공유 일정 저장소에서 일정을 삭제합니다."""

    # 둘 다 비어 있으면 store가 아무것도 지우지 않고 빈 목록을 돌려주므로 인자를 그대로 넘깁니다.
    return call_mcp_tool_sync("delete_shared_schedule", {
        "schedule_id": schedule_id,
        "source_conversation_id": source_conversation_id,
    })


@tool(args_schema=ListSharedSchedulesInput)
def list_shared_schedules(
    member_names: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    source_conversation_id: str | None = None,
    limit: int = 50,
) -> str:
    """외부 MCP 공유 일정 저장소에 등록된 일정을 조회합니다. 필터가 없으면 기본 공유 일정을 반환합니다."""

    # 필터 없음(None)과 빈 목록은 store에서 뜻이 다르므로 인자를 그대로 전달합니다.
    return call_mcp_tool_sync("list_shared_schedules", {
        "member_names": member_names,
        "date_from": date_from,
        "date_to": date_to,
        "source_conversation_id": source_conversation_id,
        "limit": limit,
    })


@tool(args_schema=CollectMemberSchedulesInput)
def collect_member_schedules(member_names: list[str], date_from: str, date_to: str) -> str:
    """내 일정과 다른 사람들의 일정을 MCP SQLite 기록에서 모읍니다.

    내 일정을 함께 모으려면 member_names에 "나"를 포함해 호출해야 합니다.
    """

    # 내 일정도 DB에서 조회 범위로 먼저 좁혀 읽습니다(limit에 늦은 날짜가 잘리는 것 방지).
    # 경계 형식은 store와 같은 규칙으로 맞춘 뒤 넘깁니다.
    bounded_date_from, bounded_date_to = normalize_external_schedule_date_bounds(
        member_names, date_from, date_to
    )
    return json_payload(_collect_member_schedules(
        member_names=member_names,
        date_from=date_from,
        date_to=date_to,
        personal_schedules=_personal_schedules_for_current_scope(
            bounded_date_from, bounded_date_to
        ),
    ))


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
        (
            "이번 회차 Nana는 '나 밖의 데이터'까지 다루는 agent다. 지금까지의 도구는 모두 내 앱 안의 기록을 "
            "다뤘지만, 다른 사람의 과거 대화와 일정, 그리고 여러 사람이 공유하는 일정 저장소는 외부 시스템에 "
            "있고 MCP 도구로만 읽고 쓸 수 있다. 내 것과 남의 것은 저장소가 다르므로 도구를 섞지 않는다."
        ),
        (
            "내 것 vs 외부 것 도구 선택 기준:\n"
            "- 내 일정·할 일·알림을 저장/조회/수정/삭제하려면 앞 회차의 personal_* 도구를 그대로 쓴다.\n"
            "- 다른 사람의 과거 대화 내용을 찾으려면 search_previous_conversations를 쓴다.\n"
            "- 다른 사람이 언제 바쁜지(busy-time)를 알려면 extract_schedules_from_history를 쓴다.\n"
            "- 나와 다른 사람의 일정을 함께 모아 비교·조율하려면 collect_member_schedules를 쓴다.\n"
            "- 여러 사람이 공유하는 일정 저장소 자체를 확인/등록/삭제하려면 list_shared_schedules와 "
            "create_shared_schedule·delete_shared_schedule을 쓴다."
        ),
        (
            "'공유 일정'은 내 개인 일정과 다른 저장소다. 사용자가 '공유 일정에 등록해줘', '공유 저장소에서 지워줘'처럼 "
            "공유 일정 저장소를 가리키거나 나 아닌 사람 이름으로 일정을 등록·삭제하라고 하면, personal_create_schedule이나 "
            "personal_delete_saved_schedules가 아니라 create_shared_schedule·delete_shared_schedule을 호출한다. "
            "내 개인 일정 도구로 저장하고 '공유 일정에 등록했다'고 답하면 사실과 다른 보고가 된다."
        ),
        (
            "두 tool의 경계는 '무엇을 묻는가'로 가른다.\n"
            "- 그 사람이 언제 바쁜지만 묻는 조회(예: '철수 언제 바빠?', '영희 7월 8일 일정 알려줘')는 "
            "extract_schedules_from_history를 쓴다.\n"
            "- 만날 시간을 찾는 조율(예: '철수랑 언제 만날 수 있을까?', '겹치는 시간 있어?', '회의 잡아줘')은 "
            "사용자가 자기를 명시하지 않았더라도 collect_member_schedules를 쓴다. 이 규칙이 위 조회 규칙보다 "
            "우선한다. 조율은 결국 누가 언제 비는지를 판단하는 일이라 내 일정이 빠지면 답이 틀어지는데, "
            "extract_schedules_from_history는 외부 멤버만 보므로 내 일정을 아예 볼 수 없다.\n"
            "list_shared_schedules는 '공유 저장소에 무엇이 등록돼 있는지' 자체를 확인할 때 쓰는 도구이므로, "
            "단순히 누가 언제 바쁜지 묻는 질문에 이걸로 대신하지 않는다."
        ),
        (
            "멤버를 여러 명 물으면 한 사람씩 도구를 반복 호출하지 말고 member_names 배열에 이름을 모두 담아 "
            "한 번만 호출한다. 반대로 member_names를 빈 배열로 넘기면 '해당하는 사람이 없음'이라는 뜻이 되어 "
            "결과가 비므로, 대상을 지정하지 않을 때는 아예 넘기지 않는다."
        ),
        (
            "사용자가 자기 일정까지 함께 보려는 요청이면(예: '나랑 철수', '저랑 하린', '우리 둘이') "
            "member_names에 \"나\"를 반드시 포함해 호출한다. collect_member_schedules는 member_names에 \"나\"가 "
            "있을 때만 내 일정을 함께 모으므로, 빼고 부르면 내 일정이 결과에서 누락된다. 반대로 사용자가 자기 일정을 "
            "묻지 않았으면 \"나\"를 넣지 않는다 — 묻지 않은 내 일정까지 답하게 된다.\n"
            "'겹치는 시간', '같이 볼 수 있는 때', '언제 만날까'처럼 시간을 맞추는 요청은 사용자 본인이 그 자리에 "
            "포함되는 것이 기본이다. 사용자가 자기는 빠진다고 명시하지 않는 한 이런 요청에는 \"나\"를 넣어 부른다. "
            "내 일정을 빼고 시간을 고르면 내가 이미 바쁜 시각을 추천하게 되는데, 결과만 봐서는 그 실수가 드러나지 않는다.\n"
            "결과에 mine_excluded_note가 있으면 \"나\"를 빼고 불러서 그 기간의 내 일정이 실제로 빠졌다는 뜻이다. "
            "사용자가 함께 포함되는 조율이었다면 \"나\"를 넣어 한 번 더 호출하고 그 결과로 답한다. "
            "반대로 사용자가 빠지는 요청이었다면(예: '나는 참석 안 해') 그대로 두고 다시 부르지 않는다. "
            "이 표시만 보고 무조건 \"나\"를 넣지 않는다 — 묻지 않은 내 일정까지 답하게 된다."
        ),
        (
            "외부 과거 대화는 '검색 → 로드' 순서로 본다. search_previous_conversations로 conversation_id를 찾고, "
            "그 대화의 전체 내용이 필요하면 그 id로 load_conversation_messages를 호출한다. "
            "검색 query에는 사용자 문장을 그대로 넣지 말고 핵심 명사나 짧은 구만 넣는다."
        ),
        (
            "외부 조회 결과가 비어 있으면 그 사람이나 일정이 외부 기록에 없다는 뜻이다. 이름을 임의로 바꿔 추측하거나 "
            "없는 일정을 지어내지 않고, 찾지 못했다고 답한다. 외부 일정을 근거로 답할 때는 날짜와 시간을 "
            "조회 결과에 있는 값으로만 말한다."
        ),
        (
            "단, 결과에 external_error나 warning이 있으면 '외부 일정이 없다'는 뜻이 아니라 조회 자체가 실패했다는 뜻이다. "
            "이때는 그 사람이 한가하다고 말하지 않고, 외부 일정을 확인하지 못했다고 밝힌 뒤 다시 시도할지 묻는다. "
            "종료 시간이 '미정'인 일정은 끝나는 시각을 모르는 것이므로 그 뒤가 비어 있다고 단정하지 않는다."
        ),
        (
            "누가 언제 바쁜지 묻는데 기간이 특정되지 않으면(예: '철수 언제 바빠?') 어느 기간을 볼지 먼저 되묻는다. "
            "오늘 하루로 좁히거나 오늘 이후만 보는 것처럼 기간을 임의로 정하면, 실제로 일정이 있어도 그 기간 밖이라 "
            "결과가 비어 '일정이 없다'고 잘못 답하게 된다. 되묻지 않고 조회했다면 어떤 기간을 봤는지 답변에 밝히고 "
            "그 기간 밖은 확인하지 않았다고 덧붙인다."
        ),
        (
            "다른 사람과 만날 시간을 잡아 달라는 요청은 그 사람이 그 시간에 비어 있는지 먼저 확인한 뒤 진행한다. "
            "사용자가 시간을 직접 지정했더라도 확인을 건너뛰지 않는다. 상대의 다른 일정과 겹치면 등록하기 전에 "
            "무엇과 겹치는지 알리고 다른 시간을 제안한다. 확인 없이 곧바로 공유 일정으로 등록하지 않는다. "
            "내 선호(집중 시간 등)를 반영하라는 조건이 붙어도 선호와 상대 일정을 모두 확인한 뒤 시간을 제안한다."
        ),
        (
            "도구가 오류를 돌려주면 그 내용을 읽고 고쳐서 다시 시도한다. 공유 일정 등록에는 날짜가 반드시 필요하므로 "
            "날짜를 모르면 지어내지 말고 사용자에게 묻는다. 조회 개수처럼 허용 범위가 정해진 값은 범위를 넘기지 않고 "
            "허용되는 값으로 다시 호출한다."
        ),
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
