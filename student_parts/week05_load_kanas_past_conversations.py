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

WEEK05_EXTERNAL_HISTORY_PROMPT = (
    # 외부 멤버 대화/일정의 출처와 tool 선택 기준을 구분한다.
    "다른 사람의 이전 대화와 일정은 앱 데이터베이스가 아니라 외부 저장소에 있고, "
    "외부 저장소는 MCP tool로만 조회할 수 있다. "
    "어떤 대화가 있었는지 찾을 때는 search_previous_conversations를 쓰고, "
    "query에는 조사나 문장 전체가 아니라 짧은 핵심 명사나 구를 넣는다. "
    "찾은 대화의 전체 내용이 필요하면 그 대화의 conversation_id로 "
    "load_conversation_messages를 호출한다. "
    "다른 사람이 언제 바쁜지만 알면 될 때는 대화 전문을 읽지 않고 "
    "extract_schedules_from_history로 일정 row를 바로 받는다."
)

WEEK05_SCHEDULE_COLLECTION_PROMPT = (
    # 여러 사람의 일정을 모을 때 호출할 tool과 이번 주차의 책임 범위를 정한다.
    "내 일정과 다른 사람 일정을 함께 모아야 하는 요청은 collect_member_schedules 한 번으로 처리한다. "
    "이 tool이 내부에서 외부 일정 조회까지 수행하므로 "
    "extract_schedules_from_history를 따로 다시 호출하지 않는다. "
    "MCP tool 호출은 한 번에 수 초가 걸리므로 같은 조회를 반복하지 않는다. "
    "공유 일정 저장소에 어떤 row가 등록되어 있는지 확인할 때만 list_shared_schedules를 쓴다. "
    "이때 member_names는 반드시 지정한다. "
    "조건을 모두 비워 두면 실습용 기본 일정만 조회되고 내 일정은 결과에 포함되지 않는다. "
    "날짜 범위는 사용자가 기간을 지정한 경우에만 넣고, 지정하지 않았으면 date_from과 date_to를 비워 둔다. "
    "기간을 임의로 오늘 하루로 좁히면 등록된 row가 있어도 0건이 조회된다. "
    "여러 사람이 모두 가능한 최종 회의 시간을 확정하는 것은 이번 주차의 범위가 아니므로, "
    "모은 일정을 근거로 바쁜 시간과 비어 있는 시간을 설명하는 데까지만 답한다. "
    "종료 시간이 '미정'인 일정은 겹침 여부를 판단하지 말고, "
    "빈 시간대를 제안하기 전에 사용자에게 종료 시간을 먼저 확인한다. "
    "tool 결과에 errors 항목이 비어 있지 않으면 조회하지 못한 대상이 있다는 뜻이므로, "
    "확보한 rows로 답하되 어떤 조회가 실패했는지 함께 알린다."
)

WEEK05_SHARED_SCHEDULE_WRITE_PROMPT = (
    # 공유 일정 저장소에 직접 등록/삭제하는 tool의 사용 조건을 좁힌다.
    "내 일정을 새로 만들거나 지우는 요청은 Week 3 앱 일정 tool로 처리한다. "
    "앱 일정을 저장하거나 삭제하면 공유 일정 저장소의 내 복사본도 함께 처리되므로, "
    "create_shared_schedule과 delete_shared_schedule을 따로 호출하지 않는다. "
    "이 두 tool은 앱에 대응 일정이 없는 공유 저장소 일정을 직접 등록하거나 정리할 때만 쓴다. "
    "delete_shared_schedule은 사용자가 삭제 대상을 지정한 경우에만 호출하고, "
    "먼저 list_shared_schedules로 대상 schedule_id를 확인한다. "
    "schedule_id와 source_conversation_id 중 확인된 값 하나만 넣는다. "
    "두 값을 함께 넣으면 조건이 OR로 묶여 의도한 것보다 많은 일정이 삭제된다."
)


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

"""APP_SCHEDULE_FETCH_LIMIT을 따로 두는 이유.

1. AppSQLiteStore.list_schedules의 limit 기본값은 12다(fixed/app_store.py:482).
   일정 조율은 날짜 범위 안의 모든 일정을 근거로 삼아야 하므로 기본값을 그대로 쓰면
   조회 결과가 잘려 바쁜 시간이 누락된다.

2. list_schedules는 date_from/date_to를 인자로 받지만, 이 값으로 좁히더라도
   같은 날짜에 여러 일정이 있으면 12건 제한에 걸릴 수 있다.
   그래서 조회 단계에서는 넉넉하게 받고 날짜 범위 판정은 _row_in_date_range에서 처리한다.
"""
APP_SCHEDULE_FETCH_LIMIT = 200


