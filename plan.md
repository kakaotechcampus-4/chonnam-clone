# Week 4 — Nana's Memory RAG 도구

## Context

`student_parts/week04_retrieve_nanas_memory.py`는 RAG를 데이터 출처별로 분리하는 것을 가르칩니다: 개인 참고자료(ChromaDB), 구조화된 저장 요청(SQLite), 앱 대화 기록(SQLite → lazy sync된 ChromaDB). 현재 파일에는 스캐폴딩(import, `CONFIG` 기반 store 싱글턴, Pydantic 입력 스키마, `json_payload`/`safe_limit` helper, 그리고 `week04_tools()`/`week04_system_prompt()`/`build_week04_agent()`)이 이미 구성되어 있지만, 실제 데이터 접근 로직은 helper 함수 6개 + `@tool` 데코레이터 함수 5개에서 `...` 상태의 stub으로 남아 있고, `week04_prompt_parts()`에도 빈 확장 지점이 있습니다.

목표: agent가 (1) 개인 참고자료를 저장/검색하고, (2) SQLite에 저장된 요청을 검색하고, 추가 과제로 (3) ChromaDB로 lazy sync한 앱 대화 메시지를 검색할 수 있도록 위 stub들만 정확히 채우는 것입니다 — 각 tool은 course에서 기대하는 정확한 JSON 계약(top-level `hits` vs `rows` 키)을 반환해야 합니다.


## 호출해야 할 핵심 store 시그니처 (소스에서 직접 확인함)

- `PersonalReferenceStore.add_personal_reference(title, content, tags=None) -> dict` — 키: `reference_id, title, content, tags, backend`.
- `PersonalReferenceStore.search_personal_references(query, limit=3) -> list[dict]` — 파라미터명은 `top_k`가 아니라 `limit`. 각 hit은 `id, title, content, tags(콤마로 join된 문자열), distance`를 가짐.
- `PersonalReferenceStore.backend_info() -> dict`.
- `AppSQLiteStore.search_saved_requests(query, kind=None, limit=5) -> list[dict]` — `structured_requests` 테이블의 row(`SELECT *`).
- `AppSQLiteStore.list_schedules(limit=12, kind=None, date_from=None, date_to=None, ...)`.
- `ConversationRAGStore.sync_from_sqlite(sqlite_store) -> dict` — `{upserted, skipped, deleted, total}`.
- `ConversationRAGStore.search(*, query, top_k=5, exclude_conversation_id=None, conversation_id=None) -> list[dict]` — hit은 `chunk_id, conversation_id, title, status, content, distance, metadata{...}`를 가짐.
- `ConversationRAGStore.context_from_hits(hits) -> str`, `ConversationRAGStore.backend_info() -> dict`.
- `current_session_scope()` / `DEFAULT_SESSION_SCOPE` (`fixed/session_scope.py`, 이미 import되어 있음) — 기본적으로 제외할 "현재 대화"를 판단하는 데 사용.


## 구현 계획

모든 수정은 `student_parts/week04_retrieve_nanas_memory.py` 안에서, 기존 stub의 본문만 채우는 방식으로 진행합니다 (시그니처 변경 없음).

## 구현 대상

### 메인 과제

1. **`add_personal_reference_dict`** — `reference_store.add_personal_reference(title=title, content=content, tags=tags or [])` 호출, `{"reference_backend": reference_store.backend_info(), "reference": <결과>}` 반환.

2. **`search_personal_reference_hits`** — 빈 query면 `[]` 반환하도록 strip 후 가드, `safe_limit(top_k, default=2, maximum=20)`로 clamp, `reference_store.search_personal_references(query, limit=limit)` 호출, 각 raw hit을 `{"id", "content", "distance", "metadata": {"title", "tags"}}`로 매핑.

3. **`search_saved_request_rows`** — 빈 query면 `[]` 반환하도록 strip 후 가드, `safe_limit(top_k, default=3, maximum=50)`로 clamp, `sqlite_store.search_saved_requests(query, limit=limit)` 결과를 그대로 반환 (결과 없으면 빈 리스트가 자연스럽게 전달됨).

