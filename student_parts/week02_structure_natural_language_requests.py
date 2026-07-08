from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.tools import tool
from pydantic import BaseModel, Field, model_validator

from fixed.config import CONFIG
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from student_parts.week01_wake_up_nana import join_system_prompt, week01_prompt_parts, week01_tools


RequestKind = Literal["personal_schedule", "group_schedule", "todo", "reminder", "unknown"]
_WEEK02_AGENT: Any | None = None
_KOREAN_WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]


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
        description="요청 종류. personal_schedule/group_schedule/todo/reminder/unknown 중 하나만 담습니다."
    )
    title: str | None = Field(
        default=None, description="일정/할 일/알림 제목. 문장에서 알 수 없으면 임의로 짓지 말고 None으로 둡니다."
    )
    date: str | None = Field(
        default=None,
        description="YYYY-MM-DD 형식 날짜. 상대 표현('다음 주 수요일' 등)은 base_date 기준으로 변환합니다. 확실하지 않으면 None.",
    )
    start_time: str | None = Field(default=None, description="HH:MM 24시간 형식 시작 시간. 확실하지 않으면 None.")
    end_time: str | None = Field(default=None, description="HH:MM 24시간 형식 종료 시간. 명시되지 않으면 None.")
    members: list[str] = Field(default_factory=list, description="참석자/관련 멤버 이름 목록. 모르면 빈 list로 둡니다.")
    priority: str | None = Field(default=None, description="할 일의 우선순위. 언급이 없으면 None.")
    reason: str | None = Field(
        default=None,
        description="kind를 이렇게 판단한 근거, 또는 kind가 unknown일 때 사용자에게 되물을 질문 문장입니다.",
    )
    original_text: str = Field(default="", description="구조화하기 전 원문(자연어 또는 Week 1 tool JSON)을 보존합니다.")

    @model_validator(mode="after")
    def _check_required_fields_for_kind(self) -> "StructuredRequest":
        """kind별 필수 필드가 비어 있으면 검증 오류를 내서 ToolStrategy가 재시도하게 합니다."""

        if self.kind == "group_schedule" and not self.members:
            raise ValueError("group_schedule은 members(참석자 최소 1명)가 필요합니다. 없으면 kind=unknown으로 두세요.")
        if self.kind == "todo" and self.date is None:
            raise ValueError("todo는 date(마감일)가 필요합니다. 확인되지 않았으면 kind=unknown으로 두세요.")
        if self.kind == "reminder" and (self.date is None or self.start_time is None):
            raise ValueError(
                "reminder는 기준 사건의 date/start_time이 필요합니다. 확인되지 않았으면 kind=unknown으로 두세요."
            )
        return self


class StructuredRequestBatch(BaseModel):
    """여러 자연어 의도를 StructuredRequest 목록으로 나누는 메인과제 스키마입니다."""

    requests: list[StructuredRequest] = Field(
        default_factory=list,
        description="문장에서 분리된 StructuredRequest 목록. 요청이 하나뿐이어도 길이 1의 list로 둡니다.",
    )
    base_date: str = Field(
        default_factory=current_app_date_iso,
        description="상대 날짜를 해석하는 기준일(YYYY-MM-DD). 오늘 날짜를 그대로 담습니다.",
    )


def _coerce_structured_request(value: Any) -> StructuredRequest:
    """LangChain structured output 결과를 StructuredRequest로 정규화합니다."""

    if isinstance(value, StructuredRequest):
        return value
    if isinstance(value, dict):
        return StructuredRequest.model_validate(value)
    raise RuntimeError(f"예상하지 못한 structured output 형태입니다: {type(value)!r}")


_STRUCTURED_REQUEST_RETRY_ATTEMPTS = 3


def extract_structured_request(text: str) -> StructuredRequest:
    """Week 3 이상에서 agent를 새로 띄우지 않고 자연어를 StructuredRequest로 바꿉니다."""

    structured_llm = chat_model().with_structured_output(StructuredRequest, method="function_calling")
    messages = [
        {"role": "system", "content": join_system_prompt(week02_prompt_parts())},
        {"role": "user", "content": text},
    ]
    last_error: Exception | None = None
    for _ in range(_STRUCTURED_REQUEST_RETRY_ATTEMPTS):
        try:
            result = structured_llm.invoke(messages)
            return _coerce_structured_request(result)
        except Exception as exc:  # noqa: BLE001 - 구조화 실패는 재시도 대상이라 넓게 잡습니다.
            last_error = exc
    raise last_error


@tool
def extract_schedule_request(query: str) -> str:
    """Week 3 이상 agent가 저장/조율 전에 호출하는 구조화 bridge tool입니다."""

    structured_request = extract_structured_request(query)
    payload = {
        "ok": True,
        "tool_name": "extract_schedule_request",
        "base_date": current_app_date_iso(),
        "structured_request": structured_request.model_dump(),
    }
    return json.dumps(payload, ensure_ascii=False)


def week02_tools() -> list[Any]:
    """Week 2 agent에 Week 1 도구를 노출해 tool JSON을 structured_response 근거로 씁니다."""

    return week01_tools()


