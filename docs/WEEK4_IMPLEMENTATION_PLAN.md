# Week 4 구현 계획 — 출처를 구분하는 Nana의 기억 검색(RAG)

> 대상 파일: `student_parts/week04_retrieve_nanas_memory.py`
> 이 문서는 구현 전 계획서다. **Week 4 메인 과제와 UI trace 로컬 로그 기능**을 구현하며, 강의의 추가 과제와 이전 버전 호환 검색은 보류한다.
> `student_parts_baseline/week03_build_nanas_logbook.py`는 이전 주차 정답 참고용이며 수정하지 않는다.

---

## 0. 목표와 핵심 원칙

Week 3까지 Nana는 자연어 요청을 구조화해 SQLite에 저장할 수 있게 됐다. Week 4에서는 저장된 정보를 다시 찾되, 모든 데이터를 하나의 검색 함수로 섞지 않고 **출처별 tool을 분리**한다.

```text
사용자 질문
  ├─ 개인 참고자료를 저장                       → add_personal_reference
  ├─ 내 선호·메모·참고자료를 검색              → search_personal_references (ChromaDB)
  └─ 저장한 일정·할 일·알림을 검색             → search_saved_requests (SQLite)
```

핵심 원칙은 다음과 같다.

1. **출처를 구분한다.** 개인 참고자료와 구조화 요청은 서로 다른 저장소와 tool을 사용한다.
2. **helper와 tool의 역할을 분리한다.** helper는 저장소 호출과 결과 정규화를, `@tool` 함수는 입력 제한과 JSON 직렬화를 담당한다.
3. **메인 과제만 agent에 노출한다.** 미구현 추가 과제 tool은 목록과 prompt에서 제외해 실행 중 스텁이 선택되지 않게 한다.
4. **기존 Week 1~3 동작을 보존한다.** `week03_tools()`와 `week03_prompt_parts()` 위에 Week 4 메인 기능만 누적한다.
5. **강의 정답 파일은 수정하지 않는다.** Week 4 과제는 `student_parts/week04_retrieve_nanas_memory.py`에 구현하고, UI trace 로그를 연결하는 데 필요한 런타임 파일만 최소 범위로 수정한다.

---

## 1. 구현 범위

### 이번 구현: 메인 과제

- 개인 참고자료 저장 helper/tool
  - `add_personal_reference_dict`
  - `add_personal_reference`
- 개인 참고자료 검색 helper/tool
  - `search_personal_reference_hits`
  - `search_personal_references`
- SQLite 저장 요청 검색 helper/tool
  - `search_saved_request_rows`
  - `search_saved_requests`
- 출처에 맞는 tool을 선택하게 하는 `week04_prompt_parts`
- 메인 과제 tool만 노출하도록 `week04_tools` 구성

### 함께 구현: UI trace 로컬 로그

- UI에서 질문을 보내고 최종 trace가 만들어질 때 질문·답변·trace를 로컬 JSONL 파일에 저장
- 중간 진행 상태(`답변을 진행중입니다`, `현재 ... 실행 중`)는 저장하지 않고 요청당 최종 결과 한 건만 저장
- 정상 응답뿐 아니라 오류 trace도 저장
- 로그 저장 실패가 채팅 답변과 UI trace 출력을 막지 않도록 best-effort로 처리
- 로그 파일은 이미 Git에서 제외되는 `data/logs/agent_traces.jsonl` 사용

### 이번 구현에서 제외: 추가 과제

- 앱의 과거 일반 대화를 ChromaDB에 lazy sync하고 검색
  - `search_conversation_messages_dict`
  - `search_conversation_message_rows`
  - `search_conversation_messages`
- 이전 버전 호환 통합 검색
  - `search_nana_memory`

메인 과제는 추가 과제에 의존하지 않으므로 단독으로 완성할 수 있다. 다만 starter의 `week04_tools()`에는 추가 과제인 `search_conversation_messages`가 포함되어 있다. 이번에는 이 도구를 목록에서 제외하고 prompt에서도 과거 대화 검색을 안내하지 않는다. 따라서 추가 과제 함수에 스텁이 남아 있어도 agent의 메인 흐름에는 진입하지 않는다.

추후 추가 과제를 진행하게 되면 관련 helper/tool을 모두 구현하고 검증한 뒤 `search_conversation_messages`를 `week04_tools()`와 prompt에 함께 복원한다. `search_nana_memory`는 현재 tool 목록에 직접 노출되지 않으므로 보류 상태가 메인 과제에 영향을 주지 않는다.

