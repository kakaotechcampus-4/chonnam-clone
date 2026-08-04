from __future__ import annotations

from datetime import datetime
from typing import TypedDict


class ScheduleValidation(TypedDict):
    valid: bool
    missing_fields: list[str]
    invalid_fields: dict[str, str]


class ScheduleInputValidationError(ValueError):
    """제공된 일정 값의 형식이나 범위가 잘못된 경우 발생합니다."""

    def __init__(self, invalid_fields: dict[str, str]) -> None:
        self.invalid_fields = dict(invalid_fields)
        super().__init__(f"일정 입력값이 유효하지 않습니다: {self.invalid_fields}")


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
    title: str | None,
    date: str | None,
    start_time: str | None,
    end_time: str | None = None,
    end_date: str | None = None,
) -> ScheduleValidation:
    """일정 생성 입력의 누락값, 형식, 시간 순서를 공통 규칙으로 검사합니다."""

    required_fields = {
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
    }
    missing_fields = [
        name
        for name, value in required_fields.items()
        if value is None or not value.strip()
    ]
    invalid_fields: dict[str, str] = {}

    if date and not is_valid_date(date):
        invalid_fields["date"] = "YYYY-MM-DD 형식의 실제 날짜여야 합니다."
    if start_time and not is_valid_time(start_time):
        invalid_fields["start_time"] = "HH:MM 형식의 실제 시간이어야 합니다."
    if end_time and end_time != "미정" and not is_valid_time(end_time):
        invalid_fields["end_time"] = "HH:MM 형식의 실제 시간이거나 '미정'이어야 합니다."
    if end_date and not is_valid_date(end_date):
        invalid_fields["end_date"] = "YYYY-MM-DD 형식의 실제 날짜여야 합니다."

    times_are_present_and_valid = (
        date is not None
        and start_time is not None
        and end_time is not None
        and end_time != "미정"
        and not invalid_fields
    )
    if times_are_present_and_valid:
        if end_date is None and end_time <= start_time:
            missing_fields.append("end_date")
        elif end_date is not None:
            start_at = datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M")
            end_at = datetime.strptime(f"{end_date} {end_time}", "%Y-%m-%d %H:%M")
            if end_at <= start_at:
                invalid_fields["end_date"] = "종료 일시는 시작 일시보다 늦어야 합니다."

    missing_fields = list(dict.fromkeys(missing_fields))

    return {
        "valid": not missing_fields and not invalid_fields,
        "missing_fields": missing_fields,
        "invalid_fields": invalid_fields,
    }


def clarification_question(validation: ScheduleValidation, title: str | None = None) -> str | None:
    """누락된 일정 정보를 사용자가 한 번에 답할 수 있는 질문으로 바꿉니다."""

    fields = list(validation["missing_fields"])
    if not fields:
        return None
    if fields == ["start_time"] and title:
        return f"{title} 일정은 몇 시에 시작하나요?"
    labels = [FIELD_LABELS.get(name, name) for name in fields]
    if len(labels) == 1:
        return f"{labels[0]}은 무엇인가요?"
    return f"{', '.join(labels[:-1])}와 {labels[-1]}은 무엇인가요?"
