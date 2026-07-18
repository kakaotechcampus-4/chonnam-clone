from __future__ import annotations

import json
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.tools import tool
from pydantic import BaseModel, Field

from fixed.config import CONFIG
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from student_parts.week01_wake_up_nana import join_system_prompt, week01_prompt_parts, week01_tools


RequestKind = Literal["personal_schedule", "group_schedule", "todo", "reminder", "unknown"]
_WEEK02_AGENT: Any | None = None


# [2주차 수강생 구현 가이드]
#
# 목표
#   Week 2의 핵심은 사용자의 한국어 자연어 요청이나 Week 1 tool이 만든 JSON payload를
#   일정 앱이 읽을 수 있는 StructuredRequest/StructuredRequestBatch로 바꾸는 것입니다.
#   Week 1이 이미 정해진 인자를 받아 임시 일정을 만들었다면, Week 2는 "내일 오후 3시" 같은
#   자연어와 created_schedule JSON을 날짜/시간/종류/멤버 필드로 구조화합니다.
#   구조화 결과는 아직 SQLite, RAG, 외부 멤버 일정 조율 흐름에 저장하지 않습니다.
#
# 과제 구성
#   - 메인과제: Week 2 agent가 자연어 또는 Week 1 tool JSON을 StructuredRequestBatch로
#     최종 반환하는 세로 슬라이스를 완성합니다.
#   - 추가 과제: 메인과제에서 만든 StructuredRequest 스키마를 Week 3 이상 저장/조율 흐름에서
#     재사용할 수 있도록 bridge 함수를 완성합니다.
#
# 구현 위치와 사용할 코드
#   - 이 파일(student_parts/week02_structure_natural_language_requests.py)의
#     StructuredRequest, StructuredRequestBatch, week02_tools(), week02_prompt_parts(),
#     week02_system_prompt(), build_week02_agent()를 확인합니다.
#   - build_week02_agent()는 langchain.agents.create_agent, fixed/llm.py의 chat_model(),
#     week02_system_prompt(), response_format=StructuredRequestBatch를 사용해 Week 2 agent를 만듭니다.
#   - week02_tools()는 Week 1 도구 목록을 그대로 가져옵니다. Week 2 agent는 개인 일정 생성 요청에서
#     personal_create_schedule이 반환한 created_schedule JSON payload를 읽고
#     response_format=StructuredRequestBatch로 최종 구조화 결과를 확인합니다.
#   - week02_prompt_parts()는 student_parts/week01_wake_up_nana.py의 week01_prompt_parts() 위에
#     Week 2 구조화 지시를 추가합니다.
#   - _coerce_structured_request(), extract_structured_request(), extract_schedule_request()는
#     Week 3 이상에서 재사용되는 구조화 bridge입니다. Week 2 파일에 있지만 Week 2 agent에
#     공개되는 tool은 아닙니다.
#
# 메인과제 구현 대상
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
#      - build_week02_agent()에 response_format=StructuredRequestBatch를 연결해
#        ./run.sh --week2가 동작하게 합니다.
#      - 개인 일정 생성 요청에서는 Week 1 personal_create_schedule tool 결과의 created_schedule JSON을
#        LLM이 읽어 StructuredRequestBatch로 최종 변환하는 흐름을 확인합니다.
#
# 추가 과제 구현 대상
#   1. _coerce_structured_request
#      - LangChain structured output 결과가 이미 StructuredRequest이면 그대로 반환합니다.
#      - dict이면 StructuredRequest.model_validate(...)로 검증해 반환합니다.
#      - 예상한 형태가 아니면 RuntimeError를 발생시켜 잘못된 LLM 응답을 조용히 통과시키지 않습니다.
#
#   2. extract_structured_request
#      - chat_model().with_structured_output(StructuredRequest, method="function_calling")를 사용합니다.
#      - system 메시지에는 join_system_prompt(week02_prompt_parts())를 넣고,
#        user 메시지에는 text를 넣어 structured LLM을 호출합니다.
#      - 자연어 또는 JSON 문자열을 StructuredRequest 하나로 검증/구조화합니다.
#
#   3. extract_schedule_request
#      - extract_structured_request(query) 결과에 ok/tool_name/base_date를 붙입니다.
#      - structured_request에는 model_dump() 결과를 넣고, json.dumps(..., ensure_ascii=False)로 반환합니다.
#      - Week 3 이상 저장 tool이 structured_request 필드를 그대로 받을 수 있게 만듭니다.
#
# StructuredRequest 읽는 법
#   - kind: personal_schedule, group_schedule, todo, reminder, unknown 중 하나입니다.
#   - title/date/start_time/end_time: 일정 앱이 실제 저장이나 생성에 사용할 핵심 필드입니다.
#   - members: 참석자/관련 멤버 list입니다. 모르면 빈 list로 둡니다.
#   - priority/reason/original_text: 할 일 우선순위, 판단 근거, 원문 보존용 필드입니다.
#   - 모르는 값을 억지로 만들지 않는 것이 중요합니다. 확실하지 않으면 None 또는 빈 list가 안전합니다.
#   - date/start_time/end_time은 확실할 때만 YYYY-MM-DD, HH:MM 형식으로 채웁니다.
#
# bridge 동작 기준
#   - 요청이 하나뿐이어도 Week 2 agent의 structured_response에는 StructuredRequest 하나를 담습니다.
#   - 여러 일정/할 일/알림 의도가 한 문장에 섞이면 Week 2 agent에서는 여러 StructuredRequest로 나눕니다.
#   - extract_structured_request()는 bridge 용도라 StructuredRequest 하나만 반환합니다.
#   - Week 1 personal_create_schedule은 이미 분해된 인자로 임시 일정을 생성하고,
#     Week 2 agent와 bridge는 그 JSON payload를 읽어 저장 가능한 구조로 최종 변환한다는 차이를 비교합니다.
#
# 참고 코드
#   - week01_prompt_parts()
#      Week 1 system prompt를 이어받아 Week 2 구조화 지시를 누적할 때 사용합니다.
#   - week01_tools()
#      Week 1 개인 일정 tool 목록입니다. Week 2 agent는 이 tool 결과 JSON을 구조화 근거로 씁니다.
#   - extract_structured_request / extract_schedule_request
#      Week 3 이상에서 DB 저장/조율 tool chain에 쓰는 bridge 코드입니다.
#      query 문자열이 자연어든 Week 1 tool JSON이든, Python rule/parser로 매핑하지 않고
#      structured LLM 호출로 구조화한 뒤 JSON tool payload로 감쌉니다.
#
# 검증 방법
#   - 메인과제: ./run.sh --week2로 실행한 뒤 "다음 주 화요일 오후 3시에 철수랑 회의 잡아줘" 같은
#     문장을 입력합니다. 최종 답변이 StructuredRequestBatch class 형식의 structured_response로
#     나오는지 확인합니다.
#   - 추가 과제: Week 3을 실행한 뒤 trace에서 extract_schedule_request 이후
#     save_structured_request가 호출되는지 봅니다. extract_schedule_request의 반환 JSON에
#     ok/tool_name/base_date/structured_request가 들어 있는지 확인합니다.
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
#
#   - _coerce_structured_request(value)
#     LangChain structured output 결과가 이미 StructuredRequest이면 그대로 쓰고, dict이면 Pydantic 검증을 거쳐
#     StructuredRequest로 바꿉니다. 예상한 형태가 아니면 오류를 내서 잘못된 LLM 응답을 조용히 통과시키지 않습니다.
#
#   - extract_structured_request(text)
#     agent loop를 새로 만들지 않고 chat_model().with_structured_output(...)만 사용해 자연어 또는 JSON 문자열을
#     StructuredRequest로 검증/구조화합니다. Week 3 이상에서 저장/조율 직전 입력을 구조화해야 할 때 재사용하는 bridge 함수입니다.
#
#   - extract_schedule_request(query)
#     Week 3 이상 agent가 저장/조율 전에 호출하는 LangChain bridge tool입니다.
#     extract_structured_request(...) 결과에 ok/tool_name/base_date를 붙여 JSON 문자열로 반환하므로,
#     이후 저장 tool이 structured_request 필드를 그대로 받을 수 있습니다.


