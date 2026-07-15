# Week 3 스터디 & ADR — 구조화 결과를 SQLite에 저장·조회·수정·삭제 (Nana의 기록장)

- 대상 파일: `student_parts/week03_build_nanas_logbook.py`
- 브랜치: `junyoung/week3` (base = `junyoung/final`)
- 범위: **메인 + 추가 전부 구현 완료.**

이 문서는 (1) 구현 코드 해설 + (2) 설계 결정 기록(ADR)을 담는다.

---

## 1. 이번 주 한 일 (요약)

Week2가 "말 → `StructuredRequest`(구조화)"까지였다면, Week3는 그 결과를 **SQLite에 저장**하고 **다시 조회/수정/삭제**한다. Week1의 일정은 대화가 끝나면 사라지는 임시 메모리였지만, Week3부터 Nana는 앱 DB에 남는 **"기록장"**을 갖는다.

핵심 흐름: `extract_schedule_request`(Week2 구조화) → `save_structured_request`(`@tool`이 `args_schema`로 검증) → `AppSQLiteStore` 저장 → `personal_list_saved_schedules`로 조회(새 대화·앱 재시작에도 유지) → 필요 시 수정/삭제.

구현 목록: 저장(`save_structured_request`), 조회(`list_saved_requests`/`get_saved_request`/`personal_list_saved_schedules`), 수정(`personal_update_saved_schedule`), 삭제(`personal_delete_saved_schedules`+guard), Week1 호환 생성(`personal_create_schedule`), 레거시 정규화(`unwrap_legacy_payload`/`_save_input_from`/`save_structured_request_payload`), 프롬프트/agent.

---

## 2. 구현 해설 (코드 워크스루)

각 항목은 **① 쉽게 말하면(비유) → ② 코드 → ③ 구현 의도 → ④ 과제 원문 / ✳️ 내 판단** 순서다.

전체 비유: **Week3 = 접수처 뒤에 생긴 "문서 보관 창고(SQLite)".** Week2 창구가 손님 말을 신청서로 옮겨 적었다면(구조화), Week3는 그 신청서를 **창고에 실제로 보관**하고, 나중에 **꺼내 보고(조회)·고쳐 쓰고(수정)·폐기(삭제)**한다. 각 `@tool`은 창고 관리인에게 "이거 넣어/찾아/고쳐/버려"라고 시키는 **접수 창구**일 뿐, 실제 선반 정리(SQL)는 창고 관리인(`AppSQLiteStore`)이 한다.

---

### 2.1 `SaveStructuredRequestInput` — 저장 직전 검증하는 "입고 전표"

**① 쉽게 말하면**
Week2 신청서(`StructuredRequest`)에 **창고 입고용 칸 하나(`source_schedule_id`)만 덧붙인 전표**. 창고에 넣기 직전, 이 전표 양식에 맞는지 한 번 더 검사한다.

**② 코드**
```python
class SaveStructuredRequestInput(StructuredRequest):   # ← Week2 스키마 상속
    kind: RequestKind = Field(default="unknown", description="분류된 요청 종류")
    source_schedule_id: str | None = Field(default=None, description="Week 1 임시 일정에서 넘어온 원본 일정 ID")

    @model_validator(mode="before")
    @classmethod
    def unwrap_legacy_payload(cls, value):
        if isinstance(value, StructuredRequest):
            return value.model_dump()
        if isinstance(value, dict):
            if isinstance(value.get("structured_request"), dict):
                return value["structured_request"]
            if isinstance(value.get("payload"), dict):
                return value["payload"]
        return value
```

**③ 구현 의도**
- **Week2 스키마를 상속**해서 필드를 재정의하지 않고 그대로 물려받고, `source_schedule_id`(Week1 임시 일정과 연결할 원본 ID)만 추가했다. → Week2와 저장 스키마가 항상 같은 필드를 공유한다.
- `unwrap_legacy_payload`(`model_validator(mode="before")` = 검증 **전에** 입력을 손보는 훅)는 예전 trace/테스트가 `{"structured_request": {...}}`나 `{"payload": {...}}`처럼 **한 겹 감싸서** 보내던 걸 벗겨낸다. 감싸져 있으면 알맹이를 꺼내고, 아니면 그대로 통과 → 이후 필드 검증은 Pydantic이 한다.

