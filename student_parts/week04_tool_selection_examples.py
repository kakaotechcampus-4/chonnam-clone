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