class StructuredRequest(BaseModel):
    """LLM structured output으로 추출되는 2주차 요청 스키마입니다."""

    kind: RequestKind = Field(
        description=(
            "요청 종류. 아래 기준을 위에서부터 순서대로 판정한다.\n"
            '- 1순위 reminder: "알려줘", "리마인드", "까먹지 않게" 같은 알림 요청 표현이 있으면 '
            '"~까지" 마감 표현이 함께 있어도 reminder. 알림 요청 표현이 없으면 reminder가 아니다.\n'
            '  예: "내일 3시에 회의 있다고 미리 알려줘", "저녁에 약 먹는 거 까먹지 않게 해줘", '
            '"금요일까지 보고서 마감 알려줘" → reminder\n'
            "- 2순위 todo: 특정 시각의 약속이 아니라 마감이 있거나 완료해야 할 작업이면 todo. "
            "알림 요청 표현 없이 마감 표현만 있으면 todo.\n"
            '  예: "금요일까지 보고서 제출해야 해", "할 일 목록에 우유 사기 추가해줘" → todo\n'
            "- 3순위 group_schedule: 여러 사람의 가능 시간을 조율하거나 팀/모임 공동 일정을 잡는 요청이면 "
            "group_schedule.\n"
            '  예: "팀원들이랑 회식 날짜 좀 잡아줘. 다들 되는 시간으로" → group_schedule\n'
            "- 4순위 personal_schedule: 특정 날짜/시각에 나의 일정을 만드는 요청이면 personal_schedule. "
            "참석자 이름이 언급되어도 시간이 이미 정해진 내 일정이면 personal_schedule이고 "
            "members에 이름을 담는다.\n"
            '  예: "다음 주 화요일 오후 3시에 철수랑 회의 잡아줘" → personal_schedule\n'
            "- 5순위 unknown: 위 기준으로 확실히 판정할 수 없으면 unknown으로 두고 "
            "reason에 판단이 어려운 이유를 남긴다.\n"
            '  예: "저번에 말한 그거 일정 알아서 좀 해줘" → unknown'
        )
    )
    title: str | None = Field(
        default=None,
        description="일정/할 일의 제목. 원문에서 확실히 알 수 없으면 None으로 둔다.",
    )
    date: str | None = Field(
        default=None,
        description=(
            "일정 날짜(YYYY-MM-DD). 상대 표현은 base_date 기준으로 해석해 채우고, "
            "확실하지 않으면 지어내지 말고 None으로 둔다."
        ),
    )
    start_time: str | None = Field(
        default=None,
        description="시작 시각(HH:MM, 24시간제). 확실하지 않으면 지어내지 말고 None으로 둔다.",
    )
    end_time: str | None = Field(
        default=None,
        description="종료 시각(HH:MM, 24시간제). 확실하지 않으면 지어내지 말고 None으로 둔다.",
    )
    members: list[str] = Field(
        default_factory=list,
        description="참석자/관련 멤버 이름 목록. 모르면 빈 list로 둔다.",
    )
    priority: str | None = Field(
        default=None,
        description=(
            "할 일 우선순위. low/medium/high 중 하나로 채우고, 원문에 없으면 None으로 둔다. "
            "'중요한/급한' 같은 표현은 high로 해석한다."
        ),
    )
    reason: str | None = Field(
        default=None,
        description="이렇게 구조화한 판단 근거를 짧은 한국어로 남긴다.",
    )
    original_text: str = Field(
        default="",
        description="구조화의 근거가 된 사용자 요청 원문을 그대로 보존한다.",
    )


