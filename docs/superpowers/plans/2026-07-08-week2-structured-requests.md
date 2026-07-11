# Week 2 자연어 요청 구조화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `student_parts/week02_structure_natural_language_requests.py`의 메인과제(스키마 + agent 세로 슬라이스)와 심화과제(bridge 함수 3개)를 구현해서, `./run.sh --week2`에서 자연어/Week1 tool JSON을 `StructuredRequestBatch`로 구조화하는 agent가 동작하게 한다.

**Architecture:** Pydantic 스키마(`StructuredRequest`/`StructuredRequestBatch`) 위에 `create_agent(..., response_format=StructuredRequestBatch)`로 구조화 agent를 만들고(메인과제), 그 아래 Week 3+가 재사용할 순수 함수형 bridge 3개(`_coerce_structured_request` → `extract_structured_request` → `extract_schedule_request`)를 쌓는다(심화과제). 시스템 프롬프트는 few-shot 예시 2개를 포함한다(다중 의도 분리, Week1 tool JSON 변환).

**Tech Stack:** Python 3.11, LangChain (`langchain.agents.create_agent`, `langchain.tools.tool`), Pydantic v2 (`BaseModel`), `langchain_openai.ChatOpenAI`(`fixed/llm.py`의 `chat_model()` 경유), `uv` 패키지 매니저.

## Global Constraints

- 수정 파일은 `student_parts/week02_structure_natural_language_requests.py` 단 하나. `fixed/`는 수정하지 않는다.
- 이 리포지토리에는 자동 테스트 하니스가 없다(README 명시). 각 태스크의 "테스트"는 `uv run python -c "..."` 스크립트로 대체한다.
- 커밋 시 항상 파일을 명시적으로 지정해 `git add`한다 (`git add -A`/`git add .` 금지 — 과거 CRLF·무관 파일 혼입 사고 재발 방지).
- Task 2, 4, 5, 6은 실제 LLM 호출이 필요하다. 시작 전에 `.env`에 `PROXY_TOKEN`이 설정되어 있는지 확인한다: `test -f .env && grep -q PROXY_TOKEN .env && echo "OK: PROXY_TOKEN 설정됨"`.
- 작업 브랜치는 `kimdaewon/week2`. 시작 전 확인: `git branch --show-current` → `kimdaewon/week2`가 출력되어야 한다.
- 커밋 메시지는 스펙(`docs/superpowers/specs/2026-07-08-week2-structured-requests-design.md`)에 명시된 문구를 그대로 사용한다.

---

### Task 1: `StructuredRequest` / `StructuredRequestBatch` 스키마 정의

**Files:**
- Modify: `student_parts/week02_structure_natural_language_requests.py:154-172`

**Interfaces:**
- Consumes: 없음 (파일 최상단에 이미 있는 `RequestKind`, `current_app_date_iso` 사용)
- Produces: `StructuredRequest(kind, title, date, start_time, end_time, members, priority, reason, original_text)`, `StructuredRequestBatch(requests: list[StructuredRequest], base_date: str)` — 이후 모든 태스크가 이 두 클래스를 그대로 가져다 쓴다.

- [ ] **Step 1: 검증 스크립트 작성 (아직 실패해야 정상)**