**④ 과제 원문**
> SaveStructuredRequestInput은 Week 2 StructuredRequest를 상속하고, Week 1 호환용 source_schedule_id만 추가합니다.
> SaveStructuredRequestInput.unwrap_legacy_payload는 예전 trace/테스트의 payload/structured_request wrapper를 저장 스키마로 풉니다.

---

### 2.2 `save_structured_request` — 창고에 실제로 넣는 "입고 처리"(메인 핵심)

**① 쉽게 말하면**
창구 직원이 **전표를 창고 관리인에게 넘겨 선반에 올리는** 일. 직원은 전표 내용을 정리해서 넘길 뿐, 선반에 어떻게 꽂히는지(SQL)는 관리인이 처리한다.

**② 코드**
```python
@tool(args_schema=SaveStructuredRequestInput)
def save_structured_request(kind="unknown", title=None, ..., source_schedule_id=None):
    payload = {"kind": kind, "title": title, ..., "source_schedule_id": source_schedule_id}
    payload = {k: v for k, v in payload.items() if v is not None}   # None 값 제외
    result = _store().save_structured_request(payload)
    return json_payload(tool_result("save_structured_request", ok=True, **result))
```

**③ 구현 의도**
- `@tool(args_schema=SaveStructuredRequestInput)` — LangChain이 이 스키마로 **입력을 먼저 검증**한 뒤 함수를 부른다. 그래서 **본문에서 Pydantic 객체를 다시 만들지 않고**, 이미 검증된 인자를 저장 dict로 모으기만 한다(얇은 입구).
- **`None` 값 제외**: 안 채워진 필드는 저장 payload에서 빼서 DB에 불필요한 빈 값이 안 들어가게 한다.
- 결과는 `tool_result`로 `ok`/`tool_name`을 붙이고 `json_payload`(=한글 안 깨지는 JSON)로 반환.

**④ 과제 원문**
> @tool(args_schema=SaveStructuredRequestInput)으로 Week 2 구조화 결과를 검증합니다. tool 본문에서는 Pydantic class를 다시 만들지 말고, 함수 인자로 들어온 값을 바로 저장 dict로 정리합니다. 자연어 문자열이나 ok/tool_name/base_date wrapper를 직접 저장하지 않습니다.

---

### 2.3 조회 3형제 — `list_saved_requests` / `get_saved_request` / `personal_list_saved_schedules`

**① 쉽게 말하면**
창고에서 꺼내 보는 세 가지 방법. **원본 신청서 목록**(list_saved_requests), **신청서 한 장 단건**(get_saved_request, 번호로), **정리된 일정 목록**(personal_list_saved_schedules).

**② 코드**
```python
@tool(args_schema=SavedRequestListInput)
def list_saved_requests(kind=None, date_from=None, date_to=None):
    rows = _store().list_saved_requests(kind=kind, date_from=date_from, date_to=date_to)
    return json_payload(tool_result("list_saved_requests", ok=True, rows=rows))

@tool(args_schema=SavedRequestGetInput)
def get_saved_request(request_id):
    row = _store().get_saved_request(request_id)          # 없으면 None
    return json_payload(tool_result("get_saved_request", ok=True, row=row))

@tool(args_schema=SavedScheduleListInput)
def personal_list_saved_schedules(limit=50, kind=None, date_from=None, date_to=None):
    effective_kind = kind or "personal_schedule"          # 기본 개인 일정
    schedules = _store().list_schedules(limit=limit, kind=effective_kind, date_from=date_from, date_to=date_to)
    filters = {"limit": limit, "kind": effective_kind, "date_from": date_from, "date_to": date_to}
    return json_payload(tool_result("personal_list_saved_schedules", ok=True, filters=filters, schedules=schedules))
```

