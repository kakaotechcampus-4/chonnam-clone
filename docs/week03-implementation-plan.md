# week03_build_nanas_logbook.py 구현 계획

> [week03-code-structure-analysis.md](./week03-code-structure-analysis.md)의 구조 분석과, 대화로 확정한 전제(구조화는 tool 호출 인자/DB 컬럼 경계에서 일어나고 최종 답변만 자연어)를 바탕으로 실제 구현 순서를 정리한다. `student_parts_baseline/`은 구현 시 참고하지 않는다.

## 1. 확정된 전제

- **agent 타입**: `response_format` 없는 순수 ReAct 도구 호출 에이전트. week01과 동일한 패턴 (`create_agent(model=chat_model(), tools=week03_tools(), system_prompt=week03_system_prompt())`).
- **구조화 지점**: `save_structured_request`의 `args_schema=SaveStructuredRequestInput`(Pydantic)이 검증하는 tool 호출 인자, 그리고 `AppSQLiteStore`가 실제로 쓰는 SQL 컬럼. 이 두 곳만 구조화되어 있으면 된다.
- **자연어 지점**: tool 호출들이 끝난 뒤 LLM이 생성하는 마지막 assistant 메시지 하나. `structured_response`를 만들지 않으므로 `extract_final_text()`가 이 메시지를 그대로 사용자에게 보여준다.
- **extract_schedule_request의 실제 역할**: week02에 이미 구현된 이 tool은 항상 `kind="unknown"`, `original_text=query`만 반환하는 얇은 스텁이다 (LLM 호출이 없는 순수 Python 함수). 따라서 이 tool을 호출하는 것 자체는 trace 검증(주석의 "extract_schedule_request 다음에 save_structured_request가 호출되는지")을 만족시키는 절차이고, **실제 kind/title/date 등 필드값 판단은 LLM이 시스템 프롬프트 규칙을 보고 스스로 하는 것**이지 이 tool의 반환값을 근거로 하는 게 아니다. 이 사실을 시스템 프롬프트에 명시해야 한다 (§3 참고).

## 2. 프롬프트 구조화 방침: `week02_prompt_parts()` spread 대신 명시적 선택

`week01-week02-prompt-separation-plan.md`에서 확립한 원칙("주차가 높다고 이전 주차 전체를 상속하지 않고, 이번 agent의 역할에 필요한 정책만 선택한다")을 week03에도 그대로 적용한다. `week02_structure_natural_language_requests.py`가 이미 `week01_prompt_parts()`를 spread하지 않고 `prompts/common.py` + `prompts/week02.py`에서 필요한 상수만 개별 선택하는 것과 같은 패턴이다.

```python
def week03_prompt_parts() -> list[str]:
    return [
        *week03_prompt_parts()  # (X) 이렇게 통째로 spread하지 않는다
    ]
```

대신 `student_parts/prompts/week03.py`를 새로 만들고, week03은 `common.py` + `week02.py` + `week03.py`에서 각각 필요한 조각만 골라 조합한다.

```python
def week03_prompt_parts() -> list[str]:
    return [
        NANA_IDENTITY_PROMPT,
        date_time_prompt(),
        NO_GUESSING_PROMPT,
        CHAT_MEMORY_PROMPT,
        WEEK02_CLASSIFICATION_PROMPT,
        WEEK02_PERSONAL_CREATE_TOOL_PROMPT,
        WEEK02_TOOL_PAYLOAD_MAPPING_PROMPT,
        WEEK03_FIELD_FILLING_PROMPT,
        SQLITE_MEMORY_PROMPT,
        WEEK03_TOOL_CALL_PROMPT,
        WEEK03_SCOPE_PROMPT,
    ]
```

spread를 없애면 이전에 고려했던 "`WEEK02_SCOPE_PROMPT` 무효화 문장 끼워넣기" 같은 편법이 필요 없어진다 — 애초에 `WEEK02_SCOPE_PROMPT`를 선택하지 않으면 되기 때문이다. 다만 그 대신 **지금까지 spread로 공짜로 딸려오던 것들을 다시 하나하나 판단**해야 한다.

### 2.1 `prompts/week02.py` 상수 5개 중 재사용 여부