```bash
uv run python -c "
from student_parts.week02_structure_natural_language_requests import StructuredRequest, StructuredRequestBatch

r = StructuredRequest(kind='personal_schedule', title='테스트')
assert r.date is None
assert r.members == []
assert r.original_text == ''

batch = StructuredRequestBatch(requests=[r])
assert len(batch.requests) == 1
assert isinstance(batch.base_date, str) and len(batch.base_date) == 10

print('OK: schema smoke test passed')
"
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: 위 명령 그대로 실행
Expected: FAIL (`AttributeError: 'StructuredRequest' object has no attribute 'date'` 또는 유사한 오류) — 현재 두 클래스 본문이 `...`뿐이라 필드가 없기 때문.

- [ ] **Step 3: 스키마 구현**

`student_parts/week02_structure_natural_language_requests.py:154-172`을 아래로 교체:

```python
class StructuredRequest(BaseModel):
    """LLM structured output으로 추출되는 2주차 요청 스키마입니다."""

    kind: RequestKind = Field(description="요청 종류: personal_schedule/group_schedule/todo/reminder/unknown 중 하나")
    title: str | None = Field(default=None, description="일정 또는 할 일의 제목")
    date: str | None = Field(default=None, description="YYYY-MM-DD 형식. 확실할 때만 채운다")
    start_time: str | None = Field(default=None, description="HH:MM 형식. 확실할 때만 채운다")
    end_time: str | None = Field(default=None, description="HH:MM 형식. 확실할 때만 채운다")
    members: list[str] = Field(default_factory=list, description="참석자 또는 관련 인물 목록. 모르면 빈 리스트")
    priority: str | None = Field(default=None, description="할 일의 우선순위")
    reason: str | None = Field(default=None, description="이 kind/필드로 판단한 근거")
    original_text: str = Field(default="", description="사용자가 입력한 원문 또는 원본 JSON 문자열")


class StructuredRequestBatch(BaseModel):
    """여러 자연어 의도를 StructuredRequest 목록으로 나누는 메인과제 스키마입니다."""

    requests: list[StructuredRequest] = Field(default_factory=list, description="분리된 StructuredRequest 목록")
    base_date: str = Field(
        default_factory=current_app_date_iso,
        description="상대 날짜 표현을 해석하는 기준일(YYYY-MM-DD)",
    )
```

- [ ] **Step 4: 실행해서 통과 확인**

Run: Step 1과 동일한 명령
Expected: `OK: schema smoke test passed` 출력, 에러 없음

- [ ] **Step 5: 커밋**

```bash
git add student_parts/week02_structure_natural_language_requests.py
git commit -m "week2: StructuredRequest/StructuredRequestBatch 스키마 정의"
```

---

### Task 2: Agent 세로 슬라이스 연결 (`week02_tools`/`week02_system_prompt`/`week02_prompt_parts`/`build_week02_agent`)

**Files:**
- Modify: `student_parts/week02_structure_natural_language_requests.py:203-239`

**Interfaces:**
- Consumes: `StructuredRequest`/`StructuredRequestBatch` (Task 1), `week01_prompt_parts()`/`week01_tools()`(이미 import됨), `current_app_date_iso()`(이미 import됨), `CONFIG`/`chat_model`/`create_agent`(이미 import됨)
- Produces: `week02_prompt_parts() -> list[str]`, `week02_system_prompt() -> str`, `week02_tools() -> list[Any]`, `build_week02_agent() -> object` (agent의 `.invoke({"messages": [...]})` 결과 dict에 `"structured_response"` 키로 `StructuredRequestBatch` 반환) — Task 4가 `week02_prompt_parts()`를 그대로 재사용한다.

- [ ] **Step 1: 검증 스크립트 작성 (아직 실패해야 정상)**

```bash
uv run python -c "
from student_parts.week02_structure_natural_language_requests import build_week02_agent

agent = build_week02_agent()
result = agent.invoke({'messages': [('user', '다음 주 화요일 오후 3시에 철수랑 회의 잡고, 어제 낸 과제 리마인더도 추가해줘')]})
batch = result['structured_response']
print(batch)
assert len(batch.requests) == 2
kinds = {r.kind for r in batch.requests}
assert 'group_schedule' in kinds
assert 'reminder' in kinds
print('OK: week02 agent 다중 의도 분리 검증 통과')
"
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: 위 명령 그대로 실행
Expected: FAIL (`AttributeError: 'NoneType' object has no attribute 'invoke'`) — `build_week02_agent()`가 현재 `...`만 있어 암묵적으로 `None`을 반환하기 때문.

- [ ] **Step 3: 구현**

`student_parts/week02_structure_natural_language_requests.py:203-239`를 아래로 교체:

