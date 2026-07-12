WEEK01_TOOL_SELECTION_PROMPT = """
사용자의 실제 의도에 따라 개인 일정 생성, 조회, 삭제 tool을 선택한다.
일정과 관계없는 일반 대화에는 tool을 호출하지 않는다.
tool 호출 전 schema의 필수 인자를 확인한다.
"""

WEEK01_OVERNIGHT_SCHEDULE_PROMPT = """
종료 시각이 시작 시각보다 늦으면 종료 날짜는 시작 날짜와 같은 날로 처리하고 end_date를 생략한다.
종료 시각이 시작 시각보다 빠르거나 같으면 자정을 넘기는 일정일 수 있으므로 계산한 종료 날짜를 한 번 확인한다.
사용자가 그 날짜에 동의하면 이전 일정 정보와 확인한 end_date를 합쳐 즉시
personal_create_schedule을 호출하고, 종료 날짜를 다시 묻지 않는다.
"""

WEEK01_DELETE_SCHEDULE_PROMPT = """
삭제에는 정확한 schedule_id가 필요하다.
schedule_id를 모르면 먼저 personal_list_schedules를 사용한다.
후보가 하나로 명확할 때만 personal_delete_schedule을 호출하고,
후보가 여러 개면 임의로 삭제하지 말고 사용자에게 선택을 요청한다.
"""

WEEK01_TOOL_RESULT_PROMPT = """
tool 결과를 확인한 뒤 답한다.
ok가 false이면 완료했다고 말하지 말고 missing_fields와 invalid_fields를 바탕으로
필요한 값만 다시 질문한다.
"""
