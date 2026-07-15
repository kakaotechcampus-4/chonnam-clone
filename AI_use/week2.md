Q : week02_tools()에서 week1에서 구현한 tool 목록을 그대로 반환하라고 하는데 return personal_create_schedule(), personal_list_schedules(), personal_delete_schedule()이렇게 하는게 맞나?

A : ()를 붙이면 안된다. personal_create_schedule 같은 함수들은 @tool 데코레이터가 붙은 LangChain tool 객체라서, ()로 호출하면 실제 스케줄 생성/조회/삭제가 실행돼버립니다 — agent에 넘길 tool 목록이 아니라 실행 결과(문자열)가 반환됩니다.
, 이미 week01_tools가 있어서 재사용 하면 된다. 

Q : week02_system_prompt(), week02_propmt_parts()의 차이가 뭐야

A : week02_system_prompt()는 **최종 완성된 하나의 문자열(str)**을 반환하는 함수.
join_system_prompt(week02_prompt_parts()) 형태로, 위 조각들을 실제로 합쳐서 LLM에게 넘길 완전한 system prompt를 만듭니다.
build_week02_agent()가 create_agent(...)를 호출할 때 system_prompt=week02_system_prompt()로 바로 사용되는 값입니다

week02_prompt_parts()는 *문자열 조각들의 리스트(list[str])**를 반환하는 함수.
Week 1의 week01_prompt_parts() 결과를 그대로 이어받고(*week01_prompt_parts()), 그 위에 Week 2에서 추가로 필요한 지시사항(자연어를 StructuredRequest 필드로 구조화하라, 현재 날짜 기준 사용, Week 1 tool JSON을 다시 호출하지 말고 읽기만 해라, SQLite/RAG는 안 한다 등)을 조각(item)으로 하나씩 append 하는 자리입니다.

Q : week02_prompt_parts부분 어떻게 작성해야 하는지 예시 조금 알려줘 

A : f"""
너는 2주차 '요청 구조화(structuring)' agent다.
오늘 기준 날짜는 {current_app_date_iso()}이며, "내일", "다음 주 화요일" 같은 상대 날짜 표현은
이 날짜를 기준으로 계산해서 절대 날짜(YYYY-MM-DD)로 변환한다.
"""

Q : 이 코드에 structured_response가 어디 있어?

A : week02_structure_natural_language_requests.py 안에는 structured_response라는 변수나 키가 실제 코드로 존재하지 않습니다 — 전부 주석/docstring에서만 언급됩니다 (week02_structure_natural_language_requests.py:81,89,94,185,205,211).

이유는 structured_response가 이 파일에서 직접 만드는 값이 아니라, LangChain의 create_agent(..., response_format=StructuredRequestBatch)가 내부적으로 생성해주는 결과 키이기 때문입니다.

Q : week02_system_prompt()에서     # TODO: join_system_prompt(...)로 week02_prompt_parts()와 Week 2 structured_response 최종 답변 규칙을 합치는 방법

A : join_system_prompt는 list[str]을 받아서 하나로 합치는 함수니까, week02_prompt_parts()가 반환한 리스트에 "최종 답변 규칙" 문자열을 하나 더 추가해서 통째로 넘기면 됩니다.


def week02_system_prompt() -> str:
    """2주차 agent가 따르는 시스템 프롬프트입니다."""

    final_answer_rule = """
최종 답변은 반드시 StructuredRequestBatch 형식의 structured_response로만 반환하라.
자연어 설명이나 추가 텍스트를 덧붙이지 말고, requests 목록에 StructuredRequest를 담아라.
요청이 하나뿐이어도 requests 목록 안에 StructuredRequest 하나를 넣어라.
base_date에는 현재 날짜를 넣는다.
"""

    return join_system_prompt([
        *week02_prompt_parts(),
        final_answer_rule,
    ])


Q : structuredRequestBatch가 base_date가 프롬프트를 입력한 당시 날짜를 기준으로 작성 되는 거지?