class StructuredRequestBatch(BaseModel):
    """여러 자연어 의도를 StructuredRequest 목록으로 나누는 메인과제 스키마입니다."""

    requests: list[StructuredRequest] = Field(
        default_factory=list,
        description="구조화된 요청 목록. 요청이 하나뿐이어도 StructuredRequest 하나를 담은 list로 유지한다.",
    )
    base_date: str = Field(
        default_factory=current_app_date_iso,
        description="상대/모호한 날짜 표현을 해석한 기준일(YYYY-MM-DD).",
    )


def _coerce_structured_request(value: Any) -> StructuredRequest:
    """LangChain structured output 결과를 StructuredRequest로 정규화합니다."""

    if isinstance(value, StructuredRequest):
        return value
    if isinstance(value, dict):
        return StructuredRequest.model_validate(value)
    raise RuntimeError(
        f"structured output이 StructuredRequest 형태가 아닙니다: {type(value).__name__}"
    )


def extract_structured_request(text: str) -> StructuredRequest:
    """Week 3 이상에서 agent를 새로 띄우지 않고 자연어를 StructuredRequest로 바꿉니다."""

    structured_llm = chat_model().with_structured_output(
        StructuredRequest, method="function_calling"
    )
    result = structured_llm.invoke([
        ("system", join_system_prompt(week02_prompt_parts())),
        ("user", text),
    ])
    return _coerce_structured_request(result)