**③ 구현 의도**
- 필터(`kind`/`date_from`/`date_to`)를 store에 **그대로 위임**한다. tool은 얇게.
- `personal_list_saved_schedules`는 기본 `kind="personal_schedule"`로 두고(개인 일정 조회가 기본 목적), 어떤 조건으로 조회했는지 `filters`를 함께 반환해 trace에서 알아보기 쉽게 했다. `limit`으로 과다 조회를 막는다.
- **결과가 없어도 예외를 던지지 않는다** — `rows=[]` / `row=None`을 그대로 유지. (조회 실패가 아니라 "없음"이 정상 응답)

**④ 과제 원문**
> list는 kind/date_from/date_to 필터를 AppSQLiteStore.list_saved_requests(...)에 그대로 넘깁니다. get은 request_id 하나로 단건 조회합니다. 조회 결과가 없어도 예외를 던지지 말고 rows=[] 또는 row=None 형태를 유지합니다.
> 날짜가 명확한 조회는 date_from/date_to로 범위를 좁히고, 너무 많은 row가 들어가지 않게 limit을 사용합니다.

---

### 2.4 `personal_update_saved_schedule` — 보관된 문서 "고쳐 쓰기"(추가)

**① 쉽게 말하면**
창고에 있는 일정을 꺼내 **필요한 칸만 고쳐 다시 넣는** 일. 안 건드릴 칸은 비워서(`None`) 넘기면 그대로 둔다. 없는 번호면 "그런 거 없음"(`ok=False`).

**② 코드**
```python
@tool(args_schema=SavedScheduleUpdateInput)
def personal_update_saved_schedule(schedule_id, title=None, date=None, start_time=None, end_time=None, attendees=None):
    result = _store().update_schedule(schedule_id, title=title, date=date, start_time=start_time, end_time=end_time, attendees=attendees)
    if result is None:
        return json_payload(tool_result("personal_update_saved_schedule", ok=False, error=f"schedule_id를 찾을 수 없습니다: {schedule_id}", schedule_id=schedule_id))
    return json_payload(tool_result("personal_update_saved_schedule", ok=True, updated_schedule=result.get("schedule"), shared_sync=result.get("shared_sync")))
```

**③ 구현 의도**
- `None`=미변경 규칙을 그대로 store에 넘긴다(store가 None 필드는 건너뜀).
- store가 `None`을 돌려주면(=ID 없음) `ok=False`로 정직하게 실패를 알린다.
- 성공 시 `updated_schedule`과 **공유 저장소 동기화 결과(`shared_sync`)**를 함께 반환 — 개인/그룹 일정은 외부 공유 저장소에도 복사본이 있어서 그 갱신 결과를 같이 보여준다.

**④ 과제 원문**
> AppSQLiteStore.update_schedule(...) 결과를 JSON 응답으로 완성하고, 공유 일정 복사본 동기화 결과(shared_sync)도 함께 반환합니다. None으로 들어온 필드는 "수정하지 않음"이라는 뜻입니다. ID를 못 찾으면 ok=False로 답합니다.

---

### 2.5 삭제 — `_delete_saved_schedules`(guard) + `personal_delete_saved_schedules`(추가)

**① 쉽게 말하면**
폐기 처리. 단, **"조건 없이 다 버려"는 사고로 이어지므로 막는다.** schedule_ids나 날짜/제목/시간 필터, 또는 "전부 삭제(`delete_all`)"를 **명시**해야만 지운다.

**② 코드**
```python
def _delete_saved_schedules(*, store, schedule_ids=None, date=None, title=None, start_time=None, time_unspecified=False, delete_all=False):
    filters = {...}
    has_condition = delete_all or bool(schedule_ids) or any([date, title, start_time, time_unspecified])
    if not has_condition:                                   # ← 안전 guard
        return tool_result("personal_delete_saved_schedules", ok=False, error="삭제 조건이 없습니다. ...", deleted_count=0, filters=filters, deleted=[])
    deleted = store.delete_all_schedules() if delete_all else store.delete_schedules_by_filter(...)
    return tool_result("personal_delete_saved_schedules", ok=True, deleted_count=len(deleted), filters=filters, deleted=deleted)
```

