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