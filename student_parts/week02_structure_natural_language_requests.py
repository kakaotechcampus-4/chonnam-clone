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

    kind: RequestKind = Field(description=(
        "이 요청 조각을 아래 다섯 종류 중 정확히 하나로 분류합니다. "
        "판단이 겹칠 때는 사용자가 시킨 동작 동사를 우선합니다(동작 동사 우선 규칙).\n"
        "- personal_schedule: 본인 외 다른 참석자가 전혀 없는 일정입니다. 시각이 있는지 없는지는 판단 기준이 아닙니다 — "
        "'이 날 뭐 해?'라는 질문에 대한 답이 되는 활동(예약, 약속, 모임, 방문, ~하러 가다 등)이면 personal_schedule입니다. "
        "예: '내일 3시 병원 예약'(시각 있음), '다음 주 월요일에 치과 예약 잡아줘'(시각 없어도 personal_schedule).\n"
        "- group_schedule: 일정에서 본인 외 다른 참석자가 한 명이라도 있으면 personal_schedule이 아니라 group_schedule로 분류합니다. "
        "이 판단은 문장이 요청형인지 진술형인지와 무관하게, 오직 참석자 유무만으로 합니다. "
        "구체적 이름(철수·영희)이든 '팀'·'가족'·'팀원들' 같은 그룹이든, members가 본인 외 인물로 채워지면 group_schedule입니다. "
        "예: '철수랑 회의 잡아줘', '팀 회의', '팀원들이랑 회식하자, 영희랑 민수 부를게', '영희랑 저녁 약속 있어'.\n"
        "- todo: 완료해야 할 작업입니다. 시각이 있는지 없는지는 판단 기준이 아닙니다 — "
        "'언제까지 끝내야 해?'라는 질문에 대한 답이 되는, 마감을 향한 의무·작업(끝내다, 제출하다, 작성하다, 마감 등)이면 todo입니다. "
        "참석자가 없다는 이유만으로 personal_schedule로 분류하지 않습니다. 마감 날짜는 date에 보존합니다. "
        "예: '기말 보고서 작성해야 해', '장보기 등록해줘', '나 혼자 이 프로젝트 끝내야 해, 마감 다음 주 금요일'.\n"
        "- reminder: 특정 시점에 알려달라는 것 자체가 주 의도입니다(알림·알람·리마인드·~알려줘). "
        "예: '오후 5시에 약 먹으라고 알려줘'.\n"
        "- unknown: 위 기준에 맞지 않거나 불명확합니다. 확실하지 않으면 unknown으로 둡니다.\n"
        "겹치는 예시1) '내일 3시까지 보고서 작성해야하는 거 알람해줘' -> reminder. "
        "내용은 보고서 작성(todo)이지만 사용자가 시킨 동작이 '알람해줘'이므로 reminder가 이깁니다. "
        "이때 마감 3시는 date/start_time에 보존하고, reason에 'todo에 대한 알림'이라고 근거를 남깁니다.\n"
        "겹치는 예시2) '철수랑 회의 있는 거 알람해줘' -> reminder. "
        "참석자(철수)가 있어 group_schedule로 보일 수 있지만, 사용자가 시킨 동작이 '알람해줘'이므로 reminder가 이깁니다. "
        "이때 참석자 정보는 members에 보존합니다.\n"
        "겹치는 예시3) '영희랑 저녁 약속 있어' -> group_schedule. "
        "'잡아줘' 같은 요청형이 아니라 이미 있는 약속을 진술하는 문장이지만, 참석자(영희)가 있으므로 personal_schedule이 아니라 group_schedule입니다.\n"
        "겹치는 예시4) '나 혼자 이 프로젝트 끝내야 해, 마감 다음 주 금요일' -> todo. "
        "날짜(다음 주 금요일)가 있어 personal_schedule로 보일 수 있지만, '이 날 뭐 해?'의 답이 아니라 '언제까지 끝내야 해?'의 답이므로 todo입니다. "
        "date에는 마감일을 보존합니다.\n"
        "요청 조각 하나는 반드시 하나의 kind만 가집니다."
    ))
    title: str | None = Field(default=None, description="요청의 제목 또는 할 일 이름입니다. 모르면 None으로 둡니다.")
    date: str | None = Field(default=None, description="일정 날짜입니다. 확실할 때만 YYYY-MM-DD 형식으로 채우고 모르면 None으로 둡니다.")
    start_time: str | None = Field(default=None, description="일정 시작 시간입니다. 확실할 때만 HH:MM 형식으로 채웁니다. '오전'·'오후'·'아침'·'점심'·'저녁'·'밤'·'미정'처럼 정확한 시각이 아닌 표현이거나 아예 시간 언급이 없으면, 그 단어를 값으로 그대로 옮기지 말고 이 필드 자체를 반드시 None(빈 값)으로 둡니다.")
    end_time: str | None = Field(default=None, description="일정 종료 시간입니다. 확실할 때만 HH:MM 형식으로 채웁니다. '오전'·'오후'·'아침'·'점심'·'저녁'·'밤'·'미정'처럼 정확한 시각이 아닌 표현이거나 아예 시간 언급이 없으면, 그 단어를 값으로 그대로 옮기지 말고 이 필드 자체를 반드시 None(빈 값)으로 둡니다.")
    members: list[str] = Field(default_factory=list, description="일정 참석자/관련 멤버 목록입니다. 모르면 빈 list로 둡니다.")
    priority: str | None = Field(default=None, description="이번 요청의 우선순위입니다. 급함/보통/낮음처럼 원문에 긴급함이나 중요도가 드러날 때 채우고 모르면 None으로 둡니다.")
    reason: str | None = Field(default=None, description="이번 요청을 해당 kind로 분류하거나 필드를 채운 판단 근거입니다. 모르면 None으로 둡니다.")
    original_text: str = Field(default="", description="이번 요청에 해당하는 사용자 원문 문장입니다. 원문을 그대로 담습니다.")