def _schedule_scope(schedule: dict[str, Any]) -> str:
    return str(schedule.get("session_id") or DEFAULT_SESSION_SCOPE)


def _schedule_identifier(schedule: dict[str, Any]) -> str:
    """앱 일정 row와 임시 일정 row에서 중복 판정용 식별자를 읽습니다."""

    """식별자 키가 두 개인 이유와, 이 비교만으로 중복 판정이 끝나는 근거.

    1. 저장 위치에 따라 키 이름이 다르다.
       앱 SQLite 일정 row는 schedule_id(예: sch_0d7edca91b)를 가지고,
       Week 1 임시 일정 row는 id(예: personal_ab12cd34ef)를 가진다.

    2. 임시 일정이 앱 SQLite에 저장되는 경로는 하나뿐이다.
       student_parts/week03_build_nanas_logbook.py:576의 personal_create_schedule이
       :547의 structured_request_from_week01_schedule로 source_schedule_id에
       임시 일정 id를 넣어 저장하고, fixed/app_store.py:353의
       schedule_id = source_schedule_id or new_id("sch")가 그 값을 그대로 쓴다.

    3. 그래서 이미 저장된 임시 일정은 항상 식별자가 일치한다.
       임시 일정을 저장하면서 id를 새로 발급하는 경로는 없으므로, 내용이 같고
       id만 다른 저장 row는 임시 일정에서 온 row가 아니다. 내용 기반 비교를
       추가하면 별개 일정을 근거 없이 제외할 수 있어 두지 않는다.
    """
    return str(schedule.get("schedule_id") or schedule.get("id") or "")


def _personal_schedules_for_current_scope() -> list[dict[str, Any]]:
    """SQLite 저장 일정과 현재 대화의 임시 일정만 group 조율 후보로 사용합니다."""

    """내 일정을 두 출처에서 읽는 이유와 처리 순서.

    1. 두 출처의 성질이 다르다.
       Week 3 이후 저장된 일정은 앱 SQLite에 남아 대화가 바뀌어도 유지된다.
       Week 1 임시 일정은 PERSONAL_SCHEDULES 리스트에만 있고 앱을 다시 시작하면 사라진다.
       일정 조율 근거로는 두 출처가 모두 필요하다.

    2. 임시 일정에만 대화 범위 조건을 적용한다.
       AppSQLiteStore.list_schedules는 session 필터를 받지 않으므로 저장된 일정은
       전부 조회된다. 반면 임시 일정은 다른 대화에서 만든 값이 섞이면 안 되므로
       current_session_scope()와 같은 범위만 남긴다.

    3. 중복 판정은 식별자 비교 하나로 한다.
       임시 일정이 앱 SQLite에 저장되는 경로에서 저장 row가 임시 일정 id를 그대로
       물려받는다. 근거는 _schedule_identifier()의 2번, 3번 항목에 있다.

    4. 처리 순서
       (1) 앱 SQLite에서 저장된 일정을 조회한다.
       (2) 조회된 일정의 식별자 집합을 만든다.
       (3) 임시 일정 중 현재 대화 범위이고 그 집합에 없는 항목만 고른다.
       (4) 저장 일정 뒤에 임시 일정을 이어 붙여 반환한다.
    """
    saved_schedules = AppSQLiteStore(CONFIG.app_db_path).list_schedules(limit=APP_SCHEDULE_FETCH_LIMIT)
    saved_identifiers = {_schedule_identifier(schedule) for schedule in saved_schedules}

    current_scope = current_session_scope()
    temporary_schedules = [
        schedule
        for schedule in PERSONAL_SCHEDULES
        if _schedule_scope(schedule) == current_scope
        and _schedule_identifier(schedule) not in saved_identifiers
    ]
    return [*saved_schedules, *temporary_schedules]


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

    """날짜 필드에 description을 붙인 이유.

    1. system prompt 문장만으로는 인자 값이 고정되지 않는다.
       WEEK05_SCHEDULE_COLLECTION_PROMPT에 날짜 범위를 비워 두라고 적어도, 실제
       실행에서 LLM이 date_from/date_to를 실행 시점 날짜 하루로 채우는 경우가
       반복해서 나타났다. 그 결과 "나" row가 9건 있는데 0건이 조회됐다.

    2. description은 인자마다 tool schema에 함께 전달된다.
       LLM은 tool을 고를 때 이 설명을 인자 단위로 읽으므로, 전체 지시문에 있는
       한 문장보다 해당 인자에 직접 붙은 설명이 값 선택에 더 크게 작용한다.

    3. 값 자체를 코드에서 무시하지는 않는다.
       date_from과 date_to가 같은 날짜인 조회는 "그 하루만 보기"라는 정상 요청일
       수도 있다. wrapper에서 두 값을 지우면 그 요청을 처리할 수 없으므로,
       판단 근거만 LLM에게 더 정확히 전달한다.
    """

    member_names: list[str] | None = Field(
        default=None,
        description="조회할 멤버 이름 목록. 내 공유 일정을 확인할 때는 [\"나\"]를 넣는다. "
        "이 값을 비우면 실습용 기본 멤버 일정만 조회되고 내 일정은 포함되지 않는다.",
    )
    date_from: str | None = Field(
        default=None,
        description="조회 시작 날짜(YYYY-MM-DD). 사용자가 기간을 말한 경우에만 넣는다. "
        "기간을 말하지 않았으면 오늘 날짜를 넣지 말고 None으로 비워 둔다. "
        "비워 두면 등록된 모든 기간의 row가 조회된다.",
    )
    date_to: str | None = Field(
        default=None,
        description="조회 종료 날짜(YYYY-MM-DD). 사용자가 기간을 말한 경우에만 넣는다. "
        "기간을 말하지 않았으면 오늘 날짜를 넣지 말고 None으로 비워 둔다.",
    )
    source_conversation_id: str | None = Field(
        default=None,
        description="앱 원본 요청 ID로 좁혀 볼 때만 넣는다. 확실하지 않으면 None.",
    )
    limit: int = Field(default=50, ge=1, le=200, description="조회할 최대 row 수.")


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


