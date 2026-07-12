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
    kind: RequestKind = Field(description="""
                            사용자의 입력을 RequestKind 중 정확히 하나로 분류한다.
                            가능한 값은 personal_schedule, group_schedule, todo, reminder, unknown 뿐이다.

                            핵심 원칙:
                            - 일정에 대한 행동을 취해야 하면 todo이다. [Do에 집중]
                            - 일정이 이미 존재하거나 예정되어 있음을 말하면 schedule이다. [Be에 집중]
                            - 개인 일정이면 personal_schedule, 다른 사람과 함께하는 일정이면 group_schedule이다.
                            - "예약"이라는 단어가 있어도 "예약 있어"는 personal_schedule이고, "예약 해야돼/예약해야 해/예약하기/예약 잡아야 해"는 반드시 todo이다.

                            분류 우선순위:
                            1. 알림을 설정하거나 특정 시점에 알려달라는 요청이면 reminder
                            2. 사용자가 앞으로 해야 할 행동이 핵심이면 todo
                            3. 이미 잡힌 일정의 존재를 말하고, 개인 일정이면 personal_schedule
                            4. 이미 잡힌 일정의 존재를 말하고, 공동 참여 일정이면 group_schedule
                            5. 위에 해당하지 않으면 unknown

                            todo:
                            사용자가 앞으로 완료해야 하는 행동, 작업, 준비, 제출, 구매, 연락, 작성, 예약, 예매, 신청, 등록 등이 핵심이면 todo이다.
                            날짜/시간이 포함되어 있어도, 그 시점이 마감이나 실행 시점일 뿐이고 사용자가 해야 할 행동이 핵심이면 todo로 분류한다.

                            특히 아래 표현은 반드시 todo로 분류한다:
                            - "예약 해야돼", "예약해야 해", "예약하기", "예약 잡아야 해"
                            - "예매해야 해", "신청해야 해", "등록해야 해"
                            - "제출해야 해", "보내야 해", "전화해야 해", "준비해야 해"

                            Examples:
                            - "내일 오후 3시에 치과 예약 해야돼" -> todo
                            - "내일 오후 3시까지 치과 예약해야 해" -> todo
                            - "내일 치과 예약 잡기" -> todo
                            - "모레까지 보고서 제출하는 거 잊지마" -> todo
                            - "회의 전에 자료 출력해두기" -> todo
                            - "민수한테 전화하기" -> todo

                            personal_schedule:
                            사용자 개인에게 이미 잡혀 있거나 예정된 일정의 존재를 말하는 경우.
                            사용자가 새로 해야 할 행동보다, 그 일정이 있다는 사실이 핵심이면 personal_schedule이다.

                            Examples:
                            - "내일 오후 3시에 치과 예약 있어" -> personal_schedule
                            - "내일 오후 3시에 치과 가야 돼" -> personal_schedule
                            - "금요일 오전에 건강검진이야" -> personal_schedule
                            - "다음 주 화요일에 면접 있어" -> personal_schedule

                            group_schedule:
                            두 명 이상이 함께 참여하는 일정, 약속, 회의, 모임, 수업, 행사, 팀 활동의 존재를 말하는 경우.
                            일정 자체가 핵심이면 group_schedule이고, 그 일정을 위해 해야 할 준비 행동이면 todo이다.

                            Examples:
                            - "내일 오후 2시에 팀 회의 있어" -> group_schedule
                            - "토요일에 민수랑 점심 약속 있어" -> group_schedule
                            - "금요일 7시에 스터디 모임" -> group_schedule
                            - "회의 전에 자료 준비해야 해" -> todo

                            reminder:
                            사용자가 특정 시점에 알림을 받거나 다시 알려달라고 명시적으로 요청한 경우.

                            Examples:
                            - "내일 오전 9시에 회의 있다고 알려줘" -> reminder
                            - "30분 뒤에 약 먹으라고 리마인드해줘" -> reminder

                            unknown:
                            위 네 가지로 분류할 수 없는 일반 대화, 감정 표현, 과거 경험, 단순 정보, 질문, 잡담.

                            Examples:
                            - "어제 저녁 10시에 과제했더니 피곤하네" -> unknown
                            - "요즘 너무 바빠" -> unknown
                            - "안녕?" -> unknown

                            헷갈리는 비교:
                            - "치과 예약 있어" -> personal_schedule
                            - "치과 예약 해야돼" -> todo
                            - "치과 가야 돼" -> personal_schedule
                            - "치과 예약 잡아야 돼" -> todo
                            - "회의 있어" -> group_schedule
                            - "회의 자료 준비해야 해" -> todo
                            
                            가장 중요한 판정 규칙:
                            사용자가 아직 하지 않은 행동을 해야 한다고 말하면 반드시 todo이다.
                            날짜나 시간이 함께 있어도, 그 날짜/시간은 할 일의 마감 또는 목표 시점일 뿐이다.

                            특히 다음 표현이 있으면 반드시 todo로 분류한다:
                            - 해야돼 / 해야 해 / 해야 한다
                            - 하기 / 해두기 / 준비하기
                            - 잡아야 해 / 예약해야 해 / 신청해야 해 / 제출해야 해
                            - 잊지마, 까먹지마

                            예외:
                            이미 일정이 잡혀 있음을 말하는 경우만 schedule로 분류한다.
                            - "예약 있어", "일정 있어", "회의 있어", "약속 있어", "면접이야", "수업이야"

                            중요한 비교:
                            - "내일 오후 3시에 치과 예약 해야돼" -> todo
                            이유: 치과 예약이 이미 있는 것이 아니라, 사용자가 예약하는 행동을 해야 하기 때문
                            - "내일 오후 3시에 치과 예약 있어" -> personal_schedule
                            이유: 이미 잡힌 개인 일정의 존재를 말하기 때문
                            - "내일 오후 3시에 치과 가야 돼" -> personal_schedule
                            이유: 치과 방문 일정에 참석해야 한다는 뜻이기 때문
                            - "내일 오후 3시까지 치과 예약해야 해" -> todo
                            이유: 예약하는 행동을 완료해야 하기 때문

                            분류 우선순위:
                            1. "알려줘", "리마인드해줘", "깨워줘"처럼 알림 요청이면 reminder
                            2. "해야 해", "하기", "준비", "제출", "예약해야 해"처럼 수행할 행동이면 todo
                            3. 이미 존재하는 공동 일정이면 group_schedule
                            4. 이미 존재하는 개인 일정이면 personal_schedule
                            5. 그 외는 unknown
                            """)
    # TODO: title/date/start_time/end_time 필드를 str | None 타입으로 선언하고 기본값은 None으로 두세요.
    title: str | None = Field(default=None, description="""
                            사용자의 요청 또는 기록 내용을 짧은 명사구/문장으로 요약한다.
                            원문 전체를 복사하지 말고, 사용자가 하려는 일이나 남기려는 정보를 핵심만 담는다.
                            값을 추론할 수 없으면 빈 문자열이 아니라, 입력에서 확인 가능한 최소 내용으로 작성한다.

                            Examples:
                            - "내일 오후 3시에 치과 예약 해야돼" -> "치과 예약하기"
                            - "모레까지 보고서 제출하는 거 잊지마" -> "보고서 제출"
                            - "어제 저녁 10시에 과제했더니 피곤하네" -> "과제 후 피곤함"
                            """)
    date: str | None = Field(default=None, description="YYYY-MM-DD")
    start_time: str | None = Field(default=None, description="HH:MM")
    end_time: str | None = Field(default=None, description="HH:MM")
    # TODO: members 필드를 list[str] 타입으로 선언하고 default_factory=list를 사용하세요.
    members: list[str] = Field(default_factory=list, description="""
                            요청에 관련된 사람들의 이름 목록이다.
                            사용자 본인은 포함하지 않는다.
                            명시적으로 등장한 사람만 포함하고, 추측하지 않는다.
                            사람 이름이 없으면 빈 배열 []을 사용한다.

                            Examples:
                            - "민수한테 내일 전화해야 해" -> ["민수"]
                            - "엄마 생신 선물 사기" -> ["엄마"]
                            - "내일 치과 예약 해야돼" -> []
                            """)
    # TODO: priority/reason 필드를 str | None 타입으로 선언하고 기본값은 None으로 두세요.
    priority: str | None = Field(default=None, description="""
                                요청의 중요도/긴급도를 분류한다.
                                명시적 단서가 없으면 기본값은 medium으로 둔다.

                                high:
                                - 오늘/내일처럼 임박한 마감
                                - "급해", "반드시", "중요", "최대한 빨리" 등 강한 표현
                                - 병원, 결제, 제출, 면접, 시험 등 놓치면 손해가 큰 일

                                medium:
                                - 일반적인 할 일 또는 명확한 마감이 있지만 강한 긴급 표현은 없음
                                - 기본값

                                low:
                                - 언젠가, 나중에, 시간 나면 등 느슨한 표현
                                - 참고용 기록, 가벼운 아이디어

                                Examples:
                                - "오늘 안에 세금 납부해야 해" -> high
                                - "모레까지 보고서 제출" -> high 또는 medium, 정책에 따라 고정 필요
                                - "책 추천 리스트 정리하기" -> medium
                                - "나중에 사고 싶은 키보드 적어둬" -> low
                                
                                """)
    reason: str | None = Field(default=None, description="""
                            priority를 선택한 이유를 짧게 설명한다.
                            사용자 요청에 특정 일정이 언급되어 있고, 그 일정과의 관계 때문에 중요도가 달라진다면 그 내용을 함께 적는다.

                            일정과의 관계 표현:
                            - "+": 특정 일정과 직접적으로 관련되어 더 중요하다고 판단한 경우
                            - "-": 특정 일정과 관련은 있지만 핵심 행동이 아니거나, 일정 대비 보조적/덜 중요한 경우

                            특정 일정이 언급된 경우에는 해당 일정의 title을 짧게 포함한다.
                            일정이 명확하지 않으면 + 또는 -를 사용하지 않는다.
                            reason은 추측이 아니라 사용자 문장에 드러난 단서를 기반으로 작성한다.

                            Examples:
                            - "내일 오후 3시에 치과 예약 해야돼"
                            -> "내일 오후 3시 일정인 '치과 예약'과 직접 관련되어 중요도가 높음 (+)"

                            - "모레까지 보고서 제출하는 거 잊지마"
                            -> "모레까지 제출해야 하는 '보고서 제출' 마감과 직접 관련되어 중요도가 높음 (+)"

                            - "다음 주 면접 전에 자기소개서 한 번 읽어보기"
                            -> "다음 주 '면접'을 준비하기 위한 작업이라 일정과 관련되어 있음 (+)"

                            - "여행 갈 때 읽을 책 찾아보기"
                            -> "'여행'과 관련은 있지만 필수 준비물이나 마감 행동은 아니므로 보조적인 요청으로 판단함 (-)"

                            - "나중에 사고 싶은 키보드 적어둬"
                            -> "명확한 마감이나 중요한 일정이 없어 낮은 중요도로 판단함"
                            
                            """)
    # TODO: original_text 필드를 str 타입으로 선언하고 기본값은 ""로 두세요.
    original_text: str | None = Field(default="", description="원문 보존용 필드야. reason에서 언급되거나 사용되는 사용자 요청의 원문을 작성해줘.")
    # TODO: 각 필드에는 LLM structured output이 이해할 수 있도록 한국어 description을 달아주세요.
    ...


