# Week 5 튜터링 가이드

대상 파일: `student_parts/week05_load_kanas_past_conversations.py`

이 문서는 수강생이 TODO를 **직접** 작성하고, Claude는 정답 코드를 대신 써주지 않고 힌트/설계 방향만 제시하는 튜터링 세션을 위한 참고 문서다. 튜터링할 때마다 이 파일을 먼저 읽고 현재 진행 상태와 힌트 포인트를 확인한다.

## 배경

Week 1(`student_parts/week01_wake_up_nana.py`), Week 2(`student_parts/week02_structure_natural_language_requests.py`), Week 3(`student_parts/week03_build_nanas_logbook.py`), Week 4(`student_parts/week04_retrieve_nanas_memory.py`)는 이미 구현되어 있고 Week 5에서 그대로 재사용한다.

- Week 1: 개인 일정 CRUD tool, `join_system_prompt`, `PERSONAL_SCHEDULES`(현재 대화 범위 임시 일정)
- Week 2: 자연어를 구조화하는 `StructuredRequest` 스키마
- Week 3: 구조화된 일정/할 일/리마인더를 SQLite에 영속 저장하는 `AppSQLiteStore`
- Week 4: 참고자료/SQLite 기록/앱 대화 발화를 출처별로 검색하는 RAG tool 모음, `week04_tools()`, `week04_prompt_parts()`

Week 5는 나나가 **외부 SQLite/MCP 서버**에 있는 Kana의 이전 대화와 공유 일정을 다루게 만드는 단계다. 학생이 직접 SQL을 작성하는 주차가 아니라, MCP tool(`mcp_server/sqlite_mcp_server.py`, 학생 구현 대상 아님)을 호출하고 그 결과를 agent용 JSON으로 전달하는 wrapper tool을 만드는 주차다.

> 파일 상단 35~177행의 `[5주차 수강생 구현 가이드]` 주석 블록에 목표·메인/추가 과제 구분·핵심 흐름·역할 태그(`[메인]`/`[추가]`/`[공통]`)·반환값 규칙이 이미 상세히 적혀 있다. 이 문서는 그 내용을 반복하지 않고, TODO를 순서대로 짚어가는 체크리스트 역할만 한다. 막히면 먼저 그 주석 블록을 다시 읽는다.

## TODO 목록 (진행 순서)

메인과제 (외부 이전 대화 검색·로드, 일정 추출, 공유 일정 조회, 멤버 일정 통합 — Week 6 하위 agent가 그대로 재사용하는 연결 지점):

1. **`_personal_schedules_for_current_scope`** (189~193행, 현재 `...`) — `AppSQLiteStore(CONFIG.app_db_path).list_schedules(...)`로 SQLite 저장 일정을 읽고, `PERSONAL_SCHEDULES`(Week 1 임시 일정)에서 현재 대화 범위(`_schedule_scope`)에 속하면서 SQLite에 아직 없는 것만 합침
2. **`search_previous_conversations`** (tool, 297행, 현재 `...`) — `call_mcp_tool_sync("search_previous_conversations", args)` 호출 결과 문자열을 그대로 반환. 멤버 이름 정규화는 MCP 경계에서 이미 처리되므로 wrapper에서 중복 변환하지 않음
3. **`load_conversation_messages`** (tool, 305행, 현재 `...`) — `call_external_tool_payload("load_conversation_messages", {"conversation_id": conversation_id})` 결과를 `json_payload()`로 감싸서 반환. sender/content/created_at 순서 보존
4. **`extract_schedules_from_history`** (tool, 313행, 현재 `...`) — `call_mcp_tool_sync("extract_schedules_from_history", args)` 호출. 결과 rows는 member_name/title/date/start_time/end_time/notes 필드 유지
5. **`list_shared_schedules`** (tool, 355행, 현재 `...`) — `call_mcp_tool_sync("list_shared_schedules", args)` 호출해 공유 일정 저장소 row 조회
6. **`_collect_member_schedules`** (285~286행, 현재 `...`) — 인자로 받은 `personal_schedules`(내 일정)와 `extract_schedules_from_history` 호출 결과(외부 멤버 busy-time)를 같은 member_name/title/date/start_time/end_time/notes row 구조로 합치고, `fixed/external_people_store.py`의 `normalize_external_member_names()`/`normalize_external_schedule_date_bounds()`/`external_schedule_summary()`로 정규화·요약
7. **`collect_member_schedules`** (tool, 363행, 현재 `...`) — 위 helper들을 조합해 `_personal_schedules_for_current_scope()` + `_collect_member_schedules(...)` 결과(rows + schedule_summary)를 `json_payload()`로 반환
8. **`week05_prompt_parts()` 인라인 TODO** (393행) — Week 5 Kana history agent 시스템 프롬프트 지시문 추가 (언제 외부 대화 검색/일정 추출/공유 일정 조회 tool을 쓸지 안내)

