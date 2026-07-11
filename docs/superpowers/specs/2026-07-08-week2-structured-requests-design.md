# Week 2 — 자연어 요청 구조화 (`student_parts/week02_structure_natural_language_requests.py`) 설계

## Context

Week 1(`student_parts/week01_wake_up_nana.py`)에서는 LLM이 이미 분해된 인자(title/date/start_time 등)를 받아 `PERSONAL_SCHEDULES`에 임시 일정을 만드는 tool 3개를 구현했다. Week 2의 목표는 그 위에 한 단계를 더 쌓는 것이다: 사용자의 한국어 자연어 요청이나 Week 1 tool이 반환한 `created_schedule` JSON을, 이후 주차(Week 3+)의 저장/조율 로직이 읽을 수 있는 `StructuredRequestBatch`/`StructuredRequest` 스키마로 변환한다.

파일에는 이미 매우 구체적인 `[2주차 수강생 구현 가이드]` 주석(20~151행)이 있고, 과제는 두 부분으로 나뉜다.
- **메인과제**: `StructuredRequest`/`StructuredRequestBatch` 스키마 정의, `week02_tools/system_prompt/prompt_parts/build_week02_agent` 연결 — `./run.sh --week2`로 동작하는 Week 2 agent 세로 슬라이스.
- **심화과제**: `_coerce_structured_request`/`extract_structured_request`/`extract_schedule_request` — Week 3 이상이 저장 전에 재사용할 "bridge" 함수. 심화는 메인의 `StructuredRequest` 클래스에 의존하므로 메인을 먼저 구현해야 한다.

이 스펙은 메인 → 심화 순서로, 단계별 커밋과 검증을 포함해 진행 방식을 정리한다.

## 목표 상태 (완료 기준)
- `./run.sh --week2` 실행 후 자연어 요청을 입력하면 `structured_response`가 `StructuredRequestBatch` 형태로 반환된다.
- 하나의 문장에 여러 의도(예: 일정 + 리마인더)가 섞이면 여러 `StructuredRequest`로 분리된다.
- Week 1 tool의 `created_schedule` JSON을 입력으로 받으면, tool을 다시 호출하지 않고 그 필드를 그대로 옮겨 구조화한다.
- `extract_schedule_request` tool을 직접 호출하면 `ok/tool_name/base_date/structured_request` 키를 가진 JSON 문자열을 반환한다.
- 확실하지 않은 값은 `None`/빈 리스트로 남고, 억지로 채워지지 않는다.

## 스키마 설계

```python
class StructuredRequest(BaseModel):
    kind: RequestKind = Field(description="요청 종류: personal_schedule/group_schedule/todo/reminder/unknown")
    title: str | None = Field(default=None, description="일정/할 일 제목")
    date: str | None = Field(default=None, description="YYYY-MM-DD, 확실할 때만")
    start_time: str | None = Field(default=None, description="HH:MM, 확실할 때만")
    end_time: str | None = Field(default=None, description="HH:MM, 확실할 때만")
    members: list[str] = Field(default_factory=list, description="참석자/관련 인물")
    priority: str | None = Field(default=None, description="할 일 우선순위")
    reason: str | None = Field(default=None, description="이렇게 분류한 판단 근거")
    original_text: str = Field(default="", description="원문 보존")


class StructuredRequestBatch(BaseModel):
    requests: list[StructuredRequest] = Field(default_factory=list, description="분리된 요청 목록")
    base_date: str = Field(default_factory=current_app_date_iso, description="상대 날짜 해석 기준일")
```
가이드가 필드/타입/기본값을 명시하고 있어 구현 방식에 선택지가 거의 없다. `current_app_date_iso`는 이미 12행에서 import되어 있다.

## Agent 세로 슬라이스 + Few-shot 프롬프트 (채택: Approach B)

세 가지 프롬프트 접근법을 검토했다:
- **A. 최소 지시** — 스키마 `description`만 믿고 프롬프트를 짧게 유지. 구현이 빠르지만 다중 의도 문장에서 분리가 불안정할 위험.
- **B. Few-shot 예시 포함 (채택)** — 프롬프트에 입력→출력 예시 2개를 명시적으로 포함. 정확도가 가장 안정적.
- **C. 규칙 기반 상세 지시(예시 없음)** — 기존 Week 1 스타일과는 가장 일관되지만 다중 의도 분리 정확도가 B보다 낮을 수 있음.

사용자가 **B(Few-shot)**를 선택했다. `week02_prompt_parts()`는 `week01_prompt_parts()`를 이어받은 뒤 아래를 추가한다:
1. 역할/규칙 문단: 오늘 날짜(`current_app_date_iso()`) 기준 상대 날짜 계산, 다중 의도 분리, Week 1 tool JSON을 받으면 재호출 없이 필드만 옮기기, 값 불확실 시 `None`/빈 리스트, SQLite/RAG/외부 조율 안 함.
2. **예시 1 (다중 의도 분리)**: "다음 주 화요일 오후 3시에 철수랑 회의 잡고, 어제 낸 과제 리마인더도 추가해줘" → `group_schedule` 1개 + `reminder` 1개로 분리되는 예시.
3. **예시 2 (Week 1 tool JSON 변환)**: `personal_create_schedule`의 `created_schedule` JSON을 입력받아 tool 재호출 없이 `personal_schedule` 1개로 변환하는 예시.
4. 두 예시 모두 "날짜 값은 형식 예시일 뿐이며, 실제 응답은 항상 위에서 안내한 오늘 날짜를 기준으로 새로 계산한다"는 경고 문구를 포함해, LLM이 예시의 날짜 리터럴을 그대로 베끼는 것을 방지한다.

