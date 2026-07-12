from __future__ import annotations

from datetime import datetime
from typing import TypedDict


class ScheduleValidation(TypedDict):
    valid: bool
    missing_fields: list[str]
    invalid_fields: dict[str, str]


FIELD_LABELS = {
    "title": "일정 제목",
    "date": "날짜",
    "start_time": "시작 시간",
    "end_time": "종료 시간",
    "end_date": "종료 날짜",
}


def is_valid_date(value: str) -> bool:
    """값이 YYYY-MM-DD 형식의 실제 날짜인지 확인합니다."""

    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    return parsed.strftime("%Y-%m-%d") == value


def is_valid_time(value: str) -> bool:
    """값이 24시간제 HH:MM 형식의 실제 시간인지 확인합니다."""

    try:
        parsed = datetime.strptime(value, "%H:%M")
    except (TypeError, ValueError):
        return False
    return parsed.strftime("%H:%M") == value


def validate_schedule_input(
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    end_date: str | None = None,
) -> ScheduleValidation:
    """일정 생성 입력의 누락값, 형식, 시간 순서를 공통 규칙으로 검사합니다."""

    required_fields = {"title": title, "date": date, "start_time": start_time}
    missing_fields = [name for name, value in required_fields.items() if not value.strip()]
    format_rules = {
        "date": (date, is_valid_date, "YYYY-MM-DD 형식의 실제 날짜여야 합니다."),
        "start_time": (start_time, is_valid_time, "HH:MM 형식의 실제 시간이어야 합니다."),
    }
    invalid_fields = {
        name: error
        for name, (value, validator, error) in format_rules.items()
        if name not in missing_fields and not validator(value)
    }

    if end_time != "미정" and not is_valid_time(end_time):
        invalid_fields["end_time"] = "HH:MM 형식의 실제 시간이거나 '미정'이어야 합니다."
    if end_date is not None and not is_valid_date(end_date):
        invalid_fields["end_date"] = "YYYY-MM-DD 형식의 실제 날짜여야 합니다."

    times_are_valid = not any(
        name in missing_fields or name in invalid_fields
        for name in ("date", "start_time", "end_time", "end_date")
    )
    if times_are_valid and end_time != "미정":
        normalized_end_date = end_date or date
        start_at = datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M")
        end_at = datetime.strptime(f"{normalized_end_date} {end_time}", "%Y-%m-%d %H:%M")
        if end_at <= start_at:
            if end_date is None and end_time <= start_time:
                invalid_fields["end_date"] = (
                    "종료 시각이 시작 시각보다 빠르거나 같습니다. "
                    "자정을 넘기는 일정인지 종료 날짜를 확인해 주세요."
                )
            else:
                invalid_fields["end_date"] = "종료 일시는 시작 일시보다 늦어야 합니다."

    return {
        "valid": not missing_fields and not invalid_fields,
        "missing_fields": missing_fields,
        "invalid_fields": invalid_fields,
    }


def clarification_question(validation: ScheduleValidation, title: str | None = None) -> str | None:
    """공통 검증 결과를 사용자가 한 번에 답할 수 있는 질문으로 바꿉니다."""

    fields = list(validation["missing_fields"])
    fields.extend(name for name in validation["invalid_fields"] if name not in fields)
    if not fields:
        return None
    if fields == ["start_time"] and title:
        return f"{title} 일정은 몇 시에 시작하나요?"
    labels = [FIELD_LABELS.get(name, name) for name in fields]
    if len(labels) == 1:
        return f"{labels[0]}은 무엇인가요?"
    return f"{', '.join(labels[:-1])}와 {labels[-1]}은 무엇인가요?"
