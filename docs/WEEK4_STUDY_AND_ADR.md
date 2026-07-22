# Week 4 스터디 & ADR — 출처를 구분하는 기억 검색과 로컬 Trace 기록

- 대상 과제 파일: `student_parts/week04_retrieve_nanas_memory.py`
- 추가 구현 파일: `fixed/local_trace_log.py`, `fixed/agent_runtime.py`
- 브랜치: `junyoung/week4` (base = 최신 `junyoung/final` + `main` 강의자료)
- 범위: **Week 4 메인 과제 완료**, 강의 추가 과제는 보류, UI trace 로컬 로그 기능 추가
- 구현 커밋: `c009d2f`

이 문서는 구현 코드의 동작을 설명하고, 구현 과정에서 선택한 설계의 배경·결정·결과를 ADR로 기록한다.

---

## 1. 이번 주 한 일

Week 3에서는 자연어 요청을 구조화해 SQLite에 저장했다. Week 4 메인 과제에서는 저장된 정보를 질문의 성격에 맞는 출처에서 다시 찾도록 확장했다.

구현한 기능은 다음 세 가지다.

1. `add_personal_reference`: 개인 선호·메모·참고자료를 ChromaDB에 저장한다.
2. `search_personal_references`: 자연어 의미가 가까운 개인 참고자료를 vector search로 찾는다.
3. `search_saved_requests`: Week 3에서 SQLite에 저장한 일정·할 일·알림을 문자열 조건으로 찾는다.

추가로 UI에 표시되는 최종 agent trace를 `data/logs/agent_traces.jsonl`에 기록하는 기능을 구현했다. 질문, 최종 답변, tool call/result가 포함된 trace를 한 요청당 한 줄로 저장한다.

전체 흐름은 다음과 같다.

```text
사용자 질문
  │
  ├─ 개인 선호·메모를 새로 기억해야 함
  │    └─ add_personal_reference
  │         └─ OpenAI embedding 생성 → ChromaDB 저장
  │
  ├─ 개인 선호·메모를 찾아야 함
  │    └─ search_personal_references
  │         └─ query embedding → ChromaDB vector search → hits
  │
  └─ 저장된 일정·할 일·알림을 찾아야 함
       └─ search_saved_requests
            └─ SQLite LIKE 검색 → rows

agent 실행 완료
  └─ RuntimeResult(answer, trace, conversation_id)
       ├─ UI에 최종 답변과 trace 표시
       └─ data/logs/agent_traces.jsonl에 최종 실행 한 건 append
```

---

## 2. 먼저 이해할 개념

### 2.1 RAG는 검색 결과를 답변 근거로 제공하는 구조다

RAG(Retrieval-Augmented Generation)는 LLM이 답을 만들기 전에 외부 저장소에서 관련 정보를 검색하고, 그 검색 결과를 답변 근거로 사용하게 하는 방식이다.

Week 4의 흐름을 단계로 나누면 다음과 같다.

```text
질문 입력
  → 질문에 맞는 검색 tool 선택
  → 저장소에서 관련 데이터 조회
  → tool이 JSON 결과 반환
  → LLM이 검색 결과를 읽고 최종 답변 작성
```

중요한 점은 LLM이 ChromaDB나 SQLite를 직접 읽지 않는다는 것이다. LLM은 어떤 tool을 호출할지 결정하고, Python tool이 저장소를 조회한 뒤 반환한 JSON만 읽는다.

### 2.2 이번 메인 과제에는 서로 다른 두 검색 방식이 있다

| 구분 | 개인 참고자료 | 저장된 일정·할 일·알림 |
|---|---|---|
| Tool | `search_personal_references` | `search_saved_requests` |
| 저장소 | ChromaDB | SQLite |
| 검색 방식 | embedding 기반 vector search | `LIKE` 기반 문자열 검색 |
| 반환 최상위 키 | `hits` | `rows` |
| 적합한 질문 | 표현이 달라도 의미가 비슷한 메모 검색 | 저장 당시 제목·이유·원문에 포함된 핵심어 검색 |

두 검색을 모두 “기억 검색”이라고 부를 수 있지만 내부 동작은 다르다.

- ChromaDB 검색은 질문과 참고자료를 vector로 바꾼 뒤 거리로 관련성을 계산한다.
- SQLite 검색은 `raw_json`, `title`, `reason`에 query 문자열이 포함됐는지 확인한다.

따라서 `search_saved_requests`를 vector RAG라고 설명하면 실제 구현과 맞지 않는다. 이 도구는 구조화 데이터 저장소를 직접 검색하는 retrieval tool이다.

### 2.3 embedding과 distance