| 상수 | week03 처리 | 이유 |
|---|---|---|
| `WEEK02_CLASSIFICATION_PROMPT` | 그대로 재사용 | kind 분류 기준·unknown 처리는 week03에서도 동일 |
| `WEEK02_PERSONAL_CREATE_TOOL_PROMPT` | 그대로 재사용 | `personal_create_schedule` 호출 조건이 동일 |
| `WEEK02_TOOL_PAYLOAD_MAPPING_PROMPT` | 그대로 재사용 | `created_schedule` → 필드 매핑 규칙이 동일 |
| `WEEK02_CLARIFICATION_STATE_PROMPT` | **재사용 금지** — week03 버전 새로 작성 | `status="needs_clarification"/"complete"`, `structured_request=StructuredRequestBatch` 등 `Week02Response` 계약 언어를 그대로 담고 있어, response_format이 없는 week03에 넣으면 "최종 답변을 그 객체로 만들어라"는 잘못된 지시가 됨 |
| `WEEK02_STRUCTURED_OUTPUT_PROMPT` | **재사용 금지** — week03 버전 새로 작성 | 위와 동일한 이유. "최종 결과는 Week02Response로 구조화한다"는 문장이 §1의 전제(최종 답변은 자연어)와 정면 충돌 |
| `WEEK02_SCOPE_PROMPT` | 선택하지 않음(제외) | "SQLite 저장을 하지 않는다"는 Week 2 한정 문장이므로 애초에 목록에 넣지 않는다 |

`WEEK02_CLARIFICATION_STATE_PROMPT`와 `WEEK02_STRUCTURED_OUTPUT_PROMPT`의 알맹이(부족한 값은 한 번에 확인, kind/title/date/... 필드를 채우는 기준)는 여전히 필요하므로, `Week02Response`/`status`/`structured_request` 계약 언어를 뺀 **week03 전용 버전**(`WEEK03_FIELD_FILLING_PROMPT` 등, §3.2)으로 다시 쓴다. `common.py`의 `NO_GUESSING_PROMPT`가 이미 계약-무관 버전으로 "부족하거나 모호한 값은 필요한 항목만 모아 한 번에 확인한다"를 담당하고 있으니 그 위에 필드별 기준만 얹으면 된다.

### 2.2 부수적으로 드러난 tool 이중화 문제

`week03_tools()`는 `week01_tools()`에서 `personal_create_schedule`만 week03 호환 버전으로 교체하고, **`personal_list_schedules`/`personal_delete_schedule`(Week 1의 세션 메모리 버전)은 그대로 남는다.** 즉 최종 tool 목록에 "메모리 기반 조회/삭제"와 "SQLite 기반 조회/삭제"(`personal_list_saved_schedules`/`personal_delete_saved_schedules`)가 동시에 존재한다. 프롬프트에서 "조회/삭제는 SQLite 버전을 우선 사용한다"를 명시하지 않으면, LLM이 메모리 전용 tool을 호출해 새 대화에서 빈 목록을 반환할 위험이 있다 — 이 규칙을 `WEEK03_TOOL_CALL_PROMPT`에 반드시 포함한다.

## 3. 프롬프트 내용 설계

### 3.1 `SQLITE_MEMORY_PROMPT`

역할: "대화가 끝나도 데이터가 남는다"는 Week 3의 핵심 차이를 LLM에게 알려준다.

포함할 내용:
- 저장된 일정/할 일/알림은 SQLite에 남아 새 대화·재시작 이후에도 조회할 수 있다.
- "내 일정 보여줘" 같은 조회 요청은 대화 기억에만 의존하지 말고 매번 `personal_list_saved_schedules`로 실제 DB를 확인한다.
- 수정/삭제 전에는 먼저 조회 tool로 후보를 확인해 정확한 `schedule_id`를 얻은 뒤 사용한다 (제목만으로 추측해 삭제하지 않는다).

### 3.2 `WEEK03_FIELD_FILLING_PROMPT` (신규)

역할: `WEEK02_CLARIFICATION_STATE_PROMPT` / `WEEK02_STRUCTURED_OUTPUT_PROMPT`가 담당하던 "필드를 어떻게 채우는가"를 계약 언어 없이 재정의.

포함할 내용:
- `kind`/`title`/`date`/`start_time`/`end_time`/`members`/`priority`/`reason`/`original_text` 필드는 Week 2와 동일한 기준(확실할 때만 채움, 모르면 `None`/빈 리스트)으로 판단한다.
- 필수값(제목/날짜/시작 시간 등)이 부족하면 `save_structured_request`를 바로 호출하지 말고, 필요한 항목만 모아 자연스러운 한국어로 한 번에 되묻는다 (`status`/`missing_fields` 같은 필드 계약이 아니라 그냥 자연어 응답으로).
- 값이 충분히 모이면 그때 `save_structured_request`(또는 해당 생성 tool)를 호출한다.

