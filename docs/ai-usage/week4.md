# Week 4 튜터링 가이드

대상 파일: `student_parts/week04_retrieve_nanas_memory.py`

이 문서는 수강생이 TODO를 **직접** 작성하고, Claude는 정답 코드를 대신 써주지 않고 힌트/설계 방향만 제시하는 튜터링 세션을 위한 참고 문서다. 튜터링할 때마다 이 파일을 먼저 읽고 현재 진행 상태와 힌트 포인트를 확인한다.

## 배경

Week 1(`student_parts/week01_wake_up_nana.py`), Week 2(`student_parts/week02_structure_natural_language_requests.py`), Week 3(`student_parts/week03_build_nanas_logbook.py`)는 이미 구현되어 있고 Week 4에서 그대로 재사용한다.

- Week 1: 개인 일정 CRUD tool(`personal_create_schedule`, `personal_list_schedules`, `personal_delete_schedule`), `join_system_prompt`, `week01_tools`
- Week 2: 자연어를 구조화하는 `StructuredRequest` / `StructuredRequestBatch` 스키마, bridge 함수 `extract_structured_request` / `extract_schedule_request`, `week02_prompt_parts`
- Week 3: 구조화된 일정/할 일/리마인더를 SQLite에 영속 저장·조회·수정·삭제하는 tool 모음("나나의 로그북"), `AppSQLiteStore`

Week 4는 나나가 **참고자료(개인 메모)**, **SQLite에 저장된 일정/할 일 기록**, **앱에 저장된 일반 채팅 발화**를 출처별로 구분해서 검색하게 만드는 단계다. Week 4의 핵심은 RAG를 하나의 마법 함수로 보지 않고, 데이터 출처별 검색 tool을 분리하는 것이다.

> 파일 상단 27~152행의 `[4주차 수강생 구현 가이드]` 주석 블록에 목표·메인/추가 과제 구분·핵심 흐름·역할 태그(`[메인]`/`[추가]`/`[공통]`)·반환값 규칙이 이미 상세히 적혀 있다. 이 문서는 그 내용을 반복하지 않고, TODO를 순서대로 짚어가는 체크리스트 역할만 한다. 막히면 먼저 그 주석 블록을 다시 읽는다.

## TODO 목록 (진행 순서)

메인과제 (개인 참고자료 + SQLite 기록 검색):

1. **`add_personal_reference_dict`** (228~229행, 현재 `...`) — `PersonalReferenceStore.add_personal_reference(...)`로 title/content/tags 저장, tags가 `None`이면 빈 list로 변환
2. **`search_personal_reference_hits`** (240~241행, 현재 `...`) — ChromaDB 검색 결과를 id/content/distance/metadata(title/tags) 구조로 정리
3. **`search_saved_request_rows`** (252~253행, 현재 `...`) — `AppSQLiteStore.search_saved_requests(query, limit)` 호출, 결과 없으면 빈 list 그대로 반환
4. **`add_personal_reference`(tool)** (287~288행, 현재 `...`) — 위 helper로 저장 후 `reference_backend`+`reference`가 담긴 JSON을 `json_payload()`로 반환
5. **`search_personal_references`(tool)** (295~296행, 현재 `...`) — top_k를 `safe_limit()`으로 보정하고 top-level `{"hits": [...]}` JSON 반환
6. **`search_saved_requests`(tool)** (303~304행, 현재 `...`) — top_k를 `safe_limit()`으로 보정하고 top-level `{"rows": [...]}` JSON 반환

추가과제 (앱 대화 발화 agentic RAG + 호환 통합 검색):

7. **`search_conversation_messages_dict`** (266~267행, 현재 `...`) — `ConversationRAGStore.sync_from_sqlite(...)`로 SQLite 대화 기록을 ChromaDB에 lazy sync한 뒤 검색, `conversation_id`가 없으면 현재 대화 범위는 제외
8. **`search_conversation_message_rows`** (279~280행, 현재 `...`) — 위 dict 결과에서 `hits`만 꺼내는 내부 helper
9. **`search_conversation_messages`(tool)** (315~316행, 현재 `...`) — 위 helper 호출 결과를 hits+rows+context/rag_backend/sync가 담긴 JSON으로 반환
10. **`search_nana_memory`(tool)** (329~330행, 현재 `...`) — 개인 참고자료 hit와 SQLite 일정 chunk를 함께 묶는 호환용 통합 검색 (핵심 4개 완료 후 선택적으로 진행)
11. **`week04_prompt_parts()` 인라인 TODO** (355행) — 질문 성격(참고자료/저장 기록/일반 대화 중 어느 쪽인지)에 따라 어떤 tool을 고를지 안내하는 system prompt 지시문 추가

> `week04_tools()`(332~341행)와 `build_week04_agent()`(359~371행)는 이미 구현되어 있다 — Week 3까지와 달리 이번 주차엔 agent builder를 새로 작성할 필요가 없다.

## 원문·트러블슈팅 기록

- 코드 작성 중 막힌 문제와 해결 과정은 `docs/troubleshooting/week4.md`에 기록한다.

## 튜터링 진행 방식

- 위 순서대로 한 항목씩 진행. 사용자가 먼저 시도하고, 막히면 개념/방향 힌트(예: `PersonalReferenceStore`/`AppSQLiteStore`/`ConversationRAGStore` 중 어떤 메서드를 쓸지, top-level JSON 키 규칙, Week 1~3 패턴과의 일관성 등)를 질문 형태나 참고 위치 pointer로 제공.
- 완성 코드를 대신 작성하지 않는다. 사용자가 작성한 코드를 Read로 확인하고 반환 JSON 형태, 출처 구분, 예외 처리만 짚어준다.
- 각 항목 완료 후 다음 항목으로 넘어가되, 사용자가 순서를 바꾸길 원하면 따른다.
- 코드 수정은 사용자가 직접 하거나, 명시적으로 "이 부분은 대신 써줘"라고 요청할 때만 Edit 사용.

## 검증 방법

- `./run.sh --week4`로 실행하고, 참고자료를 추가한 뒤 관련 질문을 입력해 trace에서 `search_personal_references` 호출과 top-level `hits` 키를 확인한다.
- 저장된 일정/할 일 관련 질문에는 `search_saved_requests`가 호출되고 top-level `rows` 키가 나오는지 확인한다.
- (추가과제) 일반 채팅 발화에 관한 질문에는 `search_conversation_messages`가 호출되고, 현재 대화(`conversation_id` 미지정 시)는 검색 결과에서 제외되는지 확인한다.
- 파일 상단 가이드 주석의 "검증 방법" 절을 참고한다.