def _row_in_date_range(date_text: Any, date_from: str, date_to: str) -> bool:
    """일정 날짜가 조회 범위에 포함되는지 판정합니다."""

    """문자열 비교로 날짜 범위를 판정하는 근거.

    1. 날짜 형식이 YYYY-MM-DD로 고정되어 있다.
       ISO 8601 날짜 문자열은 자릿수가 고정이라 사전순 비교 결과가 날짜순 비교 결과와
       일치한다. 그래서 datetime 타입으로 변환하지 않고 문자열 부등호를 사용한다.

    2. 날짜가 없는 일정은 범위 밖으로 처리한다.
       Week 2 StructuredRequest는 date를 None으로 둘 수 있고 앱 일정 row도 date가
       None일 수 있다. 날짜가 없으면 어느 날 바쁜지 판단할 수 없어 조율 근거로
       사용할 수 없으므로 False를 반환한다.

    3. 범위 경계가 비어 있으면 그 방향은 제한하지 않는다.
       normalize_external_schedule_date_bounds는 인자가 비어 있으면 빈 문자열을
       반환하므로, 빈 문자열일 때 해당 조건을 건너뛴다.
    """
    if not date_text:
        return False
    normalized_date = str(date_text)
    if date_from and normalized_date < date_from:
        return False
    if date_to and normalized_date > date_to:
        return False
    return True


def _personal_schedule_row(schedule: dict[str, Any]) -> dict[str, Any]:
    """내 일정 row를 외부 멤버 row와 같은 필드 구조로 변환합니다."""

    """변환 규칙.

    1. 필드 이름을 외부 row에 맞춘다.
       외부 MCP row는 member_name/title/date/start_time/end_time/notes를 가진다.
       내 일정 row는 owner/attendees 같은 다른 필드를 쓰므로
       _structured_request_from_schedule_row로 Week 2 스키마로 읽은 뒤 옮긴다.

    2. member_name은 "나"로 고정한다.
       공유 일정 저장소가 앱 개인 일정을 복사할 때 쓰는 이름과 같은 값을 사용해야
       Week 6에서 두 출처의 row를 같은 사람으로 인식할 수 있다.
       상수는 fixed/external_people_store.py의 PERSONAL_SHARED_MEMBER_NAME이다.

    3. notes에는 출처를 기록한다.
       앱 일정 row에는 notes 필드가 없다. 대신 이 row가 SQLite 저장 일정인지
       현재 대화 임시 일정인지 적어 두면, LLM 답변과 trace 확인에서 두 출처를
       구분할 수 있다. schedule_id가 있으면 저장 일정, 없으면 임시 일정이다.
    """
    request = _structured_request_from_schedule_row(schedule)
    source_note = "앱 SQLite 저장 일정" if schedule.get("schedule_id") else "현재 대화 임시 일정"
    return {
        "member_name": PERSONAL_SHARED_MEMBER_NAME,
        "title": request.title or "제목 없음",
        "date": request.date,
        "start_time": request.start_time or "미정",
        "end_time": request.end_time or "미정",
        "notes": source_note,
    }


