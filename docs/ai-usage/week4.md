# Week 4 — Nana의 기억 검색하기 (RAG)

대상 파일: `student_parts/week04_retrieve_nanas_memory.py`

## 목표

Nana가 "내가 적어 둔 참고자료", "SQLite에 저장된 일정/할 일 기록", "앱에 저장된 일반 채팅 발화"를
구분해서 검색하게 한다. RAG를 하나의 마법 함수로 보지 않고, 데이터 출처별 검색 tool을 분리하는 것이 핵심이다.

- 메인과제: 개인 참고자료를 추가하고, 참고자료와 SQLite 저장 기록을 출처별로 검색하는 RAG 세로 슬라이스를 완성한다.
- 추가 과제: 앱 대화 발화를 ChromaDB에 lazy sync해 검색하는 agentic RAG와 이전 버전 호환 통합 검색까지 확장한다.

## 이전 주차와의 연결

- `student_parts/week03_build_nanas_logbook.py`의 `week03_tools()` / `week03_prompt_parts()` 위에
  Week 4 RAG tool과 prompt 조각을 누적한다 (`week04_tools()`, `week04_prompt_parts()`).
- Week 3까지는 SQLite 구조화 기록(일정/할 일)의 저장·조회·수정·삭제만 다뤘고, Week 4는 여기에
  벡터 검색(개인 참고자료, 대화 RAG) 출처를 추가로 얹는다.

## TODO 목록 (추가 과제)

메인과제 3개 tool(`add_personal_reference`, `search_personal_references`, `search_saved_requests`)은
이미 구현되어 있다. 추가 과제(대화 RAG) 항목도 모두 구현이 끝났다.

- [x] (줄 266) `search_conversation_messages_dict` — SQLite 대화 기록을 `ConversationRAGStore.sync_from_sqlite(...)`로 lazy sync한 뒤 ChromaDB 검색 결과를 반환 — 상태: 완료
- [x] (줄 300) `search_conversation_message_rows` — `search_conversation_messages_dict(...)` 결과에서 hits만 꺼내는 내부 helper — 상태: 완료
- [x] (줄 346) `search_conversation_messages` tool — 위 helper를 호출해 `{"hits":..., "rows":..., "context":..., "rag_backend":..., "sync":...}` 형태 JSON을 반환 — 상태: 완료
- [x] (줄 365) `search_nana_memory` tool — 개인 참고자료 hit와 SQLite 일정 chunk를 한 번에 묶는 호환용 통합 검색 tool 본문 — 상태: 완료

## 이미 구현되어 있는 함수

- `_decode_attendees`, `json_payload`, `safe_limit` — 공통 helper.
- `AddPersonalReferenceInput` / `SearchPersonalReferencesInput` / `SearchSavedRequestsInput` / `SearchConversationMessagesInput` / `SearchNanaMemoryInput` — 입력 스키마.
- `add_personal_reference_dict`, `search_personal_reference_hits`, `search_saved_request_rows` — 메인과제 helper (완료).
- `add_personal_reference`, `search_personal_references`, `search_saved_requests` — 메인과제 tool 3종 (완료).
- `week04_tools()`, `week04_system_prompt()` / `week04_prompt_parts()`, `build_week04_agent()` / `build_week_agent()` — 공통 조립 함수.

## 검증 방법

- 메인과제: 참고자료를 추가한 뒤 관련 질문을 입력하고 trace에서 `search_personal_references` 호출을 확인한다.
  저장된 일정/할 일 질문은 `search_saved_requests`가 호출되는지, 결과 JSON top-level 키가 각각 `hits`, `rows`인지 확인한다.
- 추가 과제: 일반 채팅 발화 질문은 `search_conversation_messages`가 호출되고 현재 대화(`conversation_id` 미지정 시)가
  검색 결과에서 제외되는지 확인한다.
