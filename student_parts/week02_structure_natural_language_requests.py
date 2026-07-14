from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.tools import tool
from pydantic import BaseModel, Field, field_validator

from fixed.config import CONFIG
from fixed.llm import chat_model
from fixed.runtime_clock import APP_STARTED_AT, app_started_at_iso, current_app_date_iso, next_weekday_iso
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
#      - base_datetime에는 상대 시간 해석 기준 시각(app_started_at_iso)을 담습니다.
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
#      - extract_structured_request(query) 결과에 ok/tool_name/base_date/base_datetime을 붙입니다.
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
#     ok/tool_name/base_date/base_datetime/structured_request가 들어 있는지 확인합니다.
#
# 함수별 동작 설명
#   - StructuredRequest
#     Week 2 structured output의 중심 스키마입니다. LLM이 자연어에서 뽑은 요청 종류, 제목, 날짜, 시간,
#     멤버, 우선순위, 근거, 원문을 이 class 필드에 맞춰 반환합니다.
#
#   - StructuredRequestBatch
#     StructuredRequest 여러 개와 base_date/base_datetime을 함께 담는 최종 structured_response 스키마입니다.
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
#     extract_structured_request(...) 결과에 ok/tool_name/base_date/base_datetime을 붙여 JSON 문자열로 반환하므로,
#     이후 저장 tool이 structured_request 필드를 그대로 받을 수 있습니다.


class StructuredRequest(BaseModel):
    """LLM structured output으로 추출되는 2주차 요청 스키마입니다."""

    kind: RequestKind = Field(
        description=(
            "요청의 주된 의도입니다. 시간이 확정된 일정 등록은 참석자가 있어도 personal_schedule, "
            "여러 사람의 공통 가능 시간을 확인하거나 일정을 조율해야 하면 group_schedule, "
            "완료할 작업은 todo, 특정 시점에 알려 달라는 요청은 reminder, 판단할 수 없으면 unknown입니다."
        )
    )
    title: str | None = Field(default=None, description="일정, 할 일, 알림의 짧은 제목입니다.")
    date: str | None = Field(
        default=None,
        description="앱 시작 시각을 기준으로 확실히 해석한 날짜입니다. YYYY-MM-DD 형식으로만 채웁니다.",
    )
    start_time: str | None = Field(
        default=None,
        description="앱 시작 시각을 기준으로 확실히 해석한 시작 시간입니다. HH:MM 형식으로만 채웁니다.",
    )
    end_time: str | None = Field(default=None, description="확실히 해석된 종료 시간입니다. HH:MM 형식으로만 채웁니다.")
    members: list[str] = Field(default_factory=list, description="참석자나 관련 멤버 이름 목록입니다.")
    priority: str | None = Field(default=None, description="할 일이나 알림의 우선순위입니다. 모르면 None으로 둡니다.")
    reason: str | None = Field(
        default=None,
        description="분류 기준과 상대 날짜/시간 계산 기준을 확인할 수 있는 짧은 근거입니다.",
    )
    original_text: str = Field(default="", description="구조화의 근거가 된 사용자 원문 또는 tool JSON 문자열입니다.")


class StructuredRequestBatch(BaseModel):
    """여러 자연어 의도를 StructuredRequest 목록으로 나누는 메인과제 스키마입니다."""

    requests: list[StructuredRequest] = Field(
        default_factory=list,
        description="사용자 요청에서 분리한 구조화 요청 목록입니다. 요청이 하나뿐이어도 list로 반환합니다.",
    )
    base_date: str = Field(
        default_factory=current_app_date_iso,
        description="상대 날짜 표현을 해석할 때 기준이 되는 앱 현재 날짜입니다.",
    )
    base_datetime: str = Field(
        default_factory=app_started_at_iso,
        description="상대 날짜와 시간을 해석할 때 기준이 되는 타임존 포함 앱 시작 시각입니다.",
    )

    @field_validator("base_date", mode="before")
    @classmethod
    def use_app_base_date(cls, _value: Any) -> str:
        """LLM이 반환한 값과 관계없이 앱의 고정 기준일을 사용합니다."""

        return current_app_date_iso()

    @field_validator("base_datetime", mode="before")
    @classmethod
    def use_app_base_datetime(cls, _value: Any) -> str:
        """LLM이 반환한 값과 관계없이 앱의 고정 기준 시각을 사용합니다."""

        return app_started_at_iso()


def _coerce_structured_request(value: Any) -> StructuredRequest:
    """LangChain structured output 결과를 StructuredRequest로 정규화합니다."""

    if isinstance(value, StructuredRequest):
        return value
    if isinstance(value, dict):
        return StructuredRequest.model_validate(value)
    raise RuntimeError(f"StructuredRequest로 변환할 수 없는 LLM 응답입니다: {type(value).__name__}")