def _collect_member_schedules(
    *,
    member_names: list[str],
    date_from: str,
    date_to: str,
    personal_schedules: list[dict[str, Any]],
) -> dict[str, Any]:
    """내 일정과 외부 멤버 일정을 같은 row 구조로 합칩니다."""

    """호출 체인과 처리 순서.

    [도형 범례]
      ┌──┐  함수/@tool                   ___
      └──┘                             /___/|   저장소(SQLite)
                                       |___|/
       .-~-.
      ( ☁ )  프로세스 경계(MCP stdio 호출)
       `-~-~-'
      ( {...}, {...}, ... )             rows 배열


      ┌──────────────────────────────────────────────┐
      │ collect_member_schedules                     │  이 파일 863
      └───────────────────────┬──────────────────────┘
                              ▼
      ┌──────────────────────────────────────────────┐
      │ _personal_schedules_for_current_scope        │  이 파일 285
      └───────────────────────┬──────────────────────┘
                              ▼
                             ___
                            /___/|  data/kanana_app.sqlite3
                            |___|/  + PERSONAL_SCHEDULES(임시)
                              │
                              ▼
      ┌──────────────────────────────────────────────┐
      │ _collect_member_schedules                    │  이 파일 511
      └──────┬────────────────────────────────┬──────┘
             │ 내 일정                          │ 외부 멤버 일정
             ▼                                ▼
      ┌────────────────────────┐       ┌──────────────────────────┐
      │ _personal_schedule_row │ 479   │ call_mcp_tool_sync(      │
      │ _row_in_date_range     │ 451   │  "extract_schedules_     │
      └──────────┬─────────────┘       │   from_history", args)   │
                 │                     └────────────┬─────────────┘
                 │                              .-~-▼-~-~-~-~-~-.
                 │                             ( ☁ MCP 서버 호출  )
                 │                              `-~-~-~-┬-~-~-~-'
                 │                                      ▼
                 │                             ┌──────────────────────┐
                 │                             │ @mcp.tool 구현        │
                 │                             │ mcp_server/sqlite_   │
                 │                             │ mcp_server.py:53     │
                 │                             └──────────┬───────────┘
                 │                                        ▼
                 │                                       ___
                 │                                      /___/|  data/kanana_
                 │                                      |___|/  external_people
                 │                                              .sqlite3
                 │                                        │
                 └───────────────┬────────────────────────┘
                                 ▼
      ( {member_name, title, date, start_time, end_time, notes}, ... )
                                 ▼
      ┌──────────────────────────────────────────────┐
      │ external_schedule_summary(rows)              │  fixed/external_people_store.py:134
      └──────────────────────┬───────────────────────┘
                             ▼
              {"rows": [...], "schedule_summary": "..."}


    처리 순서

    1. 멤버 이름과 날짜 범위를 정규화한다.
       normalize_external_member_names는 공백을 제거하고 빈 이름을 버린다.
       normalize_external_schedule_date_bounds는 ISO datetime에서 날짜 부분만 남긴다.
       두 helper 모두 fixed/external_people_store.py에 있고, 외부 store가 조회 시점에
       같은 정규화를 다시 하므로 이 함수에서는 판정용 값을 얻는 목적으로만 호출한다.

    2. 외부 조회 대상에서 "나"를 제외한다.
       앱 개인 일정을 저장할 때 fixed/external_mcp.py:26의
       sync_personal_schedule_to_shared가 공유 일정 저장소에 member_name="나"
       복사본을 만든다. 내 일정은 이미 앱 SQLite에서 읽었으므로 외부 조회 대상에
       "나"를 남겨 두면 같은 일정이 두 번 들어간다.
       member_names에 "나"가 들어와도 내 일정 row는 항상 결과에 포함되므로,
       여기서 제외해도 누락되지 않는다.

    3. 외부 멤버가 없으면 MCP를 호출하지 않는다.
       MCP 호출 1회는 서버 subprocess를 새로 기동하므로 수 초가 걸린다.
       조회할 외부 멤버가 없으면 호출 자체를 건너뛴다.

    4. 내 일정을 외부 호출보다 먼저 계산한다.
       내 일정은 _personal_schedule_row로 변환하고 날짜 범위로 걸러낸다.
       외부 row는 store가 이미 같은 필드로 반환하므로 그대로 사용한다.
       계산 순서를 이렇게 두면 외부 호출이 실패해도 personal_rows는 남는다.

    5. 외부 호출 실패를 이 함수 안에서 처리한다.
       (1) 예외를 그대로 올리면 외부 멤버 조회 실패 하나가 내 일정 답변까지 막는다.
           그래서 외부 호출 구간만 try로 감싸고, 실패해도 personal_rows로 답할 수
           있게 한다.

       (2) 실패를 숨기지 않는다. 반환 payload의 errors 항목에 tool 이름과 예외
           정보를 담고, WEEK05_SCHEDULE_COLLECTION_PROMPT가 errors가 비어 있지
           않으면 실패 사실을 함께 알리도록 지시한다.

       (3) 잡는 예외 타입을 좁히지 않고 try 구간을 좁힌다.
           call_local_mcp_tool_sync는 단일 예외 타입을 보장하지 않는다.
           tool 이름 오류는 ValueError(fixed/mcp_client.py:113), subprocess 기동
           실패는 OSError 계열, adapter 내부 실패는 또 다른 타입으로 올라오고,
           _run_coroutine_sync가 별도 thread의 예외를 그대로 다시 발생시킨다.
           타입으로 좁히면 통신 실패 일부가 빠지므로, try 안에 MCP 호출과 JSON
           파싱 두 줄만 두어 구간으로 범위를 제한한다.

    6. 날짜, 시작 시간, 이름 순으로 정렬한다.
       외부 store의 조회 순서와 같은 기준으로 맞춰, 두 출처를 합친 뒤에도
       읽는 순서가 일정하게 유지되도록 한다.
    """
    normalized_member_names = normalize_external_member_names(member_names)
    normalized_date_from, normalized_date_to = normalize_external_schedule_date_bounds(
        member_names,
        date_from,
        date_to,
    )

    external_member_names = [
        name for name in normalized_member_names if name != PERSONAL_SHARED_MEMBER_NAME
    ]

    personal_rows = [
        _personal_schedule_row(schedule)
        for schedule in personal_schedules
        if _row_in_date_range(schedule.get("date"), normalized_date_from, normalized_date_to)
    ]

    external_rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    if external_member_names:
        try:
            external_payload = json.loads(
                call_mcp_tool_sync(
                    "extract_schedules_from_history",
                    {
                        "member_names": external_member_names,
                        "date_from": normalized_date_from,
                        "date_to": normalized_date_to,
                    },
                )
            )
            external_rows = external_payload.get("rows") or []
        except Exception as exc:
            errors.append(
                {
                    "tool": "extract_schedules_from_history",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                }
            )

    rows = [*personal_rows, *external_rows]
    rows.sort(
        key=lambda row: (
            str(row.get("date") or ""),
            str(row.get("start_time") or ""),
            str(row.get("member_name") or ""),
        )
    )

    return {
        "ok": True,
        "tool_name": "collect_member_schedules",
        "member_names": normalized_member_names,
        "external_member_names": external_member_names,
        "date_from": normalized_date_from,
        "date_to": normalized_date_to,
        "personal_row_count": len(personal_rows),
        "external_row_count": len(external_rows),
        "rows": rows,
        "schedule_summary": external_schedule_summary(rows),
        "errors": errors,
    }