class StructuredRequestBatch(BaseModel):
    """여러 자연어 의도를 StructuredRequest 목록으로 나누는 2차 과제 스키마입니다."""

    # TODO: requests 필드를 list[StructuredRequest] 타입으로 선언하고 default_factory=list를 사용하세요.
    requests: list[StructuredRequest] = Field(default_factory=list, description="""
                                            사용자 입력에서 추출한 요청들의 배열이다.
                                            하나의 입력에 여러 개의 독립적인 할 일/알림/기록이 있으면 여러 request로 분리한다.
                                            서로 같은 의미의 내용은 중복 생성하지 않는다.
                                            분류가 애매해도 입력 전체를 버리지 말고 가장 가까운 kind로 하나 이상 생성한다.

                                            Examples:
                                            - "내일 병원 예약하고 민수한테 전화해야 해"
                                            -> [
                                                {"kind": "todo", "summary": "병원 예약하기", "members": [], ...},
                                                {"kind": "todo", "summary": "민수에게 전화하기", "members": ["민수"], ...}
                                            ]

                                            - "어제 과제했더니 피곤하네"
                                            -> [
                                                {"kind": "personal", "summary": "과제 후 피곤함", "members": [], ...}
                                            ]
                                            """)
    # TODO: base_date 필드를 str 타입으로 선언하고 default_factory=current_app_date_iso를 사용하세요.
    base_date: str = Field(default_factory=current_app_date_iso, description="사용자 요청에 상대적인 날짜 개념이 나오면 base_date를 토대로 계산해줘.")
    # TODO: 각 필드에는 Week 2 구조화 결과와 상대 날짜 기준일을 설명하는 한국어 description을 달아주세요.
    ...


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

    # TODO: Week 1에서 구현한 tool 목록을 그대로 반환하세요.
    return week01_tools()
    ...