```python
def week02_tools() -> list[Any]:
    """Week 2 agent에 Week 1 도구를 노출해 tool JSON을 structured_response 근거로 씁니다."""

    return week01_tools()


def week02_system_prompt() -> str:
    """2주차 agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt(week02_prompt_parts())


def week02_prompt_parts() -> list[str]:
    """2주차 structured output agent가 따르는 system prompt 조각입니다."""

    return [
        *week01_prompt_parts(),
        (
            "너는 이제 자연어 요청이나 Week 1 tool이 반환한 JSON을 StructuredRequestBatch로 "
            "구조화하는 역할도 겸한다. "
            f"오늘 날짜는 {current_app_date_iso()}이며, 상대 날짜(예: 내일, 다음 주 화요일)는 "
            "이 날짜를 기준으로 계산해서 YYYY-MM-DD로 채운다. "
            "한 문장에 여러 의도(예: 일정과 리마인더)가 섞여 있으면 각각을 별도의 StructuredRequest로 "
            "나눠 requests 목록에 모두 담는다. "
            "Week 1 tool의 created_schedule JSON을 입력으로 받은 경우에는 tool을 다시 호출하지 않고 "
            "그 필드를 그대로 읽어 StructuredRequest로 옮긴다. "
            "값이 확실하지 않으면 억지로 채우지 말고 None 또는 빈 리스트로 둔다. "
            "Week 2는 SQLite 저장, RAG 조회, 외부 멤버 일정 조율을 하지 않는다."
        ),
        (
            "예시 1) 입력: \"다음 주 화요일 오후 3시에 철수랑 회의 잡고, 어제 낸 과제 리마인더도 추가해줘\"\n"
            "출력은 requests에 2개를 담는다:\n"
            "  1) kind=group_schedule, title=\"회의\", "
            "date=<다음 주 화요일을 오늘 날짜 기준으로 계산한 YYYY-MM-DD>, "
            "start_time=\"15:00\", members=[\"철수\"], original_text=위 문장\n"
            "  2) kind=reminder, title=\"과제 리마인더\", date=None, members=[], original_text=위 문장\n"
            "(위 날짜 값은 형식을 보여주는 예시일 뿐이며, 실제 응답에서는 항상 위에서 안내한 오늘 날짜를 "
            "기준으로 새로 계산한다.)\n\n"
            "예시 2) 입력이 Week 1 personal_create_schedule 결과 JSON인 경우 "
            "(예: {\"ok\": true, \"tool_name\": \"personal_create_schedule\", \"created_schedule\": "
            "{\"title\": \"운동\", \"date\": \"2026-07-10\", \"start_time\": \"07:00\"}}):\n"
            "출력은 requests에 1개만 담는다:\n"
            "  kind=personal_schedule, title=\"운동\", date=\"2026-07-10\", start_time=\"07:00\", "
            "original_text=입력 JSON 문자열 그대로\n"
            "(tool을 다시 호출하지 않고 created_schedule 필드를 그대로 옮긴 것에 주의한다. "
            "이 예시의 날짜도 형식 예시일 뿐이다.)"
        ),
    ]


def build_week02_agent() -> object:
    """Week 2 대화에서 structured_response를 직접 반환하는 단일 LangChain agent를 만듭니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK02_AGENT
    if _WEEK02_AGENT is None:
        _WEEK02_AGENT = create_agent(
            model=chat_model(),
            tools=week02_tools(),
            response_format=StructuredRequestBatch,
            system_prompt=week02_system_prompt(),
        )
    return _WEEK02_AGENT
```

- [ ] **Step 4: 실행해서 통과 확인**

Run: Step 1과 동일한 명령
Expected: `OK: week02 agent 다중 의도 분리 검증 통과` 출력.
LLM 응답이라 결과가 100% 결정적이지 않을 수 있다. `requests`가 2개가 아니거나 `kind` 분류가 다르면, 코드 버그가 아니라 few-shot 프롬프트 문구를 더 명확히 다듬어야 한다는 신호로 본다 — 어설션을 느슨하게 바꾸지 말고 프롬프트를 고친다.

- [ ] **Step 5: 커밋**

```bash
git add student_parts/week02_structure_natural_language_requests.py
git commit -m "week2: agent 세로 슬라이스 연결 (tools/prompt/build_week02_agent, few-shot 예시 포함)"
```

---

### Task 3: `_coerce_structured_request` 구현 (심화)

**Files:**
- Modify: `student_parts/week02_structure_natural_language_requests.py:175-181`