@tool(args_schema=SearchPreviousConversationsInput)
def search_previous_conversations(
    query: str,
    member_names: list[str] | None = None,
    limit: int = 5,
) -> str:
    """외부 SQLite 데이터베이스에 저장된 이전 대화를 검색합니다. query에는 LLM이 고른 짧은 핵심 명사나 구를 넣습니다."""

    """결과 문자열을 가공하지 않고 그대로 반환하는 이유.

    1. MCP tool이 이미 계약에 맞는 JSON 문자열을 반환한다.
       mcp_server/sqlite_mcp_server.py:41이 {"ok", "tool_name", "rows"} 구조를
       json.dumps(ensure_ascii=False)로 직렬화한다. 여기서 다시 파싱하고
       직렬화하면 같은 값을 두 번 변환하는 것뿐이다.

    2. 멤버 이름 정규화도 하지 않는다.
       fixed/external_people_store.py:408의 store 메서드가 조회 직전에
       normalize_external_member_names를 호출한다. wrapper에서 한 번 더 변환하면
       정규화 지점이 두 곳으로 늘어난다.

    3. member_names를 None 그대로 넘기는 것에 의미가 있다.
       외부 store는 None이면 모든 멤버를 검색하고, 빈 list면 지정된 멤버가 없는
       요청으로 보아 빈 rows를 반환한다. 두 경우의 동작이 다르므로 None을
       빈 list로 바꾸지 않는다.
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
    """외부 SQLite 데이터베이스에서 특정 이전 대화의 모든 메시지를 불러옵니다."""

    """이 tool만 다른 helper를 쓰는 이유와 순서 보존 조건.

    1. call_external_tool_payload는 결과를 dict로 받는다.
       fixed/external_mcp.py:20의 이 helper는 내부에서 call_local_mcp_tool_sync를
       호출한 뒤 json.loads로 파싱한다. 전송 경로는 다른 tool과 같고,
       반환 타입만 문자열이 아니라 dict다.

    2. dict를 다시 문자열로 되돌려야 tool 반환 타입이 맞는다.
       LangChain tool은 문자열을 반환해야 하므로 json_payload로 감싼다.
       ensure_ascii=False를 쓰는 json_payload를 통과시켜 한글이 유지된다.

    3. payload를 재구성하지 않는다.
       메시지 rows의 sender/content/created_at 순서는 외부 store가 시간순으로
       정렬해 반환한 결과다. dict의 키를 골라 담거나 rows를 다시 정렬하면
       그 순서가 보존되지 않을 수 있으므로 받은 payload 전체를 그대로 넘긴다.
    """
    payload = call_external_tool_payload(
        "load_conversation_messages",
        {"conversation_id": conversation_id},
    )
    return json_payload(payload)


@tool(args_schema=ExtractSchedulesFromHistoryInput)
def extract_schedules_from_history(member_names: list[str], date_from: str, date_to: str) -> str:
    """외부 SQLite 이전 대화에서 멤버별 일정을 추출합니다."""

    """날짜 형식을 이 wrapper에서 정리하지 않는 이유.

    1. store가 조회 직전에 같은 정규화를 수행한다.
       fixed/external_people_store.py:457-458에서 멤버 이름과 날짜 범위를
       각각 normalize_external_member_names,
       normalize_external_schedule_date_bounds로 정리한다.

    2. 반환 payload에 요약이 이미 포함되어 있다.
       mcp_server/sqlite_mcp_server.py:65-73이 rows와 함께
       external_schedule_summary(rows) 결과를 schedule_summary로 담아 반환한다.
       그래서 이 wrapper는 결과 문자열을 그대로 전달하면 된다.

    3. rows의 필드 구성도 유지된다.
       member_name/title/date/start_time/end_time/notes는 store가 만든 형태이며
       이 함수에서 필드를 추가하거나 이름을 바꾸지 않는다.
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
    """외부 MCP 공유 일정 저장소에 일정을 등록하거나 갱신합니다."""

    """인자를 그대로 넘기고 결과 문자열을 반환하는 이유.

    1. store가 등록 직전에 값을 정리한다.
       fixed/external_people_store.py:253-262가 member_name/title/notes에서 소괄호
       내용을 제거하고, date에서 ISO datetime의 날짜 부분만 남기고, start_time과
       end_time이 비어 있으면 "미정"을 채운다. wrapper에서 같은 처리를 하면 정리
       지점이 두 곳으로 늘어난다.

    2. schedule_id는 None을 그대로 넘긴다.
       None이면 store가 new_id("shared")로 새 id를 발급하고(같은 파일 263행),
       기존 id를 넘기면 ON CONFLICT(schedule_id) DO UPDATE로 같은 일정이 갱신된다
       (278-285행). wrapper에서 id를 만들어 채우면 갱신 경로를 쓸 수 없다.

    3. end_time 기본값 "미정"을 다른 값으로 바꾸지 않는다.
       사용자가 종료 시간을 말하지 않은 일정은 "미정"으로 남긴다. 겹침 판정은
       WEEK05_SCHEDULE_COLLECTION_PROMPT의 지시대로 사용자에게 확인한 뒤 한다.

    4. source_conversation_id를 보존한다.
       앱 개인 일정의 자동 동기화 복사본은 이 값에 "app:{request_id}"를 넣고
       (fixed/external_mcp.py:50), 삭제할 때 같은 값으로 대상을 찾는다(126행).
       직접 등록한 일정도 같은 규칙을 따를 수 있게 값을 그대로 전달한다.
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
    """외부 MCP 공유 일정 저장소에서 일정을 삭제합니다. schedule_id와 source_conversation_id 중 확인된 값 하나만 넣습니다."""

    """두 인자에 기본값을 채우지 않고 그대로 넘기는 이유.

    1. 두 값이 모두 없으면 store가 아무 일정도 삭제하지 않는다.
       fixed/external_people_store.py:318-319가 빈 목록을 반환하고 DELETE 문을
       실행하지 않는다. wrapper에서 기본값을 채우면 이 조건이 동작하지 않는다.

    2. 두 값을 함께 넘기면 삭제 범위가 넓어진다.
       조회와 삭제의 조건이 AND가 아니라 OR로 연결되므로(같은 파일 335행, 340행),
       schedule_id와 source_conversation_id 중 하나만 일치해도 삭제된다.
       그래서 확인된 값 하나만 넣도록 WEEK05_SHARED_SCHEDULE_WRITE_PROMPT에 적었다.

    3. 결과 문자열을 가공하지 않는다.
       mcp_server/sqlite_mcp_server.py:124-132가 deleted_count와 삭제된 일정 목록을
       담아 반환하므로, LLM이 몇 건이 삭제됐는지 답변 근거로 쓸 수 있다.
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
    """외부 MCP 공유 일정 저장소에 등록된 일정을 조회합니다. 필터가 없으면 기본 공유 일정을 반환합니다."""

    """필터 인자를 그대로 넘겨야 하는 이유.

    1. 필터가 하나도 없으면 store가 조회 조건을 대체한다.
       fixed/external_people_store.py:355-359을 보면 member_names, date_from,
       date_to, source_conversation_id가 모두 비어 있을 때
       JULY_PRACTICE_MEMBER_NAMES(철수·영희·민준·서연·지훈·하린)와
       2026-07-07 ~ 2026-07-17로 조건이 바뀐다.

    2. 그래서 "나" 일정은 필터 없는 조회로 확인할 수 없다.
       "나"는 대체 조건의 멤버 목록에 없다. 앱 개인 일정의 공유 복사본을 확인할
       때는 member_names=["나"]처럼 조건을 명시해야 한다.
       실측 결과 필터 없는 조회는 18건을 반환하고 그 안에 "나" row는 없으며,
       member_names=["나"]로 조회하면 9건이 나온다.

    3. member_names의 None과 빈 list는 동작이 다르다.
       None이면 위 1번의 대체 조건 판정 대상이 되고, 빈 list이면
       fixed/external_people_store.py:366-367에 의해 빈 rows가 반환된다.
       wrapper에서 None을 빈 list로 바꾸면 이 구분이 사라진다.

    4. 날짜 범위를 임의로 채우면 등록된 row가 있어도 0건이 반환된다.
       member_names만 지정하면 1번의 대체 조건이 적용되지 않으므로, 날짜 조건 없이
       그 멤버의 모든 기간 row가 조회된다. 반면 date_from/date_to를 채우면
       fixed/external_people_store.py:375-380의 date >= ? AND date <= ? 조건이
       추가된다. 실제 앱 실행에서 사용자가 기간을 말하지 않았는데도 LLM이 두 값을
       실행 시점 날짜(2026-07-29) 하루로 채워, "나" row가 9건 있는 상태에서 0건이
       조회되고 "등록된 일정이 없습니다" 답변이 나온 적이 있다. 그래서
       WEEK05_SCHEDULE_COLLECTION_PROMPT에 날짜 범위를 비워 두는 조건을 따로 적었다.
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
    """내 일정과 다른 사람들의 일정을 MCP SQLite 기록에서 모읍니다."""

    """내 일정 조회를 이 함수에서 먼저 실행하는 이유.

    1. 대화 범위 값이 이 함수의 실행 문맥에만 있다.
       현재 대화 범위는 fixed/session_scope.py의 ContextVar로 관리된다.
       MCP 호출은 fixed/mcp_client.py:67에서 별도 thread를 만들어 실행하고,
       ContextVar는 새 thread로 전파되지 않는다.
       실제로 확인하면 새 thread에서 current_session_scope()는
       DEFAULT_SESSION_SCOPE를 반환한다.

    2. 그래서 조회 순서를 고정한다.
       (1) 이 함수(tool 본문, 메인 thread)에서
           _personal_schedules_for_current_scope()를 호출해 내 일정을 먼저 읽는다.
       (2) 읽은 결과를 personal_schedules 인자로 넘긴다.
       (3) _collect_member_schedules 안에서 외부 MCP 호출을 수행한다.

    3. 반환은 json_payload로 감싼다.
       _collect_member_schedules는 dict를 반환하므로 tool 반환 타입인 문자열로
       바꿔야 한다. rows와 schedule_summary가 이 payload 안에 함께 들어간다.
    """
    payload = _collect_member_schedules(
        member_names=member_names,
        date_from=date_from,
        date_to=date_to,
        personal_schedules=_personal_schedules_for_current_scope(),
    )
    return json_payload(payload)


def week05_tools() -> list[Any]:
    """4주차까지의 도구에 외부 SQLite/MCP 일정 도구를 누적한 목록입니다."""

    """create_shared_schedule과 delete_shared_schedule을 목록에 넣은 이유.

    1. 두 tool의 본문을 구현했다.
       추가 과제 대상이지만 call_mcp_tool_sync 호출로 구현해 문자열을 반환하므로,
       문자열 반환을 요구하는 LangChain tool 목록에 넣어도 조건이 맞는다.

    2. 사용 조건은 코드가 아니라 prompt에서 좁힌다.
       create_agent에 전달되는 tool 목록이 LLM이 선택할 수 있는 범위다. 두 tool을
       목록에 넣은 뒤, 어떤 요청에서 호출해야 하는지는
       WEEK05_SHARED_SCHEDULE_WRITE_PROMPT에 적었다.

    3. 조회 tool을 쓰기 tool보다 앞에 둔다.
       삭제는 list_shared_schedules로 대상 schedule_id를 확인한 뒤 호출하는
       순서이므로, 목록에서도 조회 tool을 먼저 둔다.
    """
    return [
        *week04_tools(),
        search_previous_conversations,
        load_conversation_messages,
        extract_schedules_from_history,
        list_shared_schedules,
        collect_member_schedules,
        create_shared_schedule,
        delete_shared_schedule,
    ]


def week05_system_prompt() -> str:
    """5주차 단일 agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt(week05_prompt_parts())


