from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from fixed.external_people_store import normalize_external_member_names
from fixed.langchain_trace import extract_agent_events, extract_final_text
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from fixed.schedule_decision import (
    CommonSlotCandidate,
    decide_final_slot_payload,
    find_common_available_slots_payload,
    normalize_date_bound,
)
from student_parts.week01_wake_up_nana import join_system_prompt
from student_parts.week02_structure_natural_language_requests import extract_schedule_request
from student_parts.week04_retrieve_nanas_memory import week04_prompt_parts, week04_tools
from student_parts.week05_load_kanas_past_conversations import (
    collect_member_schedules,
    extract_schedules_from_history,
    list_shared_schedules,
    load_conversation_messages,
    search_previous_conversations,
    week05_prompt_parts,
)


_NANA_SUBAGENT: Any | None = None
_KANA_SUBAGENT: Any | None = None
_SUPERVISOR_AGENT: Any | None = None
FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION = """여러 사람의 공통 가능 시간 후보를 '검증'하는 도구다. 이 도구는 후보를 대신 계산해 주지 않는다. 네(Kana agent)가 앞선 일정 조회 결과의 busy_rows를 직접 읽고, 어떤 busy row와도 겹치지 않는 시간대를 candidate_slots에 직접 채워 넘겨야 한다. candidate_slots의 각 항목은 date(YYYY-MM-DD), start_time(HH:MM), end_time(HH:MM), duration_minutes, reason(이 시간을 고른 짧은 근거)을 포함한다. 각 후보는 넘긴 busy_rows의 어떤 항목과도 시간이 겹치면 안 된다. busy_rows는 앞선 collect_member_schedules/extract_schedules_from_history 등의 tool output에서 그대로 복사해 함께 넘긴다(생략하면 도구가 자동 조회한다). 이 도구 결과로 답변을 끝내지 말고, 검증된 후보 중 하나를 골라 반드시 decide_final_slot을 이어서 호출한다."""
DECIDE_FINAL_SLOT_DESCRIPTION = """회의/모임의 최종 시간을 '기록'하는 도구다. 이 도구는 최종 시간을 자동으로 선택하지 않는다. 네(Kana agent)가 find_common_available_slots로 검증된 후보 중 하나를 직접 골라 넘겨야 한다. 고른 후보는 selected_index(candidate_slots 내 index) 또는 selected_slot(후보 객체)로 지정하고, final_slot을 'YYYY-MM-DD HH:MM-HH:MM' 형식 문자열로 함께 채운다. 최종 시간을 확정했으면 needs_agent_selection=false, 아직 고르지 못했으면 final_slot=null, needs_agent_selection=true로 둔다. reason에는 이 시간을 고르거나 보류한 사용자-facing 설명을 적는다. 근거 trace를 위해 candidate_slots, busy_rows, member_names, date_from/date_to도 함께 넘긴다."""


def week06_system_prompt() -> str:
    """6주차 supervisor agent가 따르는 시스템 프롬프트입니다."""

    return supervisor_system_prompt()


def week06_prompt_parts() -> list[str]:
    """1~6주차 supervisor system prompt 조각을 누적합니다."""

    return [
        *week05_prompt_parts(),
        """[Week 6 구조 — 너는 위임하는 supervisor다]
이제 너는 일을 직접 처리하지 않는다. 위 주차들의 도구 사용 지침은 하위 에이전트(Nana/Kana)가 참고할 배경 지식일 뿐이며, 너 자신은 personal_*, search_*, collect_* 같은 도구를 직접 호출하지 않는다. 너에게 주어진 도구는 nana_agent와 kana_agent 둘뿐이다.

[위임 판단 기준]
- Nana(nana_agent): 내 개인 일정 조회/생성/수정/삭제, todo·reminder 저장, 내 선호·습관 등 개인 참고자료 저장/검색, 내 과거 앱 대화 검색.
- Kana(kana_agent): 외부 팀원의 과거 대화 검색, 외부 팀원의 바쁜 시간 조회, 공유 일정 저장소 조회, 여러 사람의 공통 가능 시간을 찾아 회의/모임 시간을 조율·결정하는 일.
- 애매하면 "나 혼자의 일정·기록"은 Nana, "다른 사람과 맞추는 일정"은 Kana로 보낸다.""",
    ]


