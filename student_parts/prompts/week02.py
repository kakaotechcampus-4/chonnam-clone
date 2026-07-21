WEEK02_CLASSIFICATION_PROMPT = """
사용자의 발화가 일정, 할 일, 알림처럼 처리 가능한 요청인지 판단한다.
처리 가능한 요청 의도가 명확하지 않으면 부족한 값을 묻지 말고 status="complete"로 둔다.
이때 structured_request 안에 kind="unknown"인 요청을 담고,
title/date/start_time/end_time/priority는 None, members는 빈 list로 둔다.
reason에는 unknown으로 판단한 근거를 짧게 적는다.
"""

WEEK02_CLARIFICATION_STATE_PROMPT = """
먼저 대화 전체를 읽고 이전 턴에서 받은 제목, 날짜, 시간과 새 사용자 답변을 합쳐 판단한다.
일정 생성 또는 등록 요청에는 title, date, start_time이 필요하다.

필수값이 부족하거나 모호하면 status="needs_clarification"으로 둔다.
missing_fields에는 확인이 필요한 필드 이름을 모두 담고 structured_request는 null로 둔다.
clarification_question은 Python의 고정 문장을 기대하지 말고,
현재 대화에 맞춰 필요한 필드만 한 번에 묻는 자연스러운 한국어 질문으로 직접 만든다.

필요한 정보가 모두 채워졌으면 status="complete", clarification_question=null,
missing_fields=[]로 두고 structured_request를 완성한다.
"""

WEEK02_STRUCTURED_OUTPUT_PROMPT = """
최종 결과는 Week02Response로 구조화한다.
complete의 structured_request는 StructuredRequestBatch다.
자연어 요청은 요청 단위로 나누며, 요청이 하나뿐이어도 requests 목록에 담는다.

StructuredRequest 필드는 다음 기준으로 채운다.
- kind: personal_schedule, group_schedule, todo, reminder, unknown 중 하나만 사용한다.
- title: 일정, 할 일, 알림의 제목을 채운다. 확실하지 않으면 None이다.
- date: 확실할 때만 YYYY-MM-DD 형식으로 채운다. 날짜 언급이 없으면 base_date를 복사하지 않는다.
- start_time/end_time: 확실할 때만 HH:MM 형식으로 채운다.
- members: 참석자나 관련 멤버를 list로 채운다. 없거나 모르면 빈 list다.
- priority: 사용자가 말한 우선순위가 있을 때만 채운다.
- reason: 어떤 표현이나 tool payload를 근거로 구조화했는지 짧게 적는다.
- original_text: 사용자 원문을 그대로 보존한다. tool 결과나 내부 메타데이터로 대체하지 않는다.

base_date에는 현재 앱 기준 날짜를 YYYY-MM-DD 형식으로 담는다.
모르는 scalar 값은 None, list 값은 빈 list로 두고 억지로 만들지 않는다.
"""

WEEK02_PERSONAL_CREATE_TOOL_PROMPT = """
개인 일정 생성 요청의 title, date, start_time이 모두 명확할 때만 personal_create_schedule을 호출한다.
tool 결과의 ok가 false이면 완료로 확정하지 말고 missing_fields와 invalid_fields를 확인한다.
"""

WEEK02_TOOL_PAYLOAD_MAPPING_PROMPT = """
Week 1 tool JSON을 받은 경우 같은 정보를 다시 추측하지 말고 payload를 읽는다.
personal_create_schedule 결과의 created_schedule을 개인 일정 구조화의 우선 근거로 사용한다.
created_schedule.title은 title, date는 date, start_time은 start_time,
attendees는 members로 옮긴다. end_time이 "미정"이면 end_time은 None으로 둔다.
"""

WEEK02_SCOPE_PROMPT = """
Week 2에서는 SQLite 저장, RAG 검색, 외부 멤버 일정 조율을 하지 않는다.
"""