def week05_prompt_parts() -> list[str]:
    """1~5주차 system prompt 조각을 누적합니다."""

    """prompt 조각을 네 개로 나눈 이유.

    1. 출처 구분과 호출 규칙, 쓰기 조건을 분리했다.
       WEEK05_EXTERNAL_HISTORY_PROMPT는 어떤 데이터가 외부 저장소에 있고 어떤
       tool로 접근하는지를 정하고, WEEK05_SCHEDULE_COLLECTION_PROMPT는 조회 tool
       중 무엇을 몇 번 호출할지를 정하고, WEEK05_SHARED_SCHEDULE_WRITE_PROMPT는
       공유 저장소에 직접 등록·삭제하는 tool을 언제 쓰는지를 정한다.

    2. 마지막 조각에는 실행 시점 값이 들어간다.
       current_app_date_iso()는 호출 시점의 앱 기준 날짜를 반환하므로 상수로
       둘 수 없고, 이 함수 안에서 문자열을 만든다.

    3. 조각 순서가 우선순위에 관계된다.
       join_system_prompt는 뒤에 오는 지시를 우선한다고 안내하므로, 이번 주차의
       지시를 week04_prompt_parts() 뒤에 둔다.
    """
    return [
        *week04_prompt_parts(),
        WEEK05_EXTERNAL_HISTORY_PROMPT,
        WEEK05_SCHEDULE_COLLECTION_PROMPT,
        WEEK05_SHARED_SCHEDULE_WRITE_PROMPT,
        (
            f"오늘 날짜는 {current_app_date_iso()}이다. 이번 주(Week 5)의 범위는 "
            "외부 저장소에 있는 다른 사람의 이전 대화와 일정을 MCP tool로 불러오는 것이다. "
            "내가 저장한 참고자료와 내 일정 기록은 이전 주차 tool로 찾고, "
            "다른 사람의 대화와 일정은 MCP tool로 찾는다. "
            "일정 조회 결과를 설명할 때는 tool 결과의 rows와 schedule_summary를 근거로 삼고, "
            "rows에 없는 날짜나 시간을 추측해서 answer에 넣지 않는다."
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