### 3.3 `WEEK03_TOOL_CALL_PROMPT`

역할: 저장/조회/수정/삭제 각 시나리오에서 tool을 어떤 순서로 호출해야 하는지 안내.

포함할 내용:
1. §2.2의 tool 이중화 규칙: 조회/삭제는 `personal_list_saved_schedules`/`personal_delete_saved_schedules`(SQLite) 를 우선 사용하고, Week 1의 메모리 전용 조회/삭제 tool은 사용하지 않는다.
2. 저장 흐름: `extract_schedule_request(query=...)`를 먼저 호출한다. 이 tool의 반환값이 항상 `kind="unknown"`이어도, 실제 필드 값은 §3.2 규칙에 따라 LLM이 직접 판단해서 `save_structured_request`의 인자로 채운다.
3. 개인 일정 생성 요청이면 `personal_create_schedule`(Week 3 호환 버전, 이중 저장) 하나로 충분하고 별도로 `save_structured_request`를 또 호출할 필요는 없다. `todo`/`reminder`/`group_schedule`처럼 전용 생성 tool이 없는 종류만 `save_structured_request`를 직접 호출한다.
4. 수정 흐름: `personal_list_saved_schedules`로 후보 확인 → `personal_update_saved_schedule(schedule_id=...)`.
5. 삭제 흐름: `personal_list_saved_schedules`로 후보 확인 → `personal_delete_saved_schedules(schedule_ids=[...])`. 조건 없이 전부 삭제하는 요청은 사용자가 명확히 "전부"라고 말했을 때만 `delete_all=True`를 쓴다.
6. tool 결과의 `ok`가 `false`이면 성공으로 답하지 않고 원인을 사용자에게 설명한다.

### 3.4 `WEEK03_SCOPE_PROMPT` (신규, `WEEK02_SCOPE_PROMPT` 대체)

`WEEK02_SCOPE_PROMPT`("SQLite 저장, RAG 검색, 외부 멤버 일정 조율을 하지 않는다")를 그대로 상속하지 않게 됐으므로, week03에 맞는 범위 문장을 새로 정의한다.

```python
WEEK03_SCOPE_PROMPT = """
Week 3에서는 구조화된 요청을 SQLite에 저장하고 조회/수정/삭제한다.
RAG 검색, 외부 멤버 일정 조율은 아직 Week 3 범위가 아니다.
"""
```

현재 날짜는 `common.py`의 `date_time_prompt()`를 직접 선택했으므로(§2) 별도로 중복 추가하지 않는다.

## 4. 함수 구현 순서 (의존관계 순)

의존관계가 없는 것부터: 스키마 정규화 → 저장 → 조회 → 수정/삭제 → 조립부.

### 4.1 `SaveStructuredRequestInput.unwrap_legacy_payload`

예전 trace/테스트에서 `{"payload": {...}}` 또는 `{"structured_request": {...}}`로 감싸 들어올 수 있는 입력을 평평한 dict로 푼다. 정상 agent 경로(LLM이 필드를 직접 넘기는 경우)에서는 이미 flat dict이므로 그대로 통과시킨다.

```python
@model_validator(mode="before")
@classmethod
def unwrap_legacy_payload(cls, value: Any) -> Any:
    if isinstance(value, dict):
        for wrapper_key in ("structured_request", "payload"):
            wrapped = value.get(wrapper_key)
            if isinstance(wrapped, dict):
                value = {**value, **wrapped}
                value.pop(wrapper_key, None)
    return value
```

### 4.2 `_save_input_from` / `save_structured_request_payload`

`_save_input_from`은 dict / JSON 문자열 / 자연어 문자열 / `StructuredRequest` / `SaveStructuredRequestInput` 어떤 걸 받아도 `SaveStructuredRequestInput` 하나로 정규화한다. 자연어 문자열은 `extract_structured_request(value)`로 먼저 구조화한 뒤 `.model_dump()`를 거쳐 검증한다.

`save_structured_request_payload`는 `_save_input_from(request)`로 검증한 뒤 `(store or _store()).save_structured_request(validated.model_dump())`을 호출하고 `tool_result(...)`로 감싼다. 이 helper는 agent가 직접 부르는 게 아니라 테스트/내부 호출용이라는 점을 유지한다.

### 4.3 `save_structured_request` (메인, 핵심 tool)