**③ 구현 의도**
- 삭제 로직과 **안전 규칙을 한 곳(`_delete_saved_schedules`)에 모았다.** tool(`personal_delete_saved_schedules`)과 helper(`delete_saved_schedules_dict`)가 이 함수를 공유 → 규칙이 한 군데라 실수가 줄어든다.
- `deleted_count`/`filters`/`deleted`를 항상 반환해 trace에서 "무엇이, 어떤 조건으로 지워졌는지" 확인 가능.

**④ 과제 원문**
> 조건 없이 삭제하지 않도록 _delete_saved_schedules(...)에서 안전 규칙을 확인합니다. deleted_count, filters, deleted를 유지해야 trace에서 무엇이 지워졌는지 확인할 수 있습니다.

---

### 2.6 Week1 호환 생성 — `personal_create_schedule` + `structured_request_from_week01_schedule`(추가)

**① 쉽게 말하면**
Week1의 "일정 생성"을 **이름 그대로 유지하되, 이제는 임시 메모리 + 창고(SQLite) 둘 다에 기록**하는 이중 기록. 옛 손님(Week1 방식)이 와도 창고에 남게 된다.

**② 코드**
```python
def structured_request_from_week01_schedule(schedule):
    end_time = schedule.get("end_time")
    if end_time in (None, "", "미정"):
        end_time = None
    return SaveStructuredRequestInput(kind="personal_schedule", title=schedule.get("title"), date=schedule.get("date"),
        start_time=schedule.get("start_time"), end_time=end_time,
        members=schedule.get("attendees") or [], original_text=schedule.get("title") or "",
        source_schedule_id=schedule.get("id"))            # attendees→members, id→source_schedule_id

@tool("personal_create_schedule")
def personal_create_schedule(title, date, start_time, end_time="미정", attendees=None):
    created = json.loads(week01_personal_create_schedule.invoke({...}))     # ① Week1 임시 생성
    save_input = structured_request_from_week01_schedule(created.get("created_schedule", {}))
    sqlite_save = _store().save_structured_request(save_input.model_dump(exclude_none=True))  # ② SQLite 저장
    return json_payload({**created, "structured_request": save_input.model_dump(), "sqlite_save": sqlite_save})
```

**③ 구현 의도**
- `week03_tools()`가 Week1의 생성 도구를 **이 버전으로 교체**한다. Week1 버전은 임시 메모리만 남겼지만, Week3 취지(기록장)에 맞게 **DB 저장까지** 하도록 감쌌다.
- 변환 함수는 Week1 필드명을 Week3 스키마로 매핑한다: `attendees`→`members`, `id`→`source_schedule_id`.

**④ 과제 원문**
> Week 1과 같은 이름을 유지하면서 임시 일정 생성 결과를 SQLite에도 저장하는 이중 기록 tool입니다. week01_personal_create_schedule 결과를 structured_request_from_week01_schedule()로 변환해 저장합니다.

**✳️ 내 판단 (범위 밖·소소한 정규화)** — `end_time "미정" → None`
과제는 "attendees/id 변환"만 지시했다. 그런데 Week1의 `end_time` 기본값은 `"미정"`(시각이 아닌 한국어)이라, 그대로 저장하면 `HH:MM`을 기대하는 뒤 로직과 어긋날 수 있다. Week2에서 세운 "'미정' 같은 비-시각 값은 `None`" 규칙을 **여기서도 코드로 적용**했다(빈 문자열도 `None` 처리). 데이터 일관성을 위한 판단이다.

---

### 2.7 레거시 정규화 helper — `_save_input_from` / `save_structured_request_payload`(추가)

**① 쉽게 말하면**
agent(대화)를 거치지 않고 **코드/테스트에서 직접 저장**할 때 쓰는 뒷문. 들어온 게 dict든, JSON 문자열이든, 자연어든, Week2 객체든 **전부 하나의 저장 전표로 맞춰서** 창고에 넣는다.