def extract_structured_request(text: str) -> StructuredRequest:
    """Week 3 이상에서 agent를 새로 띄우지 않고 자연어를 StructuredRequest로 바꿉니다."""

    structured_llm = chat_model().with_structured_output(StructuredRequest, method="function_calling")
    result = structured_llm.invoke(
        [
            ("system", join_system_prompt(week02_prompt_parts())),
            ("user", text),
        ]
    )
    return _coerce_structured_request(result)


@tool
def extract_schedule_request(query: str) -> str:
    """Week 3 이상 agent가 저장/조율 전에 호출하는 구조화 bridge tool입니다."""

    structured_request = extract_structured_request(query)
    return json.dumps(
        {
            "ok": True,
            "tool_name": "extract_schedule_request",
            "base_date": current_app_date_iso(),
            "base_datetime": app_started_at_iso(),
            "structured_request": structured_request.model_dump(),
        },
        ensure_ascii=False,
    )


def week02_tools() -> list[Any]:
    """Week 2 agent에 Week 1 도구를 노출해 tool JSON을 structured_response 근거로 씁니다."""

    return week01_tools()


def week02_system_prompt() -> str:
    """2주차 agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt(
        [
            *week02_prompt_parts(),
            (
                "최종 응답은 반드시 StructuredRequestBatch structured_response로 반환한다. "
                "요청이 하나뿐이어도 requests 목록 안에 StructuredRequest 하나를 담는다. "
                "여러 일정, 할 일, 알림 의도가 섞이면 의도별로 StructuredRequest를 나누어 담는다."
            ),
            (
                "personal_create_schedule tool 결과 JSON을 받은 경우 created_schedule 값을 읽어 "
                "title, date, start_time, end_time, members 필드를 채운다. "
                "이 tool 결과는 시간이 확정된 개인 일정이므로 kind='personal_schedule'로 분류한다. "
                "이미 생성된 tool JSON을 다시 만들기 위해 같은 tool을 반복 호출하지 않는다."
            ),
        ]
    )


def _week02_few_shot_examples() -> str:
    """앱 시작 시각에 맞춘 분류와 상대 시간 예시를 JSON 문자열로 만듭니다."""

    tomorrow = (APP_STARTED_AT + timedelta(days=1)).date().isoformat()
    after_20_minutes = APP_STARTED_AT + timedelta(minutes=20)
    after_30_minutes = APP_STARTED_AT + timedelta(minutes=30)
    examples = [
        {
            "input": "내일 오후 2시에 철수와 점심 식사 예약",
            "expected": {
                "kind": "personal_schedule",
                "title": "점심 식사",
                "date": tomorrow,
                "start_time": "14:00",
                "members": ["철수"],
                "reason": "시간이 확정된 일정 등록 요청이며 참석자 존재만으로 그룹 조율이 되지는 않음",
            },
        },
        {
            "input": "철수와 다음 주에 가능한 시간을 찾아 회의 잡아줘",
            "expected": {
                "kind": "group_schedule",
                "title": "회의",
                "date": None,
                "start_time": None,
                "members": ["철수"],
                "reason": "철수의 가능 시간을 확인하고 공동 일정을 조율해야 함",
            },
        },
        {
            "input": "내일까지 과제 제출하기를 할 일로 추가해줘",
            "expected": {
                "kind": "todo",
                "title": "과제 제출",
                "date": tomorrow,
                "start_time": None,
                "members": [],
                "reason": "특정 시각 알림이 아니라 완료해야 할 작업을 추가하는 요청임",
            },
        },
        {
            "input": "낮잠 좀 잘거니까 20분 뒤에 깨워줘.",
            "expected": {
                "kind": "reminder",
                "title": "낮잠 깨우기",
                "date": after_20_minutes.date().isoformat(),
                "start_time": after_20_minutes.strftime("%H:%M"),
                "members": [],
                "reason": f"앱 시작 시각 {app_started_at_iso()}에서 20분 뒤를 계산함",
            },
        },
        {
            "input": "다음 주 화요일 오후 3시에 철수랑 회의 잡고, 과제 리마인더도 알려줘",
            "expected_requests": [
                {
                    "kind": "personal_schedule",
                    "title": "회의",
                    "date": next_weekday_iso(1),
                    "start_time": "15:00",
                    "members": ["철수"],
                    "reason": "다음 주 화요일 오후 3시로 확정된 일정 등록 요청임",
                },
                {
                    "kind": "reminder",
                    "title": "과제 리마인더",
                    "date": None,
                    "start_time": None,
                    "members": [],
                    "reason": "알림 시점은 없지만 과제 리마인더를 요청함",
                },
            ],
        },
        {
            "input": "나중에 그거 적당히 처리해줘",
            "expected": {
                "kind": "unknown",
                "title": None,
                "date": None,
                "start_time": None,
                "members": [],
                "reason": "요청 대상과 처리 유형을 판단할 정보가 부족함",
            },
        },
    ]
    relative_time_examples = {
        "base_datetime": app_started_at_iso(),
        "20분 뒤": {
            "date": after_20_minutes.date().isoformat(),
            "start_time": after_20_minutes.strftime("%H:%M"),
        },
        "30분 뒤": {
            "date": after_30_minutes.date().isoformat(),
            "start_time": after_30_minutes.strftime("%H:%M"),
        },
    }
    return (
        "다음 분류 예시의 기준을 그대로 따른다. 각 예시 payload에는 핵심 필드만 표시했지만 최종 응답은 "
        "StructuredRequest의 모든 필드를 채운다.\n"
        f"{json.dumps(examples, ensure_ascii=False, indent=2)}\n"
        "상대 시간 계산 예시:\n"
        f"{json.dumps(relative_time_examples, ensure_ascii=False, indent=2)}"
    )


def week02_prompt_parts() -> list[str]:
    """2주차 structured output agent가 따르는 system prompt 조각입니다."""

    return [
        *week01_prompt_parts(),
        (
            "너는 Week 2 요청 구조화 agent다. "
            f"상대 날짜 표현은 앱 현재 날짜 {current_app_date_iso()}를 기준으로 해석하고, "
            f"상대 시간 표현은 타임존이 포함된 앱 시작 시각 {app_started_at_iso()}를 기준으로 해석한다. "
            "앱이 실행되는 동안 이 기준 시각은 바뀌지 않는다. "
            f"최종 StructuredRequestBatch의 base_date에는 {current_app_date_iso()}, "
            f"base_datetime에는 {app_started_at_iso()}를 그대로 넣는다."
        ),
        (
            "'다음 주 월요일'처럼 다음 주의 요일을 말하면 앱 기준일이 속한 주의 바로 다음 "
            "월요일부터 일요일 사이에서 해당 요일을 선택한다. "
            f"현재 기준 다음 주 화요일은 {next_weekday_iso(1)}이다."
        ),
        (
            "사용자의 한국어 자연어 요청을 StructuredRequest 필드로 구조화한다. "
            "날짜와 시간이 이미 확정된 일정 등록은 참석자가 있어도 kind='personal_schedule'이다. "
            "참석자들의 가능 시간을 확인하거나 공통 시간을 찾고 협의해야 하는 요청만 kind='group_schedule'이다. "
            "members가 있다는 사실만으로 group_schedule로 분류하지 않는다. "
            "할 일은 kind='todo', 알림은 kind='reminder', 분류가 불확실하면 kind='unknown'을 사용한다. "
            "reason에는 시간 확정 여부, 조율 필요 여부 또는 알림 의도처럼 kind를 선택한 근거를 반드시 남긴다."
        ),
        (
            "'N분 뒤'나 'N시간 뒤'는 앱 시작 시각에 정확히 N분 또는 N시간을 더해 계산한다. "
            "계산 결과의 날짜를 date에 YYYY-MM-DD로, 시각을 start_time에 HH:MM으로 넣는다. "
            "기준 시각의 초는 계산에 포함하되 start_time에는 분까지만 쓰고 초는 버리며 반올림하지 않는다. "
            "계산 결과가 자정을 넘으면 date도 다음 날짜로 바꾼다. 예를 들어 "
            "2026-07-09T23:50:00+09:00에서 20분 뒤는 date='2026-07-10', start_time='00:10'이다. "
            "reason에는 앱 시작 시각과 더한 시간을 기록한다."
        ),
        (
            "모르는 값을 추측해서 만들지 않는다. 날짜와 시간은 확실할 때만 YYYY-MM-DD, HH:MM 형식으로 채우고, "
            "불확실한 문자열 값은 None, 멤버가 없거나 모르면 빈 list를 사용한다. "
            "original_text에는 사용자의 원문이나 입력 JSON 문자열을 보존한다."
        ),
        (
            "personal_create_schedule은 시간이 확정된 personal_schedule 등록에만 호출한다. "
            "group_schedule, todo, reminder, unknown 요청에는 Week 1 개인 일정 tool을 호출하지 않고 직접 구조화한다. "
            "Week 1 tool JSON을 받은 경우 다시 tool을 호출하지 말고 payload를 읽어 structured_response를 만든다. "
            "personal_create_schedule 결과라면 created_schedule의 title/date/start_time/end_time/attendees를 "
            "StructuredRequest의 title/date/start_time/end_time/members로 옮긴다."
        ),
        (
            "한 문장에 일정, 할 일, 알림이 함께 있으면 각각 별도의 StructuredRequest로 나눈다. "
            "예를 들어 '다음 주 화요일 오후 3시에 철수랑 회의 잡고, 과제 리마인더도 알려줘'는 "
            "시간이 확정된 personal_schedule과 reminder 두 요청으로 나눈다."
        ),
        _week02_few_shot_examples(),
        "Week 2에서는 SQLite 저장, RAG 검색, 외부 멤버 일정 조율을 수행하지 않고 구조화 결과만 반환한다.",
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
