from __future__ import annotations

import json
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.tools import tool
from pydantic import BaseModel, Field, model_validator

from fixed.config import CONFIG
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from student_parts.week01_wake_up_nana import join_system_prompt, week01_prompt_parts, week01_tools


RequestKind = Literal["personal_schedule", "group_schedule", "todo", "reminder", "unknown"]
_WEEK02_AGENT: Any | None = None

KIND_REQUIRED_FIELDS: dict[str, list[str]] = {
    "personal_schedule": ["title", "date"],
    "group_schedule":    ["title", "date", "members"],
    "todo":              ["title"],
    "reminder":          ["title", "date"],
    "unknown":           [],
}


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
        description="요청 종류. personal_schedule·group_schedule·todo·reminder·unknown 중 하나."
        " 여러 kind에 걸쳐 보이면 personal_schedule/group_schedule > todo > reminder > unknown 순으로 우선 판단하되,"
        " \"알려줘\"·\"기억해놔\"·\"잊지마\"·\"까먹지 않게 해줘\"처럼 명시적으로 상기를 요청하는 표현이 있으면"
        " 날짜가 있어도 reminder를 최우선으로 판단."
        " 분류 불가 → unknown."
        """
        - personal_schedule : 사용자 본인이 참석·처리해야 하는, 날짜/시간이 정해진 개인 일정.
        예) "내일 10시 치과 일정 잡아줘", "이번 주 토요일 결혼식 있어"
        반복 일정이어도 반복 규칙을 담을 필드가 없으니 가장 가까운 날짜 하나만 채우고,
        반복 여부는 reason에 한 문장으로 남겨.
        
        - group_schedule    : 사용자 외에 다른 참석자가 있는 일정. 참석자가 특정 인물이 아니라 소속 팀·모임 이름이어도 members에 그 이름을 담아. 참석자를 빼면 personal_schedule과 동일하게 판단해.
        예) "다음 주 목요일 철수랑 일정 잡아줘"(members=["철수"]), "이번 주 일요일 S축구단 풋살 있어"(members=["S축구단"])
        
        - todo  : 날짜/시간이 정해지지 않고, 사용자가 스스로 알아서 처리하면 되는 개인 행동.
        예) "우유 좀 사야겠다", "설거지 해야지"
        주의: 날짜가 언급되면 todo가 아니라 personal_schedule/group_schedule로 분류해.
        (예: "목요일 네일 예약하기"는 날짜가 있으므로 personal_schedule)
        - reminder : "알려줘"·"기억해놔"·"잊지마"·"까먹지 않게 해줘"처럼 사용자가 잊지 않도록 상기시켜달라고
        명시적으로 요청하는 표현이 있으면, 날짜가 있어도 personal_schedule/group_schedule보다 reminder를 우선한다.
        예) "내일 기차 예약하는 거 알려줘", "낼 모레 새벽 2시 취소표 나오는 거 기억해놔", "모레까지 보고서 작성하는 거 잊지마"
        - unknown : 위 4개에 속하지 않는 것. 과거 사실에 대한 진술, 잡담, 애매한 표현 등.
        예) "오늘 저녁 약속 드럽게 재미없었어", "철수 걔를 봐 말아"

        [kind별 필수 필드]
        - personal_schedule : title, date
        - group_schedule    : title, date, members (최소 1명)
        - todo              : title
        - reminder          : title, date
        - unknown           : 없음 (original_text만 보존)

        필수 필드가 불확실할 때는 억지로 만들지 않고 None으로 두되 reason에 이유를 남겨.
        """
    )
    title: str | None = Field(
        default=None,
        description="일정·할 일·리마인더 제목. personal_schedule·group_schedule·todo·reminder에서는 필수이므로 최대한 채운다. 정말 알 수 없을 때만 None.",
    )
    date: str | None = Field(default=None, description=""""내일"·"다음 주 화요일" 같은 상대 날짜는 base_date 기준으로 YYYY-MM-DD로 변환.
        personal_schedule·group_schedule·reminder에서는 필수이므로 최대한 채운다.
        todo이거나 변환이 불가능하거나 언급이 없으면 None.""")
    start_time: str | None = Field(default=None, description=""""일정/할일의 시작 시각. "오후 3시"→15:00, "점심"→12:00처럼
    합리적으로 추론 가능하면 24시간제 HH:MM으로 채운다.
    시각이 전혀 언급되지 않았으면 None (임의로 추정하지 않는다).""")
    end_time: str | None = Field(default=None, description=""""일정의 종료 시각. 명시적으로 언급됐거나 ("2시부터 4시까지") 관례상 기본 소요시간(예: 회의 1시간)을 적용할 만큼 맥락이 뚜렷할 때만 채운다.
    끝나는 시각이 불명확하면 start_time만 채우고 end_time은 None으로 둔다.""")
    members: list[str] = Field(
        default_factory=list,
        description="참석자·관련 멤버 이름 목록. 특정 인물이 아니라 소속 팀·모임 이름이 언급돼도 담을 수 있다."
        " group_schedule에서는 최소 1명 필수이므로 언급되면 list에 담아. 그 외에는 없으면 빈 list.",
    )
    priority: str | None = Field(default=None, description="""todo의 우선순위. "high"/"medium"/"low" 중 하나만 사용. 사용자가 명시적으로 급함/여유를 언급하지 않으면 None으로 둔다.""")
    reason: str | None = Field(
        default=None,
        description="판단 근거. kind·날짜·시간이 불확실하거나 추정이 필요할 때 한 문장으로 이유를 남겨.",
    )
    original_text: str = Field(default="", description="사용자 원문. 감사 추적·디버깅용으로 반드시 보존한다.")

    @model_validator(mode="before")
    @classmethod
    def _coerce_none_defaults(cls, data: Any) -> Any:
        """LLM이 optional 필드에 null을 채워 보내는 경우, 타입에 맞는 기본값으로 보정한다."""

        if isinstance(data, dict):
            if data.get("members") is None:
                data["members"] = []
            if data.get("original_text") is None:
                data["original_text"] = ""
        return data


