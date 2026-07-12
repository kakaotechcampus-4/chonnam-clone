from __future__ import annotations

import json
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.tools import tool
from pydantic import BaseModel, Field, model_validator

from fixed.config import CONFIG
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from student_parts.prompts.common import (
    CHAT_MEMORY_PROMPT,
    NANA_IDENTITY_PROMPT,
    NO_GUESSING_PROMPT,
    date_time_prompt,
    join_system_prompt,
)
from student_parts.prompts.week02 import (
    WEEK02_CLASSIFICATION_PROMPT,
    WEEK02_CLARIFICATION_STATE_PROMPT,
    WEEK02_PERSONAL_CREATE_TOOL_PROMPT,
    WEEK02_SCOPE_PROMPT,
    WEEK02_STRUCTURED_OUTPUT_PROMPT,
    WEEK02_TOOL_PAYLOAD_MAPPING_PROMPT,
)
from student_parts.week01_wake_up_nana import week01_tools


RequestKind = Literal["personal_schedule", "group_schedule", "todo", "reminder", "unknown"]
_WEEK02_AGENT: Any | None = None


# [2주차 1회차 수강생 구현 가이드]
#
# 목표
#   Week 1 tool이 만든 JSON payload나 사용자의 한국어 자연어 요청을 일정 앱이 읽을 수 있는
#   StructuredRequest/StructuredRequestBatch로 바꿉니다. Week 1은 이미 정해진 인자를 받아
#   임시 일정을 만들었다면, Week 2는 그 tool 결과 JSON과 "내일 오후 3시" 같은 자연어를
#   날짜/시간/종류/멤버 필드로 구조화하는 단계입니다. 구조화 결과는 아직 저장하지 않습니다.
#
# 구현 위치와 사용할 코드
#   - 이 파일(student_parts/week02_structure_natural_language_requests.py)의 StructuredRequest 스키마와
#     StructuredRequestBatch, week02_tools(), week02_prompt_parts(), week02_system_prompt(),
#     build_week02_agent()를 확인합니다.
#   - build_week02_agent()는 langchain.agents.create_agent, fixed/llm.py의 chat_model(),
#     week02_system_prompt(), response_format=Week02Response를 사용해 Week 2 agent를 만듭니다.
#   - week02_tools()는 Week 1 도구 목록을 그대로 가져옵니다. Week 2 agent는 개인 일정 생성 요청에서
#     personal_create_schedule이 반환한 created_schedule JSON payload를 읽고
#     Week02Response가 완료되면 내부 StructuredRequestBatch를 최종 구조화 결과로 확인합니다.
#   - week02_prompt_parts()는 prompts/common.py의 공통 정책과 prompts/week02.py의
#     Week 2 전용 정책을 선택하며 Week 1 CRUD 프롬프트 전체를 상속하지 않습니다.
#
# 구현 대상
#   1. StructuredRequest 스키마
#      - kind/title/date/start_time/end_time/members/priority/reason/original_text 필드가
#        이후 Week 3 저장 payload의 기준이 됩니다.
#      - kind는 RequestKind Literal에 들어 있는 값만 허용합니다.
#      - 각 필드에는 LLM structured output이 이해할 수 있도록 한국어 description을 붙입니다.
#
#   2. StructuredRequestBatch 스키마
#      - requests에는 StructuredRequest 목록을 담고, 요청이 하나뿐이어도 list 형태를 유지합니다.
#      - base_date에는 상대 날짜 해석 기준일(current_app_date_iso)을 담습니다.
#
#   3. Week 2 agent 세로 슬라이스
#      - week02_tools()는 Week 1 tool 목록을 그대로 반환합니다.
#      - week02_prompt_parts()와 week02_system_prompt()에는 자연어/Week 1 tool JSON을
#        StructuredRequestBatch로 구조화하라는 지시를 넣습니다.
#      - build_week02_agent()에 response_format=Week02Response를 연결해
#        ./run.sh --week2가 동작하게 합니다.
#      - 개인 일정 생성 요청에서는 Week 1 personal_create_schedule tool 결과의 created_schedule JSON을
#        LLM이 읽어 StructuredRequestBatch로 최종 변환하는 흐름을 확인합니다.
#
# StructuredRequest 읽는 법
#   - kind: personal_schedule, group_schedule, todo, reminder, unknown 중 하나입니다.
#   - title/date/start_time/end_time: 일정 앱이 실제 저장이나 생성에 사용할 핵심 필드입니다.
#   - members: 참석자/관련 멤버 list입니다. 모르면 빈 list로 둡니다.
#   - priority/reason/original_text: 할 일 우선순위, 판단 근거, 원문 보존용 필드입니다.
#   - 모르는 값을 억지로 만들지 않는 것이 중요합니다. 확실하지 않으면 None 또는 빈 list가 안전합니다.
#   - date/start_time/end_time은 확실할 때만 YYYY-MM-DD, HH:MM 형식으로 채웁니다.
#
# 참고 코드
#   - prompts/common.py / prompts/week02.py
#      공통 정책과 Week 2 분류·재질문·구조화 정책을 역할별로 제공합니다.
#   - week01_tools()
#      Week 1 개인 일정 tool 목록입니다. Week 2 agent는 이 tool 결과 JSON을 구조화 근거로 씁니다.
#
# 검증 방법
#   ./run.sh --week2로 실행한 뒤 "다음 주 화요일 오후 3시에 철수랑 회의 잡아줘" 같은 문장을 입력합니다.
#   최종 답변이 StructuredRequestBatch class 형식의 structured_response로 나오는지 확인합니다.
#
# 함수별 동작 설명
#   - StructuredRequest
#     Week 2 structured output의 중심 스키마입니다. LLM이 자연어에서 뽑은 요청 종류, 제목, 날짜, 시간,
#     멤버, 우선순위, 근거, 원문을 이 class 필드에 맞춰 반환합니다.
#
#   - StructuredRequestBatch
#     StructuredRequest 여러 개와 base_date를 함께 담는 최종 structured_response 스키마입니다.
#     요청이 하나뿐이어도 requests list 안에 StructuredRequest 하나를 담습니다.
#
#   - week02_tools()
#     Week 1 개인 일정 tool을 그대로 노출합니다. Week 2 agent는 개인 일정 생성 요청에서
#     created_schedule JSON을 structured_response의 근거로 사용할 수 있습니다.
#
#   - week02_system_prompt() / week02_prompt_parts()
#     선택한 공통·Week 2 정책을 조합하고, system_prompt 함수는 추가 지시를 직접 작성하지 않습니다.
#
#   - build_week02_agent() / build_week_agent()
#     response_format=Week02Response가 설정된 agent를 만들고 재사용합니다.
#     build_week_agent()는 실행기가 찾는 표준 entry point입니다.