embedding은 텍스트의 특징을 숫자 배열(vector)로 표현한 값이다. 개인 참고자료를 추가할 때 문서 embedding을 저장하고, 검색할 때 질문 embedding과 저장된 vector 사이의 거리를 계산한다.

`PersonalReferenceStore.search_personal_references()`가 반환하는 `distance`는 ChromaDB 검색 결과의 원본 값이다. 이 값은 임의로 유사도 점수로 변환하지 않고 그대로 tool 결과에 포함했다. collection의 거리 metric에 따라 해석 방식이 달라질 수 있으므로, 현재 코드는 결과 순서를 유지하고 distance는 비교·디버깅 정보로 제공한다.

### 2.4 JSONL과 trace

JSONL(JSON Lines)은 한 줄에 JSON 객체 하나를 기록하는 파일 형식이다.

```text
{"실행": "첫 번째 기록"}
{"실행": "두 번째 기록"}
{"실행": "세 번째 기록"}
```

전체 파일을 하나의 JSON 배열로 다시 작성하지 않고 새 실행 결과를 끝에 추가할 수 있다. 각 줄을 독립적으로 `json.loads()`할 수 있어 로그에 적합하다.

이번 로그에서 trace는 agent가 어떤 tool을 어떤 인자로 호출했고, tool이 무엇을 반환했는지 보여주는 구조화 데이터다. UI에 표시된 최종 trace dict를 파일에도 그대로 기록해 화면과 로컬 기록을 직접 비교할 수 있게 했다.

---

## 3. 구현 해설

각 항목은 **코드 → 동작 → 구현 의도 → 구현 근거** 순서로 정리한다.

### 3.1 `safe_limit` — 검색 결과 개수의 경계 보정

**코드**

```python
def safe_limit(limit: int, default: int = 5, maximum: int = 50) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))
```

**동작**

1. 입력을 `int`로 변환한다.
2. 변환할 수 없으면 기본값을 사용한다.
3. 최소 1, 최대 `maximum` 범위로 제한한다.

예를 들어 참고자료 검색의 최대값이 20이면 `safe_limit(100, default=2, maximum=20)`은 20을 반환한다. 0이나 음수는 1로 보정된다.

**구현 의도**

`top_k`가 지나치게 크면 불필요한 검색 결과가 tool 응답에 포함되고 LLM context도 커진다. 최소·최대 범위를 한 helper에서 처리해 도구마다 같은 제한 방식을 사용하게 했다.

Pydantic `args_schema`도 `ge`/`le`로 범위를 검증한다. `safe_limit`은 정상적인 LangChain tool 호출에서는 두 번째 방어선이고, helper나 함수가 직접 재사용되는 경로까지 고려한 방어 코드다.

**구현 근거**

- 과제 요구: tool 내부에서 `safe_limit()`으로 `top_k`를 안전한 범위로 정리한다.
- 현재 범위: 참고자료는 1~20, 저장 요청은 1~50으로 제한한다.

---

### 3.2 `add_personal_reference_dict` — 저장소 호출과 응답 구성

**코드**

```python
def add_personal_reference_dict(reference_store, *, title, content, tags=None):
    normalized_tags = tags or []
    reference = reference_store.add_personal_reference(
        title=title,
        content=content,
        tags=normalized_tags,
    )
    return {
        "reference_backend": reference_store.backend_info(),
        "reference": reference,
    }
```

**동작**

- `tags=None`을 빈 list로 바꾼다.
- `PersonalReferenceStore.add_personal_reference()`에 저장을 위임한다.
- 저장된 참고자료와 backend 정보를 함께 반환한다.

실제 store는 새 `reference_id`를 만들고, content의 embedding을 생성해 ChromaDB collection에 저장한다. metadata에는 title과 tags가 들어간다.

**구현 의도**

helper가 전역 `REFERENCE_STORE`에 직접 의존하지 않고 `reference_store`를 인자로 받게 했다. 실제 앱에서는 ChromaDB store를 전달하고, 단위 테스트에서는 외부 API를 호출하지 않는 fake store를 전달할 수 있다.

`reference_backend`에는 vector store 종류, embedding model, collection 이름 등이 들어간다. 저장 결과가 어느 backend에서 만들어졌는지 trace에서 확인할 수 있다.

**구현 근거**

- 과제 요구: title/content/tags를 store에 전달하고 `tags=None`은 빈 list로 바꾼다.
- 과제 반환 계약: `reference_backend`와 `reference`를 포함한다.

---

### 3.3 `add_personal_reference` — LangChain tool 경계

**코드**