**② 코드**
```python
def _save_input_from(value):
    if isinstance(value, SaveStructuredRequestInput): return value
    if isinstance(value, StructuredRequest): return SaveStructuredRequestInput.model_validate(value.model_dump())
    if isinstance(value, str):
        try: parsed = json.loads(value.strip())
        except (ValueError, TypeError): parsed = None
        if isinstance(parsed, dict): return SaveStructuredRequestInput.model_validate(parsed)
        return SaveStructuredRequestInput.model_validate(extract_structured_request(value.strip()).model_dump())  # 자연어→Week2 구조화
    if isinstance(value, dict): return SaveStructuredRequestInput.model_validate(value)
    raise RuntimeError(f"저장 입력을 해석할 수 없습니다: {type(value)!r}")

def save_structured_request_payload(request, *, store=None):
    save_input = _save_input_from(request)
    result = (store or _store()).save_structured_request(save_input.model_dump(exclude_none=True))
    return tool_result("save_structured_request", ok=True, **result)
```

**③ 구현 의도 & ✳️ 내 판단**
- 과제는 "dict/JSON/자연어를 직접 저장할 때 쓰는 helper"라고 했다. **자연어면 Week2 `extract_structured_request`로 먼저 구조화**하고, JSON/ dict면 스키마 검증, 이미 객체면 그대로 — 이렇게 입력 형태별 분기를 내가 설계했다.
- 예상 못 한 타입은 `raise`로 조기 차단(Week2 `_coerce`와 같은 fail-fast 철학).

**④ 과제 원문**
> _save_input_from / save_structured_request_payload는 tool 없이 dict/JSON/자연어를 직접 저장할 때 쓰는 helper입니다. 자연어 문자열이 들어오면 Week 2 extract_structured_request(...)로 먼저 구조화합니다.

---

### 2.8 프롬프트 & agent — `week03_prompt_parts` / `build_week03_agent`

**① 쉽게 말하면**
Week2 매뉴얼 위에 **"이제 창고에 저장한다"는 새 규칙**을 얹고, 그 규칙대로 일하는 직원(agent)을 배치한다.

**② 코드**
```python
def week03_prompt_parts():
    return [*week02_prompt_parts(), SQLITE_MEMORY_PROMPT, WEEK03_TOOL_CALL_PROMPT,
            f"[Week3] 오늘 날짜 기준은 {current_app_date_iso()}이다. 이번 주차 범위는 ... 저장/조회/수정/삭제다. ..."]

def build_week03_agent():
    if not CONFIG.has_openai_key: raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK03_AGENT
    if _WEEK03_AGENT is None:
        _WEEK03_AGENT = create_agent(model=chat_model(), tools=week03_tools(), system_prompt=week03_system_prompt())
    return _WEEK03_AGENT
```

**③ 구현 의도**
- `SQLITE_MEMORY_PROMPT`(영속 저장 규칙) + `WEEK03_TOOL_CALL_PROMPT`(구조화→저장→조회→수정→삭제 순서) + 오늘 날짜/범위 안내를 Week2 프롬프트 위에 누적.
- **`response_format`을 걸지 않는다** (Week2와의 차이). Week2는 최종 답을 스키마로 강제했지만, Week3 agent는 **도구를 호출해 저장/조회하고 최종 답은 자연어**로 한다.

**④ 과제 원문**
> Week 3 agent가 "구조화 후 저장" 흐름을 따르도록 system prompt를 조립합니다. Week 1~3 tool을 가진 agent를 한 번만 만들고 재사용합니다.

---

## 2-Q. 코드 공부 보충 (구현 후 한 줄씩 파고든 Q&A)

> 구현을 마친 뒤 코드를 한 줄씩 뜯어보며 헷갈렸던 부분을 문답으로 정리했다. (2.1~2.5 심화)

