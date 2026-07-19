from __future__ import annotations

from datetime import date as date_cls, time as time_cls #가독성을 위해 date_cls, time_cls로 명명
import json
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.tools import tool
from pydantic import BaseModel, Field, field_validator

from fixed.config import CONFIG
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from student_parts.week01_wake_up_nana import join_system_prompt, week01_prompt_parts, week01_tools


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
#     week02_system_prompt(), response_format=StructuredRequestBatch를 사용해 Week 2 agent를 만듭니다.
#   - week02_tools()는 Week 1 도구 목록을 그대로 가져옵니다. Week 2 agent는 개인 일정 생성 요청에서
#     personal_create_schedule이 반환한 created_schedule JSON payload를 읽고
#     response_format=StructuredRequestBatch로 최종 구조화 결과를 확인합니다.
#   - week02_prompt_parts()는 student_parts/week01_wake_up_nana.py의 week01_prompt_parts() 위에
#     Week 2 구조화 지시를 추가합니다.
#
# 구현 대상
#   1. StructuredRequest 스키마
#      - kind/title/date/start_time/end_time/members/priority/reason/original_text 필드가
#        이후 Week 3 저장 payload의 기준이 됩니다.
#      - kind는 RequestKind Literal에 들어 있는 값만 허용합니다.
#      - 각 필드에는 LLM structured output이 이해할 수 있도록 한국어 description을 붙입니다.
#
#   2. StructuredRequestBatch 스키마
#      - requests 에는 StructuredRequest 목록을 담고, 요청이 하나뿐이어도 list 형태를 유지합니다.
#      - base_date 에는 상대 날짜 해석 기준일(current_app_date_iso)을 담습니다.
#
#   3. Week 2 agent 세로 슬라이스
#      - week02_tools()는 Week 1 tool 목록을 그대로 반환합니다.
#      - week02_prompt_parts()와 week02_system_prompt()에는 자연어/Week 1 tool JSON을
#        StructuredRequestBatch로 구조화하라는 지시를 넣습니다.
#      - build_week02_agent()에 response_format=StructuredRequestBatch를 연결해
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
#   - week01_prompt_parts()
#      Week 1 system prompt를 이어받아 Week 2 구조화 지시를 누적할 때 사용합니다.
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
#     Week 1 prompt 위에 "자연어를 StructuredRequestBatch로 출력한다"는 Week 2 지시를 누적합니다.
#
#   - build_week02_agent() / build_week_agent()
#     response_format=StructuredRequestBatch가 설정된 agent를 만들고 재사용합니다.
#     build_week_agent()는 실행기가 찾는 표준 entry point입니다.