```python
@tool(args_schema=AddPersonalReferenceInput)
def add_personal_reference(title, content, tags=None) -> str:
    return json_payload(
        add_personal_reference_dict(
            REFERENCE_STORE,
            title=title,
            content=content,
            tags=tags,
        )
    )
```

**동작**

1. LangChain이 `AddPersonalReferenceInput`으로 입력을 검증한다.
2. helper에 전역 ChromaDB store와 검증된 값을 전달한다.
3. helper가 반환한 dict를 한글이 보존되는 JSON 문자열로 바꾼다.

**구현 의도**

tool 본문에는 저장 방식이나 metadata 변환 로직을 넣지 않았다. tool은 입력 검증과 JSON 반환 경계만 담당하고, 실제 저장 흐름은 helper와 store에 둔다.

이 분리는 단위 테스트를 단순하게 한다. helper는 일반 Python 함수로 테스트할 수 있고, tool은 `.invoke()`를 통해 JSON 계약만 별도로 확인할 수 있다.

**구현 근거**

- 과제 요구: helper 결과를 `json_payload()`로 감싼 문자열로 반환한다.
- Week 3에서 사용한 “tool은 얇은 입구” 구조를 그대로 유지했다.

---

### 3.4 `search_personal_reference_hits` — store 결과를 tool 계약으로 변환

**코드**

```python
rows = reference_store.search_personal_references(query, limit=top_k)
return [
    {
        "id": row.get("id"),
        "content": row.get("content", ""),
        "distance": row.get("distance"),
        "metadata": {
            "title": row.get("title", ""),
            "tags": row.get("tags", ""),
        },
    }
    for row in rows
]
```

**동작**

`PersonalReferenceStore`의 검색 결과는 `id`, `title`, `content`, `tags`, `distance`가 같은 단계에 있는 dict다. helper는 이를 다음 형태로 바꾼다.

```json
{
  "id": "ref_...",
  "content": "중요한 회의는 오전을 선호한다.",
  "distance": 0.12,
  "metadata": {
    "title": "집중 시간",
    "tags": "preference,meeting"
  }
}
```

**구현 의도**

검색 본문과 검색 결과의 설명 정보를 분리했다.

- `content`: LLM이 답변 근거로 읽는 문서 본문
- `metadata`: 문서 제목과 분류 정보
- `distance`: vector 검색 결과를 확인하는 값

누락될 수 있는 문자열 필드는 빈 문자열로 처리해 응답 key가 안정적으로 유지되게 했다. 검색 순서와 distance는 store가 반환한 그대로 유지한다.

**구현 근거**

- 과제 반환 계약: hit에 `id`, `content`, `distance`, `metadata(title/tags)`가 있어야 한다.
- 프로젝트 판단: store 내부 형식을 외부 tool 계약으로 직접 노출하지 않고 helper에서 명시적으로 변환한다.

---

### 3.5 `search_personal_references` — `hits` 계약 유지

**코드**

```python
@tool(args_schema=SearchPersonalReferencesInput)
def search_personal_references(query: str, top_k: int = 2) -> str:
    normalized_top_k = safe_limit(top_k, default=2, maximum=20)
    hits = search_personal_reference_hits(
        REFERENCE_STORE,
        query=query,
        top_k=normalized_top_k,
    )
    return json_payload({"hits": hits})
```

**동작과 의도**

- `top_k`를 보정한 뒤 검색 helper를 호출한다.
- 최상위 JSON key를 항상 `hits`로 유지한다.
- 검색 결과가 없으면 예외 대신 `{"hits": []}`를 반환한다.

최상위 key를 고정하면 LLM과 trace를 읽는 코드가 결과 형태를 예측할 수 있다. 검색 성공 여부를 별도 boolean으로 만들지 않고, `hits`의 내용으로 결과 유무를 표현한다.

**구현 근거**

- 과제에서 지정한 course repo 계약이 `{"hits": [...]}`다.
- 빈 검색 결과는 실패가 아니라 정상적인 조회 결과로 취급한다.

---

### 3.6 `search_saved_request_rows` — SQLite 검색의 얇은 helper

**코드**

```python
def search_saved_request_rows(sqlite_store, *, query, top_k=3):
    return sqlite_store.search_saved_requests(query, limit=top_k)
```

**동작**

`AppSQLiteStore.search_saved_requests()`는 `structured_requests` 테이블의 `raw_json`, `title`, `reason`에서 query를 `LIKE`로 검색하고 최신순으로 제한한다.

메서드 시그니처는 다음과 같다.

```python
search_saved_requests(query, kind=None, limit=5)
```

따라서 `top_k`는 `limit=top_k`처럼 키워드 인자로 전달해야 한다. `search_saved_requests(query, top_k)`처럼 두 번째 위치 인자로 넘기면 `top_k`가 limit이 아니라 `kind`에 들어간다.