### (2.1) `unwrap_legacy_payload` — `value`의 정체와 분기
- `model_validator(mode="before")`라 `value`는 **검증 전 날것의 입력**이다: `dict`일 수도, `StructuredRequest` 객체일 수도, 그 외일 수도 있다. 그래서 `isinstance`로 타입을 먼저 확인한다.
- `if isinstance(value, StructuredRequest): return value.model_dump()` — 입력이 **객체**면 dict로 바꿔서 넘긴다. (객체엔 `value["키"]` 대괄호 접근이 안 되니까 먼저 dict화)
- `return value["structured_request"]` — 입력이 **wrapper dict**(`{"structured_request": {...}}`)면 **알맹이만** 꺼낸다. 이 줄은 `if isinstance(value, dict):` **안**이라 value가 dict임이 이미 확정 → 대괄호 인덱싱이 안전하다.
- 세 경우: ①평범한 dict→그대로 ②wrapper→알맹이 ③객체→`model_dump()`. 즉 **"무엇이 오든 평평한 dict로 통일"하는 전처리기**.

### (2.2) `save_structured_request`는 Week2에 없던 **새 함수** + "직접 저장 안 함"의 뜻
- Week2엔 저장 함수가 없다. **재사용된 건 함수가 아니라 스키마(필드)** — `SaveStructuredRequestInput(StructuredRequest)` 상속으로 필드를 물려받았을 뿐, 저장 행동(SQLite)은 Week3에서 새로 짠 것이다.
- "자연어 문자열이나 ok/tool_name/base_date wrapper를 직접 저장하지 않는다" = DB엔 **구조화 필드(kind/title/date…)만** 넣고, **원문 문장**이나 도구 응답 **봉투**(`{ok, tool_name, base_date, structured_request}`)를 통째로 넣지 않는다는 뜻. `args_schema`가 구조화 필드만 받게 돼 있어 구조적으로 강제된다.

### (payload 정리 & `_store`)
- `payload = {k: v for k, v in payload.items() if v is not None}` — **None인 칸만 제외**한다(빈 문자열 `""`·빈 리스트 `[]`·`0`은 남긴다). 안 채운 필드를 DB에 안 넣으려는 것.
- `_store()` = `AppSQLiteStore(CONFIG.app_db_path)`를 만들어 돌려주는 **팩토리**. 도구는 이걸 불러 SQL을 시키는 **얇은 입구**일 뿐, 실제 SQL은 store가 실행한다.

### (2.3) 조회는 왜 3개인가 + 누가 DB를 읽나
- 저장이 **두 테이블**로 나뉜다: `structured_requests`(원본 요청 "대장", 모든 kind) / `schedules`(정리된 "일정 선반", 개인·그룹 일정). 그래서 조회도 **대상(대장 vs 선반) × 방식(목록 vs 단건)**으로 갈린다.
  - `list_saved_requests` = 대장 목록, `get_saved_request` = 대장 단건, `personal_list_saved_schedules` = 선반(일정) 목록.
- **DB를 실제로 읽는 건 `AppSQLiteStore`(SQL 실행)이지 LLM이 아니다.** LLM은 ①어떤 도구를 부를지 결정 → ②도구가 돌려준 JSON을 읽고 → ③자연어 최종 답을 작성한다. LLM은 SQL 권한이 없어 DB에 직접 접근하지 못한다.
- 흐름상 위치: **저장 다음 단계**이자 **수정/삭제의 앞단**(먼저 목록에서 `schedule_id`를 확인한 뒤 고치거나 지운다).
- `effective_kind = kind or "personal_schedule"` — 종류를 안 밝히면 개인 일정을 기본으로 조회한다.

### (2.4) `shared_sync`는 어디서 오나
- 우리 week03 코드가 만들지 않는다. store의 `update_schedule`(및 save)이 `sync_personal_schedule_to_shared(...)` 등으로 **외부 공유 저장소 동기화**를 수행하고 그 결과를 돌려주며, week03 도구는 그걸 **응답에 그대로 전달(투명 보고)**만 한다. (`.get("schedule")`/`.get("shared_sync")`는 store 반환 dict에서 두 조각을 안전하게 꺼내는 것)

### (2.5) 삭제 guard의 실제 동작
- "그냥 삭제해줘"처럼 **대상이 없으면** `has_condition=False`라 store를 아예 안 부르고 `ok=False`로 **거절**한다.
- "오늘 회의 삭제"→필터 삭제, "전부 삭제"→`delete_all=True`를 명시할 때만 전체 삭제.
- `filters`/`deleted_count`/`deleted`는 안전장치가 아니라 **"무엇을 지웠는지 남기는 기록"**이다(되돌리기 어려운 삭제라 흔적을 남긴다).

