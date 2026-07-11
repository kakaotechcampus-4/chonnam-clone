# Week 2 구현 계획 — 자연어/Week1 JSON → StructuredRequest 구조화

> 대상 파일: `student_parts/week02_structure_natural_language_requests.py`
> 작업 브랜치: `junyoung/week2` (base = `junyoung/final`)
> 이 문서는 구현 전 세운 계획서다. 메인·심화 모두 구현 완료했으며, §7이 심화(bridge) 상세 계획이다.

---

## 0. 한눈에 보기

Week 1은 "이미 분해된 인자"를 받아 임시 일정을 만들었다. Week 2의 핵심은 그 앞단, 즉
**사람이 쓴 자연어("다음 주 화요일 오후 3시에 철수랑 회의 잡아줘")나 Week 1 tool이 뱉은
`created_schedule` JSON을 → 앱이 저장할 수 있는 구조(`StructuredRequest`)로 변환**하는 것이다.
저장(SQLite)·RAG·외부 멤버 조율은 Week 2 범위가 아니다(그건 Week 3 이후).

```
[사용자 자연어]  ┐
                 ├─▶ Week2 agent (LLM + response_format=StructuredRequestBatch)
[Week1 tool JSON]┘         │
                          ▼
                 structured_response = StructuredRequestBatch
                 { requests:[StructuredRequest, ...], base_date }
```

추가(심화) 과제는 위 스키마를 **agent 없이도** 재사용할 수 있게 만드는 bridge 3형제
(`_coerce_structured_request` → `extract_structured_request` → `extract_schedule_request`)이다.
Week 3 이후 저장/조율 tool chain이 이 bridge를 호출한다.

---

## 1. 과제 범위

- **메인 과제 (필수)**: `StructuredRequest`, `StructuredRequestBatch` 스키마 + `week02_tools()`,
  `week02_prompt_parts()`, `week02_system_prompt()`, `build_week02_agent()` 를 완성해
  `./run.sh --week2` 가 `StructuredRequestBatch` 형태의 `structured_response`를 돌려주게 한다.
- **추가 과제 (선택)**: `_coerce_structured_request()`, `extract_structured_request()`,
  `extract_schedule_request()` bridge 함수 완성. 메인 위에 얹는 방식이라 언제 추가해도 됨.

---

## 2. 사전 확인 — 이미 검증한 연동 지점

- **Registry**: `fixed/week_agent_registry.py` 26행이 week 2 → 이 모듈로 매핑하고,
  `build_week_agent()`(파일 맨 아래, 이미 `build_week02_agent()` 호출하도록 되어 있음)를 표준 진입점으로 부른다.
- **런타임 표시**: `fixed/langchain_trace.py` 가 agent 결과에서 `result["structured_response"]`를
  읽어 최종 답변/trace로 보여준다 → 우리는 `response_format`만 제대로 걸면 됨.
- **LLM**: `fixed/llm.py`의 `chat_model()` → `ChatOpenAI`(temperature=0). `langchain>=1.0`이라
  `create_agent(..., response_format=...)` 와 `chat_model().with_structured_output(...)` 모두 지원.
- **키 가드**: `CONFIG.has_openai_key` (없으면 `RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")`).
- **기준일**: `current_app_date_iso()` (상대 날짜 해석용 base_date).
- **Week1이 제공하는 것 (import 됨)**:
  - `week01_tools()` → `[personal_create_schedule, personal_list_schedules, personal_delete_schedule]`
  - `week01_prompt_parts()` → 날짜 + Nana 페르소나 prompt 조각 list
  - `join_system_prompt(parts)` → 조각들을 누적 system prompt 문자열로 합침
  - `personal_create_schedule`의 반환 JSON `created_schedule` 필드:
    `id, title, date, start_time, end_time, attendees, created_at, session_id`

---

## 3. 구현 순서 (의존성 순 — 이 순서대로 하면 막힘 없음)

### Step 1 — `StructuredRequest` 스키마
필드(가이드 157~162행 TODO 그대로):
- `kind: RequestKind` — `Field(description=...)`. RequestKind = `personal_schedule/group_schedule/todo/reminder/unknown`.
- `title / date / start_time / end_time: str | None = None`
- `members: list[str] = Field(default_factory=list)`
- `priority / reason: str | None = None`
- `original_text: str = ""`
- 모든 필드에 **한국어 description** (LLM structured output이 필드 의미를 알아듣게).
  예: `date: "YYYY-MM-DD. 확실할 때만 채우고 모르면 None"`.