`week02_tools()`는 `week01_tools()`를 그대로 반환하고, `week02_system_prompt()`는 `join_system_prompt(week02_prompt_parts())`를 반환한다. `build_week02_agent()`는 `build_week01_agent()`와 동일한 패턴(전역 캐시 `_WEEK02_AGENT`, `CONFIG.has_openai_key` 체크)에 `tools=week02_tools()`, `response_format=StructuredRequestBatch`, `system_prompt=week02_system_prompt()`를 연결한다.

## 심화(Bridge 함수) 설계

```python
def _coerce_structured_request(value: Any) -> StructuredRequest:
    if isinstance(value, StructuredRequest):
        return value
    if isinstance(value, dict):
        return StructuredRequest.model_validate(value)
    raise RuntimeError(f"예상치 못한 structured output 타입: {type(value)!r}")


def extract_structured_request(text: str) -> StructuredRequest:
    structured_llm = chat_model().with_structured_output(StructuredRequest, method="function_calling")
    result = structured_llm.invoke(
        [("system", join_system_prompt(week02_prompt_parts())), ("user", text)]
    )
    return _coerce_structured_request(result)


@tool
def extract_schedule_request(query: str) -> str:
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
- `chat_model()`은 `ChatOpenAI` 인스턴스이므로 `[("system", ...), ("user", ...)]` 튜플 리스트를 바로 `invoke`할 수 있다 — `SystemMessage`/`HumanMessage` 추가 import가 필요 없어 기존 파일의 최소 의존성 스타일과 맞는다.
- `_coerce_structured_request`가 예상 밖 타입에서 즉시 `RuntimeError`를 내므로, `extract_structured_request`는 별도 try/except로 감싸지 않고 예외를 그대로 전파한다 (가이드의 "잘못된 LLM 응답을 조용히 통과시키지 않는다" 요구와 일치).
- 이 파일에는 Week 1의 `_json` 헬퍼가 없으므로 `extract_schedule_request`는 `json.dumps(..., ensure_ascii=False)`를 직접 호출한다.

## 구현 순서 · 커밋 계획 (세분화, 총 5커밋)

| # | 커밋 | 대상 |
|---|---|---|
| 1 | `week2: StructuredRequest/StructuredRequestBatch 스키마 정의` | 스키마 2개 |
| 2 | `week2: agent 세로 슬라이스 연결 (tools/prompt/build_week02_agent, few-shot 예시 포함)` | `week02_tools`, `week02_system_prompt`, `week02_prompt_parts`, `build_week02_agent` |
| 3 | `week2(심화): _coerce_structured_request 구현` | `_coerce_structured_request` |
| 4 | `week2(심화): extract_structured_request 구현` | `extract_structured_request` |
| 5 | `week2(심화): extract_schedule_request bridge tool 구현` | `extract_schedule_request` |

각 커밋 전, 관련 파일만 명시적으로 `git add`한다 (이전 Week 1 작업에서 겪은 `git add -A`발 CRLF/무관 파일 혼입을 반복하지 않기 위함).

## 검증 계획

자동 테스트 하니스가 없으므로(README 명시) 커밋마다 빠른 스크립트 검증 후, 전체 구현이 끝나면 실제 앱으로 최종 확인한다.

| 커밋 | 검증 방법 | LLM 호출 |
|---|---|---|
| 1. 스키마 | `uv run python -c`로 `StructuredRequest`/`StructuredRequestBatch` 인스턴스 생성 후 `model_dump()` 확인 | 불필요 |
| 2. Agent 연결 | `build_week02_agent()`를 직접 호출해 자연어 문장 하나를 넣고 `structured_response` 형태 확인 | 필요 |
| 3. `_coerce_structured_request` | `StructuredRequest` 인스턴스 / dict / 잘못된 타입(예: int) 3가지 입력 → 정상 반환·정상 반환·`RuntimeError` 확인 | 불필요 |
| 4. `extract_structured_request` | 자연어 문장을 넣고 반환된 `StructuredRequest` 필드 확인 | 필요 |
| 5. `extract_schedule_request` | `.invoke({"query": "..."})` 호출 후 반환 JSON에 `ok/tool_name/base_date/structured_request` 키 존재 확인 | 필요 |

**최종 검증**: 5개 커밋 완료 후 `./run.sh --week2` 실행 → Gradio 채팅에서 (a) 다중 의도 문장, (b) 개인 일정 자연어 요청을 입력해 상세 trace의 `structured_response`가 기대한 형태로 나오는지 확인한다.

## 범위 밖 (Out of scope)
- SQLite 저장, RAG 조회, 외부 멤버 일정 조율 — Week 3 이상에서 다룸.
- 자동화된 pytest 테스트 하니스 추가 — 이 리포지토리의 기존 검증 방식(수동 trace 확인)을 따른다.
