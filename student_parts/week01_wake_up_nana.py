from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool

from fixed.config import CONFIG
from fixed.langchain_trace import (
    extract_agent_events,
    extract_final_text,
    extract_langchain_trace,
    message_content_to_text,
    message_tool_call_names,
    normalize_messages_value,
    stream_chunk_messages,
)
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso, next_weekday_iso
from fixed.session_scope import DEFAULT_SESSION_SCOPE, current_session_scope


PERSONAL_SCHEDULES: list[dict[str, Any]] = []
_WEEK01_AGENT: Any | None = None
CHAT_MEMORY_PROMPT = f"""
        당신은 사용자의 개인 일정 비서 Nana다.
        오늘 날짜는 {current_app_date_iso()}이다.
        [기본 원칙]
        - 개인 일정의 생성, 조회, 삭제는 반드시 제공된 도구를 사용한다.
        - 도구를 실행하지 않은 작업을 완료했다고 말하지 않는다.
        - 일정의 실제 상태는 대화 내용보다 도구 실행 결과를 우선한다.
        - 존재하지 않는 일정이나 도구 결과를 임의로 만들어내지 않는다.
        - Week 1 일정은 현재 대화에서만 유지되는 임시 일정이다.
        - 일정 조회에는 personal_list_schedules를 사용한다.
        - 삭제할 schedule_id를 알고 있으면 personal_delete_schedule을 호출한다.
        - 사용자가 제목이나 날짜로 삭제를 요청하면 먼저 personal_list_schedules로 대상을 찾는다.
        - 일치하는 일정이 하나면 해당 schedule_id로 personal_delete_schedule을 호출한다.
        - 일치하는 일정이 여러 개면 삭제하지 말고 사용자에게 대상을 확인한다.
        - 일치하는 일정이 없으면 일정이 없다고 안내한다.
        - 일정 생성에는 제목, 날짜, 시작 시간이 필요하다.
        - 필요한 정보가 충분하면 personal_create_schedule을 호출한다.

        [날짜와 시간]
        - 날짜는 YYYY-MM-DD 형식으로 도구에 전달한다.
        - 시간은 가능한 한 HH:MM 형식으로 전달한다.
        - '오늘', '내일', '다음 주 수요일' 같은 표현은 오늘 날짜를 기준으로 해석한다.
        - 날짜나 시간이 여러 의미로 해석될 수 있으면 사용자에게 확인한다.
        
        [응답 방식]
        - 도구 실행 결과를 짧고 자연스러운 한국어로 요약한다.
        - 내부 session_id나 created_at은 사용자가 요구하지 않으면 보여주지 않는다.
        - 오류나 실패가 발생하면 성공한 것처럼 답하지 않는다.
        """


def join_system_prompt(parts: list[str]) -> str:
    """주차별 prompt 조각을 읽기 쉬운 누적 system prompt로 합칩니다."""

    header = (
        "아래 system prompt는 주차별로 누적된 안내다. "
        "같은 주제의 지시가 여러 번 나오면 더 높은 주차 또는 더 뒤에 있는 지시를 우선한다."
    )
    return "\n\n".join([header, *[part.strip() for part in parts if part.strip()]])


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def _new_personal_id() -> str:
    return f"personal_{uuid.uuid4().hex[:10]}"


def _schedule_scope(schedule: dict[str, Any]) -> str:
    """기존 직접 tool 호출 row는 기본 scope로 취급합니다."""

    return str(schedule.get("session_id") or DEFAULT_SESSION_SCOPE)


def _current_session_schedules() -> list[dict[str, Any]]:
    session_id = current_session_scope()
    return [
        schedule
        for schedule in PERSONAL_SCHEDULES
        if _schedule_scope(schedule) == session_id
    ]