### Step 2 — `StructuredRequestBatch` 스키마
- `requests: list[StructuredRequest] = Field(default_factory=list)` — 요청이 하나여도 list 유지.
- `base_date: str = Field(default_factory=current_app_date_iso)` — 상대 날짜 기준일.
- 두 필드에 한국어 description.

### Step 3 — `week02_tools()`
- `return week01_tools()` — Week1 도구를 그대로 노출(개인 일정 생성 시 `created_schedule` JSON을 구조화 근거로 씀).

### Step 4 — `week02_prompt_parts()`
- 이미 `*week01_prompt_parts()`로 시작하도록 스캐폴드됨. 그 뒤에 조각 추가:
  1. Week2 구조화 agent 역할 + 오늘 날짜 기준(`current_app_date_iso()`).
  2. 자연어를 `kind/title/date/start_time/end_time/members ...` 필드로 구조화하라는 지시.
  3. **Week1 tool JSON을 받으면 tool을 다시 부르지 말고** payload를 읽어 structured_response로 만들라는 지시.
  4. Week2는 SQLite 저장·RAG·외부 멤버 조율을 하지 않는다고 명시.

### Step 5 — `week02_system_prompt()`
- `join_system_prompt(week02_prompt_parts())` + 최종 답변 규칙:
  - 요청이 하나여도 `requests`에 `StructuredRequest` 하나를 담아라.
  - 여러 의도가 섞이면 여러 `StructuredRequest`로 분리하라.
  - `personal_create_schedule` 결과의 `created_schedule`을 읽어 필드를 채워라.

### Step 6 — `build_week02_agent()`
- `CONFIG.has_openai_key` 없으면 `RuntimeError(...)`.
- 전역 `_WEEK02_AGENT` 재사용(없을 때만 생성).
- `create_agent(model=chat_model(), tools=week02_tools(), response_format=StructuredRequestBatch, system_prompt=week02_system_prompt())`.
- → **여기까지가 메인 과제.** `./run.sh --week2` 검증 (§5).

### Step 7 — `_coerce_structured_request(value)` *(추가)*
- `isinstance(value, StructuredRequest)` → 그대로 반환.
- `isinstance(value, dict)` → `StructuredRequest.model_validate(value)`.
- 그 외 → `raise RuntimeError(...)` (잘못된 LLM 응답을 조용히 통과시키지 않음).

### Step 8 — `extract_structured_request(text)` *(추가)*
- `llm = chat_model().with_structured_output(StructuredRequest, method="function_calling")`.
- `llm.invoke([{"role":"system", ...join_system_prompt(week02_prompt_parts())}, {"role":"user","content":text}])`.
- 결과를 `_coerce_structured_request(...)`로 정규화해 `StructuredRequest` 하나 반환.
- (agent loop를 새로 안 띄우고 LLM 한 방으로 구조화하는 bridge)

### Step 9 — `extract_schedule_request(query)` *(추가, @tool)*
- `req = extract_structured_request(query)`.
- `payload = {"ok": True, "tool_name": "extract_schedule_request", "base_date": current_app_date_iso(), "structured_request": req.model_dump()}`.
- `return json.dumps(payload, ensure_ascii=False)`.
- → **여기까지가 추가 과제.**

---

## 4. 프롬프트 설계에서 특히 신경 쓸 매핑 규칙

Week1 산출물과 Week2 스키마의 필드 이름/형식이 살짝 달라서, system prompt에 아래를 명시해야 LLM이 헷갈리지 않는다.

- `attendees`(Week1 JSON) → `members`(StructuredRequest). 이름 다름을 매핑하라고 지시.
- Week1 `end_time` 기본값이 `"미정"`인데, StructuredRequest의 `end_time`은 `HH:MM` 또는 `None`.
  → `"미정"` 같은 비-시각 값은 `None`으로 두라고 지시.
- 상대 날짜("다음 주 화요일")는 `base_date`(오늘) 기준으로 `YYYY-MM-DD`로 환산. 애매하면 `None`.
- **모르는 값을 지어내지 말 것**(None / 빈 list가 안전) — 가이드 92행 핵심 원칙.
- `kind` 판정: 개인 일정=personal_schedule, 여럿 참석/회의=group_schedule, 할 일=todo, 알림=reminder, 불명확=unknown.

---

## 5. 검증 계획