---

## 3. 검증 방법 (액티브)

**실제 실행(메인 정식 검증)**: `./run.sh --week3`(Windows는 `KANANA_ACTIVE_WEEK=3` + `uv run python app.py`)
1. `내일 10시 개인 코칭 저장해줘` → trace에서 `extract_schedule_request` → `save_structured_request` 확인.
2. `내 일정 보여줘` → `personal_list_saved_schedules` 조회.
3. **앱 재시작/새 대화**에도 저장 유지되면 메인 통과.
4. (추가) 저장 후 `수정`/`삭제`로 `personal_update_saved_schedule`/`personal_delete_saved_schedules` 확인.

**오프라인(LLM 불필요, 이미 통과)**: 가짜 store로 각 tool을 직접 호출해 검증 — 저장 payload에서 `None` 제외됨, 조회 `rows=[]`/`row=None` 유지, 삭제 **조건 없으면 `ok=False`**·필터삭제·전체삭제, 수정 성공/없음(`ok=False`), Week1 변환(`attendees→members`, `'미정'→None`), 호환 생성이 임시+SQLite 이중 기록. 전부 통과.

**실행 검증 결과 (라이브, 2026-07-15)**: 실제 앱(`KANANA_ACTIVE_WEEK=3`)으로 전 기능을 확인했다.
- **저장**: "내일 10시 개인 코칭 저장해줘" → trace에서 `extract_schedule_request` → `save_structured_request` 순서로 호출, `schedules` 테이블 저장(`sch_...`) + `shared_sync` 성공.
- **조회**: "내 일정 보여줘" → `personal_list_saved_schedules`(SQLite)로 저장분 정상 조회. (초기엔 LLM이 Week1 임시 도구 `personal_list_schedules`를 골라 빈 목록이 나왔고, ADR-4 수정 후 올바른 도구를 사용하게 됨)
- **수정**: "방금 작업 12시로 바꿔줘" → `personal_update_saved_schedule`로 시작 시간 12:00 변경 확인.
- **삭제**: "개인 코칭 일정 다 지워줘" → `personal_delete_saved_schedules`로 3건 삭제 확인.
- **관찰**: 같은 문장을 여러 번 저장하면 매번 새 row가 생긴다(중복). dedup을 하지 않기 때문이며 정상 동작이다(→ ADR-5).

---

## 4. ADR — 설계 결정 기록

> 형식: 배경 → 결정 → 결과.

### ADR-1. tool은 "얇은 입구", 검증은 스키마·저장은 store
- **배경**: 저장/조회/수정/삭제마다 입력 검증 + SQL 접근이 필요하다.
- **결정**: 입력 검증은 `@tool(args_schema=...)`(Pydantic)에 맡기고, SQL은 `AppSQLiteStore`에 맡긴다. tool 본문은 **인자 정리 + store 호출 + 응답 포장**만 한다.
- **결과**: 각 tool이 짧고 일관됨. 검증·SQL 로직 중복이 없다. (과제 지시와도 일치)

### ADR-2. 삭제는 조건이 있을 때만 (안전 guard)
- **배경**: 삭제는 되돌리기 어렵고, 조건 없는 삭제는 전체 삭제 사고로 이어질 수 있다.
- **결정**: `_delete_saved_schedules`에서 조건(ids/필터/`delete_all`)이 하나도 없으면 **거부(`ok=False`)**. 전체 삭제는 `delete_all=True`를 명시할 때만.
- **결과**: 실수로 전부 지우는 사고 방지. 삭제 규칙이 한 함수에 모여 tool/헬퍼가 공유.