**구현 의도**

helper는 검색 정책을 새로 만들지 않고 기존 SQLite store의 계약을 그대로 사용한다. 결과의 `raw_json` 등 근거 필드도 제거하지 않는다.

**구현 근거**

- 과제 요구: `AppSQLiteStore.search_saved_requests(query, limit)`를 호출한다.
- 실제 Python 시그니처를 확인해 `limit`을 키워드로 명시했다.

---

### 3.7 `search_saved_requests` — `rows` 계약 유지

**코드**

```python
@tool(args_schema=SearchSavedRequestsInput)
def search_saved_requests(query: str, top_k: int = 3) -> str:
    normalized_top_k = safe_limit(top_k, default=3, maximum=50)
    rows = search_saved_request_rows(
        SQLITE_STORE,
        query=query,
        top_k=normalized_top_k,
    )
    return json_payload({"rows": rows})
```

**동작과 의도**

- 검색 결과 제한을 1~50으로 보정한다.
- SQLite 결과를 최상위 `rows`에 담는다.
- 결과가 없으면 `{"rows": []}`를 반환한다.

개인 참고자료는 `hits`, 구조화 저장 요청은 `rows`로 구분한다. 이 차이는 단순한 이름 차이가 아니라 vector search 결과와 DB row의 출처가 다르다는 것을 나타낸다.

---

### 3.8 `week04_tools` — 구현된 메인 도구만 공개

**코드**

```python
def week04_tools() -> list[Any]:
    return [
        *week03_tools(),
        add_personal_reference,
        search_personal_references,
        search_saved_requests,
    ]
```

starter 코드에는 추가 과제인 `search_conversation_messages`도 목록에 있었다. 이번 구현은 메인 과제만 진행했으므로 해당 tool을 목록에서 제외했다.

함수 자체의 스텁은 파일에 남아 있지만 agent는 `week04_tools()`에 포함된 tool만 볼 수 있다. 따라서 사용자가 과거 대화를 묻더라도 미구현 함수가 선택되어 `...`를 반환하는 경로는 생기지 않는다.

이 결정은 추가 과제를 삭제한 것이 아니다. 나중에 추가 과제를 구현한다면 helper와 tool을 완성하고 테스트한 뒤 목록에 다시 추가할 수 있다.

---

### 3.9 `week04_prompt_parts` — 질문과 검색 출처 연결

프롬프트에는 다음 선택 규칙을 추가했다.

```text
개인 선호·메모·참고자료 저장
  → add_personal_reference

개인 선호·메모·참고자료 질문
  → search_personal_references

저장한 일정·할 일·알림 질문
  → search_saved_requests

일정·할 일·알림 저장 요청
  → Week 3의 구조화 및 SQLite 저장 도구
```

**구현 의도**

“기억해 줘”라는 표현만 보면 개인 참고자료 저장과 일정 저장이 겹칠 수 있다. 그래서 데이터 종류를 기준으로 경계를 명시했다.

- 선호·메모·참고자료는 ChromaDB 개인 참고자료로 저장한다.
- 일정·할 일·알림은 기존 Week 3 구조화/SQLite 저장 흐름을 유지한다.

두 출처가 모두 필요한 질문은 두 검색 tool을 각각 호출하고 답변에서 출처를 구분하게 했다. 검색 결과가 없으면 알고 있는 것처럼 추측하지 않도록 지시했다.

---

### 3.10 `LocalTraceLogStore` — 최종 실행 결과를 JSONL로 저장

**코드 핵심**

```python
record = {
    "schema_version": 1,
    "logged_at": now_iso(),
    "active_week": active_week,
    "conversation_id": conversation_id,
    "user_message": user_message,
    "assistant_answer": assistant_answer,
    "trace": trace,
}

encoded = json.dumps(record, ensure_ascii=False, default=str)
with self._append_lock:
    self.path.parent.mkdir(parents=True, exist_ok=True)
    with self.path.open("a", encoding="utf-8", newline="\n") as log_file:
        log_file.write(encoded + "\n")
```

**동작**

- 실행 한 건을 dict로 구성한다.
- 한글을 그대로 유지하는 JSON 문자열로 변환한다.
- `data/logs/agent_traces.jsonl` 끝에 한 줄을 추가한다.
- 디렉터리가 없으면 최초 기록 시 생성한다.
- 파일 쓰기에 실패하면 warning을 남기고 `False`를 반환한다.

**구현 의도**

`schema_version`을 두어 나중에 필드가 바뀌어도 로그 형식을 구분할 수 있게 했다. `logged_at`은 로컬 타임존이 포함된 ISO 시각이다.