@tool
def extract_schedule_request(query: str) -> str:
    """Week 3 이상 agent가 저장/조율 전에 호출하는 구조화 bridge tool입니다."""

    try:
        structured = extract_structured_request(query)
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "tool_name": "extract_schedule_request",
                "base_date": current_app_date_iso(),
                "error": str(exc),
            },
            ensure_ascii=False,
        )
    payload = {
        "ok": True,
        "tool_name": "extract_schedule_request",
        "base_date": current_app_date_iso(),
        "structured_request": structured.model_dump(),
    }
    return json.dumps(payload, ensure_ascii=False)


def week02_tools() -> list[Any]:
    """Week 2 agent에 Week 1 도구를 노출해 tool JSON을 structured_response 근거로 씁니다."""

    return week01_tools()


def week02_system_prompt() -> str:
    """2주차 agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt([
        *week02_prompt_parts(),
        "## 최종 답변 규칙\n"
        "- 최종 답변은 반드시 StructuredRequestBatch 형식의 structured_response로 낸다.\n"
        "- 요청이 하나뿐이어도 requests 목록에 StructuredRequest 하나를 담는다.\n"
        "- personal_create_schedule tool 결과 JSON이 ok=true이면 created_schedule의 "
        "title/date/start_time/end_time/attendees 값을 그대로 읽어 StructuredRequest 필드를 채운다.\n"
        "- 애초에 존재하지 않는 날짜/시각이거나 tool 결과에서 created_schedule을 읽을 수 없으면 "
        "일정이 생성되지 않은 것이다. 이때도 최종 답변은 반드시 StructuredRequestBatch 구조화 "
        '출력으로 내고 자유 텍스트로 답하지 않는다. 해당 요청은 kind="unknown"으로 두고 reason에 '
        "이유를 요약해 담는다. 값을 지어내서 채우지 말고 확실한 필드만 채우며 나머지는 None으로 두고, "
        "original_text에는 사용자 요청 원문을 보존한다.",
    ])


def week02_prompt_parts() -> list[str]:
    """2주차 structured output agent가 따르는 system prompt 조각입니다."""

    return [
        *week01_prompt_parts(),
        "## Week 2 역할: 요청 구조화 agent\n"
        "- 사용자의 한국어 자연어 요청을 구조화된 요청으로 바꾼다.",
        "## 구조화 규칙\n"
        "- 자연어 요청을 StructuredRequest 필드(kind/title/date/start_time/end_time/members/"
        "priority/reason/original_text)로 구조화한다.\n"
        "- date는 YYYY-MM-DD, 시간은 HH:MM 형식만 쓴다.\n"
        "- 확실하지 않은 값은 지어내지 말고 None 또는 빈 list로 둔다.\n"
        "- 시각이 원문에 명시되지 않은 종류(todo, reminder 등)나 '금요일까지' 같은 마감 표현은 "
        "start_time/end_time을 임의 값으로 채우지 말고 None으로 둔다.",
        "## kind 판정과 tool 사용\n"
        "- kind 판정은 StructuredRequest kind 필드 설명에 있는 우선순위 기준을 따른다.\n"
        "- 알림 요청 표현이 있으면 마감 표현이 함께 있어도 reminder이고, "
        "알림 요청 표현 없이 마감 표현만 있으면 todo다.\n"
        "- tool은 kind가 personal_schedule인 요청에만 호출한다. "
        "group_schedule/todo/reminder/unknown으로 판정한 요청은 tool을 호출하지 말고 바로 구조화한다.\n"
        "- 여러 사람의 가능 시간 조율이 필요하거나 날짜/시각이 아직 정해지지 않은 요청은 "
        "내 개인 일정 생성이 아니므로 personal_create_schedule을 호출하지 않는다.",
        "## Tool 결과 처리\n"
        "- ok=true인 Week 1 tool 결과 JSON을 이미 받은 경우 같은 tool을 다시 호출하지 말고, "
        "그 payload를 읽어 structured_response를 만든다.\n"
        "- 사용자 입력 자체가 tool 결과 JSON이면 original_text에는 그 JSON 문자열을 그대로 담고, "
        "자연어 문장을 지어내지 않는다.",
        "## Week 2 범위 제한\n"
        "- SQLite 저장, RAG, 외부 멤버 일정 조율은 하지 않는다.",
    ]


def build_week02_agent() -> object:
    """Week 2 대화에서 structured_response를 직접 반환하는 단일 LangChain agent를 만듭니다."""

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