커밋은 기능별로 중간 생성하지 않고, Week 4 메인 과제와 로컬 trace 로그 구현·검증이 모두 끝난 뒤 한 번 진행한다.

---

## 2. 확인한 연동 지점과 실제 API 계약

### `PersonalReferenceStore`

- `add_personal_reference(title, content, tags=None) -> dict`
  - 반환 필드: `reference_id`, `title`, `content`, `tags`, `backend`
  - ChromaDB metadata에는 tags가 쉼표로 합쳐진 문자열로 저장된다.
- `search_personal_references(query, limit=3) -> list[dict]`
  - 각 검색 결과: `id`, `title`, `content`, `tags`, `distance`
- `backend_info() -> dict`
  - vector store, embedding provider/model, collection, 저장 경로 정보를 제공한다.

### `AppSQLiteStore`

- `search_saved_requests(query, kind=None, limit=5) -> list[dict]`
  - `structured_requests`의 `raw_json`, `title`, `reason`을 LIKE 검색한다.
  - 두 번째 위치 인자는 `kind`이므로 **반드시 `limit=...` 키워드 인자**로 호출한다.
  - 결과가 없으면 빈 list를 반환한다.
- `list_schedules(limit=12, kind=None, date_from=None, date_to=None) -> list[dict]`
  - 호환 통합 검색에서 일정 후보를 만들 때 사용한다.
  - `attendees_json`은 `attendees: list`로 디코딩되어 반환된다.

### `ConversationRAGStore` — 추가 과제 참고용, 이번에는 사용하지 않음

- `sync_from_sqlite(sqlite_store) -> dict`
  - SQLite 대화별 chunk를 만들고 신규/변경/삭제분만 ChromaDB에 반영한다.
  - 반환 필드: `upserted`, `skipped`, `deleted`, `total`
- `search(query=..., top_k=..., exclude_conversation_id=..., conversation_id=...) -> list[dict]`
  - 대화 단위 hit를 반환한다.
  - 각 hit에는 `chunk_id`, `conversation_id`, `title`, `status`, `content`, `distance`, `metadata`가 포함된다.
- `context_from_hits(hits) -> str`
  - agent가 답변 근거로 쓰기 쉬운 문자열을 만든다.
- `backend_info() -> dict`
  - 대화 RAG의 ChromaDB/embedding 정보를 반환한다.

### 현재 대화 범위 — 추가 과제 참고용, 이번에는 사용하지 않음

- `current_session_scope()`는 agent가 실행 중인 현재 `conversation_id`를 반환한다.
- 직접 tool을 호출해 실제 대화가 없을 때는 `DEFAULT_SESSION_SCOPE`가 반환된다.
- 따라서 명시적 `conversation_id`가 없고 scope가 기본값이 아닐 때만 `exclude_conversation_id`로 사용한다.

### UI trace 생성 경로

- `app.py`의 `finish_agent_response()`가 `AgentRuntime.stream_agent()`를 순회한다.
- 진행 중에는 `status_text`만 UI에 표시한다.
- 최종 `event.result`가 도착하면 `RuntimeResult.answer`, `RuntimeResult.trace`, `RuntimeResult.conversation_id`가 UI로 전달된다.
- `AgentRuntime.run_agent()`도 같은 최종 `RuntimeResult` 구조를 사용한다.
- 따라서 로그 저장 지점은 UI 함수가 아니라 **`AgentRuntime`이 최종 결과를 조립한 직후**로 둔다. 이렇게 하면 스트리밍/비스트리밍 경로가 같은 형식으로 저장되고 UI 코드에 중복 로직이 생기지 않는다.

---

## 3. 반환 JSON 계약

이번에 구현하고 agent에 노출하는 메인 `@tool` 함수는 `json_payload()`를 사용해 한글이 보존되는 JSON 문자열을 반환한다.

| Tool | 최상위 필수 키 | 핵심 내용 |
|---|---|---|
| `add_personal_reference` | `reference_backend`, `reference` | 저장 backend와 새 참고자료 |
| `search_personal_references` | `hits` | `id/content/distance/metadata(title, tags)` 목록 |
| `search_saved_requests` | `rows` | SQLite structured request row 목록 |

빈 검색 결과는 오류로 바꾸지 않는다.

- 참고자료 없음: `{"hits": []}`
- 저장 요청 없음: `{"rows": []}`

---