class StructuredRequest(BaseModel):
    """LLM structured output으로 추출되는 2주차 요청 스키마입니다."""

    kind: RequestKind = Field(
        ...,
        description=(
            "요청 종류입니다. 개인 일정은 personal_schedule, 그룹 일정은 group_schedule, "
            "할 일은 todo, 알림은 reminder, 분류가 어렵다면 unknown입니다."
        ),
    )
    title: str | None = Field(
        None,
        description="일정, 할 일, 알림의 제목입니다. 확실하지 않으면 None입니다.",
    )
    date: str | None = Field(
        None,
        description=(
            "요청 날짜입니다. 확실할 때만 YYYY-MM-DD 형식으로 채웁니다. "
            "사용자가 날짜를 말하지 않았다면 base_date를 복사하지 말고 None입니다."
        ),
    )
    start_time: str | None = Field(
        None,
        description="시작 시각입니다. 확실할 때만 24시간제 HH:MM 형식으로 채우고, 알 수 없으면 None입니다.",
    )
    end_time: str | None = Field(
        None,
        description="종료 시각입니다. 확실할 때만 24시간제 HH:MM 형식으로 채우고, 알 수 없으면 None입니다.",
    )
    members: list[str] = Field(
        default_factory=list,
        description="참석자나 관련 멤버 이름 목록입니다. 없거나 알 수 없으면 빈 리스트입니다.",
    )
    priority: str | None = Field(
        None,
        description="할 일이나 요청의 우선순위입니다. 사용자가 말하지 않았거나 확실하지 않으면 None입니다.",
    )
    reason: str | None = Field(
        None,
        description="요청을 이 구조로 분류하고 필드를 채운 근거를 짧게 설명합니다.",
    )
    original_text: str = Field(
        "",
        description="구조화의 근거가 된 사용자 원문 또는 tool 결과 요약입니다.",
    )


class StructuredRequestBatch(BaseModel):
    """여러 자연어 의도를 StructuredRequest 목록으로 나누는 2차 과제 스키마입니다."""

    requests: list[StructuredRequest] = Field(
        default_factory=list,
        description="구조화된 요청 목록입니다. 요청이 하나뿐이어도 반드시 리스트에 담습니다.",
    )
    base_date: str = Field(
        default_factory=current_app_date_iso,
        description="오늘, 내일, 다음 주 같은 상대 날짜를 해석할 때 사용한 기준 날짜입니다.",
    )


