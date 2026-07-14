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
from fixed.runtime_clock import next_weekday_iso
from fixed.session_scope import DEFAULT_SESSION_SCOPE, current_session_scope
from student_parts.prompts.common import (
    CHAT_MEMORY_PROMPT,
    NANA_IDENTITY_PROMPT,
    NO_GUESSING_PROMPT,
    date_time_prompt,
    join_system_prompt,
)
from student_parts.prompts.week01 import (
    WEEK01_DELETE_SCHEDULE_PROMPT,
    WEEK01_OVERNIGHT_SCHEDULE_PROMPT,
    WEEK01_TOOL_RESULT_PROMPT,
    WEEK01_TOOL_SELECTION_PROMPT,
)
from student_parts.schedule_clarification import (
    is_valid_date as _is_valid_date,
    is_valid_time as _is_valid_time,
    validate_schedule_input as _validate_schedule_input,
)


PERSONAL_SCHEDULES: list[dict[str, Any]] = []
_WEEK01_AGENT: Any | None = None

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
    return [schedule for schedule in PERSONAL_SCHEDULES if _schedule_scope(schedule) == session_id]


@tool
def personal_create_schedule(
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    end_date: str | None = None,
    attendees: list[str] | None = None,
) -> str:
    """새 개인 일정을 생성합니다.

    사용자가 일정을 만들거나 등록해 달라고 요청할 때 사용합니다.
    date와 end_date는 YYYY-MM-DD, 시간은 HH:MM 형식으로 전달합니다.
    end_date를 생략하면 date와 같은 날로 처리합니다.
    """

    validation = _validate_schedule_input(title, date, start_time, end_time, end_date)
    if not validation["valid"]:
        return _json(
            {
                "ok": False,
                "tool_name": "personal_create_schedule",
                "error": "invalid_input",
                "missing_fields": validation["missing_fields"],
                "invalid_fields": validation["invalid_fields"],
            }
        )

    schedule = {
        "id": _new_personal_id(),
        "title": title.strip(),
        "date": date,
        "start_time": start_time,
        "end_date": end_date or date,
        "end_time": end_time,
        "attendees": list(attendees or []),
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
    """현재 대화의 개인 일정을 조회합니다.

    사용자가 일정 목록이나 특정 날짜 범위의 일정을 확인할 때 사용합니다.
    date_from과 date_to는 YYYY-MM-DD 형식이며, 생략하면 해당 경계를 제한하지 않습니다.
    """

    schedules = _current_session_schedules()
    if date_from:
        schedules = [schedule for schedule in schedules if schedule["date"] >= date_from]
    if date_to:
        schedules = [schedule for schedule in schedules if schedule["date"] <= date_to]

    return _json(
        {
            "ok": True,
            "tool_name": "personal_list_schedules",
            "schedules": schedules,
        }
    )


@tool
def personal_delete_schedule(schedule_id: str) -> str:
    """현재 대화의 개인 일정을 정확한 일정 ID로 삭제합니다.

    사용자가 기존 일정을 취소하거나 삭제할 때 사용합니다.
    제목이나 날짜가 아니라 조회 결과의 정확한 schedule_id를 전달해야 합니다.
    """

    session_id = current_session_scope()
    before_count = len(PERSONAL_SCHEDULES)
    PERSONAL_SCHEDULES[:] = [
        schedule
        for schedule in PERSONAL_SCHEDULES
        if not (schedule.get("id") == schedule_id and _schedule_scope(schedule) == session_id)
    ]
    deleted = len(PERSONAL_SCHEDULES) < before_count

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
    """공통 정책과 Week 1 일정 CRUD 정책을 명시적으로 조합합니다."""

    return [
        NANA_IDENTITY_PROMPT,
        date_time_prompt(),
        NO_GUESSING_PROMPT,
        CHAT_MEMORY_PROMPT,
        WEEK01_TOOL_SELECTION_PROMPT,
        WEEK01_OVERNIGHT_SCHEDULE_PROMPT,
        WEEK01_DELETE_SCHEDULE_PROMPT,
        WEEK01_TOOL_RESULT_PROMPT,
    ]


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


def list_personal_schedule_dicts(date_from: str | None = None, date_to: str | None = None) -> list[dict[str, Any]]:
    """개인 일정 dict 목록이 필요한 내부 코드에서 사용하는 비-도구 헬퍼입니다."""

    schedules = json.loads(personal_list_schedules.invoke({"date_from": date_from, "date_to": date_to}))
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