## 4. 구현 순서

### Step 1 — 공통 입력 제한과 결과 형식 확정

- `safe_limit()`으로 tool 경계에서 `top_k`/`limit`를 보정한다.
  - 참고자료: 기본 2, 최대 20
  - 저장 요청: 기본 3, 최대 50
- `json_payload()`만 사용해 JSON 문자열을 만든다.
- Pydantic `args_schema`가 기본 검증을 수행하더라도 helper 직접 호출과 방어적 동작을 고려해 limit 전달 값을 명확히 한다.

### Step 2 — 개인 참고자료 저장 [메인]

#### `add_personal_reference_dict`

1. `tags is None`이면 빈 list로 정규화한다.
2. `reference_store.add_personal_reference(title=..., content=..., tags=...)`를 호출한다.
3. 다음 dict를 반환한다.
   - `reference_backend`: `reference_store.backend_info()`
   - `reference`: 저장소가 반환한 참고자료 dict

#### `add_personal_reference`

1. 전역 `REFERENCE_STORE`를 helper에 전달한다.
2. helper 결과를 `json_payload()`로 직렬화한다.
3. 동일한 입력으로 중복 호출하면 별도 reference가 생성된다는 저장소 특성을 그대로 둔다.

### Step 3 — 개인 참고자료 검색 [메인]

#### `search_personal_reference_hits`

1. `reference_store.search_personal_references(query, limit=top_k)`를 호출한다.
2. 저장소의 평평한 검색 결과를 아래 구조로 정리한다.

```text
{
  "id": ...,
  "content": ...,
  "distance": ...,
  "metadata": {
    "title": ...,
    "tags": ...
  }
}
```

3. 저장소가 돌려준 순서와 distance를 유지한다.
4. 누락된 metadata는 빈 값으로 처리해 agent가 key 존재를 안정적으로 가정할 수 있게 한다.

#### `search_personal_references`

1. `top_k`를 1~20으로 보정한다.
2. helper를 호출한다.
3. 최상위 계약을 정확히 `{"hits": [...]}`로 유지한다.

### Step 4 — SQLite 저장 요청 검색 [메인]

#### `search_saved_request_rows`

1. `sqlite_store.search_saved_requests(query, limit=top_k)`를 호출한다.
2. 결과가 없으면 변형 없이 `[]`를 반환한다.
3. `raw_json` 등 근거 필드를 임의로 제거하지 않는다.

#### `search_saved_requests`

1. `top_k`를 1~50으로 보정한다.
2. helper를 호출한다.
3. 최상위 계약을 `{"rows": [...]}`로 유지한다.

### Step 5 — Week 4 tool 목록과 system prompt [메인]

`week04_prompt_parts()`는 `*week03_prompt_parts()` 뒤에 Week 4 규칙을 추가한다.

- “기억해 줘/참고자료로 저장해 줘” → `add_personal_reference`
- 개인 선호·메모·참고자료 질문 → `search_personal_references`
- 저장된 일정·할 일·알림 질문 → `search_saved_requests`
- 질문이 참고자료와 저장 요청 양쪽에 걸치면 두 tool을 각각 호출하고 출처를 구분해 답변
- 검색 결과가 없으면 기억한다고 추측하지 말고 없음을 명시하기
- 날짜 해석은 기존 Week 1~3 prompt 규칙을 유지하기

`week04_tools()`는 이번에 구현하는 도구만 누적한다.

```python
return [
    *week03_tools(),
    add_personal_reference,
    search_personal_references,
    search_saved_requests,
]
```

`search_conversation_messages`는 구현 전까지 노출하지 않는다. `build_week04_agent()`의 model/tool/system prompt 조립과 agent 캐시는 기존 구조를 유지한다.

추가 과제 본문에서만 사용할 예정인 import가 메인 구현 후에도 미사용 상태라면 제거해 Ruff 검사를 통과시키고, 나중에 추가 과제를 구현할 때 다시 추가한다.

### Step 6 — UI 최종 trace를 로컬 JSONL로 저장 [프로젝트 추가 기능]

#### 로그 저장 모듈

`fixed/local_trace_log.py`를 새로 만들고 로컬 파일 append 책임을 분리한다.