class StructuredRequestBatch(BaseModel):
    """여러 자연어 의도를 StructuredRequest 목록으로 나누는 메인과제 스키마입니다."""

    requests: list[StructuredRequest] = Field(default_factory=list, description="자연어 요청을 구조화한 StructuredRequest 목록입니다. 요청이 하나뿐이어도 list 형태를 유지합니다.")
    base_date: str = Field(default_factory=current_app_date_iso, description="상대 날짜 해석 기준일입니다. 현재 날짜를 YYYY-MM-DD 형식으로 담습니다.")


def _coerce_structured_request(value: Any) -> StructuredRequest:
    """LangChain structured output 결과를 StructuredRequest로 정규화합니다."""

    if isinstance(value, StructuredRequest):
        return value
    if isinstance(value, dict):
        return StructuredRequest.model_validate(value)
    raise RuntimeError(f"예상치 못한 structured output 타입: {type(value)}")


def extract_structured_request(text: str) -> StructuredRequest:
    """Week 3 이상에서 agent를 새로 띄우지 않고 자연어를 StructuredRequest로 바꿉니다."""

    structured=chat_model().with_structured_output(StructuredRequest, method="function_calling")
    result=structured.invoke([
        {"role": "system", "content": join_system_prompt(week02_prompt_parts())},
        {"role": "user", "content": text}
    ])
    return _coerce_structured_request(result)


@tool
def extract_schedule_request(query: str) -> str:
    """Week 3 이상 agent가 저장/조율 전에 호출하는 구조화 bridge tool입니다."""

    request=extract_structured_request(query)
    return json.dumps({ 
        "ok": True,
        "tool_name": "extract_schedule_request",
        "base_date": current_app_date_iso(),
        "structured_request": request.model_dump(),
    }, ensure_ascii=False)
    

def week02_tools() -> list[Any]:
    """Week 2 agent에 Week 1 도구를 노출해 tool JSON을 structured_response 근거로 씁니다."""

    return week01_tools()


def week02_system_prompt() -> str:
    """2주차 agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt([
        *week02_prompt_parts(),
         (
            "출력은 반드시 StructuredRequestBatch 스키마에 맞는 정확히 하나의 JSON 객체여야 한다. "
            "그 앞뒤에 어떤 설명, 마크다운 코드펜스, 두 번째 JSON도 붙이지 않는다."
         )
    ])

def week02_prompt_parts() -> list[str]:
    """2주차 structured output agent가 따르는 system prompt 조각입니다."""

    return [
        *week01_prompt_parts(),
        (
            "이번 회차에서는 자연어 요청을 StructuredRequestBatch 형식의 structured_response로 구조화하는 agent 역할을 수행한다. "
            "현재 날짜를 기준으로 상대 날짜를 해석하고, 요청이 하나뿐이어도 requests 목록에 StructuredRequest 하나를 담는다. "
            "personal_create_schedule tool 결과 JSON의 created_schedule을 읽어 각 필드를 채우되, tool을 다시 호출하지 않고 payload를 읽어 structured_response로 만든다. "
            "personal_create_schedule tool의 이름·설명('개인 일정')·end_time 기본값('미정')은 전부 Week 1의 저장 관례일 뿐이며, "
            "kind·start_time·end_time 등 Week 2 필드 규칙과는 무관하다: attendees(참석자)가 있으면 이 도구를 썼더라도 kind는 group_schedule로 분류하고, "
            "'오전'·'오후'·'아침'·'점심'·'저녁'·'밤'·'미정'처럼 정확한 시각이 아닌 단어는 start_time/end_time 값으로 그대로 옮기지 않고 반드시 null(None)로 남긴다. "
            "SQLite 저장, RAG, 외부 멤버 일정 조율은 수행하지 않는다."
        ),
        (
            "kind 판단 순서(반드시 지킨다): ① 사용자가 시킨 동작 동사(알려줘·알람·리마인드 vs 완료해야 할 작업)를 "
            "일정 여부보다 먼저 확인해 reminder/todo인지 정한다. ② 여기 해당하지 않고 일정을 잡는 것이 주 의도이면 "
            "참석자 유무로 group_schedule/personal_schedule을 가른다. ③ 위 어디에도 맞지 않으면 unknown이다. "
            "구체적 분류 기준과 예시는 kind 필드 설명을 따른다."
        )
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
            system_prompt=week02_system_prompt()
        )
    return _WEEK02_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week02_agent()