**메인 과제**
1. `.env`에 `PROXY_TOKEN` 설정 확인 (없으면 `RuntimeError`).
2. `./run.sh --week2` 실행 (Windows(PowerShell)에서는 `KANANA_ACTIVE_WEEK=2` + `uv run python app.py`로 동일 실행).
3. 테스트 입력:
   - 단일: `"다음 주 화요일 오후 3시에 철수랑 회의 잡아줘"` → `requests` 1개, kind=group_schedule, members=["철수"], date/​start_time 채워짐.
   - 복수 의도: `"내일 오전 운동하고, 금요일까지 보고서 마감 알림 걸어줘"` → `requests` 2개(todo/reminder 등)로 분리.
   - Week1 경유: 개인 일정 생성 요청 → `personal_create_schedule` 호출 후 그 `created_schedule`을 읽어 최종 batch로 변환되는지 trace 확인.
4. 최종 답변이 `StructuredRequestBatch` 형태 `structured_response`로 나오는지 확인.

**추가 과제**
- 정석 검증은 Week3 실행 후 trace에서 `extract_schedule_request` → `save_structured_request` 순서 확인인데, **Week3가 아직 없다.**
- 임시 확인: 로컬 파이썬 스니펫으로 `extract_schedule_request.invoke({"query": "..."})` 반환 JSON에 `ok/tool_name/base_date/structured_request`가 들어있는지만 확인.

---

## 6. 제출 체크리스트

- [x] 메인 6개 대상 완성
- [x] 심화 bridge 3함수 완성
- [x] `fixed/` 등 제공 코드 미수정 (week02 파일만 작업)
- [ ] 실제 실행으로 `StructuredRequestBatch` 반환 확인(단일·복수·Week1경유)
- [ ] `junyoung/week2` → base `junyoung/final`로 PR

---

## 7. 심화(추가) 과제 상세 구현 계획 — bridge 3형제

> 심화(bridge) 상세 계획. (현재 구현 완료 — 실제 코드는 대상 파일 참고)

### 7.0 심화가 뭐고 왜 필요한가 (비유)
- 메인 Week2 agent는 **대화하면서** 구조화한다(채팅 요청 → agent가 batch 반환).
- 심화 bridge는 **agent(대화 루프) 없이 함수 한 번**으로 자연어/JSON을 StructuredRequest로 바꾸는 "지름길"이다.
- 비유: 메인 agent = 상담원과 대화해 신청서 작성. bridge = **무인 키오스크**에 문장 넣으면 신청서가 바로 나옴.
- 왜? Week3 이상에서 "저장/조율 직전에 입력을 구조화"할 때 agent를 새로 띄우면 무겁다 → LLM 한 방으로 구조화하는 재사용 함수를 만들어 둔다.
- **호출 사슬(위에서 아래로 부름)**: `extract_schedule_request`(@tool, Week3가 호출) → `extract_structured_request`(LLM 호출) → `_coerce_structured_request`(결과 정규화).
- **구현은 아래에서 위로**: ①`_coerce` → ②`extract_structured_request` → ③`extract_schedule_request`.

### 7.1 `_coerce_structured_request(value)` — LLM 결과를 StructuredRequest로 정규화
- **목적**: `with_structured_output` 반환이 환경/버전에 따라 이미 `StructuredRequest` 객체일 수도, `dict`일 수도 있어서 **무엇이 오든 StructuredRequest로 통일**한다.
- **비유**: 송장이 손글씨(dict)로 오든 전산 출력(객체)으로 오든 표준 양식으로 맞춰주는 접수 데스크.
- **코드 스케치**
```python
def _coerce_structured_request(value: Any) -> StructuredRequest:
    if isinstance(value, StructuredRequest):
        return value
    if isinstance(value, dict):
        return StructuredRequest.model_validate(value)
    raise RuntimeError(f"예상치 못한 structured output 형식: {type(value)!r}")
```
- **엣지**: None·문자열 등 예상 밖이면 조용히 넘기지 말고 `RuntimeError`(잘못된 LLM 응답 조기 차단).
- **과제 원문**
  > 1. _coerce_structured_request
  >  - LangChain structured output 결과가 이미 StructuredRequest이면 그대로 반환합니다.
  >  - dict이면 StructuredRequest.model_validate(...)로 검증해 반환합니다.
  >  - 예상한 형태가 아니면 RuntimeError를 발생시켜 잘못된 LLM 응답을 조용히 통과시키지 않습니다.
- **검증**: **LLM 없이 오프라인 가능** — ①StructuredRequest 입력→그대로 ②dict 입력→검증 통과 ③이상한 값(예: `123`)→RuntimeError.