def nana_prompt_parts() -> list[str]:
    """Week 6 Nana 하위 에이전트 전용 system prompt 조각입니다."""

    return [
        *week04_prompt_parts(),
        """[너는 Nana 하위 에이전트다]
너는 supervisor가 개인 일정·기록 업무를 위임할 때 실행되는 Nana다. supervisor의 지시는 보이지 않으니, 넘겨받은 요청만 근거로 판단해 처리한다.
- 담당: 내 개인 일정 조회/생성/수정/삭제, todo·reminder 저장, 개인 참고자료 저장/검색, 내 과거 앱 대화 검색.
- 외부 팀원과의 일정 조율이나 공통 시간 찾기는 네 담당이 아니다. 그런 요청을 받으면 그 부분은 처리할 수 없다고 짧게 알린다.""",
    ]


def kana_prompt_parts() -> list[str]:
    """Week 6 Kana 하위 에이전트 전용 system prompt 조각입니다."""

    return [
        f"""너는 Nana의 동료 에이전트 Kana다. 사용자와 한국어로 대화하며, 여러 사람의 일정을 맞추는 일을 맡는다. 도구가 돌려준 데이터만 근거로 삼아 지어내지 말고 답한다.
오늘 날짜는 {current_app_date_iso()}이다.
[담당]
- 외부 팀원의 과거 대화 검색(search_previous_conversations), 특정 대화 전체 내용 조회(load_conversation_messages).
- 외부 팀원의 바쁜 시간 조회(extract_schedules_from_history), 공유 일정 저장소 조회(list_shared_schedules).
- 나와 팀원의 빈 시간을 모아 회의/모임 시간 조율(collect_member_schedules, 내 일정 "나" 자동 포함).
- 확정된 개인 일정을 앱에 저장하는 일은 Nana 담당이다. 저장이 필요하면 그건 Nana가 한다고 답한다.

[그룹 시간 조율 순서]
1) collect_member_schedules로 나와 외부 팀원의 busy-time을 모은다.
2) 그 busy_rows를 근거로 어떤 일정과도 겹치지 않는 후보 시간을 직접 골라 find_common_available_slots에 넘겨 검증한다. 도구가 후보를 대신 계산해 주지 않는다.
3) 검증된 후보 중 하나를 직접 골라 decide_final_slot으로 최종 시간을 확정한다. 아직 고르지 못하면 needs_agent_selection=true로 둔다.
find_common_available_slots에서 답을 끝내지 말고 반드시 decide_final_slot까지 이어서 호출한다.

[응답 스타일]
- conversation_id, schedule_id 같은 내부 식별자는 사용자가 요구하지 않으면 노출하지 않는다.""",
    ]


def nana_system_prompt() -> str:
    return join_system_prompt(nana_prompt_parts())


def kana_system_prompt() -> str:
    return join_system_prompt(kana_prompt_parts())


def supervisor_system_prompt() -> str:
    return join_system_prompt(
        [
            *week06_prompt_parts(),
            """[supervisor 실행 규칙]
어떤 요청이든 먼저 nana_agent 또는 kana_agent 중 정확히 하나를 호출하고, 그 반환 결과만 근거로 사용자에게 한국어로 답한다. 너 스스로 일정을 지어내거나 다른 도구를 직접 쓰지 않는다. 하위 에이전트가 돌려준 answer를 신뢰해 최종 답변을 구성하며, 그룹 조율이면 kana_agent가 올린 최종 시간(final_slot)을 답에 반영한다.""",
        ]
    )


def _tool_call_names(events: list[dict[str, Any]]) -> list[str]:
    return [event["tool_name"] for event in events if event.get("event") == "tool_call" and event.get("tool_name")]