**Interfaces:**
- Consumes: `StructuredRequest`(Task 1)
- Produces: `_coerce_structured_request(value: Any) -> StructuredRequest` — Task 4가 이 함수를 그대로 호출한다.

- [ ] **Step 1: 검증 스크립트 작성 (아직 실패해야 정상)**

```bash
uv run python -c "
from student_parts.week02_structure_natural_language_requests import _coerce_structured_request, StructuredRequest

r = StructuredRequest(kind='personal_schedule', title='회의')
assert _coerce_structured_request(r) is r

d = {'kind': 'todo', 'title': '과제'}
coerced = _coerce_structured_request(d)
assert isinstance(coerced, StructuredRequest)
assert coerced.title == '과제'

try:
    _coerce_structured_request(123)
    raise AssertionError('RuntimeError를 기대했지만 발생하지 않음')
except RuntimeError:
    pass

print('OK: _coerce_structured_request 검증 통과')
"
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: 위 명령 그대로 실행
Expected: FAIL (`AssertionError` at `assert _coerce_structured_request(r) is r`) — 함수 본문이 `...`뿐이라 `None`을 반환하기 때문.

- [ ] **Step 3: 구현**

`student_parts/week02_structure_natural_language_requests.py:175-181`을 아래로 교체:

```python
def _coerce_structured_request(value: Any) -> StructuredRequest:
    """LangChain structured output 결과를 StructuredRequest로 정규화합니다."""

    if isinstance(value, StructuredRequest):
        return value
    if isinstance(value, dict):
        return StructuredRequest.model_validate(value)
    raise RuntimeError(f"예상치 못한 structured output 타입: {type(value)!r}")
```

- [ ] **Step 4: 실행해서 통과 확인**

Run: Step 1과 동일한 명령
Expected: `OK: _coerce_structured_request 검증 통과` 출력, 에러 없음

- [ ] **Step 5: 커밋**

```bash
git add student_parts/week02_structure_natural_language_requests.py
git commit -m "week2(심화): _coerce_structured_request 구현"
```

---

### Task 4: `extract_structured_request` 구현 (심화)

**Files:**
- Modify: `student_parts/week02_structure_natural_language_requests.py:184-190`

**Interfaces:**
- Consumes: `_coerce_structured_request`(Task 3), `week02_prompt_parts()`(Task 2), `join_system_prompt`(이미 import됨), `chat_model()`(이미 import됨)
- Produces: `extract_structured_request(text: str) -> StructuredRequest` — Task 5가 이 함수를 호출한다.

- [ ] **Step 1: 검증 스크립트 작성 (아직 실패해야 정상)**

```bash
uv run python -c "
from student_parts.week02_structure_natural_language_requests import extract_structured_request

result = extract_structured_request('내일 오후 2시에 병원 예약 잡아줘')
print(result)
assert result.start_time == '14:00'
print('OK: extract_structured_request 검증 통과')
"
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: 위 명령 그대로 실행
Expected: FAIL (`AttributeError: 'NoneType' object has no attribute 'start_time'`) — 함수가 `...`만 있어 `None`을 반환하기 때문.

- [ ] **Step 3: 구현**

`student_parts/week02_structure_natural_language_requests.py:184-190`을 아래로 교체:

```python
def extract_structured_request(text: str) -> StructuredRequest:
    """Week 3 이상에서 agent를 새로 띄우지 않고 자연어를 StructuredRequest로 바꿉니다."""

    structured_llm = chat_model().with_structured_output(StructuredRequest, method="function_calling")
    result = structured_llm.invoke(
        [("system", join_system_prompt(week02_prompt_parts())), ("user", text)]
    )
    return _coerce_structured_request(result)
```

- [ ] **Step 4: 실행해서 통과 확인**

Run: Step 1과 동일한 명령
Expected: `OK: extract_structured_request 검증 통과` 출력.
LLM 응답이므로 `start_time`이 `'14:00'`이 아니게 나오면, 프롬프트의 시간 지시 문구를 점검할 신호로 본다.

- [ ] **Step 5: 커밋**

```bash
git add student_parts/week02_structure_natural_language_requests.py
git commit -m "week2(심화): extract_structured_request 구현"
```