```python
@tool(args_schema=SaveStructuredRequestInput)
def save_structured_request(
    kind="unknown", title=None, date=None, start_time=None, end_time=None,
    members=None, priority=None, reason=None, original_text="", source_schedule_id=None,
) -> str:
    payload = {
        "kind": kind, "title": title, "date": date,
        "start_time": start_time, "end_time": end_time,
        "members": members or [], "priority": priority,
        "reason": reason, "original_text": original_text,
        "source_schedule_id": source_schedule_id,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    result = _store().save_structured_request(payload)
    return json_payload(tool_result("save_structured_request", ok=True, **result))
```

`args_schema`가 이미 타입/`Literal` 검증을 끝냈으므로 함수 본문에서 Pydantic class를 다시 만들지 않는다 (파일 주석의 명시적 요구사항).

### 4.4 `list_saved_requests` / `get_saved_request`

`AppSQLiteStore.list_saved_requests(...)` / `get_saved_request(...)`에 인자를 그대로 위임. 결과가 없어도 예외를 던지지 않고 `rows=[]` 또는 `row=None`을 유지.

### 4.5 `personal_list_saved_schedules`

기본 `kind="personal_schedule"`로 두고(파일 주석 379번 줄의 명시적 지시) `AppSQLiteStore.list_schedules(limit, kind, date_from, date_to)`에 위임. 응답에 `filters`와 `schedules`를 함께 담는다.

### 4.6 `structured_request_from_week01_schedule` / `personal_create_schedule` (Week 1 호환)

`AppSQLiteStore.save_structured_request`에는 이미 **멱등성 처리**가 있다: `source_schedule_id`가 `schedules.schedule_id`로 이미 존재하면 재삽입하지 않고 기존 row를 반환한다. 이 성질을 활용해 Week 1의 임시 id를 그대로 Week 3 `schedule_id`로 재사용한다. `original_text`에는 일정 dict를 직렬화하지 않고 `extract_schedule_request`가 보존한 사용자 원문을 전달한다. 내부 id는 `source_schedule_id`, 전체 저장 payload는 `raw_json`이 각각 담당한다.

```python
def structured_request_from_week01_schedule(
    schedule: dict[str, Any], *, original_text: str = ""
) -> SaveStructuredRequestInput:
    return SaveStructuredRequestInput(
        kind="personal_schedule",
        title=schedule.get("title"),
        date=schedule.get("date"),
        start_time=schedule.get("start_time"),
        end_time=schedule.get("end_time") if schedule.get("end_time") != "미정" else None,
        members=list(schedule.get("attendees") or []),
        original_text=original_text,
        source_schedule_id=schedule.get("id"),
    )
```

```python
@tool("personal_create_schedule")
def personal_create_schedule(
    title, date, start_time, end_time="미정", attendees=None, original_text=""
) -> str:
    week1_result = json.loads(
        week01_personal_create_schedule.invoke(
            {"title": title, "date": date, "start_time": start_time, "end_time": end_time, "attendees": attendees}
        )
    )
    if not week1_result.get("ok"):
        return json_payload(tool_result("personal_create_schedule", ok=False, **week1_result))

    save_input = structured_request_from_week01_schedule(
        week1_result["created_schedule"], original_text=original_text
    )
    sqlite_save = save_structured_request_payload(save_input)
    return json_payload(
        tool_result(
            "personal_create_schedule",
            ok=True,
            created_schedule=week1_result["created_schedule"],
            structured_request=save_input.model_dump(),
            sqlite_save=sqlite_save,
        )
    )
```

`end_time == "미정"`을 `None`으로 바꾸는 규칙은 `WEEK02_TOOL_PAYLOAD_MAPPING_PROMPT`에서 이미 쓰인 것과 동일한 규칙이므로 일관성 있게 재사용한다.

### 4.7 `_delete_saved_schedules` (추가, 삭제 guard)

```python
def _delete_saved_schedules(*, store, schedule_ids=None, date=None, title=None,
                             start_time=None, time_unspecified=False, delete_all=False) -> dict[str, Any]:
    has_condition = delete_all or schedule_ids or date or title or start_time or time_unspecified
    if not has_condition:
        return tool_result("personal_delete_saved_schedules", ok=False, error="no_delete_condition",
                            deleted_count=0, filters={}, deleted=[])

    if delete_all:
        deleted = store.delete_all_schedules()
    else:
        deleted = store.delete_schedules_by_filter(
            schedule_ids=schedule_ids, date=date, title=title,
            start_time=start_time, time_unspecified=time_unspecified,
        )
    filters = {"schedule_ids": schedule_ids, "date": date, "title": title,
               "start_time": start_time, "time_unspecified": time_unspecified, "delete_all": delete_all}
    return tool_result("personal_delete_saved_schedules", ok=True,
                        deleted_count=len(deleted), filters=filters, deleted=deleted)
```