def extract_langchain_trace(result: dict[str, Any]) -> dict[str, Any]:
    """Week 6 supervisor 실행 결과를 UI trace payload로 변환합니다."""

    events = extract_agent_events(result)
    inner_tool_names: list[str] = []
    final_slot_payload: dict[str, Any] | None = None
    final_decision_payload: dict[str, Any] | None = None
    selected_agent: str | None = None

    for event in events:
        if event.get("event") == "tool_call" and event.get("tool_name") in {"nana_agent", "kana_agent"}:
            selected_agent = event["tool_name"]
        content = event.get("content")
        if isinstance(content, dict):
            inner_tool_names.extend(content.get("inner_tool_names") or [])
            if content.get("final_slot_payload"):
                final_slot_payload = content["final_slot_payload"]
            elif "final_slot" in content:
                final_slot_payload = content
            if content.get("final_decision_payload"):
                final_decision_payload = content["final_decision_payload"]

    return {
        "events": events,
        "supervisor_selected_agent": selected_agent,
        "inner_tool_names": inner_tool_names,
        "final_slot_payload": final_slot_payload,
        "final_decision_payload": final_decision_payload,
    }


def tool_name(tool_object: Any) -> str:
    return getattr(tool_object, "name", getattr(tool_object, "__name__", str(tool_object)))


class FindCommonAvailableSlotsInput(BaseModel):
    member_names: list[str] = Field(description="공통 가능 시간을 찾아야 하는 외부 멤버 이름 목록")
    date_from: str = Field(description="조회 시작 날짜. ISO datetime이면 날짜 부분만 사용")
    date_to: str = Field(description="조회 종료 날짜. ISO datetime이면 날짜 부분만 사용")
    duration_minutes: int = Field(default=60, ge=30, le=480, description="회의 길이(분)")
    workday_start: str = Field(default="09:00", description="허용 업무 시간 시작 HH:MM")
    workday_end: str = Field(default="18:00", description="허용 업무 시간 종료 HH:MM")
    limit: int = Field(default=5, ge=1, le=20, description="최대 후보 수")
    busy_rows: list[dict[str, Any]] | None = Field(
        default=None,
        description="앞선 일정 조회 tool output에서 복사한 busy_rows. 후보는 이 row들과 overlap/겹치면 안 됩니다.",
    )
    candidate_slots: list[CommonSlotCandidate] = Field(
        default_factory=list,
        description=(
            "LLM agent가 직접 고른 후보 목록. 각 항목은 date, start_time, end_time, "
            "duration_minutes, reason을 포함하고 busy_rows와 겹치면 안 됩니다."
        ),
    )
    llm_reason: str | None = Field(default=None, description="LLM agent가 후보 목록을 고른 전체 이유")


class DecideFinalSlotInput(BaseModel):
    candidate_slots: list[Any] = Field(default_factory=list, description="find_common_available_slots 결과의 후보 목록")
    selected_slot: Any | None = Field(default=None, description="LLM agent가 직접 고른 후보 객체")
    selected_index: int | None = Field(default=None, description="LLM agent가 직접 고른 candidate_slots index")
    final_slot: str | None = Field(
        default=None,
        description="최종 확정 시간 텍스트. 형식은 'YYYY-MM-DD HH:MM-HH:MM'. 미확정이면 null",
    )
    needs_agent_selection: bool | None = Field(
        default=None,
        description="후보 선택이 더 필요하면 true, final_slot을 확정했으면 false",
    )
    member_names: list[str] | None = Field(default=None, description="회의 대상 멤버 목록")
    date_from: str | None = Field(default=None, description="요청 날짜 범위 시작")
    date_to: str | None = Field(default=None, description="요청 날짜 범위 종료")
    duration_minutes: int = Field(default=60, description="회의 길이(분)")
    reason: str | None = Field(default=None, description="최종 선택 또는 보류에 대한 사용자-facing 설명")
    busy_rows: list[dict[str, Any]] | None = Field(default=None, description="최종 결정 근거로 남길 busy_rows")