- `LocalTraceLogStore`는 생성 시 로그 파일 경로를 받는다.
- 기본 경로는 `DATA_DIR / "logs" / "agent_traces.jsonl"`로 한다.
- 부모 디렉터리는 최초 기록 시 `mkdir(parents=True, exist_ok=True)`로 생성한다.
- 한 요청을 JSON 한 줄로 직렬화하고 UTF-8 append 모드로 기록한다.
- `json.dumps(..., ensure_ascii=False, default=str)`를 사용해 한글과 예상 밖 직렬화 타입을 안전하게 처리한다.
- 프로세스 내부의 동시 Gradio 요청이 같은 파일에 섞이지 않도록 `threading.Lock`으로 한 줄 append 구간을 보호한다.
- 로그 저장 예외는 경고로 남기고 호출자에게 전파하지 않는다.

#### `AgentRuntime` 연동

`fixed/agent_runtime.py`에 logger를 주입할 수 있게 해 테스트 가능성을 확보한다.

1. `AgentRuntime.__init__()`에서 기본 `LocalTraceLogStore`를 생성하되 테스트에서는 fake logger를 주입할 수 있게 한다.
2. 내부 `_log_final_result(user_message, result)` helper 하나에서 로그 record를 구성한다.
3. `run_agent()`는 assistant 메시지와 최종 `RuntimeResult`가 완성된 뒤 한 번 기록한다.
4. `stream_agent()`는 `event.result`가 도착한 최종 분기에서 한 번 기록한다.
5. stream이 결과 없이 종료되는 fallback 오류 결과도 한 번 기록한다.
6. `status_text`를 yield하는 중간 분기에서는 기록하지 않는다.
7. 로그 호출 후 기존 `yield`/`return` 순서를 유지해 UI trace payload와 화면 동작을 바꾸지 않는다.

#### JSONL record 계약

각 줄은 독립적으로 파싱 가능한 다음 구조를 사용한다.

```json
{
  "schema_version": 1,
  "logged_at": "2026-07-22T12:34:56+09:00",
  "active_week": 4,
  "conversation_id": "conv_...",
  "user_message": "내가 선호하는 회의 시간은 언제야?",
  "assistant_answer": "...",
  "trace": {
    "mode": "active_week_agent",
    "active_week": 4,
    "conversation_id": "conv_...",
    "events": []
  }
}
```

- `logged_at`은 로컬 타임존이 포함된 ISO 8601 시각으로 기록한다.
- `trace`는 UI에 전달한 최종 dict를 그대로 기록해 화면과 파일을 대조할 수 있게 한다.
- 전체 대화 history나 환경 변수는 추가하지 않는다.
- 질문·답변·tool 인자·tool 결과에는 개인정보가 포함될 수 있으므로 로그는 `data/` 밖으로 복사하거나 Git에 추가하지 않는다.

---

## 5. 보류한 추가 과제

이번 구현과 완료 판정에는 아래 항목을 포함하지 않는다.

- `search_conversation_messages_dict`: SQLite 대화를 ChromaDB에 lazy sync하고 현재 대화를 제외해 검색
- `search_conversation_message_rows`: 위 검색 결과에서 hits만 반환
- `search_conversation_messages`: `hits`, `rows`, `context`, `rag_backend`, `sync` JSON 반환
- `search_nana_memory`: 개인 참고자료와 SQLite 일정을 합친 이전 버전 호환 검색

이 함수들의 TODO/스텁은 의도적으로 남겨 둔다. 추후 구현하기로 결정하면 네 함수를 별도 계획과 검증 범위로 묶고, 완성 전에는 agent tool 목록에 추가하지 않는다.

---

## 6. 검증 계획

이 저장소에는 자동 테스트 하네스가 없으므로 **오프라인 helper 검증 → 실제 저장소 검증 → agent/UI 검증** 순서로 확인한다.

### 6.1 정적 검증

- 메인 과제 helper/tool과 prompt의 `TODO`/`...`가 제거됐는지 확인
- 남아 있는 TODO가 보류한 추가 과제 함수에만 있는지 확인
- `week04_tools()`에 미구현 `search_conversation_messages`가 없는지 확인
- `uv run ruff check student_parts/week04_retrieve_nanas_memory.py`
- `uv run ruff format --check student_parts/week04_retrieve_nanas_memory.py`
- `uv run python -m py_compile student_parts/week04_retrieve_nanas_memory.py`
- trace 로그 관련 파일도 Ruff, format check, `py_compile` 대상으로 함께 검사

### 6.2 네트워크 없는 helper 검증

가짜 store를 주입해 다음을 확인한다.