def week02_system_prompt() -> str:
    """2주차 agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt(week02_prompt_parts())


def week02_prompt_parts() -> list[str]:
    """2주차 structured output agent가 따르는 system prompt 조각입니다."""

    today = current_app_date_iso()
    today_date = date.fromisoformat(today)
    today_weekday = _KOREAN_WEEKDAYS[today_date.weekday()]

    past_offset = min(4, today_date.day - 1) if today_date.day > 1 else 1
    past_example_date = today_date - timedelta(days=past_offset)
    future_example_date = today_date + timedelta(days=1)
    next_month = today_date.month + 1 if today_date.month < 12 else 1
    next_month_year = today_date.year if today_date.month < 12 else today_date.year + 1
    past_example_answer = date(next_month_year, next_month, past_example_date.day)

    return [
        *week01_prompt_parts(),
        f"""## Week 2 · 자연어 요청을 StructuredRequestBatch로 구조화

오늘 날짜는 {today}({today_weekday})입니다. 이번 주차는 개인 일정 tool 호출에서 한 걸음 더 나아가, 사용자의
자연어 요청이나 Week 1 tool이 반환한 JSON payload를 최종적으로 StructuredRequestBatch 형태로
구조화해 답하는 것이 목표입니다.

### 최종 답변 규칙
- 최종 답변은 반드시 StructuredRequestBatch 형태의 structured_response로 반환합니다.
- requests 목록에는 요청이 하나뿐이어도 StructuredRequest 하나를 담습니다.
- 한 문장에 여러 일정/할 일/알림 의도가 섞여 있으면 각각을 별도 StructuredRequest로 나눠 requests에 담습니다.
- base_date에는 오늘 날짜({today})를 담습니다.
- 대화에 여러 turn이 있으면, 이전 turn에서 kind=unknown으로 되물었던 원래 의도(personal_schedule/
  group_schedule/todo/reminder 중 무엇이었는지)는 유지한 채, 이번 turn에서 사용자가 답한 정보로
  빠졌던 필드만 채워 완성합니다. 예를 들어 reminder로 되물은 뒤 날짜/시간을 답 받았다면, kind를
  personal_schedule 같은 다른 종류로 바꾸지 말고 reminder를 유지하며 완성합니다.

### personal_create_schedule tool 결과 처리
- 개인 일정 생성 요청이면 먼저 personal_create_schedule tool을 호출해 임시 일정을 만듭니다.
- tool이 반환한 created_schedule JSON은 다시 tool을 호출하지 않고 그대로 읽어, 그 안의
  title/date/start_time/end_time/attendees 값으로 StructuredRequest 필드를 채웁니다.
  attendees는 members 필드로 옮깁니다.
- created_schedule의 end_time이 "미정"이면 아직 시간이 정해지지 않았다는 뜻이므로,
  StructuredRequest의 end_time은 문자열 "미정"이 아니라 None으로 둡니다.

### 구조화 규칙
- kind는 personal_schedule/group_schedule/todo/reminder/unknown 중 하나입니다.
- 참석자(실제 이름)가 구체적으로 언급되면 group_schedule, 없으면 personal_schedule로 분류합니다.
  '팀', '다같이'처럼 뭉뚱그린 표현은 참석자로 인정하지 않습니다.
- 날짜가 '다음 주 수요일'처럼 상대적으로 표현되면 오늘({today}) 기준으로 계산해 YYYY-MM-DD로 변환합니다.
  연도는 항상 오늘과 같은 {today[:4]}년을 사용하며, 학습 데이터에 익숙한 다른 연도로 절대 바꾸지 않습니다.
- 사용자가 월을 말하지 않고 '일'만 말하면(예: 'N일까지', 'N일에 만나'), 그 일(day)이 이번 달 기준으로
  이미 지났으면 다음 달 같은 일로 계산하고, 아직 지나지 않았으면 이번 달 같은 일로 계산합니다. 예를 들어
  오늘이 {today}이면, 월 없이 '{past_example_date.day}일까지'라고만 말한 것은 이번 달 {past_example_date.day}일이
  이미 지났으므로 {past_example_answer.isoformat()}로 계산해야 하고, '{future_example_date.day}일까지'라고만
  말한 것은 아직 지나지 않았으므로 {future_example_date.isoformat()}로 계산해야 합니다. 이 예시의 숫자가
  아니라 '이미 지났는지 여부로 이번 달/다음 달을 판단한다'는 원리를 모든 날짜 계산에 적용합니다.
- todo는 date 필드에 마감일(due date)을 담습니다. 마감일이 대화에서 확인되지 않으면 임의로
  채우지 말고 kind를 unknown으로 두고 reason에 마감일을 되묻는 질문을 남깁니다.
- reminder는 몇 분 전에 알릴지(예: "30분 전")만으로는 실제로 언제 울릴지 알 수 없습니다. 기준이
  되는 사건의 날짜와 시간이 대화에서 확인되지 않았다면 reminder로 확정하지 말고 kind를 unknown으로
  두고 reason에 그 사건이 정확히 언제인지 되묻는 질문을 남깁니다.
- 확실하지 않은 값은 임의로 채우지 말고 None 또는 빈 list로 둡니다. kind를 unknown으로 둘 때는
  reason에 사용자에게 되물을 질문 문장을 남깁니다.

### 이번 주차에서 하지 않는 것
- SQLite 저장, RAG 검색, 외부 멤버 일정 조율은 Week 2에서 다루지 않습니다. 구조화 결과를 만드는 것까지만 합니다.""",
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
            # ToolStrategy로 감싸는 이유: 클래스를 그대로 넘기면 이 proxy에서 가끔 JSON이 두 번
            # 붙어 응답돼 파싱이 실패한다(week02_structured_nana.py에서 먼저 겪은 문제).
            response_format=ToolStrategy(StructuredRequestBatch),
            system_prompt=week02_system_prompt(),
        )
    return _WEEK02_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week02_agent()