---

### Task 5: `extract_schedule_request` bridge tool 구현 (심화)

**Files:**
- Modify: `student_parts/week02_structure_natural_language_requests.py:193-200`

**Interfaces:**
- Consumes: `extract_structured_request`(Task 4), `current_app_date_iso()`(이미 import됨), `json`(이미 import됨), `@tool`(이미 import됨)
- Produces: `extract_schedule_request` — LangChain `@tool`, `.invoke({"query": str}) -> str`(JSON 문자열, 키: `ok`/`tool_name`/`base_date`/`structured_request`). 이 파일의 마지막 구현 대상이며 이후 태스크는 없다.

- [ ] **Step 1: 검증 스크립트 작성 (아직 실패해야 정상)**

```bash
uv run python -c "
from student_parts.week02_structure_natural_language_requests import extract_schedule_request
import json

raw = extract_schedule_request.invoke({'query': '내일 오후 2시에 병원 예약 잡아줘'})
payload = json.loads(raw)
assert payload['ok'] is True
assert payload['tool_name'] == 'extract_schedule_request'
assert 'base_date' in payload and len(payload['base_date']) == 10
assert 'structured_request' in payload
assert payload['structured_request']['start_time'] == '14:00'
print('OK: extract_schedule_request 검증 통과')
"
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: 위 명령 그대로 실행
Expected: FAIL (`json.decoder.JSONDecodeError` 또는 `TypeError`) — 함수가 `...`만 있어 `None`을 반환하고 `json.loads(None)`이 실패하기 때문.

- [ ] **Step 3: 구현**

`student_parts/week02_structure_natural_language_requests.py:193-200`을 아래로 교체:

```python
@tool
def extract_schedule_request(query: str) -> str:
    """Week 3 이상 agent가 저장/조율 전에 호출하는 구조화 bridge tool입니다."""

    request = extract_structured_request(query)
    return json.dumps(
        {
            "ok": True,
            "tool_name": "extract_schedule_request",
            "base_date": current_app_date_iso(),
            "structured_request": request.model_dump(),
        },
        ensure_ascii=False,
    )
```

- [ ] **Step 4: 실행해서 통과 확인**

Run: Step 1과 동일한 명령
Expected: `OK: extract_schedule_request 검증 통과` 출력.

- [ ] **Step 5: 커밋**

```bash
git add student_parts/week02_structure_natural_language_requests.py
git commit -m "week2(심화): extract_schedule_request bridge tool 구현"
```

---

### Task 6: 최종 통합 검증 (수동, 사람이 직접 — 에이전트가 대신할 수 없음)

**Files:** 없음 (코드 변경 없음)

**Interfaces:** 없음 — Task 1~5로 완성된 `./run.sh --week2` 앱을 브라우저로 직접 확인하는 단계.

이 단계는 Gradio 웹 UI를 눈으로 보고 클릭/타이핑해야 하므로 에이전트가 자동화할 수 없다. 사람이 직접 수행한다.

- [ ] **Step 1: 앱 실행**

Run: `./run.sh --week2`
Expected: 터미널에 Gradio 로컬 URL(예: `http://127.0.0.1:7860`)이 출력됨

- [ ] **Step 2: 다중 의도 문장 테스트**

브라우저에서 앱 열고 채팅에 입력: `다음 주 화요일 오후 3시에 철수랑 회의 잡고, 어제 낸 과제 리마인더도 추가해줘`
"상세" trace 탭에서 `structured_response`의 `requests`가 2개(`group_schedule` 1개, `reminder` 1개)로 나뉘는지 확인.

- [ ] **Step 3: 개인 일정 자연어 요청 테스트**

채팅에 입력: `내일 오후 2시에 병원 예약 잡아줘`
trace에서 `personal_create_schedule` tool이 호출되고, 이어서 그 `created_schedule` JSON이 `structured_response`의 `personal_schedule` 요청으로 반영되는지 확인.

- [ ] **Step 4: 완료 표시**

위 두 시나리오가 기대대로 동작하면 Week 2 메인과제+심화과제 구현이 끝난 것이다. 별도 커밋 없음(코드 변경 없음).