- `tags=None`이 빈 list로 전달되는지
- `search_personal_reference_hits`가 metadata 중첩 구조를 만드는지
- `search_saved_request_rows`가 `limit`을 kind로 잘못 전달하지 않는지
- 빈 결과가 각각 `hits=[]`, `rows=[]`로 유지되는지
- `safe_limit`이 음수·0·최댓값 초과·변환 불가 값에 안전한지
- JSON 결과에서 한글이 `\uXXXX`가 아닌 원문으로 유지되는지

### 6.3 실제 저장소/tool 검증

`PROXY_TOKEN`이 있는 환경에서 임시 또는 개발용 데이터로 확인한다.

1. 참고자료 추가 → 관련 검색 → `hits[0].metadata.title/tags`와 distance 확인
2. Week 3 tool로 일정/할 일 저장 → `search_saved_requests`로 검색 → top-level `rows` 확인

### 6.4 agent/UI 시나리오

PowerShell 기준으로 `KANANA_ACTIVE_WEEK=4`를 설정하고 `uv run python app.py`를 실행한다.

| 입력 예시 | 기대 tool/결과 |
|---|---|
| “나는 중요한 회의를 오전에 선호한다고 참고자료에 저장해 줘” | `add_personal_reference` |
| “내가 선호하는 회의 시간은 언제야?” | `search_personal_references`, 근거 기반 답변 |
| “지난번 저장한 코칭 일정 찾아줘” | `search_saved_requests` |
| 참고자료와 일정 양쪽에 걸친 질문 | 필요한 검색 tool을 각각 호출하고 출처별 답변 |

상세 trace에서 tool 이름과 결과 JSON의 최상위 키를 함께 확인한다.

### 6.5 로컬 trace 로그 검증

임시 경로와 fake logger를 사용한 검증:

- 한글 질문·답변·trace를 기록하고 JSONL 한 줄을 다시 `json.loads()`할 수 있는지
- 두 번 기록하면 기존 내용을 덮지 않고 두 줄로 append되는지
- stream의 여러 `status_text` 뒤에도 최종 record는 한 건만 남는지
- `run_agent()`와 `stream_agent()`가 같은 schema를 쓰는지
- agent 오류 및 `stream_completed_without_result`도 저장되는지
- 쓰기 권한 오류를 강제로 만들었을 때 UI 결과는 정상 반환되는지

실제 UI 검증:

1. 앱에서 Week 4 질문을 한 번 전송한다.
2. 화면에 최종 trace가 표시되는지 확인한다.
3. `data/logs/agent_traces.jsonl`의 마지막 줄을 읽는다.
4. 화면의 `conversation_id`, 질문, 답변, trace events가 로그와 같은지 비교한다.
5. 질문을 한 번 더 보내 로그가 한 줄만 추가되는지 확인한다.

---

## 7. 주의할 점

- `student_parts_baseline/`은 읽기 전용으로 유지한다. `fixed/`에서는 로컬 로그 모듈 추가와 `agent_runtime.py` 연결만 허용하고, 기존 저장소·trace 변환 로직은 수정하지 않는다.
- ChromaDB add/query는 실제 embedding 호출 시 `PROXY_TOKEN`이 필요하다. import 가능 여부와 실제 검색 가능 여부를 구분한다.
- SQLite 저장 요청 검색은 vector RAG가 아니라 LIKE 검색이다. 응답과 prompt에서 ChromaDB 검색처럼 설명하지 않는다.
- ChromaDB distance는 점수 방향을 임의로 뒤집거나 유사도라고 이름을 바꾸지 않고 원본 값을 유지한다.
- 추가 과제 함수가 미구현인 동안 `search_conversation_messages`를 `week04_tools()` 또는 prompt에 노출하지 않는다.
- `current_app_date_iso`, `DEFAULT_SESSION_SCOPE`, `current_session_scope`처럼 추가 과제 전용인 미사용 import는 이번 구현에서 정리할 수 있다.
- 조회 결과가 없다는 것은 정상 결과이며 예외나 임의의 기억 생성으로 바꾸지 않는다.
- JSONL에는 질문·답변과 tool 결과가 평문으로 남는다. 대화 삭제와 로그 삭제는 별개이며, 로그가 불필요해지면 `data/logs/agent_traces.jsonl`을 직접 삭제한다.
- 로그 기록 실패는 warning 대상이지만 agent 응답 실패로 취급하지 않는다.
- 모든 구현과 검증이 끝난 뒤 `git diff --check`와 최종 diff를 확인하고 한 번만 커밋한다.