`threading.Lock`은 같은 앱 프로세스 안에서 여러 Gradio 요청이 동시에 append할 때 한 줄 쓰기 구간이 섞이는 것을 막는다. 여러 프로세스가 같은 파일을 쓰는 상황까지 해결하는 lock은 아니지만, 현재 로컬 단일 앱 실행 범위에는 맞는다.

`default=str`은 예상하지 못한 객체가 trace에 포함되더라도 문자열로 변환해 로그 전체가 실패할 가능성을 줄인다. 기존 trace는 이미 JSON 표시 가능한 형태로 정리되지만, 파일 기록 경계에서 한 번 더 방어한다.

**구현 근거**

- 프로젝트 추가 요구: UI에서 질문하고 표시된 trace를 로컬에 저장한다.
- 프로젝트 판단: append가 간단하고 실행별 복구가 쉬운 JSONL을 선택했다.

---

### 3.11 `AgentRuntime._log_final_result` — UI 직전 최종 결과 경계에서 기록

**코드 핵심**

```python
def _log_final_result(self, user_message: str, result: RuntimeResult) -> None:
    try:
        self.trace_log_store.append(
            active_week=self.active_week,
            conversation_id=result.conversation_id,
            user_message=user_message,
            assistant_answer=result.answer,
            trace=result.trace,
        )
    except Exception as exc:
        LOGGER.warning("최종 agent trace를 로컬 로그에 기록하지 못했습니다: %s", exc)
```

이 helper는 다음 세 최종 경로에서 호출된다.

1. `run_agent()`의 동기 실행 성공 결과
2. `stream_agent()`에서 `event.result`가 도착한 결과
3. stream이 결과 없이 끝난 `stream_completed_without_result` fallback

`status_text`만 있는 중간 event에서는 호출하지 않는다. 따라서 화면의 “답변을 진행중입니다”, “현재 X 실행 중” 같은 상태가 여러 번 발생해도 로그는 최종 결과 한 건만 추가된다.

**왜 `app.py`에서 직접 기록하지 않았나**

`app.py`는 UI 컴포넌트의 입력·출력을 연결한다. 실제 최종 `RuntimeResult`는 `AgentRuntime`에서 만들어지고 동기/스트리밍 실행 모두 같은 구조를 사용한다.

로그를 runtime에 두면 다음 장점이 있다.

- UI 코드와 파일 저장 코드를 분리할 수 있다.
- 동기/스트리밍 경로가 같은 기록 함수를 사용한다.
- UI 외의 코드가 `AgentRuntime`을 호출해도 같은 로그가 남는다.
- fake logger를 주입해 파일 없이 테스트할 수 있다.

**실패 처리**

`LocalTraceLogStore.append()` 내부와 `_log_final_result()` 호출부에서 모두 예외를 막는다. 기본 logger의 파일 오류뿐 아니라 테스트나 향후 다른 logger 구현이 예외를 던지는 경우에도 agent 답변은 정상 반환된다.

로그는 핵심 응답이 아니라 관찰을 위한 부가 기능이므로, 로그 실패가 채팅 실패로 전파되지 않게 했다.

---

## 4. 코드 공부 보충 Q&A

### Q1. Pydantic이 범위를 검사하는데 `safe_limit`이 또 필요한가?

정상적인 LangChain tool 호출은 `SearchPersonalReferencesInput`이나 `SearchSavedRequestsInput`이 먼저 검증한다. 따라서 범위를 벗어난 값은 함수 본문에 들어오기 전에 거절될 수 있다.

`safe_limit`은 다음 경로를 위한 추가 방어다.

- 내부 helper나 원래 함수를 직접 재사용하는 코드
- 테스트에서 일반 Python 값으로 검증하는 경로
- 향후 args schema 적용 방식이 바뀌는 경우

두 검증은 역할이 겹치지만, 하나는 tool 입력 계약이고 다른 하나는 실행 시 최종 제한이다.

### Q2. `tags=None`을 왜 빈 list로 바꾸나?

store는 tags를 ChromaDB metadata에 쉼표로 합친 문자열로 저장한다.

```python
",".join(tags or [])
```

호출 전에 빈 list로 정규화하면 저장 결과의 `tags`도 항상 list 형태를 유지할 수 있고, `None` 처리 규칙이 tool/helper 경계에서 분명해진다.

### Q3. 검색 결과에서 title과 tags를 왜 `metadata` 안에 넣나?

`content`는 검색된 본문이고, title/tags는 본문을 설명하는 속성이다. 둘을 구분하면 LLM이나 후속 코드가 답변 근거와 문서 설명을 다른 목적으로 사용할 수 있다.