A : 짧게 답하면 "의도는 맞지만 구현상 항상 그렇게 동작하지는 않습니다." 코드를 보면 두 군데에 날짜가 관여합니다.
1. StructuredRequestBatch.base_date 필드
default_factory는 LLM이 base_date 값을 아예 안 채워줬을 때만 실행되는 Pydantic 기본값입니다. 이 경로로 들어가면 실제로 "지금 이 순간"의 날짜가 들어갑니다.
2. 하지만 실제로는 LLM이 직접 base_date를 채웁니다 — 시스템 프롬프트가 그렇게 지시하기 때문입니다 
 그리고 LLM이 "현재 날짜"로 아는 값은 week02_prompt_parts():272-274에서 f-string으로 박아넣은 current_app_date_iso() 값입니다.
문제: build_week02_agent()(:292-304)가 전역 _WEEK02_AGENT를 캐싱합니다.

week02_system_prompt()(→week02_prompt_parts()→current_app_date_iso())는 agent가 처음 생성될 때 딱 한 번만 호출됩니다. 즉 서버를 껐다 켜지 않고 계속 띄워두면, 이후 모든 요청에서 LLM이 참조하는 "현재 날짜"는 최초 agent 생성 시점의 날짜로 고정되고, 그 이후 실제 요청이 들어온 날짜와는 무관하게 그 값을 기준으로 base_date나 "내일" 같은 상대 표현을 해석하게 됩니다.

Q : 현재 날짜는 {current_app_date_iso()}이고, 현재 날짜는 매번 프롬프트를 실행할 때 마다 다시 계산한다. 이렇게 프롬프트 파츠에 추가하는건 어때

A : 그건 실제 동작을 바꾸지 않습니다 — 오히려 거짓 문구가 됩니다.

문제는 current_app_date_iso()가 f-string이 평가되는 시점(=week02_prompt_parts() 호출 시점)에 딱 한 번 계산돼서 프롬프트 문자열에 고정된 값(예: "2026-07-10")으로 박힌다는 것입니다. 그런데 build_week02_agent()가 _WEEK02_AGENT를 캐싱하기 때문에 week02_prompt_parts() 자체가 agent 최초 생성 시 단 한 번만 호출됩니다.

그 상태에서 "현재 날짜는 매번 프롬프트를 실행할 때마다 다시 계산한다"는 문장을 추가하면:

실제로는 재계산되지 않는데
프롬프트 텍스트에는 "매번 재계산된다"고 적혀 있고
심지어 그 문장 옆에는 최초 생성 시점에 고정된 옛 날짜 값이 그대로 박혀 있는
모순된 상태가 됩니다. LLM에게 사실과 다른 지시를 주는 셈이라 문제를 감추기만 하고 고치지는 못합니다.

Q : chat_model().with_structured_output(StructuredRequest, method="function_calling") 이 함수는 어떤 기능이야

A : chat_model()이 LangChain의 ChatOpenAI 인스턴스를 반환하니(fixed/llm.py:15), .with_structured_output(...)은 LangChain 표준 API입니다.

하는 일: 일반 chat model을 감싸서, invoke() 결과가 자유 텍스트가 아니라 지정한 Pydantic 스키마 인스턴스로 바로 나오게 만들어줍니다.

1. StructuredRequest Pydantic 모델의 필드/타입/description을 OpenAI function(tool) 스키마로 자동 변환
2. 모델 호출 시 "이 함수를 반드시 호출해서 답해라"는 식으로 tool을 하나 강제로 노출 (tool_choice를 그 함수로 고정)
3. LLM이 실제로 대화 응답을 만드는 게 아니라 그 함수의 인자로 값을 채워서 반환
4. LangChain이 그 함수 호출 인자를 받아서 StructuredRequest.model_validate(...)로 파싱해 파이썬 객체로 돌려줌

즉 이 줄은 "새 agent를 만들지 않고, 가벼운 단발성 LLM 호출로 text를 StructuredRequest 객체로 강제 변환하는" 역할입니다.

Q : extract_structed_request에서 시스템 메시지랑 user메시지 어떻게 추가해

A : invoke()는 메시지 리스트를 받는데, LangChain에서는 세 가지 표기법을 다 지원합니다. 이 코드베이스엔 아직 메시지 클래스를 안 썼으니, import 없이 쓸 수 있는 튜플 방식이 제일 간단합니다

[("system", "..."), ("human", "...")] # 튜플 (import 불필요가장 짧음)
[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]  # dict (OpenAI 포맷 그대로)
[SystemMessage(content="..."), HumanMessage(content=text)]     # 클래스 (fromlangchain_core.messages import ...)