조건 없는 삭제를 막는 것이 이 함수의 핵심 책임(파일 주석 89번 줄)이므로 `has_condition` 체크를 가장 먼저 둔다.

### 4.8 `personal_update_saved_schedule` / `personal_delete_saved_schedules` / `delete_saved_schedules_dict`

- `personal_update_saved_schedule`: `None`이 아닌 필드만 `AppSQLiteStore.update_schedule(...)`에 넘긴다. 반환값이 `None`이면(`schedule_id` 못 찾음) `ok=False`, 있으면 `updated_schedule`/`shared_sync`를 담아 반환.
- `personal_delete_saved_schedules`: 입력을 그대로 `_delete_saved_schedules(store=_store(), ...)`에 위임.
- `delete_saved_schedules_dict`: `app_store or _store()`를 골라 `_delete_saved_schedules(...)`를 호출하는 얇은 wrapper (tool invoke 없이 테스트에서 직접 호출).

## 5. 조립부

- `week03_tools()`: 이미 구현되어 있는 스켈레톤 그대로 두되(§1의 tool 목록), `personal_create_schedule` 교체 로직만 §4.6 구현과 맞물리는지 확인.
- `week03_system_prompt()` / `week03_prompt_parts()`: §2·§3 반영.
- `build_week03_agent()`:

```python
def build_week03_agent() -> object:
    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK03_AGENT
    if _WEEK03_AGENT is None:
        _WEEK03_AGENT = create_agent(
            model=chat_model(),
            tools=week03_tools(),
            system_prompt=week03_system_prompt(),
        )
    return _WEEK03_AGENT
```

`response_format` 인자를 넣지 않는 것이 §1의 핵심 전제다.

## 6. 구현 순서 요약 (체크리스트)

1. `student_parts/prompts/week03.py` 신설: `WEEK03_FIELD_FILLING_PROMPT`, `SQLITE_MEMORY_PROMPT`, `WEEK03_TOOL_CALL_PROMPT`, `WEEK03_SCOPE_PROMPT` 작성 (§2, §3)
2. `week03_prompt_parts()`를 spread 없이 명시적 선택 목록으로 재작성 (§2)
3. `SaveStructuredRequestInput.unwrap_legacy_payload` (§4.1)
4. `save_structured_request` (§4.3) — 메인과제 핵심
5. `list_saved_requests` / `get_saved_request` / `personal_list_saved_schedules` (§4.4, §4.5)
6. `_save_input_from` / `save_structured_request_payload` (§4.2) — 이후 §4.6에서 재사용
7. `structured_request_from_week01_schedule` / `personal_create_schedule` 호환 tool (§4.6)
8. `_delete_saved_schedules` (§4.7)
9. `personal_update_saved_schedule` / `personal_delete_saved_schedules` / `delete_saved_schedules_dict` (§4.8)
10. `build_week03_agent()` (§5)

## 7. 검증 계획

```bash
uv run python -m py_compile student_parts/week03_build_nanas_logbook.py
./run.sh --week3
```

메인과제:
- "내일 10시 개인 코칭 저장해줘" → trace에서 `extract_schedule_request` 다음 `personal_create_schedule`(또는 `save_structured_request`) 호출 확인
- "내 일정 보여줘" → `personal_list_saved_schedules` 호출, 방금 저장한 항목 포함 확인
- 앱 재시작 또는 새 대화 시작 후 같은 조회 → 저장된 일정이 그대로 남아있는지 확인 (SQLite 파일 기반이므로 프로세스 재시작에도 유지되어야 함)

추가과제:
- 저장된 일정 조회 후 시간 변경 요청 → `personal_update_saved_schedule` 호출, 변경 반영 확인
- 특정 일정 삭제 요청 → `personal_list_saved_schedules`로 후보 확인 후 `personal_delete_saved_schedules(schedule_ids=[...])` 호출, 목록에서 사라짐 확인
- 조건 없는 삭제 요청("다 지워줘"가 아닌 애매한 삭제) → `ok=False`, `no_delete_condition`류 실패 응답 확인

## 8. `student_parts_baseline/` 관련 메모

`student_parts_baseline/`에는 현재 week01/week02 baseline만 있고 week03 baseline은 없다. 위 계획은 baseline 파일을 참고하지 않고 `fixed/app_store.py`, `fixed/store_base.py`, `student_parts/week01_wake_up_nana.py`, `student_parts/week02_structure_natural_language_requests.py`, `student_parts/prompts/*.py`만 근거로 세웠다.