또한 과제에서 요구하는 hit 계약이 `id/content/distance/metadata(title/tags)`이므로 store 내부의 평평한 dict를 그대로 노출하지 않았다.

### Q4. ChromaDB 검색과 SQLite 검색을 하나의 tool로 합치면 더 간단하지 않나?

호출할 tool 수는 줄지만 결과의 의미가 불분명해진다.

- vector hit의 distance와 SQLite row는 같은 점수 체계가 아니다.
- 참고자료와 일정은 저장 목적과 갱신 주기가 다르다.
- 검색 실패 시 어느 출처에 데이터가 없었는지 구분하기 어렵다.
- LLM이 답변 근거의 출처를 명시하기 어려워진다.

이번 과제의 핵심도 출처별 tool을 분리하는 것이다. 여러 출처가 필요하면 agent가 두 tool을 각각 호출하게 했다.

### Q5. JSON 배열 파일 대신 JSONL을 선택한 이유는 무엇인가?

JSON 배열 파일은 새 기록을 추가할 때 기존 배열을 읽고 마지막 `]` 앞에 데이터를 넣거나 전체 파일을 다시 써야 한다. 쓰는 도중 실패하면 전체 JSON 구조가 깨질 수 있다.

JSONL은 한 줄 append만 수행한다. 일부 줄에 문제가 생겨도 다른 줄을 독립적으로 읽을 수 있고, PowerShell이나 Python에서 마지막 기록만 확인하기도 쉽다.

### Q6. 질문을 저장하면 SQLite `messages`와 로컬 로그에 중복되는 것 아닌가?

목적이 다르다.

- SQLite `messages`: 대화 UI를 다시 불러오기 위한 채팅 기록
- JSONL trace log: 한 질문에서 어떤 tool이 호출됐고 어떤 결과가 나왔는지 분석하기 위한 실행 기록

JSONL에는 질문과 답변 외에 `active_week`, trace event, 오류 정보가 함께 들어간다. 반대로 대화 삭제와 로그 삭제는 자동으로 연결하지 않았다. 로그가 더 이상 필요 없으면 파일을 별도로 삭제해야 한다.

### Q7. 추가 과제 스텁이 파일에 남아 있어도 안전한가?

현재 agent에는 안전하다. LangChain agent는 `week04_tools()`에 전달된 tool만 호출할 수 있고, 미구현 추가 과제 tool은 목록에서 제외했다.

다만 Python 코드가 `search_conversation_messages`를 직접 호출하면 아직 정상 결과를 만들 수 없다. 이 상태는 “추가 과제 보류”를 명시적으로 유지한 것이며, 향후 구현 시에는 helper·tool·prompt·tool 목록·테스트를 함께 추가해야 한다.

---

## 5. 검증 방법과 현재 결과

### 5.1 자동 검증

다음 검사를 실행했다.

```powershell
$env:PROXY_TOKEN='여기에 api key 입력'
uv run ruff check student_parts/week04_retrieve_nanas_memory.py `
  fixed/local_trace_log.py fixed/agent_runtime.py `
  tests/__init__.py tests/test_week04_main_and_trace_log.py
uv run ruff format --check student_parts/week04_retrieve_nanas_memory.py `
  fixed/local_trace_log.py fixed/agent_runtime.py `
  tests/__init__.py tests/test_week04_main_and_trace_log.py
uv run python -m unittest discover -v
```

결과:

- Ruff 검사 통과
- Ruff format check 통과
- Python compile 통과
- 단위 테스트 **12개 통과**
- `app.py` import 및 Week 4 tool wiring 확인
- `data/logs/agent_traces.jsonl`이 `.gitignore`의 `data/` 규칙에 포함됨을 확인

### 5.2 단위 테스트가 확인한 항목

**Week 4 메인 tool**

- `tags=None`이 빈 list로 정규화되는지
- 참고자료 검색 결과가 중첩 metadata 계약으로 변환되는지
- SQLite 검색 limit이 `kind` 위치 인자로 잘못 전달되지 않는지
- tool JSON에서 한글이 보존되는지
- 메인 tool 세 개만 agent에 노출되는지
- prompt에 Week 3 저장 경계가 포함되고 미구현 대화 검색은 없는지
- `safe_limit`의 최소·최대·기본값 동작

**로컬 trace 로그**

- 두 요청이 기존 파일을 덮지 않고 두 줄로 append되는지
- 각 줄을 독립적인 JSON으로 다시 읽을 수 있는지
- 한글 질문·답변·tool 이름이 보존되는지
- 파일 경로 오류가 `False` 반환으로 처리되는지
- 동기 실행에서 최종 결과가 한 번 기록되는지
- streaming의 여러 상태 event 뒤 최종 결과만 한 번 기록되는지
- stream fallback 오류도 기록되는지
- 주입된 logger가 예외를 던져도 agent 결과가 유지되는지