Q : extract_schedule_request(query)에서 LangChain bridge tool이 뭐야?

A : bridge tool"은 두 단어를 따로 봐야 합니다.

"tool" 부분 — 229번째 줄의 @tool 데코레이터 때문에 이 함수는 그냥 파이썬 함수가 아니라 LangChain Tool 객체가 됩니다. @tool이 붙으면:

함수 이름(extract_schedule_request), docstring(설명), 타입힌트(query: str)로부터 **LLM이 이해할 수 있는 함수 스펙(JSON schema)**이 자동 생성됩니다.
create_agent(tools=[...])처럼 agent의 tool 목록에 넣을 수 있고, agent가 대화 도중 스스로 판단해서 이 tool을 호출할 수 있게 됩니다. (extract_structured_request엔 @tool이 없으니 그냥 파이썬 함수로만 직접 호출되는 것과 대조적입니다.)
"bridge" 부분 — 이 tool은 최종 목적지(DB 저장, 멤버 일정 조율 등) 작업을 직접 하지 않습니다. Week 2가 만든 구조화 로직을 Week 3 이상의 저장/조율 파이프라인이 바로 쓸 수 있게 "연결"만 해주는 역할입니다:

정리하면 "bridge tool" = Week 2의 LLM 기반 구조화 능력을, Week 3 이상의 저장/조율 tool이 바로 소비할 수 있는 JSON 계약(contract)으로 변환해주는, agent가 호출 가능한 LangChain tool입니다. 저장이나 조율 로직 자체는 여기 없고, 그 앞단 "번역기" 역할만 합니다.

Q : # TODO: ok/tool_name/base_date/structured_request 키를 가진 dict를 만들고 structured_request에는 model_dump() 결과를 넣으세요.
    # TODO: json.dumps(..., ensure_ascii=False)로 JSON 문자열을 반환하세요. 이건 어떻게 하는지 알려줘

A  : Week 1 도구들(personal_create_schedule 등)이 이미 같은 패턴을 쓰고 있어서 그 컨벤션을 그대로 따르면 됩니다 
extract_structured_request(query) → 앞서 만든 함수를 호출해 StructuredRequest 객체를 받습니다.
"ok": True → Week 1 tool들과 동일한 관례. 구조화가 성공했다는 표시 (파싱 실패 시 예외가 나서 여기까지 안 옴).
"tool_name": "extract_schedule_request" → 이 값도 Week1 관례 그대로, 자기 자신의 함수 이름을 문자열로 박아넣는 것입니다. Week3 agent가 여러 tool 결과를 trace할 때 어떤 tool이 만든 결과인지 구분하는 용도입니다.
"base_date": current_app_date_iso() → 이 파일 상단에 이미 import돼 있는 함수(line 12)를 그대로 호출. extract_structured_request 자체는 base_date를 안 주므로 여기서 따로 채워줍니다.
"structured_request": structured_request.model_dump() → 핵심 포인트: structured_request는 Pydantic 모델 객체라서 json.dumps()가 그대로 직렬화 못 합니다. .model_dump()를 호출하면 Pydantic 모델 → 순수 파이썬 dict로 변환되고, 그 dict를 넣어야 json.dumps가 동작합니다.
json.dumps(payload, ensure_ascii=False) → dict 전체를 JSON 문자열로 직렬화. ensure_ascii=False는 한글이 \uXXXX로 이스케이프되지 않고 그대로 출력되게 하는 옵션 (Week1 도구들도 동일하게 씀, line 140).
@tool로 감싼 함수는 반환 타입이 str이어야 하니(agent가 tool 실행 결과를 문자열 observation으로 받음), dict를 바로 반환하면 안 되고 반드시 json.dumps로 문자열화해서 반환해야 합니다.

Q  : structured_request에 왜 model_dump를 붙여?

A : structured_request는 StructuredRequest라는 Pydantic 객체지, json.dumps가 이해하는 기본 타입(dict/list/str/int/bool/None)이 아니기 때문입니다.
json.dumps는 파이썬 내장 타입만 직렬화할 줄 알지, StructuredRequest라는 커스텀 클래스 인스턴스를 어떻게 JSON으로 바꿔야 하는지 모릅니다.

.model_dump()가 하는 일:
Pydantic 모델 인스턴스를 **필드 그대로의 값을 가진 순수 파이썬 dict**로 변환해줍니다.