4. **`add_personal_reference` tool** — `add_personal_reference_dict(REFERENCE_STORE, ...)` 호출, `json_payload({"ok": True, "tool_name": "add_personal_reference", **result})`로 감싸서 반환.

5. **`search_personal_references` tool** — `top_k` clamp, `search_personal_reference_hits` 호출, `json_payload({"ok": True, "tool_name": ..., "query", "top_k", "reference_backend": REFERENCE_STORE.backend_info(), "hits": hits})` 반환.

6. **`search_saved_requests` tool** — `top_k` clamp, `search_saved_request_rows` 호출, `json_payload({"ok": True, "tool_name": ..., "query", "top_k", "rows": rows})` 반환.

### 추가 과제

7. **`search_conversation_messages_dict`** — `top_k` clamp; `conversation_id` 정규화(빈 문자열 → `None`); 호출자가 명시적으로 넘기지 않았다면 `current_session_scope()`로 `excluded_conversation_id`를 계산(단, `DEFAULT_SESSION_SCOPE`가 아닐 때만)해서 "방금 한 말"이 검색 결과에 섞이지 않게 함; `conversation_rag_store.sync_from_sqlite(sqlite_store)` 호출 후 `.search(query=..., top_k=limit, exclude_conversation_id=..., conversation_id=...)` 호출; `hits`, `rows`(동일 리스트), `context`(`context_from_hits`로 생성), `rag_backend`(`backend_info()`로 생성), `sync`, `conversation_id`, `excluded_conversation_id`를 담은 dict 반환.

8. **`search_conversation_message_rows`** — 얇은 wrapper: `search_conversation_messages_dict(...)` 호출 후 `result["hits"]` 반환.

9. **`search_conversation_messages` tool** — `top_k` clamp, `search_conversation_messages_dict(SQLITE_STORE, CONVERSATION_RAG_STORE, ...)` 호출, 결과 dict를 `ok`, `tool_name`, `query`, `top_k`와 함께 JSON payload에 펼쳐 넣음.

**이번 범위에서 제외:** `search_nana_memory`는 현재 `...` stub 상태 그대로 둡니다 — 가이드상 "참고 코드"(compatibility helper)이며 핵심 구현 대상 4개(`add_personal_reference`, `search_personal_references`, `search_saved_requests`, `search_conversation_messages`)에 포함되지 않고, 사용자도 이번 작업에서는 구현하지 않기로 확인했습니다.

10. **`week04_prompt_parts()`** — LLM이 `search_personal_references` / `search_saved_requests` / `search_conversation_messages` 중 상황에 맞는 tool을 고르도록, course의 출처 분리 의도(참고자료 vs 구조화된 DB 기록 vs 원본 채팅 기록)에 맞는 Week 4 전용 prompt 안내를 추가합니다.

## 검증 방법

- 이 모듈에 해당하는 기존 테스트 스위트/테스트 파일이 있다면 프로젝트의 일반적인 테스트 명령으로 실행합니다.
- `build_week04_agent()`로 직접 확인: 개인 참고자료를 추가한 뒤 관련 질문을 던져서 `search_personal_references`가 호출되고, JSON 출력에 top-level `hits` 키가 있는지 확인합니다.
- 이전에 저장한 일정/할 일에 대해 질문해서 `search_saved_requests`가 호출되고 top-level `rows` 키가 있는지 확인합니다.
- (추가 과제) 일반 채팅 기록에 대해 질문해서 `search_conversation_messages`가 호출되고, JSON에 `hits`와 `rows`가 모두 있으며, 기본적으로 현재 대화 자신의 메시지는 제외되는지 확인합니다.
- `week03_build_nanas_logbook.py`, `fixed/*.py`, `search_nana_memory`, 기타 무관한 파일은 건드리지 않았는지 확인합니다 — 이번 작업은 `week04_retrieve_nanas_memory.py`의 핵심 stub 4개(+ 내부 helper)로 범위가 한정됩니다.