class StructuredRequestBatch(BaseModel):
    """여러 자연어 의도를 StructuredRequest 목록으로 나누는 2차 과제 스키마입니다."""

    requests: list[StructuredRequest] = Field(
        default_factory=list,
        description="구조화된 요청 목록. 요청이 1개뿐이어도 반드시 list에 담는다.",
    )
    base_date: str = Field(
        default_factory=current_app_date_iso,
        description="상대 날짜(내일·다음 주 등) 해석 기준일 (YYYY-MM-DD).",
    )


def missing_required_fields(req: StructuredRequest) -> list[str]:
    """kind별 필수 필드 중 값이 없는 것을 반환한다. 빈 list면 완전한 요청."""
    required = KIND_REQUIRED_FIELDS.get(req.kind, [])
    return [
        f for f in required
        if not getattr(req, f, None)
        or (isinstance(getattr(req, f), list) and not getattr(req, f))
    ]


def _coerce_structured_request(value: Any) -> StructuredRequest:
    """LangChain structured output 결과를 StructuredRequest로 정규화합니다."""

    if isinstance(value, StructuredRequest):
        return value
    if isinstance(value, dict):
        return StructuredRequest.model_validate(value)
    raise RuntimeError(f"예상치 못한 structured output 형식: {type(value)!r}")


def extract_structured_request(text: str) -> StructuredRequest:
    """Week 3 이상에서 agent를 새로 띄우지 않고 자연어를 StructuredRequest로 바꿉니다."""

    structured_llm = chat_model().with_structured_output(StructuredRequest, method="function_calling")
    result = structured_llm.invoke([
        {"role": "system", "content": join_system_prompt(week02_prompt_parts())},
        {"role": "user", "content": text},
    ])
    return _coerce_structured_request(result)


@tool
def extract_schedule_request(query: str) -> str:
    """Week 3 이상 agent가 저장/조율 전에 호출하는 구조화 bridge tool입니다."""

    structured = extract_structured_request(query)
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
        """
        최종 답변은 반드시 structured_response(StructuredRequestBatch)로만 반환한다.
        요청이 1개뿐이어도 requests 목록에 StructuredRequest 1개를 담아라.
        personal_create_schedule tool 결과가 있으면 created_schedule JSON을 읽어 필드를 채워라.
        """,
    ])


def week02_prompt_parts() -> list[str]:
    """2주차 structured output agent가 따르는 system prompt 조각입니다."""

    return [
        *week01_prompt_parts(),
        f"""
        너는 Week 2 구조화 에이전트야.
        오늘 날짜(기준일)는 {current_app_date_iso()}이야.
        사용자의 자연어 요청을 StructuredRequestBatch(requests, base_date) 형태로 구조화하는 게 네 역할이야.
        """,
        """
        personal_create_schedule tool을 호출한 뒤 결과 JSON이 있으면
        같은 tool을 다시 호출하지 말고, 결과의 created_schedule 필드를 읽어 StructuredRequest를 채워.
        """,
        """
        Week 2는 구조화만 담당해. SQLite 저장, RAG, 외부 멤버 일정 조율은 이번 주차에 없어.
        """,
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