class StructuredRequest(BaseModel):
    """LLM structured output으로 추출되는 2주차 요청 스키마입니다."""

    # TODO: kind 필드를 RequestKind 타입으로 선언하고 Field(description=...)를 붙이세요.
    # TODO: title/date/start_time/end_time 필드를 str | None 타입으로 선언하고 기본값은 None으로 두세요.
    # TODO: members 필드를 list[str] 타입으로 선언하고 default_factory=list를 사용하세요.
    # TODO: priority/reason 필드를 str | None 타입으로 선언하고 기본값은 None으로 두세요.
    # TODO: original_text 필드를 str 타입으로 선언하고 기본값은 ""로 두세요.
    # TODO: 각 필드에는 LLM structured output이 이해할 수 있도록 한국어 description을 달아주세요.
    
    kind: RequestKind = Field(description="사용자의 일정 유형을 저장하는 필드. RequestKind 리스트에 담긴 유형만 사용할 것.")
    title: str | None = Field(default=None, description="사용자의 일정 제목을 받아서 저장하는 필드. 제목은 문자열로 저장할 것. 확실하지 않으면 None으로 둘 것.")
    date: str | None = Field(default=None, description="사용자의 일정 날짜를 받아서 저장하는 필드. 날짜는 YYYY-MM-DD 형식의 문자열로 저장. 확실하지 않으면 None으로 둘 것.")
    start_time: str | None = Field(default=None, description="사용자의 일정이 시작하는 시간을 저장하는 필드. 시간은 HH:MM 형식의 문자열로 저장할 것. 확실하지 않으면 None으로 둘 것.")
    end_time: str | None = Field(default=None, description="사용자의 일정이 끝나는 시간을 저장하는 필드. 시간은 HH:MM 형식의 문자열로 저장할 것. 확실하지 않으면 None으로 둘 것.")
    members: list[str] = Field(default_factory=list, description="사용자의 일정에 참여하는 사람들을 저장하는 리스트 필드. 각 참여자의 이름을 문자열로 저장할 것. 참여자를 따로 명시하지 않으면 그대로 둘 것.")
    priority: str | None = Field(default=None, description="사용자 일정의 우선순위를 저장하는 필드. 일정의 우선순위를 직접 판단하여 '낮음', '중간', '높음'의 세 단계의 문자열중 하나로 저장하되, 확실한 근거가 있을 때만 판단하고 애매하면 None으로 둘 것.")
    reason: str | None = Field(default=None, description="priority 필드에 매긴 우선순위의 근거를 설명하여 문자열로 저장할 것. 만약 priority 필드를 None으로 설정하였다면 reason 필드도 None으로 둘 것.")
    original_text: str = Field(default="", description="사용자가 일정 추가를 요청했을 당시의 사용자 프롬프트 원문을 문자열로 저장할 것.")
    
    @field_validator("members", mode="before")
    @classmethod
    def _default_members(cls, value: Any) -> Any:
        return value or []
    
    @field_validator("date", mode="before")
    @classmethod
    def _normalize_date_format(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return None
        try:
            #fromisoformat으로 value가 유효한 날짜인지 확인 후, isoformat으로 다시 문자열로 변환
            return date_cls.fromisoformat(value.strip()).isoformat()
        except ValueError:
            return None

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def _normalize_time_format(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return None
        try:
            #timespec="minutes"를 통해 time 객체에서 HH:MM 형식의 문자열로 변환
            return time_cls.fromisoformat(value.strip()).isoformat(timespec="minutes")
        except ValueError:
            return None


class StructuredRequestBatch(BaseModel):
    """여러 자연어 의도를 StructuredRequest 목록으로 나누는 2차 과제 스키마입니다."""

    # TODO: requests 필드를 list[StructuredRequest] 타입으로 선언하고 default_factory=list를 사용하세요.
    # TODO: base_date 필드를 str 타입으로 선언하고 default_factory=current_app_date_iso를 사용하세요.
    # TODO: 각 필드에는 Week 2 구조화 결과와 상대 날짜 기준일을 설명하는 한국어 description을 달아주세요.
    requests: list[StructuredRequest] = Field(default_factory=list, description="사용자가 일정 생성을 요청하는 프롬프트에서 중요 정보들을 추출하여 저장하는 스키마 객체의 리스트 필드이다. 만약 요청이 하나뿐이어도 list 형태를 유지할 것.")
    base_date: str = Field(default_factory=current_app_date_iso, description="'내일', '어제'와 같이 현재 시각을 기준으로 상대적인 시간 혹은 날짜를 파악하기 위한 필드이다. 사용자가 불분명한 시각을 언급한다면, 이 필드를 참고하여 정확한 요청 시각을 파악할 것.")

def _coerce_structured_request(value: Any) -> StructuredRequest:
    """이후 회차에서 사용할 StructuredRequest 정규화 예약 함수입니다."""
    
    if isinstance(value, StructuredRequest):
        return value
    if isinstance(value, dict):
        return StructuredRequest.model_validate(value)
    raise RuntimeError("StructuredRequest 또는 dict 형태의 structured output이 아닙니다.")


def extract_structured_request(text: str) -> StructuredRequest:
    """이후 회차에서 사용할 단건 구조화 예약 함수입니다."""

    llm = chat_model().with_structured_output(StructuredRequest, method="function_calling")
    result = llm.invoke(
        [
            {"role": "system", "content": join_system_prompt(week02_prompt_parts())},
            {"role": "user", "content": text},
        ]
    )
    return _coerce_structured_request(result)

@tool
def extract_schedule_request(query: str) -> str:
    """이후 회차에서 저장 흐름과 연결할 예약 tool입니다."""

    structured = extract_structured_request(query)
    return json.dumps(
        {
            "ok": True,
            "tool_name": "extract_schedule_request",
            "base_date": current_app_date_iso(),
            "structured_request": structured.model_dump(),
        },
        ensure_ascii=False,
    )


def week02_tools() -> list[Any]:
    """Week 2 agent에 Week 1 도구를 노출해 tool JSON을 structured_response 근거로 씁니다."""

    # TODO: Week 1에서 구현한 tool 목록을 그대로 반환하세요.
    return week01_tools()


def week02_system_prompt() -> str:
    """2주차 agent가 따르는 시스템 프롬프트입니다."""

    # TODO: join_system_prompt(...)로 week02_prompt_parts()와 Week 2 structured_response 최종 답변 규칙을 합치세요.
    # TODO: StructuredRequestBatch에는 요청이 하나뿐이어도 requests 목록에 StructuredRequest 하나를 담도록 지시하세요.
    # TODO: personal_create_schedule tool 결과 JSON의 created_schedule을 읽어 필드를 채우도록 지시하세요.
    final_answer_rule = """만약 사용자의 요청이 하나뿐이어도, StructuredRequestBatch의 requests 목록에는 반드시 StructuredRequest 하나를 담도록 해. 
    personal_create_schedule tool을 사용한 결과로 나온 JSON의 created_schedule을 읽어서 StructuredRequest 필드를 채우는데 사용해."""
    
    return join_system_prompt([*week02_prompt_parts(), final_answer_rule])


def week02_prompt_parts() -> list[str]:
    """2주차 structured output agent가 따르는 system prompt 조각입니다."""

    return [
        *week01_prompt_parts(),
        # TODO: Week 2 요청 구조화 agent 역할과 현재 날짜(current_app_date_iso()) 기준을 추가하세요.
        # TODO: 자연어를 StructuredRequest 필드(kind/title/date/start_time/end_time/members 등)로 구조화하도록 지시하세요.
        # TODO: Week 1 tool JSON을 받은 경우 다시 tool을 호출하지 않고 payload를 읽어 structured_response로 만들도록 지시하세요.
        # TODO: Week 2에서는 SQLite 저장, RAG, 외부 멤버 일정 조율을 하지 않는다고 명시하세요.
        f"""Week 2 요청 구조화 agent의 역할은, Week 1 tool이 만든 JSON payload나 사용자의 한국어 자연어 요청을 일정 앱이 읽을 수 있는 StructuredRequest/StructuredRequestBatch로 바꿔 구조화 한뒤 출력하는 거야.
        만약 사용자의 일정 요청을 받으면, 프롬프트에서 필요한 정보들을 추출해서 StructuredRequest의 필드(kind/title/date/start_time/end_time/members)로 구조화한뒤 StructuredRequestBatch 객체의 requests 필드 리스트에 구조화한 객체를 추가해.
        정보 추출과정에서 '내일', '어제'와 같이 사용자가 불분명한 시간 정보를 입력했다면, 현재 시간 {current_app_date_iso()}를 기준으로 정확한 시간대를 파악해서 StructuredRequest의 date/start_time/end_time 필드에 요구되는 값을 채워. 
        StructuredRequestBatch 객체의 base_date 필드에는 현재 시간을 그대로 저장해.
        사용한 tool의 JSON 결과를 받으면 재호출하지 말고 payload를 읽어서 structured_response로 만들어.
        Week 2에서는 SQLite 저장, RAG, 외부 멤버 일정 조율은 하지 않을 거야.
        """
    ]


def build_week02_agent() -> object:
    """Week 2 대화에서 structured_response를 직접 반환하는 단일 LangChain agent를 만듭니다."""

    # TODO: CONFIG.has_openai_key가 없으면 RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")를 발생시키세요.
    # TODO: 전역 _WEEK02_AGENT를 재사용하고, 아직 없을 때만 create_agent(...)로 새 agent를 만드세요.
    # TODO: create_agent에는 model=chat_model(), tools=week02_tools(), response_format=StructuredRequestBatch,
    #       system_prompt=week02_system_prompt()를 연결하세요.
    # TODO: 생성 또는 재사용한 _WEEK02_AGENT를 반환하세요.
    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK02_AGENT
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