class Week02Response(BaseModel):
    """LLM이 재질문 여부와 완성된 구조화 결과를 함께 판단하는 상위 응답입니다."""

    status: Literal["needs_clarification", "complete"] = Field(
        ...,
        description="필수값이 부족하거나 모호하면 needs_clarification, 아니면 complete입니다.",
    )
    clarification_question: str | None = Field(
        None,
        description="needs_clarification일 때 사용자에게 한 번에 물을 한국어 질문입니다.",
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        description="부족하거나 모호해 확인이 필요한 필드 이름 목록입니다.",
    )
    structured_request: StructuredRequestBatch | None = Field(
        None,
        description="complete일 때만 제공하는 최종 Week 2 구조화 결과입니다.",
    )

    @model_validator(mode="after")
    def validate_status_contract(self) -> "Week02Response":
        """재질문 상태와 완료 상태가 서로 모순된 필드를 갖지 않도록 검사합니다."""

        if self.status == "needs_clarification":
            if not self.clarification_question or not self.clarification_question.strip():
                raise ValueError("needs_clarification에는 clarification_question이 필요합니다.")
            if not self.missing_fields:
                raise ValueError("needs_clarification에는 missing_fields가 필요합니다.")
            if self.structured_request is not None:
                raise ValueError("needs_clarification에서는 structured_request가 없어야 합니다.")
            return self

        if self.clarification_question is not None:
            raise ValueError("complete에서는 clarification_question이 없어야 합니다.")
        if self.missing_fields:
            raise ValueError("complete에서는 missing_fields가 비어 있어야 합니다.")
        if self.structured_request is None:
            raise ValueError("complete에는 structured_request가 필요합니다.")
        return self


def _coerce_structured_request(value: Any) -> StructuredRequest:
    """이후 회차에서 사용할 StructuredRequest 정규화 예약 함수입니다."""

    if isinstance(value, StructuredRequest):
        return value
    if isinstance(value, dict):
        if "kind" in value:
            return StructuredRequest.model_validate(value)
        return StructuredRequest(
            kind="unknown",
            original_text=json.dumps(value, ensure_ascii=False),
        )
    return StructuredRequest(kind="unknown", original_text=str(value))


def extract_structured_request(text: str) -> StructuredRequest:
    """이후 회차에서 사용할 단건 구조화 예약 함수입니다."""

    return StructuredRequest(kind="unknown", original_text=text)


@tool
def extract_schedule_request(query: str) -> str:
    """이후 회차에서 저장 흐름과 연결할 예약 tool입니다."""

    structured_request = extract_structured_request(query)
    return json.dumps(
        {
            "ok": True,
            "tool_name": "extract_schedule_request",
            "structured_request": structured_request.model_dump(),
        },
        ensure_ascii=False,
    )


def week02_tools() -> list[Any]:
    """Week 2 agent에 Week 1 도구를 노출해 tool JSON을 structured_response 근거로 씁니다."""

    return week01_tools()


class Week02ResponseAgent:
    """LLM의 상위 판단 결과를 UI가 기대하는 질문 또는 StructuredRequestBatch로 변환합니다."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    @staticmethod
    def _translate(result: dict[str, Any]) -> dict[str, Any]:
        response = Week02Response.model_validate(result.get("structured_response"))
        if response.status == "needs_clarification":
            return {"messages": [{"role": "assistant", "content": response.clarification_question}]}
        return {
            "messages": list(result.get("messages") or []),
            "structured_response": response.structured_request,
        }

    def invoke(self, payload: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._translate(self._agent.invoke(payload, *args, **kwargs))

    def stream(self, payload: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        for chunk in self._agent.stream(payload, *args, **kwargs):
            response = self._structured_response_from_chunk(chunk)
            if response is None:
                yield chunk
                continue
            yield self._translate({"structured_response": response})

    @staticmethod
    def _structured_response_from_chunk(chunk: Any) -> Any | None:
        if not isinstance(chunk, dict):
            return None
        if "structured_response" in chunk:
            return chunk["structured_response"]
        for value in chunk.values():
            if isinstance(value, dict) and "structured_response" in value:
                return value["structured_response"]
        return None


def week02_system_prompt() -> str:
    """선택된 공통·Week 2 정책 조각을 하나의 시스템 프롬프트로 조합합니다."""

    return join_system_prompt(week02_prompt_parts())


def week02_prompt_parts() -> list[str]:
    """Week 1 전체가 아닌 공통 정책과 Week 2 전용 정책만 선택합니다."""

    return [
        NANA_IDENTITY_PROMPT,
        date_time_prompt(),
        NO_GUESSING_PROMPT,
        CHAT_MEMORY_PROMPT,
        WEEK02_CLASSIFICATION_PROMPT,
        WEEK02_CLARIFICATION_STATE_PROMPT,
        WEEK02_STRUCTURED_OUTPUT_PROMPT,
        WEEK02_PERSONAL_CREATE_TOOL_PROMPT,
        WEEK02_TOOL_PAYLOAD_MAPPING_PROMPT,
        WEEK02_SCOPE_PROMPT,
    ]


def build_week02_agent() -> object:
    """Week 2 대화에서 structured_response를 직접 반환하는 단일 LangChain agent를 만듭니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK02_AGENT
    if _WEEK02_AGENT is None:
        structured_agent = create_agent(
            model=chat_model(),
            tools=week02_tools(),
            system_prompt=week02_system_prompt(),
            response_format=Week02Response,
        )
        _WEEK02_AGENT = Week02ResponseAgent(structured_agent)
    return _WEEK02_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week02_agent()
