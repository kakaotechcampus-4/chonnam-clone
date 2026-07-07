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

# TODO: 현재 채팅 기억 관련 공통 system prompt를 자유롭게 추가하세요.
CHAT_MEMORY_PROMPT = ""


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
    return [schedule for schedule in PERSONAL_SCHEDULES if _schedule_scope(schedule) == session_id]


@tool
def personal_create_schedule(
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    attendees: list[str] | None = None,
) -> str:
    """Nana의 개인 일정을 현재 대화의 임시 메모리에 생성합니다."""

    # TODO: PERSONAL_SCHEDULES에 현재 대화 범위의 개인 일정을 생성하세요.
    schedule = {
        "id": _new_personal_id(),
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "attendees": attendees or [],
        "created_at": _now_iso(),
        "session_id": current_session_scope(),
    }
    PERSONAL_SCHEDULES.append(schedule)
    return _json({"ok": True, "tool_name": "personal_create_schedule", "created_schedule": schedule})


@tool
def personal_list_schedules(date_from: str | None = None, date_to: str | None = None) -> str:
    """선택한 시작일과 종료일 범위에 포함되는 Nana의 개인 일정을 조회합니다."""

    # TODO: 현재 대화 범위의 PERSONAL_SCHEDULES를 날짜 조건으로 조회하세요.
    schedules = _current_session_schedules()

    if date_from:
        schedules = [s for s in schedules if s["date"] >= date_from]
    if date_to:
        schedules = [s for s in schedules if s["date"] <= date_to]

    return _json({
        "ok": True, 
        "tool_name": "personal_list_schedules", 
        "schedules": schedules
    })


@tool
def personal_delete_schedule(schedule_id: str) -> str:
    """일정 ID에 해당하는 개인 일정을 삭제합니다."""

    # TODO: 현재 대화 범위에서 schedule_id가 일치하는 개인 일정을 삭제하세요.
    session_id = current_session_scope()
    deleted_schedule = None

    for index, schedule in enumerate(PERSONAL_SCHEDULES):
        if schedule["id"] == schedule_id and _schedule_scope(schedule) == session_id:
            deleted_schedule = PERSONAL_SCHEDULES.pop(index)
            break

    return _json({
        "ok": deleted_schedule is not None,
        "tool_name": "personal_delete_schedule",
        "deleted": 1 if deleted_schedule is not None else 0,
        "deleted_schedule": deleted_schedule,
    })
    


def week01_tools() -> list[Any]:
    """1주차에서 직접 구현한 개인 일정 CRUD 도구 목록입니다."""

    return [personal_create_schedule, personal_list_schedules, personal_delete_schedule]


def week01_system_prompt() -> str:
    """1주차 단일 Nana agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt(week01_prompt_parts())


def week01_prompt_parts() -> list[str]:
    """1주차부터 누적되는 system prompt 조각입니다."""

    return [
        # TODO: Week 1 Nana 일정 agent system prompt를 자유롭게 추가하세요.
        "너는 개인 일정 메이트 나나다. 오늘은 " + current_app_date_iso() + "이다. "
        "상대 날짜는 이 날짜 기준으로 YYYY-MM-DD로 바꾼다. "
        "일정 생성, 조회, 삭제가 필요하면 반드시 알맞은 도구를 호출한 뒤 짧게 답한다."
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