추가과제 (공유 일정 저장소에 row 직접 등록·삭제 — 구현하지 않으려면 `week05_tools()`(367~379행) 목록에서 해당 tool 제거):

9. **`create_shared_schedule`** (tool, 330행, 현재 `...`) — `call_mcp_tool_sync("create_shared_schedule", args)` 호출, `schedule_id`/`source_conversation_id` 보존
10. **`delete_shared_schedule`** (tool, 341행, 현재 `...`) — `call_mcp_tool_sync("delete_shared_schedule", args)` 호출

> `week05_tools()`(367~379행)와 `build_week05_agent()`/`build_week_agent()`(397~415행)는 이미 구현되어 있다 — Week 4까지와 마찬가지로 이번 주차도 agent builder를 새로 작성할 필요가 없다.

## 원문·트러블슈팅 기록

- 코드 작성 중 막힌 문제와 해결 과정은 `docs/troubleshooting/week5.md`에 기록한다.

## 튜터링 진행 방식

- 위 순서대로 한 항목씩 진행. 사용자가 먼저 시도하고, 막히면 개념/방향 힌트(예: `call_mcp_tool_sync`/`call_external_tool_payload` 중 어느 걸 쓸지, `fixed/external_people_store.py` 정규화 helper 사용 위치, top-level JSON 키 규칙, Week 1~4 패턴과의 일관성 등)를 질문 형태나 참고 위치 pointer로 제공한다.
- 사용자가 "모르겠다"고 명시하면 힌트를 한 단계 강화해 의사코드 수준(호출 순서, 분기 조건, 합칠 필드명 등)까지 알려준다. 이 단계에서도 실행 가능한 완성 코드는 주지 않는다.
- "이 부분은 대신 써줘"라고 명시적으로 요청할 때만 Edit으로 완성 코드를 작성한다. 그 외에는 사용자가 작성한 코드를 Read로 확인하고 반환 JSON 형태, MCP tool 이름/인자, 예외 처리만 짚어준다.
- 각 항목 완료 후 다음 항목으로 넘어가되, 사용자가 순서를 바꾸길 원하면 따른다.
- 메인과제(1~8번) 전부 완료 후 추가과제(9~10번)로 넘어간다.

## 검증 방법

- 메인과제: `./run.sh --week5`에서 외부 팀원 일정 조회 요청을 입력하고, trace에서 `search_previous_conversations`, `load_conversation_messages`, `extract_schedules_from_history` 중 어떤 tool이 어떤 순서로 호출됐는지 확인한다. `collect_member_schedules` 결과 rows에 "나"와 외부 멤버 일정이 같은 구조로 들어 있고, `list_shared_schedules` 결과에 rows와 schedule_summary가 유지되는지 확인한다.
- 추가과제: `create_shared_schedule`로 등록한 row가 `list_shared_schedules` 조회에 나타나고 `delete_shared_schedule`로 삭제되는지 확인한다.
- 파일 상단 가이드 주석(113~120행)의 "검증 방법" 절을 참고한다.
