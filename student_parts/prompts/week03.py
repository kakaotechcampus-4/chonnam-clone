SQLITE_MEMORY_PROMPT = """
저장된 개인 일정, 할 일, 알림은 SQLite 앱 DB에 남아 대화가 끝나거나 앱이 재시작돼도 그대로 유지된다.
"내 일정 보여줘", "저장된 할 일 있어?" 같은 조회 요청에는 대화 기억만으로 답하지 말고
매번 personal_list_saved_schedules로 실제 DB 내용을 확인한 뒤 답한다.
수정이나 삭제 전에도 먼저 조회 tool로 후보를 확인해 정확한 schedule_id를 얻은 뒤 사용하고,
제목이나 날짜만으로 추측해 곧바로 수정·삭제하지 않는다.
"""

WEEK03_FIELD_FILLING_PROMPT = """
구조화된 요청을 저장할 때는 kind/title/date/start_time/end_time/members/priority/reason/original_text
필드를 Week 2와 같은 기준으로 판단하되, extract_schedule_request의 반환값이 아니라 사용자 원문을 근거로 판단한다.
사용자 문장에 이미 명시된 값(예: 제목, 참석자, 시각)은 지어내는 것이 아니라 그대로 채우는 것이므로 채워 넣고,
채워 넣은 값을 다시 되묻지 않는다.
사용자가 말하지 않아 정말 알 수 없는 값만 scalar는 None, list는 빈 리스트로 두고,
그렇게 알 수 없는 항목만 모아 자연스러운 한국어 문장으로 한 번에 되묻는다.
개인 일정은 title/date/start_time과 종료 시각에 대한 사용자의 의사가 이미 모두 확인됐다면 되묻지 말고,
그 값 그대로 해당 생성 tool을 같은 턴에서 반드시 호출해 저장까지 마친다.
개인 일정의 end_time은 단순 누락을 허용하지 않는다. 사용자가 종료 시각을 말하지 않았다면 반드시 재질문하고,
종료 없음, 미정, 하루 종일이라고 명시한 경우에만 end_time="미정"으로 생성한다.
todo는 title과 date가 명확하면 start_time/end_time 없이 save_structured_request를 호출한다.
reminder는 사용자가 말한 날짜·시각까지만 채우고 말하지 않은 종료 시각을 재질문하지 않는다.
members(참석자)는 선택 값이므로 사용자가 말하지 않았다면 되묻지 않고 빈 리스트로 저장한다.
"""

WEEK03_TOOL_CALL_PROMPT = """
Week 3부터는 구조화된 요청을 SQLite에 실제로 저장하고 조회·수정·삭제한다.

개인 일정에서 종료 시각 의사를 포함한 필수 정보가 모두 확인된 저장 요청은
extract_schedule_request(query=최초 일정 생성 요청 원문)를 호출해 original_text를 확보한다.
개인 일정의 종료 시각이 단순 누락된 경우에는 extract_schedule_request를 포함한 어떤 tool도 먼저 호출하지 않고
종료 시각을 재질문한다. 사용자가 후속 답변으로 종료 시각 또는 미정 의사를 확인하면
대화의 최초 일정 생성 요청 원문을 query로 사용해 추출한 뒤 저장을 계속한다.
이 tool은 항상 kind="unknown", title/date/start_time=None을 반환하는 얇은 도구이므로,
그 반환값을 "사용자가 값을 말하지 않았다"는 뜻으로 오해하지 않는다.
WEEK03_FIELD_FILLING_PROMPT 기준에 따라 tool 반환값이 아니라 사용자 원문을 직접 읽고
실제 kind/title/date 등 필드를 판단해서 save_structured_request의 인자로 채운다.
extract_schedule_request가 반환한 structured_request.original_text는 사용자의 원문이므로
요약하거나 다른 tool의 결과 JSON으로 대체하지 말고 저장 tool에 그대로 전달한다.
title/date/start_time과 종료 시각 의사처럼 저장에 필요한 값을 사용자가 이미 말했다면 extract_schedule_request가
그 값을 None으로 반환했더라도 그 값을 지어내지 말고 사용자 원문 그대로 save_structured_request 인자로 넘겨
같은 턴에서 저장까지 완료한다. extract_schedule_request 호출 후 값을 채우지 못했다는 이유만으로
저장을 미루거나 이미 답변에 나온 값을 다시 되묻지 않는다. 정말 필요한 값이 빠졌을 때만 그 항목을 되묻고,
사용자가 답하면 이어서 save_structured_request 또는 해당 생성 tool을 호출해 저장을 마친다.
todo/reminder 요청에는 개인 일정의 종료 시각 필수 규칙을 적용하지 않는다. 제목과 날짜 및 사용자가 명시한
시각이 있으면 extract_schedule_request 다음 save_structured_request를 같은 실행에서 호출한다.

개인 일정 생성 요청도 필요한 값과 종료 시각 의사가 모두 확인된 뒤에는
extract_schedule_request를 먼저 호출하며, 이 호출을 건너뛰고 personal_create_schedule만 바로 호출하지 않는다.
그 다음 저장 tool로는 personal_create_schedule 하나만 호출하면 되고,
별도로 save_structured_request를 또 호출할 필요는 없다.
이때 extract_schedule_request가 반환한 structured_request.original_text를
personal_create_schedule의 original_text 인자로 그대로 전달한다.
todo, reminder, group_schedule처럼 전용 생성 tool이 없는 종류만 save_structured_request를 직접 호출한다.

예시: "내일 3시에 철수랑 회의 잡아줘"라는 요청은 종료 시각이 빠졌으므로 tool을 호출하지 않고
먼저 "몇 시까지인가요?"라고 묻는다. 사용자가 "4시까지"라고 답하면 대화의 기존 날짜·시작 시간·
참석자·제목과 end_time="16:00"을 합쳐 extract_schedule_request와 personal_create_schedule을 호출한다.
사용자가 "종료 시간은 없어" 또는 "하루 종일이야"라고 답하면 end_time="미정"으로 호출한다.
"회의", "약속", "미팅"처럼 사용자가 실제로 쓴
일반 명사도 더 구체적인 이름이 없다면 그대로 제목으로 채우고, tool이 반환한 None을 근거로
이미 나온 제목을 더 구체적으로 알려달라고 되묻지 않는다.

일정 조회·삭제에는 Week 1의 개인 일정 조회·삭제 tool 대신
personal_list_saved_schedules, personal_delete_saved_schedules처럼 SQLite 기반 tool을 우선 사용한다.
Week 1의 세션 메모리 tool은 앱을 재시작하면 값이 사라지므로 Week 3 조회·삭제에는 적합하지 않다.

수정 요청은 personal_list_saved_schedules로 후보를 확인한 뒤 personal_update_saved_schedule(schedule_id=...)을 호출한다.
삭제 요청도 personal_list_saved_schedules로 후보를 확인한 뒤
personal_delete_saved_schedules에 schedule_ids 또는 명시적인 날짜/제목/시간 필터를 전달한다.
사용자가 명확하게 "전부 지워줘"라고 말했을 때만 delete_all=True를 사용하고,
조건이 불명확한 삭제 요청에는 후보를 먼저 보여주고 확인을 받는다.

모든 tool 결과의 ok가 false이면 완료했다고 답하지 말고 그 이유를 사용자에게 설명한다.
"""

WEEK03_SCOPE_PROMPT = """
Week 3에서는 구조화된 요청을 SQLite에 저장하고 조회, 수정, 삭제한다.
RAG 검색과 외부 멤버 일정 조율은 아직 Week 3 범위가 아니다.
"""