### 7.2 `extract_structured_request(text)` — agent 없이 LLM 한 방으로 구조화
- **목적**: 자연어 또는 JSON 문자열 하나를 `StructuredRequest` **하나**로 변환.
- **코드 스케치**
```python
def extract_structured_request(text: str) -> StructuredRequest:
    llm = chat_model().with_structured_output(StructuredRequest, method="function_calling")
    result = llm.invoke([
        {"role": "system", "content": join_system_prompt(week02_prompt_parts())},
        {"role": "user", "content": text},
    ])
    return _coerce_structured_request(result)
```
- **핵심/주의**
  - system 프롬프트로 `join_system_prompt(week02_prompt_parts())`를 재사용 → 메인과 **같은 매핑 규칙·날짜 기준**이 그대로 적용됨(중복 작성 X).
  - 메인 agent는 batch(여러 개)지만 bridge는 **하나만** 반환(과제 명시).
  - `with_structured_output`은 tool을 안 쓰는 순수 구조화 호출(agent loop 없음).
  - `chat_model()`이 키 없으면 이미 `RuntimeError`를 던짐 → 별도 키 가드 불필요.
- **과제 원문**
  > 2. extract_structured_request
  >  - chat_model().with_structured_output(StructuredRequest, method="function_calling")를 사용합니다.
  >  - system 메시지에는 join_system_prompt(week02_prompt_parts())를 넣고, user 메시지에는 text를 넣어 structured LLM을 호출합니다.
  >  - 자연어 또는 JSON 문자열을 StructuredRequest 하나로 검증/구조화합니다.
- **검증**: LLM 필요(라이브). PROXY_TOKEN 있는 상태에서 스니펫 호출.

### 7.3 `extract_schedule_request(query)` — Week3가 부를 @tool 래퍼
- **목적**: 위 결과를 Week3 저장 tool이 그대로 받을 수 있는 **JSON payload로 포장**.
- **코드 스케치**
```python
@tool
def extract_schedule_request(query: str) -> str:
    req = extract_structured_request(query)
    payload = {
        "ok": True,
        "tool_name": "extract_schedule_request",
        "base_date": current_app_date_iso(),
        "structured_request": req.model_dump(),
    }
    return json.dumps(payload, ensure_ascii=False)
```
- **핵심/주의**
  - `@tool` 데코레이터는 이미 붙어 있음(그대로 둠). **week02_tools()에는 넣지 않음** → 과제: "Week 2 agent에 공개되는 tool은 아닙니다".
  - `ensure_ascii=False`로 한글 안 깨지게(Week1 `_json` 관례와 동일).
  - 반환은 **문자열(JSON)** — Week1 tool 반환 규칙과 동일.
- **과제 원문**
  > 3. extract_schedule_request
  >  - extract_structured_request(query) 결과에 ok/tool_name/base_date를 붙입니다.
  >  - structured_request에는 model_dump() 결과를 넣고, json.dumps(..., ensure_ascii=False)로 반환합니다.
  >  - Week 3 이상 저장 tool이 structured_request 필드를 그대로 받을 수 있게 만듭니다.

### 7.4 검증 계획 (Week3 없이도 확인)
- **오프라인(LLM 불필요)**: `_coerce_structured_request` 3케이스를 기존 오프라인 하네스에 추가.
- **라이브(PROXY_TOKEN 필요)**: 스니펫으로 반환 JSON 형태 확인.
```python
import json
from student_parts.week02_structure_natural_language_requests import extract_schedule_request
out = extract_schedule_request.invoke({"query": "다음 주 화요일 오후 3시에 철수랑 회의 잡아줘"})
d = json.loads(out)
assert d["ok"] and d["tool_name"] == "extract_schedule_request"
assert "base_date" in d and "structured_request" in d
print(d["structured_request"])   # kind/date/members 등 채워졌는지 눈으로 확인
```
→ Week3가 없어도 반환 형태(ok/tool_name/base_date/structured_request)를 직접 확인 가능. (ADR-4 갱신: "패스" → "로컬 스니펫으로 확인")

### 7.5 리스크 / 원칙
- `with_structured_output` 반환이 환경에 따라 dict일 수 있음 → `_coerce`가 안전망 역할(그래서 먼저 만든다).
- `extract_structured_request`는 batch가 아니라 **단일** 반환 — 메인 agent와 헷갈리지 말 것.
- `fixed/` 미수정 원칙 유지(week02 파일만 작업).