class ProposeGroupScheduleInput(BaseModel):
    """기존 호환용 그룹 일정 제안 입력입니다."""

    title: str
    member_names: list[str]
    candidate_slots: list[CommonSlotCandidate] = Field(default_factory=list)
    selected_slot: CommonSlotCandidate | None = None
    reason: str | None = None


class AgentQueryInput(BaseModel):
    """하위 에이전트 위임 입력입니다."""

    query: str


def find_common_available_slots_dict(
    member_names: list[str],
    date_from: str,
    date_to: str,
    duration_minutes: int = 60,
    workday_start: str = "09:00",
    workday_end: str = "18:00",
    limit: int = 5,
    busy_rows: list[dict[str, Any]] | None = None,
    candidate_slots: list[dict[str, Any]] | None = None,
    llm_reason: str | None = None,
) -> dict[str, Any]:
    """멤버별 busy-time rows와 LLM이 고른 후보 payload를 검증 결과로 바꿉니다."""

    external_members = [name for name in normalize_external_member_names(member_names) if name != "나"]
    date_from = normalize_date_bound(date_from)
    date_to = normalize_date_bound(date_to)

    if busy_rows is None:
        collected = json.loads(
            collect_member_schedules.invoke(
                {"member_names": external_members, "date_from": date_from, "date_to": date_to}
            )
        )
        busy_rows = collected.get("rows", [])

    return find_common_available_slots_payload(
        member_names=["나", *external_members],
        date_from=date_from,
        date_to=date_to,
        busy_rows=busy_rows,
        duration_minutes=duration_minutes,
        workday_start=workday_start,
        workday_end=workday_end,
        limit=limit,
        candidate_slots=candidate_slots,
        llm_reason=llm_reason,
    )


@tool(description=FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION, args_schema=FindCommonAvailableSlotsInput)
def find_common_available_slots(
    member_names: list[str],
    date_from: str,
    date_to: str,
    duration_minutes: int = 60,
    workday_start: str = "09:00",
    workday_end: str = "18:00",
    limit: int = 5,
    busy_rows: list[dict[str, Any]] | None = None,
    candidate_slots: list[Any] | None = None,
    llm_reason: str | None = None,
) -> str:

    return json.dumps(
        find_common_available_slots_dict(
            member_names=member_names,
            date_from=date_from,
            date_to=date_to,
            duration_minutes=duration_minutes,
            workday_start=workday_start,
            workday_end=workday_end,
            limit=limit,
            busy_rows=busy_rows,
            candidate_slots=candidate_slots,
            llm_reason=llm_reason,
        ),
        ensure_ascii=False,
    )


@tool(description=DECIDE_FINAL_SLOT_DESCRIPTION, args_schema=DecideFinalSlotInput)
def decide_final_slot(
    candidate_slots: list[Any] | None = None,
    selected_slot: Any | None = None,
    selected_index: int | None = None,
    final_slot: str | None = None,
    needs_agent_selection: bool | None = None,
    member_names: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    duration_minutes: int = 60,
    reason: str | None = None,
    busy_rows: list[dict[str, Any]] | None = None,
) -> str:

    return json.dumps(
        decide_final_slot_payload(
            candidate_slots=candidate_slots,
            selected_slot=selected_slot,
            selected_index=selected_index,
            final_slot=final_slot,
            needs_agent_selection=needs_agent_selection,
            member_names=member_names,
            date_from=date_from,
            date_to=date_to,
            duration_minutes=duration_minutes,
            reason=reason,
            busy_rows=busy_rows,
        ),
        ensure_ascii=False,
    )


def kana_tools() -> list[Any]:
    return [
        extract_schedule_request,
        search_previous_conversations,
        load_conversation_messages,
        extract_schedules_from_history,
        list_shared_schedules,
        collect_member_schedules,
        find_common_available_slots,
        decide_final_slot,
    ]


def supervisor_tools() -> list[Any]:
    return [nana_agent, kana_agent]


