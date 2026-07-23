"""Week 4 tool 선택 few-shot 예시.

실제 agent를 여러 경계 질의로 돌려본 결과(8개 질문), search_conversation_messages와
search_personal_references는 잘 선택됐지만, search_saved_requests는 단 한 번도
선택되지 않았다. 일정/예약 관련 질문은 항상 Week 1/3에서 만든
personal_list_saved_schedules로 라우팅됐는데, 이 tool도 같은 structured_requests
테이블을 읽지만 docstring이 "일정 목록을 조회"라고 더 직접적으로 일정을 언급해서
LLM이 거의 항상 이쪽만 선택하는 것으로 보인다.

이 few-shot은 두 tool의 역할 경계를 명확히 하기 위한 것이다.
- personal_list_saved_schedules: 날짜/종류로 필터링한 일정 "목록"을 볼 때.
- search_saved_requests: 제목/사유/원문에 특정 키워드가 포함된 기록을 "검색"할 때.
"""

WEEK04_TOOL_SELECTION_FEW_SHOT = """
[tool 선택 few-shot 예시]
질문: "내일 일정 뭐 있어?"
-> personal_list_saved_schedules (날짜로 필터링한 목록 조회)

질문: "이번 주에 예약해둔 거 다 보여줘"
-> personal_list_saved_schedules (기간으로 필터링한 목록 조회)

질문: "저장해둔 일정 중에 '워크숍'이라는 단어 들어간 거 있어?"
-> search_saved_requests (제목/사유에 특정 키워드가 있는지 검색)

질문: "예전에 '재무팀'이랑 관련해서 저장해둔 일정이나 할 일 있었나?"
-> search_saved_requests (핵심어 기반 검색, 날짜/종류 필터가 아님)

질문: "예전에 나눴던 대화 중에 여행 얘기 있었나?"
-> search_conversation_messages (과거 대화 이력 검색)

질문: "메모해둔 참고자료 중에 커피 관련된 거 있어?"
-> search_personal_references (개인 참고자료 검색)
""".strip()


# 8개 경계 질의로 실제 agent를 돌려본 결과, "기억해줘"/"잊지 마"류 요청 중 3/8에서
# tool을 아예 호출하지 않고 "기억해뒀다"고만 답해 실제로는 아무 데도 저장되지 않았다
# (사용자에게는 저장된 것처럼 보이는 false confirmation). 날짜 유무를 1차 기준으로 먼저 걸러야
# 정보성 사실(날짜 없음)이 add_personal_reference로 확실히 라우팅된다.
WEEK04_SAVE_ROUTING_GUIDE = """
[정보 저장 tool 선택 가이드]
사용자가 정보/사실/할 일/일정/리마인더를 "기억해줘"/"잊지 마"라고 말하면,
tool 호출 없이 말로만 "기억해뒀다"고 답하지 않는다 - 반드시 아래 기준으로 tool을 호출해 실제로 저장한 뒤 답한다.

1. 날짜/마감이 있는 요청이면 -> extract_schedule_request (일정/할 일/알림으로 분류되어 저장됨)
   예) "내일 오전에 우산 챙기라고 알려줘", "환불 마감이 이번 달 말이야, 잊지 말고 있어"
2. 날짜가 없고 사용자가 직접 해야 하는 행동이면 -> extract_schedule_request (todo로 분류됨)
   예) "우유 좀 사야겠다, 기억해줘", "보고서 초안 써야 하는 거 잊지 마"
3. 날짜도 없고 행동도 아닌 단순 사실/지식/정보면 -> add_personal_reference
   예) "우리 팀 커피 취향은 다 아메리카노야, 기억해둬", "이 프로젝트 배포 서버 주소는 10.0.0.5야, 기억해놔"
""".strip()