### ADR-3. 응답 포맷 통일 (ok/tool_name + 목적별 키)
- **배경**: 도구가 많고, trace에서 결과를 알아봐야 한다.
- **결정**: 모든 `@tool`은 JSON 문자열로, `ok`/`tool_name` 기본 + 조회 `rows`/`row`, 삭제 `deleted_count`/`filters`/`deleted`, 저장/수정은 결과·`shared_sync`를 담는다. `json_payload`/`tool_result` helper로 반복 제거.
- **결과**: 응답 모양이 예측 가능하고 trace 해석이 쉬움. (과제 반환 규칙과 일치)

---

### ADR-4. Week1 임시 조회/삭제 도구를 Week3에서 노출하지 않음 (스캐폴드 의도적 수정)
- **배경**: 제공된 `week03_tools()`는 Week1의 `personal_create_schedule`만 Week3 버전으로 교체하고, `personal_list_schedules`·`personal_delete_schedule`(임시 메모리용)은 **그대로 노출**했다. 실제 실행에서 "내일 10시 개인 코칭 저장"은 SQLite에 저장됐는데, "내 일정 보여줘"에서 LLM이 **임시 메모리 조회 도구(`personal_list_schedules`)**를 골라 빈 목록을 반환하는 혼선이 발생했다(저장=SQLite / 조회=임시 메모리 불일치).
- **결정**: `week03_tools()`를 수정해 Week1 임시 조회/삭제 도구를 **노출에서 제외**하고, 생성(Week1 호환, 임시+SQLite 이중 기록) + SQLite 조회/수정/삭제 도구만 공개했다. 사용하지 않게 된 `week01_tools` import도 제거.
- **결과**: 이름 충돌(`personal_list_schedules` vs `personal_list_saved_schedules`)이 사라져 LLM이 항상 SQLite 기반 도구를 사용 → "저장 후 조회"가 일관되게 동작.
- **비고**: 이는 제공된 `week03_tools()` 조립 로직을 **의도적으로 바꾼 것**이다. Week3부터 정본 저장소가 SQLite이고 임시 메모리 조회/삭제는 6주 프로젝트에선 사실상 죽은 경로라, 프롬프트로 우회하기보다 도구 노출 자체를 정리하는 편이 근본적이라 판단했다.

### ADR-5. 동일 일정 중복 저장은 막지 않음 (dedup 미적용)
- **배경**: 실행 테스트에서 "내일 10시 개인 코칭 저장"을 여러 번 부르니 동일 내용의 일정 row가 여러 개(3건) 쌓였다.
- **결정**: 각 저장 요청을 독립된 행위로 보고 **매 요청마다 새 row를 만든다.** 같은 제목/날짜/시간이라도 자동 병합(dedup)하지 않는다.
- **결과**: 과제 범위(저장/조회/수정/삭제)에 부합하고 로직이 단순. 중복은 삭제 도구로 정리 가능.
- **비고**: dedup(같은 키 upsert)은 "무엇을 같은 일정으로 볼지"라는 정책 결정이 필요한 별도 기능이라 이번 범위 밖으로 두었다. 필요하면 이후 주차에 "같은 날짜+시간+제목이면 갱신" 규칙을 추가할 수 있다.

## 5. 용어 정리 (이번 주 새로 나온 것)

- **`@tool(args_schema=X)`**: LangChain이 도구 호출 입력을 Pydantic 스키마 `X`로 **먼저 검증**한 뒤 함수를 부르게 하는 설정. 본문에선 검증이 끝난 값만 받는다.
- **`model_validator(mode="before")`**: Pydantic이 **필드 검증 전에** 원본 입력을 손보는 훅(여기선 wrapper 벗기기).
- **상속(`class SaveStructuredRequestInput(StructuredRequest)`)**: Week2 스키마의 필드를 그대로 물려받고 일부만 추가/재정의.
- **`model_dump(exclude_none=True)`**: 모델을 dict로 변환하되 `None` 필드는 뺀다(저장 payload 정리용).
- **SQLite / 영속(persistent) 저장**: 파일 기반 DB. 프로세스가 꺼져도 데이터가 남아 새 대화·재시작에도 조회된다(Week1 임시 메모리와 반대).
- **`shared_sync`**: 개인/그룹 일정을 외부 공유 저장소에 복사·동기화한 결과.