### 5.3 실제 앱에서 확인할 시나리오

외부 embedding API가 필요한 실제 ChromaDB add/query와 실제 UI 대화는 아직 실행하지 않았다. `.env`에 유효한 `PROXY_TOKEN`이 있는 환경에서 다음을 확인한다.

1. `KANANA_ACTIVE_WEEK=4`로 앱을 실행한다.
2. “나는 중요한 회의를 오전에 선호한다고 참고자료에 저장해 줘”를 입력한다.
3. trace에서 `add_personal_reference`와 `reference_backend`를 확인한다.
4. “내가 선호하는 회의 시간은 언제야?”를 입력한다.
5. trace에서 `search_personal_references`와 최상위 `hits`를 확인한다.
6. Week 3 방식으로 저장한 일정에 대해 “저장한 코칭 일정 찾아줘”를 입력한다.
7. trace에서 `search_saved_requests`와 최상위 `rows`를 확인한다.
8. `data/logs/agent_traces.jsonl`의 마지막 줄을 읽어 화면의 질문·답변·trace와 같은지 비교한다.

PowerShell에서 마지막 로그를 확인하는 예시는 다음과 같다.

```powershell
Get-Content data/logs/agent_traces.jsonl -Encoding utf8 | Select-Object -Last 1
```

---

## 6. ADR — 설계 결정 기록

> 형식: 배경 → 결정 → 결과.

### ADR-1. 기억 출처별로 검색 tool을 분리한다

- **배경**: 개인 참고자료는 ChromaDB vector search를 사용하고, 일정·할 일·알림은 SQLite 구조화 row에 저장된다. 두 결과의 형식과 검색 의미가 다르다.
- **결정**: 개인 참고자료는 `search_personal_references`, 구조화 저장 요청은 `search_saved_requests`로 분리한다. 둘 다 필요한 질문은 agent가 각각 호출한다.
- **결과**: 답변 근거의 출처를 구분할 수 있고, vector distance와 DB row를 억지로 하나의 순위에 섞지 않는다.

### ADR-2. 메인 과제만 구현하고 추가 과제 tool은 노출하지 않는다

- **배경**: starter의 `week04_tools()`에는 추가 과제인 `search_conversation_messages`가 포함되어 있지만 이번 범위에서는 구현하지 않았다. 스텁을 노출하면 agent가 선택했을 때 정상 JSON을 반환하지 못한다.
- **결정**: `week04_tools()`에서 미구현 추가 과제 tool을 제외하고 prompt에도 과거 대화 검색 규칙을 넣지 않는다.
- **결과**: 메인 과제 흐름만 안정적으로 실행된다. 향후 추가 과제를 구현하면 테스트 완료 후 tool과 prompt를 함께 복원해야 한다.

### ADR-3. helper는 저장소 주입, tool은 전역 저장소와 JSON 경계를 담당한다

- **배경**: ChromaDB와 embedding API를 직접 사용하는 코드는 네트워크와 로컬 데이터에 의존해 단위 테스트가 어렵다.
- **결정**: `add_personal_reference_dict`, `search_personal_reference_hits`, `search_saved_request_rows`는 store를 인자로 받는다. `@tool` 함수만 앱의 전역 store를 전달하고 JSON 문자열로 반환한다.
- **결과**: fake store로 핵심 변환 로직을 오프라인 테스트할 수 있고, tool 본문이 짧게 유지된다.

### ADR-4. 출처별 최상위 JSON key를 고정한다

- **배경**: agent와 trace에서 검색 결과의 출처를 빠르게 구분해야 한다.
- **결정**: vector 검색은 `hits`, SQLite 검색은 `rows`를 최상위 key로 사용한다. 빈 결과도 각각 빈 list로 유지한다.
- **결과**: 응답 형태가 예측 가능하고, 빈 결과를 예외나 임의 생성으로 바꾸지 않는다.

### ADR-5. UI가 아니라 `AgentRuntime`의 최종 결과 경계에서 로그를 남긴다

- **배경**: UI는 streaming 상태와 최종 결과를 모두 받으며, 동기 실행 경로도 별도로 존재한다. UI handler에 기록을 넣으면 경로별 중복이 생길 수 있다.
- **결정**: `RuntimeResult`가 완성된 뒤 `_log_final_result()`를 호출한다. 중간 `status_text`는 기록하지 않는다.
- **결과**: 동기·streaming·fallback이 같은 schema를 사용하고, 요청당 최종 로그 한 건만 남는다.

