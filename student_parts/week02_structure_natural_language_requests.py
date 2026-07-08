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
    """LLM structured output으로 추출되는 2주차 요청 스키마입니다."""

    kind: RequestKind = Field(description="요청 종류")
    title: str | None = Field(default=None, description="일정")
    date: str | None = Field(default=None, description="날짜(YYYY-MM-DD)")
    start_time: str | None = Field(default=None, description="시작 시간(HH:MM)")
    end_time: str | None = Field(default=None, description="종료 시간(HH:MM)")
    members: list[str] = Field(default_factory=list, description="일정 참가자 목록")
    priority: Priority = Field(default="medium", description="요청 우선순위")
    original_text: str = Field(default="", description="사용자 요청 원문")


class StructuredRequestBatch(BaseModel):
    """여러 자연어 의도를 StructuredRequest 목록으로 나누는 2차 과제 스키마입니다."""

    requests: list[StructuredRequest] = Field(
        default_factory=list,
        description="요청 리스트",
    )
    base_date: str = Field(
        default_factory=current_app_date_iso,
        description="상대 날짜 해석 시 기준 날짜(YYYY-MM-DD)",
    )


def _coerce_structured_request(value: Any) -> StructuredRequest:
    """이후 회차에서 사용할 StructuredRequest 정규화 예약 함수입니다."""

    ...


def extract_structured_request(text: str) -> StructuredRequest:
    """이후 회차에서 사용할 단건 구조화 예약 함수입니다."""

    ...


@tool
def extract_schedule_request(query: str) -> str:
    """이후 회차에서 저장 흐름과 연결할 예약 tool입니다."""

    ...


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