def week02_system_prompt() -> str:
    """2주차 agent가 따르는 시스템 프롬프트입니다."""

    # TODO: join_system_prompt(...)로 week02_prompt_parts()와 Week 2 structured_response 최종 답변 규칙을 합치세요.
    # TODO: StructuredRequestBatch에는 요청이 하나뿐이어도 requests 목록에 StructuredRequest 하나를 담도록 지시하세요.
    # TODO: personal_create_schedule tool 결과 JSON의 created_schedule을 읽어 필드를 채우도록 지시하세요.
    structured_response=["StructuredRequestBatch에는 요청이 하나뿐이어도 requests 목록에 StructuredRequest 하나를 담아야한다."
                        , "personal_create_schedule tool의 실행 결과인 JSON의 created_schedule을 읽어서 StructuredRequest의 필드 값을 채운다."
                        , "사용자 요청만으로 유추가 안되는 항목은 각 필드의 default 항목을 따른다.",
    """
    사용자의 메시지 전체를 하나의 분석 단위로 처리한다.

    문장, 줄바꿈, 마침표의 개수만으로 요청을 분리하지 않는다.
    새로운 제목이나 독립적인 행동 의도가 명시된 경우에만 별개의 요청으로 판단한다.
    참석자, 소요 시간, 종료 시간, 장소 등의 문장은 새로운 요청이 아니라
    가장 가까운 앞 일정의 추가 정보로 결합한다.

    최종 응답은 반드시 JSON 객체 정확히 하나만 반환한다.
    설명, Markdown, 코드 블록 또는 두 개 이상의 최상위 JSON 객체를 반환하지 않는다.
    여러 요청이 있더라도 JSON 객체를 여러 개 출력하지 말고,
    하나의 StructuredRequestBatch 객체의 requests 배열 안에 모두 담는다.

    최종 출력 전 다음 조건을 확인한다.
    1. 최상위 JSON 객체가 정확히 하나인가?
    2. 최상위 필드가 requests와 base_date인가?
    3. 모든 요청이 requests 배열 안에 포함되어 있는가?
    
    예:
    "오늘 오후 7시에 독서모임 가질 거야.
    준수랑 승찬이가 함께할 거고 2시간 정도 걸릴 예정."

    위 입력은 두 개의 요청이 아니다.
    두 번째 문장은 첫 번째 독서모임의 members와 end_time을 보충한다.
    따라서 requests 배열에는 독서모임 요청 하나만 포함한다.
    """,
    """
    중요:
    personal_create_schedule tool의 이름에 포함된 "personal"은 Week 1 도구 이름일 뿐,
    StructuredRequest.kind를 personal_schedule로 결정하라는 뜻이 아니다.

    tool 결과의 created_schedule은 title/date/start_time/end_time/members 값을 참고하기 위한 payload이다.
    kind는 반드시 original_text와 members를 기준으로 다시 분류한다.

    특히 created_schedule.members 또는 StructuredRequest.members가 비어 있지 않고,
    사용자 입력이 일정의 존재를 말한다면 personal_schedule이 아니라 group_schedule로 분류한다.

    Examples:
    - "내일 승찬이랑 영어모임 가지기로 했어" -> group_schedule
    - "토요일에 민수랑 점심 약속 있어" -> group_schedule
    - "오늘 지현이랑 카페 가기로 했어" -> group_schedule
    """
                        ]
    return join_system_prompt([*week02_prompt_parts(),*structured_response])
    
    ...