### ADR-6. 로컬 trace 형식은 append-only JSONL로 한다

- **배경**: 실행마다 질문·답변·trace를 계속 추가해야 하며, 전체 로그 파일을 매번 다시 쓰고 싶지 않다.
- **결정**: `data/logs/agent_traces.jsonl`에 UTF-8 JSON 한 줄을 append한다. `schema_version`, 타임존 포함 시각, 주차, 대화 ID를 같이 기록한다.
- **결과**: 실행별 독립 파싱이 가능하고 마지막 기록을 쉽게 확인할 수 있다. `data/`가 Git에서 제외되어 PR에 개인 로그가 포함되지 않는다.

### ADR-7. 로그 저장은 best-effort로 처리한다

- **배경**: 디스크 권한, 잘못된 경로, 직렬화 문제 때문에 로그 저장이 실패할 수 있다. trace 로그는 채팅 답변보다 우선순위가 낮다.
- **결정**: 저장 모듈에서 예외를 warning과 `False`로 바꾸고, runtime 호출부에서도 주입 logger의 예외를 한 번 더 막는다.
- **결과**: 로그가 남지 않는 상황에서도 사용자 답변과 UI trace는 정상 반환된다. 실패 원인은 애플리케이션 warning으로 확인할 수 있다.

### ADR-8. 로컬 로그는 대화 데이터와 별도 보존한다

- **배경**: SQLite 대화 삭제와 실행 분석 로그는 목적이 다르다. 자동 연동하면 로그의 분석 가치와 개인정보 삭제 요구가 충돌할 수 있다.
- **결정**: 대화 삭제 시 JSONL을 자동 수정하지 않는다. 로그 삭제는 `data/logs/agent_traces.jsonl` 파일을 명시적으로 삭제하는 별도 작업으로 둔다.
- **결과**: 구현은 단순하고 실행 기록은 유지된다. 대신 질문·답변·tool 결과가 평문으로 남는다는 점을 알고 로컬 파일을 관리해야 한다.

---

## 7. 보류한 범위

다음 항목은 강의 추가 과제이며 현재 구현하지 않았다.

- `search_conversation_messages_dict`
- `search_conversation_message_rows`
- `search_conversation_messages`
- `search_nana_memory`

추가 과제를 진행한다면 다음 작업이 함께 필요하다.

1. SQLite 대화를 ChromaDB에 lazy sync한다.
2. 명시적 `conversation_id`가 없을 때 현재 대화를 검색에서 제외한다.
3. `hits`, `rows`, `context`, `rag_backend`, `sync` 계약을 구현한다.
4. assistant 발화만으로 사용자 사실을 확정하지 않도록 prompt를 보강한다.
5. 구현 완료 후 `search_conversation_messages`를 `week04_tools()`에 다시 추가한다.

현재는 스텁을 남기되 agent 노출에서 제외한 상태다.

---

## 8. 용어 정리

- **RAG(Retrieval-Augmented Generation)**: LLM이 답변하기 전에 외부 저장소에서 관련 정보를 검색해 근거로 사용하는 구조.
- **embedding**: 텍스트의 특징을 숫자 vector로 표현한 값.
- **vector search**: query vector와 저장된 vector의 거리를 비교해 관련 문서를 찾는 검색.
- **ChromaDB**: embedding vector와 문서·metadata를 저장하고 검색하는 vector database.
- **distance**: query vector와 문서 vector 사이의 거리. 현재 구현은 ChromaDB 원본 값을 그대로 반환한다.
- **metadata**: 본문을 설명하는 부가 정보. 이번 참고자료 hit에서는 title과 tags를 담는다.
- **SQLite `LIKE` 검색**: 문자열이 특정 패턴을 포함하는지 확인하는 SQL 검색. embedding 기반 의미 검색과 다르다.
- **`top_k`**: 검색 결과 중 상위 몇 개를 반환할지 정하는 값.
- **JSONL(JSON Lines)**: 한 줄에 JSON 객체 하나를 저장하는 append 친화적 파일 형식.
- **trace**: agent의 tool call, arguments, tool result, 오류 등 실행 과정을 보여주는 구조화 기록.
- **best-effort**: 부가 작업을 시도하되 실패해도 핵심 작업은 계속 진행하는 처리 방식.
- **dependency injection**: 함수나 클래스가 사용할 객체를 내부에서 고정하지 않고 외부에서 전달받는 방식. 이번 구현에서는 fake store/logger 테스트에 사용했다.
- **fallback**: 정상 결과가 만들어지지 않았을 때 반환하는 대체 결과. streaming 종료 오류도 trace 로그에 기록한다.
