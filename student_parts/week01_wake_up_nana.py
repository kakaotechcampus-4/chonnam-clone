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

CHAT_MEMORY_PROMPT = """
현재 대화에서 사용자가 이미 제공한 일정 정보를 기억한다.
후속 답변을 받으면 이전 정보와 합쳐 누락된 값만 보완하고, 이미 받은 값을 다시 묻지 않는다.
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
    return [schedule for schedule in PERSONAL_SCHEDULES if _schedule_scope(schedule) == session_id]


def _is_valid_date(value: str) -> bool:
    """값이 YYYY-MM-DD 형식의 실제 날짜인지 확인합니다."""

    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    return parsed.strftime("%Y-%m-%d") == value


def _is_valid_time(value: str) -> bool:
    """값이 24시간제 HH:MM 형식의 실제 시간인지 확인합니다."""

    try:
        parsed = datetime.strptime(value, "%H:%M")
    except (TypeError, ValueError):
        return False
    return parsed.strftime("%H:%M") == value


def _validate_schedule_input(
    title: str,
    date: str,
    start_time: str,
    end_time: str,
) -> dict[str, Any]:
    """일정 생성 입력의 누락값, 형식, 시간 순서를 검사합니다."""

    required_fields = {
        "title": title,
        "date": date,
        "start_time": start_time,
    }
    missing_fields = [field_name for field_name, value in required_fields.items() if not value.strip()]

    format_rules = {
        "date": (
            date,
            _is_valid_date,
            "YYYY-MM-DD 형식의 실제 날짜여야 합니다.",
        ),
        "start_time": (
            start_time,
            _is_valid_time,
            "HH:MM 형식의 실제 시간이어야 합니다.",
        ),
    }
    invalid_fields = {
        field_name: error_message
        for field_name, (value, validator, error_message) in format_rules.items()
        if field_name not in missing_fields and not validator(value)
    }

    if end_time != "미정" and not _is_valid_time(end_time):
        invalid_fields["end_time"] = "HH:MM 형식의 실제 시간이거나 '미정'이어야 합니다."

    times_are_valid = (
        "start_time" not in missing_fields
        and "start_time" not in invalid_fields
        and "end_time" not in invalid_fields
    )
    if times_are_valid and end_time != "미정" and end_time <= start_time:
        invalid_fields["end_time"] = "시작 시간보다 늦어야 합니다."

    return {
        "valid": not missing_fields and not invalid_fields,
        "missing_fields": missing_fields,
        "invalid_fields": invalid_fields,
    }


@tool
def personal_create_schedule(
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    attendees: list[str] | None = None,
) -> str:
    """새 개인 일정을 생성합니다.

    사용자가 일정을 만들거나 등록해 달라고 요청할 때 사용합니다.
    date는 YYYY-MM-DD, start_time과 지정된 end_time은 HH:MM 형식으로 전달합니다.
    """

    validation = _validate_schedule_input(title, date, start_time, end_time)
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
    """1주차부터 누적되는 system prompt 조각입니다."""

    return [
        f"""
        너는 개인 일정 관리 비서 Nana다.
        현재 날짜는 {current_app_date_iso()}다.

        사용자의 실제 의도를 기준으로 개인 일정 생성, 조회, 삭제 tool을 선택한다.
        일정과 관계없는 일반 대화에는 tool을 호출하지 않는다.

        tool 호출 전에 tool schema의 필수 인자를 확인한다.
        필수값이 없거나 여러 의미로 해석될 수 있으면 값을 추측하지 말고,
        확인이 필요한 항목만 모아 사용자에게 한 번에 질문한다.

        날짜는 YYYY-MM-DD, 시간은 HH:MM 형식으로 tool에 전달한다.
        '오늘', '내일', '다음 주 화요일' 같은 상대 날짜는 현재 날짜를 기준으로 해석한다.

        삭제에는 정확한 schedule_id가 필요하다.
        schedule_id를 모르면 먼저 personal_list_schedules를 사용한다.
        후보가 하나로 명확할 때만 personal_delete_schedule을 호출하고,
        후보가 여러 개면 임의로 삭제하지 말고 사용자에게 선택을 요청한다.

        tool 결과를 확인한 뒤 답한다.
        ok가 false이면 완료했다고 말하지 말고 missing_fields와 invalid_fields를 바탕으로
        필요한 값만 다시 질문한다.
        사용자에게는 한국어로 간결하고 친절하게 답한다.
        """,
        CHAT_MEMORY_PROMPT,
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
