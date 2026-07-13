# 트러블슈팅: Week 2 structured output 파싱 실패 (Extra data)

**파일**: `student_parts/week02_structure_natural_language_requests.py`  
**함수**: `build_week02_agent()`

---

## 증상

`./run.sh --week2`로 실행한 뒤 채팅에 "내일 오전 3시 일정 잡아줘"를 입력하면 아래 오류가 발생한다.

```
Week 2 agent 실행 중 오류가 발생했습니다: StructuredOutputValidationError:
Failed to parse structured output for tool 'StructuredRequestBatch':
Native structured output expected valid JSON for StructuredRequestBatch,
but parsing failed: Extra data: line 2 column 1 (char 41).
```

스키마(`StructuredRequest`/`StructuredRequestBatch`)와 `create_agent(...)` 연결을 과제 가이드대로 구현했는데도 발생한다. **수강생 구현 코드의 버그가 아니다.**

---

## 원인

### 원인 1: `create_agent`가 native JSON 모드(ProviderStrategy)를 자동 선택

langchain 1.x의 `create_agent`는 `response_format`에 Pydantic 모델을 그대로 주면,
모델이 native structured output을 지원하는지 검사(`_supports_provider_strategy`)한 뒤
**ProviderStrategy**를 자동 선택한다. `gpt-4.1-mini`는 지원 목록에 있어 이 경로를 탄다.

```python
# response_format에 Pydantic 모델을 그대로 주면
_WEEK02_AGENT = create_agent(
    ...,
    response_format=StructuredRequestBatch,  # → ProviderStrategy(native JSON 모드) 자동 선택
)
```

ProviderStrategy는 API 요청에 `response_format={"type": "json_schema", ...}`를 실어 보내고,
모델 응답 **텍스트 전체**를 `json.loads()`로 파싱한다. 응답이 순수 JSON 하나가 아니면 그대로 실패한다.

### 원인 2: 프록시 경유 모델이 JSON을 두 번 출력

파싱 직전의 실제 모델 응답을 가로채 확인한 결과, 수업용 프록시(mlapi.run)를 거친
`gpt-4.1-mini`가 native JSON 모드에서 **동일한 JSON 객체를 두 줄로 두 번** 반환했다.

```
{"base_date":"2026-07-08","requests":[]}
{"base_date":"2026-07-08","requests":[]}
```

첫 줄이 정확히 41자라서 `json.loads()`가 두 번째 줄 시작 지점에서
`Extra data: line 2 column 1 (char 41)`을 던진 것이다.

---

## structured output 파싱 흐름

```
사용자 입력 "내일 오전 3시 일정 잡아줘"
        ↓
create_agent의 model_node          ← response_format이 ProviderStrategy로 자동 결정됨
        ↓
프록시 경유 gpt-4.1-mini 호출       ← JSON 객체를 두 줄로 중복 출력
        ↓
ProviderStrategyBinding.parse()    ← 응답 텍스트 전체를 json.loads()
        ↓
json.JSONDecodeError: Extra data   ← StructuredOutputValidationError로 감싸져 UI에 표시
```

---

## 해결

> **native JSON 모드 대신 tool 호출 방식으로 구조화한다.**  
> `ToolStrategy`로 감싸면 스키마가 tool 정의로 변환되어 모델이 tool call 인자로
> 구조화 결과를 반환한다. 응답 텍스트를 통째로 파싱하는 경로를 타지 않으므로
> 프록시의 JSON 중복 출력 문제를 피할 수 있다.

```python
# ❌ 잘못된 패턴 — 프록시 환경에서 native JSON 파싱 실패
_WEEK02_AGENT = create_agent(
    model=chat_model(),
    tools=week02_tools(),
    response_format=StructuredRequestBatch,
    system_prompt=week02_system_prompt(),
)
```

```python
# ✅ 올바른 패턴 — ToolStrategy로 tool 호출 기반 구조화
from langchain.agents.structured_output import ToolStrategy

_WEEK02_AGENT = create_agent(
    model=chat_model(),
    tools=week02_tools(),
    response_format=ToolStrategy(StructuredRequestBatch),
    system_prompt=week02_system_prompt(),
)
```

같은 `StructuredRequestBatch` 스키마를 그대로 쓰므로 과제에서 요구하는
`structured_response` 결과는 동일하게 나온다. 변경 후 같은 문장을 입력하면
정상 구조화된다.

```python
StructuredRequestBatch(
    requests=[StructuredRequest(kind='personal_schedule', date='2026-07-09',
                                start_time='03:00', ...)],
    base_date='2026-07-08',
)
```

---

## 요약

| 항목 | 잘못된 방법 | 올바른 방법 |
|------|------------|------------|
| `response_format` 전달 | `StructuredRequestBatch` 그대로 | `ToolStrategy(StructuredRequestBatch)` |
| 구조화 방식 | native JSON 모드 (응답 전체를 `json.loads`) | tool 호출 인자로 구조화 결과 수신 |
| 프록시 JSON 중복 출력 | 파싱 실패 → `Extra data` 오류 | 파싱 경로를 타지 않아 영향 없음 |
| 스키마 | `StructuredRequestBatch` | 동일 — 스키마 수정 불필요 |