def agent_tool_names(agent_name: str) -> list[str]:
    if agent_name == "nana_agent":
        return [tool_name(item) for item in week04_tools()]
    if agent_name == "kana_agent":
        return [tool_name(item) for item in kana_tools()]
    if agent_name == "supervisor":
        return [tool_name(item) for item in supervisor_tools()]
    return []


@tool(args_schema=ProposeGroupScheduleInput)
def propose_group_schedule(
    title: str,
    member_names: list[str],
    candidate_slots: list[Any] | None = None,
    selected_slot: Any | None = None,
    reason: str | None = None,
) -> str:
    """Kana가 고른 후보 시간으로 최종 그룹 일정 결정 페이로드를 만듭니다."""

    slots = [slot.model_dump() if hasattr(slot, "model_dump") else slot for slot in candidate_slots or []]
    selected = selected_slot.model_dump() if hasattr(selected_slot, "model_dump") else selected_slot
    payload = {
        "title": title,
        "members": normalize_external_member_names(member_names),
        "selected_slot": selected,
        "status": "confirmed" if selected else "needs_manual_review",
        "reason": reason,
        "candidate_slots": slots,
    }
    return json.dumps(
        {
            "ok": True,
            "tool_name": "propose_group_schedule",
            "final_decision": payload,
        },
        ensure_ascii=False,
    )


@tool(args_schema=AgentQueryInput)
def nana_agent(query: str) -> str:
    """개인 일정과 개인 RAG 작업을 프롬프트 기반 Nana 하위 에이전트에게 위임합니다."""

    global _NANA_SUBAGENT
    if _NANA_SUBAGENT is None:
        _NANA_SUBAGENT = create_agent(
            model=chat_model(),
            tools=week04_tools(),
            system_prompt=nana_system_prompt(),
        )

    result = _NANA_SUBAGENT.invoke({"messages": [{"role": "user", "content": query}]})
    events = extract_agent_events(result)

    return json.dumps(
        {
            "ok": True,
            "tool_name": "nana_agent",
            "selected_agent": "nana_agent",
            "answer": extract_final_text(result),
            "trace": {"events": events},
            "inner_tool_names": _tool_call_names(events),
        },
        ensure_ascii=False,
    )


@tool(args_schema=AgentQueryInput)
def kana_agent(query: str) -> str:
    """그룹 일정 종합 작업을 프롬프트 기반 Kana 하위 에이전트에게 위임합니다."""

    global _KANA_SUBAGENT
    if _KANA_SUBAGENT is None:
        _KANA_SUBAGENT = create_agent(
            model=chat_model(),
            tools=kana_tools(),
            system_prompt=kana_system_prompt(),
        )

    result = _KANA_SUBAGENT.invoke({"messages": [{"role": "user", "content": query}]})
    events = extract_agent_events(result)

    final_slot_payload: dict[str, Any] | None = None
    final_decision_payload: Any | None = None
    for event in events:
        content = event.get("content")
        if not isinstance(content, dict):
            continue
        if "final_slot" in content:
            final_slot_payload = content
        if content.get("final_decision") is not None:
            final_decision_payload = content["final_decision"]

    return json.dumps(
        {
            "ok": True,
            "tool_name": "kana_agent",
            "selected_agent": "kana_agent",
            "answer": extract_final_text(result),
            "trace": {"events": events},
            "inner_tool_names": _tool_call_names(events),
            "final_slot_payload": final_slot_payload,
            "final_decision_payload": final_decision_payload,
        },
        ensure_ascii=False,
    )


def build_langchain_supervisor_agent() -> object:
    """nana_agent와 kana_agent 위임 도구만 노출하는 LangChain v1 슈퍼바이저입니다."""

    global _SUPERVISOR_AGENT
    if _SUPERVISOR_AGENT is None:
        _SUPERVISOR_AGENT = create_agent(
            model=chat_model(),
            tools=supervisor_tools(),
            system_prompt=supervisor_system_prompt(),
        )
    return _SUPERVISOR_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_langchain_supervisor_agent()
