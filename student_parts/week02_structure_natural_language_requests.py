from __future__ import annotations

import json
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.tools import tool
from pydantic import BaseModel, Field

from fixed.config import CONFIG
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from student_parts.week01_wake_up_nana import (
    join_system_prompt,
    week01_prompt_parts,
    week01_tools,
)

RequestKind = Literal[
    "personal_schedule", "group_schedule", "todo", "reminder", "unknown"
]
Priority = Literal["low", "medium", "high"]
_WEEK02_AGENT: Any | None = None


class StructuredRequest(BaseModel):
    """LLM structured output으로 추출하는 2주차 요청 스키마입니다."""

    kind: RequestKind = Field(
        description="요청 종류: 개인 일정, 그룹 일정, 할 일, 알림, 알 수 없음"
    )
    title: str | None = Field(
        default=None,
        description="일정/할 일/알림의 핵심 제목. 모르면 None",
    )
    date: str | None = Field(
        default=None,
        description="확정된 날짜. YYYY-MM-DD 형식, 모르면 None",
    )
    start_time: str | None = Field(
        default=None,
        description="확정된 시작 시간. HH:MM 형식, 모르면 None",
    )
    end_time: str | None = Field(
        default=None,
        description="확정된 종료 시간. HH:MM 형식, 모르면 None",
    )
    members: list[str] = Field(
        default_factory=list,
        description="참석자/관련 멤버 이름 목록. 없거나 모르면 빈 list",
    )
    priority: Priority = Field(
        default="medium",
        description="우선순위: low, medium, high 중 하나",
    )
    original_text: str = Field(
        default="",
        description="구조화의 근거가 된 원문 요청 전체",
    )


class StructuredRequestBatch(BaseModel):
    """여러 자연어 의도를 StructuredRequest 목록으로 나누는 메인과제 스키마입니다."""

    requests: list[StructuredRequest] = Field(
        default_factory=list,
        description="요청 리스트",
    )
    base_date: str = Field(
        default_factory=current_app_date_iso,
        description="상대 날짜 해석 시 기준 날짜(YYYY-MM-DD)",
    )


def _coerce_structured_request(value: Any) -> StructuredRequest:
    """LangChain structured output 결과를 StructuredRequest로 정규화합니다."""
    
    if isinstance(value, StructuredRequest) :
        return value
    
    if isinstance(value, dict) :
        return StructuredRequest.model_validate(value)
    
    raise RuntimeError("잘못된 형태")


def extract_structured_request(text: str) -> StructuredRequest:
    """Week 3 이상에서 agent를 새로 띄우지 않고 자연어를 StructuredRequest로 바꿉니다."""

    model = chat_model().with_structured_output(
        StructuredRequest,
        method="function_calling"
    )

    result = model.invoke(
        [
            ("system", join_system_prompt(week02_prompt_parts())),
            ("user", text),
        ]
    )

    return _coerce_structured_request(result)


@tool
def extract_schedule_request(query: str) -> str:
    """일정 저장/조회/조율/알림 처리 전에 호출하는 구조화 도구입니다.

    Args:
        query: 사용자가 방금 입력한 일정 관련 자연어 요청, 또는 이전 tool 호출에서 받은
            Week 1 JSON payload 문자열입니다. 내용을 요약하거나 일부만 전달하지 말고
            원문 전체를 그대로 넣습니다.

    Returns:
        StructuredRequest로 변환된 결과를 담은 JSON 문자열입니다.
    """

    structured_request = extract_structured_request(query)

    result = {
        "ok": True,
        "tool_name": "extract_schedule_request",
        "base_date": current_app_date_iso(),
        "structured_request": structured_request.model_dump(),
    }

    return json.dumps(result,ensure_ascii=False)


def week02_tools() -> list[Any]:
    """Week 2 agent에 Week 1 도구를 노출해 tool JSON을 structured_response 근거로 씁니다."""

    return week01_tools()


def week02_system_prompt() -> str:
    """2주차 agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt(
        [
            *week02_prompt_parts(),
            "최종 답변은 반드시 StructuredRequestBatch 형식으로 반환한다. 요청이 하나여도 requests에 StructuredRequest를 넣는다.",
            "personal_create_schedule 결과 JSON의 created_schedule을 읽어서 StructuredRequest의 필드를 채운다.",
            "personal_list_schedules 결과 JSON의 schedules 배열에 항목이 있으면, 각 항목을 kind='personal_schedule'인 StructuredRequest로 변환해 requests에 모두 담는다.",
            "schedules 배열이 비어 있으면 kind='unknown'인 StructuredRequest 하나를 requests에 넣고 original_text에 사용자의 조회 요청 원문을 그대로 담는다.",
        ]
    )


def week02_prompt_parts() -> list[str]:
    """2주차 structured output agent가 따르는 system prompt 조각입니다."""

    return [
        *week01_prompt_parts(),
        # 날짜는 week1프롬프트에서 전달되어 작성하지 않음
        "당신은 Week2 자연어 요청 구조화 agent입니다.",
        "사용자의 자연어 요청을 kind, title, date, start_time, end_time, members, priority, original_text Field로 structured_response를 생성한다.",
        "우선순위는 중요할 시 'high', 중요하지 않을 시 'low'로 설정한다, 언급하지 않을 시 'medium'으로",
        "Week 1 tool 결과 JSON이 주어진 경우 tool을 호출하지 않고 payload를 읽어서 structured_response로 만든다.",
        "Week 2에서는 데이터 베이스 저장, RAG, 외부 멤버 일정 조율은 실행하지 않는다.",
    ]


def build_week02_agent() -> object:
    """Week 2 대화에서 structured_response를 직접 반환하는 단일 LangChain agent를 만듭니다."""

    global _WEEK02_AGENT

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")

    if _WEEK02_AGENT is None:
        _WEEK02_AGENT = create_agent(
            model=chat_model(),
            tools=week02_tools(),
            response_format=StructuredRequestBatch,
            system_prompt=week02_system_prompt(),
        )

    return _WEEK02_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week02_agent()
