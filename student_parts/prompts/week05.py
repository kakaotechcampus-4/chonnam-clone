"""Week 05 외부 대화·공유 일정 MCP 정책입니다.

공통 정체성, 날짜 해석, 개인 일정, SQLite 저장, RAG 정책은 이전 주차 prompt에서
누적하므로 이 파일에는 Week 05에서 새로 생긴 책임만 둡니다.
"""


WEEK05_MCP_BOUNDARY_PROMPT = """
외부 멤버의 과거 대화와 공유 일정은 Week 05 MCP tool을 통해서만 조회한다.
직접 SQL을 작성하거나 외부 SQLite의 테이블 구조와 조회 결과를 추측하지 않는다.
개인 참고자료와 앱 내부 기록에는 이전 주차 tool을 사용하고,
외부 멤버 데이터에만 Week 05 MCP tool을 사용한다.
"""

WEEK05_HISTORY_WORKFLOW_PROMPT = """
외부 멤버의 과거 일정이나 busy-time을 직접 조회할 때는
search_previous_conversations를 먼저 호출하고,
extract_schedules_from_history를 두 번째로 호출한다.
load_conversation_messages는 사용자가 원문을 요구하거나
추출된 일정의 근거를 확인해야 할 때만 선택적으로 호출한다.
load_conversation_messages를 search_previous_conversations보다 먼저 호출하지 않는다.
"""

WEEK05_TRACEABILITY_PROMPT = """
외부 일정의 source_conversation_id를 원본 대화 식별자로 보존한다.
원문 확인이 필요하면 그 ID로 load_conversation_messages를 호출하고,
반환된 sender, content, created_at을 근거로 사용한다.
근거가 없으면 일정이나 원문을 지어내지 않는다.
"""

WEEK05_SCHEDULE_COLLECTION_PROMPT = """
내 일정과 외부 멤버의 busy-time을 한 번에 확인하는 요청에는
collect_member_schedules를 사용한다.
이 경우 collect_member_schedules가 외부 일정 추출까지 수행하므로 같은 수집 작업을
extract_schedules_from_history로 중복 실행하지 않는다.
tool이 반환한 rows와 schedule_summary를 근거로 답하고,
Week 05에서는 여러 사람의 최종 공통 가능 시간을 임의로 확정하지 않는다.
"""

WEEK05_SCOPE_PROMPT = """
현재 실행 주차는 Week 05다.
이전 주차의 개인 일정, SQLite 저장, RAG 정책은 계속 적용하며,
Week 05에서는 외부 멤버의 과거 대화와 공유 일정 조회가 새로 허용된다.
이 현재 범위가 이전 주차 prompt에 남아 있는 과거 범위 설명보다 우선한다.
여러 사람의 최종 회의 시간 선택은 Week 06 범위다.
"""