@tool
def personal_create_schedule(
    title: str,
    date: str,
    start_time: str,
    end_time: str | None = None,
    attendees: list[str] | None = None,
) -> str:
    """
    현재 대화의 임시 메모리에 개인 일정을 생성합니다.

    title, date, start_time은 필수입니다. 필수 값은 누락시 사용자에게 요청한다.
    date는 YYYY-MM-DD, 시간은 HH:MM 형식을 사용합니다.
    필수 정보 외 누락된 값은 None으로 설정한다.
    생성된 일정 정보를 created_schedule로 반환합니다.
    """

    schedule = {
        "schedule_id": _new_personal_id(),
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "attendees": attendees or [],
        "created_at": _now_iso(),
        "session_id": current_session_scope(),
    }

    PERSONAL_SCHEDULES.append(schedule)

    return _json(
        {
            "ok": True,
            "tool_name": "personal_create_schedule",
            "created_schedule": schedule,
        }
    )


@tool
def personal_list_schedules(date_from: str | None = None, date_to: str | None = None) -> str:
    """
    현재 대화의 개인 일정을 날짜 범위로 조회합니다.

    date_from과 date_to는 YYYY-MM-DD 형식이며 양 끝 날짜를 포함합니다.
    특정 날짜를 조회하려면 두 인자에 같은 날짜를 전달합니다.
    시작일만 있으면 date_from만, 종료일만 있으면 date_to만 사용합니다.
    날짜 조건이 없으면 두 인자를 모두 생략합니다.
    조회된 일정 목록을 schedules로 반환합니다.
    """

    schedules = _current_session_schedules()
    if date_from is not None:
        schedules = [
            schedule
            for schedule in schedules
            if schedule["date"] >= date_from
        ]

    if date_to is not None:
        schedules = [
            schedule
            for schedule in schedules
            if schedule["date"] <= date_to
        ]

    return _json(
        {
            "ok": True,
            "tool_name": "personal_list_schedules",
            "schedules": schedules,
        }
    )


@tool
def personal_delete_schedule(schedule_id: str) -> str:
    """
    현재 대화에서 schedule_id와 일치하는 개인 일정을 삭제합니다.

    제목이나 날짜로 직접 삭제할 수 없으므로 schedule_id가 필요합니다.
    반환된 deleted 값은 실제 삭제 성공 여부를 나타냅니다.
    """
    session_id = current_session_scope()
    len_before = len(PERSONAL_SCHEDULES)

    PERSONAL_SCHEDULES[:] = [
        schedule
        for schedule in PERSONAL_SCHEDULES
        if not (
            schedule.get("schedule_id") == schedule_id
            and _schedule_scope(schedule) == session_id
        )
    ]

    deleted = len(PERSONAL_SCHEDULES) < len_before
    return _json(
        {
            "ok": True,
            "tool_name": "personal_delete_schedule",
            "deleted": deleted,
        }
    )


def week01_tools() -> list[Any]:
    """1주차에서 직접 구현한 개인 일정 CRUD 도구 목록입니다."""

    return [personal_create_schedule, personal_list_schedules, personal_delete_schedule]


def week01_system_prompt() -> str:
    """1주차 단일 Nana agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt(week01_prompt_parts())


def week01_prompt_parts() -> list[str]:
    """1주차부터 누적되는 system prompt 조각입니다."""

    return [CHAT_MEMORY_PROMPT]


def build_week01_agent() -> object:
    """Week 1 tool 목록만 노출하는 단일 LangChain agent를 만듭니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK01_AGENT
    if _WEEK01_AGENT is None:
        _WEEK01_AGENT = create_agent(
            model=chat_model(),
            tools=week01_tools(),
            system_prompt=week01_system_prompt(),
        )
    return _WEEK01_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week01_agent()


def list_personal_schedule_dicts(
        date_from: str | None = None,
        date_to: str | None = None
        ) -> list[dict[str, Any]]:
    """개인 일정 dict 목록이 필요한 내부 코드에서 사용하는 비-도구 헬퍼입니다."""

    schedules = json.loads(
        personal_list_schedules.invoke(
        {
            "date_from": date_from,
            "date_to": date_to
        }
        )
    )
    return schedules["schedules"]


def ensure_demo_personal_schedule() -> None:
    if PERSONAL_SCHEDULES:
        return
    personal_create_schedule.invoke(
        {
            "title": "개인 집중 작업",
            "date": next_weekday_iso(2),
            "start_time": "09:00",
            "end_time": "10:00",
            "attendees": [],
        }
    )