def week02_prompt_parts() -> list[str]:
    """2주차 structured output agent가 따르는 system prompt 조각입니다."""

    return [
        *week01_prompt_parts(),
        # TODO: Week 2 요청 구조화 agent 역할과 현재 날짜(current_app_date_iso()) 기준을 추가하세요.
        "여기서는 사용자 요청에 따른 결과값을 StructuredRequest형식에 맞추어 조화된 출력값을 만들고, 그 과정에서 현재 날짜가 필요한 경우 base_date를 따른다."
        ,"자연어를 StructuredRequestBatch로 출력한다는 규칙은 무조건 지킨다"
        # TODO: 자연어를 StructuredRequest 필드(kind/title/date/start_time/end_time/members 등)로 구조화하도록 지시하세요.
        , "사용자의 요청을 분석하여 각 필드에 해당하는 값을 유추하여 출력을 구조화한다."
        # TODO: Week 1 tool JSON을 받은 경우 다시 tool을 호출하지 않고 payload를 읽어 structured_response로 만들도록 지시하세요.
        , "Week 1의 tool을 통해 JSON 결과값을 받은 경우, 다시 tool을 호출하지 않고, payload를 읽어 structured_response를 만든다."
        # TODO: Week 2에서는 SQLite 저장, RAG, 외부 멤버 일정 조율을 하지 않는다고 명시하세요.
        , "Week 2에서는 SQLite 저장, RAG, 외부 멤버 일정 조율을 하지 않는다"
    ]


def build_week02_agent() -> object:
    """Week 2 대화에서 structured_response를 직접 반환하는 단일 LangChain agent를 만듭니다."""

    # TODO: CONFIG.has_openai_key가 없으면 RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")를 발생시키세요.
    if not CONFIG.has_openai_key :
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    # TODO: 전역 _WEEK02_AGENT를 재사용하고, 아직 없을 때만 create_agent(...)로 새 agent를 만드세요.
    global _WEEK02_AGENT
    
    # TODO: create_agent에는 model=chat_model(), tools=week02_tools(), response_format=StructuredRequestBatch,
    #       system_prompt=week02_system_prompt()를 연결하세요.
    if _WEEK02_AGENT is None:
        _WEEK02_AGENT = create_agent(
            model=chat_model(),
            tools=week02_tools(),
            response_format=StructuredRequestBatch,
            system_prompt=week02_system_prompt(),
        )
    # TODO: 생성 또는 재사용한 _WEEK02_AGENT를 반환하세요.
    return _WEEK02_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week02_agent()
