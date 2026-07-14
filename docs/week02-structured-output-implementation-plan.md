# Week 2 구조화 출력 구현 계획

## 1. Week 2에서 구현하려는 것

Week 2의 목표는 사용자의 한국어 요청을 일정 앱이 읽을 수 있는 구조로 바꾸는 것이다.

예를 들어 사용자가 이렇게 말한다.

```text
다음 주 화요일 오후 3시에 철수랑 회의 잡아줘
```

Week 1에서는 이 요청을 보고 `personal_create_schedule` 같은 tool을 호출한 뒤 자연어로 답했다.

Week 2에서는 최종 결과가 자연어 답변이 아니라 아래와 같은 구조화된 객체가 되어야 한다.

```python
StructuredRequestBatch(
    requests=[
        StructuredRequest(
            kind="personal_schedule",
            title="회의",
            date="2026-07-14",
            start_time="15:00",
            end_time=None,
            members=["철수"],
            priority=None,
            reason="사용자가 철수와 회의 일정을 요청함",
            original_text="다음 주 화요일 오후 3시에 철수랑 회의 잡아줘",
        )
    ],
    base_date="2026-07-08",
)
```

즉 Week 2의 핵심은 LLM이 자유롭게 말하게 두는 것이 아니라, 정해진 Pydantic 스키마에 맞춰 결과를 만들게 하는 것이다.

## 2. Week 1과 연결되는 방식

Week 2 파일은 Week 1 파일에서 세 가지를 가져온다.

```python
from student_parts.week01_wake_up_nana import (
    join_system_prompt,
    week01_prompt_parts,
    week01_tools,
)
```

각각의 역할은 다음과 같다.

- `week01_tools()`: Week 1에서 만든 개인 일정 tool 목록을 그대로 가져온다.
- `week01_prompt_parts()`: Week 1의 Nana 역할, 날짜 해석 규칙, tool 사용 규칙을 이어받는다.
- `join_system_prompt()`: Week 1 규칙과 Week 2 규칙을 하나의 system prompt로 합친다.

따라서 Week 2는 Week 1을 새로 구현하는 단계가 아니다.

Week 1의 일정 도구와 기본 프롬프트를 재사용하고, 마지막 출력 형식만 `StructuredRequestBatch`로 바꾸는 단계다.

실행 흐름은 다음과 같다.

```text
./run.sh --week2
-> fixed/week_agent_registry.py
-> student_parts.week02_structure_natural_language_requests
-> build_week_agent()
-> build_week02_agent()
-> create_agent(...)
```

## 3. 구현 순서

아래 순서로 구현하면 좋다.

1. `StructuredRequest` 스키마 완성
2. `StructuredRequestBatch` 스키마 완성
3. Week 1 tool 목록 연결
4. Week 2 prompt 작성
5. Week 2 system prompt 작성
6. Week 2 agent builder 작성
7. 문법 확인과 실행 확인

## 4. `StructuredRequest` 구현

`StructuredRequest`는 요청 하나를 표현하는 스키마다.

예를 들어 "회의 잡아줘"라는 요청 하나가 `StructuredRequest` 하나가 된다.

필드는 다음 의미를 가진다.

| 필드 | 의미 |
| --- | --- |
| `kind` | 요청 종류 |
| `title` | 일정이나 할 일 제목 |
| `date` | 요청 날짜 |
| `start_time` | 시작 시각 |
| `end_time` | 종료 시각 |
| `members` | 참석자나 관련 멤버 |
| `priority` | 할 일의 우선순위 |
| `reason` | 이렇게 구조화한 이유 |
| `original_text` | 사용자의 원문 |

`kind`는 아무 문자열이나 넣으면 안 된다.

아래 값 중 하나만 허용된다.

```python
RequestKind = Literal[
    "personal_schedule",
    "group_schedule",
    "todo",
    "reminder",
    "unknown",
]
```

각 필드는 `Field(description=...)`를 가져야 한다.

이 description은 단순한 주석이 아니다. LangChain structured output에서 LLM이 각 필드를 어떻게 채워야 하는지 이해하는 설명으로 사용된다.

예를 들어 `date`는 이렇게 설명할 수 있다.

```python
date: str | None = Field(
    None,
    description="요청 날짜입니다. 확실할 때만 YYYY-MM-DD 형식으로 채우고, 알 수 없으면 None입니다.",
)
```

중요한 규칙은 다음과 같다.

- 날짜는 확실할 때만 `YYYY-MM-DD`로 채운다.
- 시간은 확실할 때만 `HH:MM`으로 채운다.
- 모르는 문자열 값은 `None`으로 둔다.
- 모르는 목록 값은 빈 리스트 `[]`로 둔다.
- 참석자가 없거나 알 수 없으면 `members=[]`로 둔다.
- 원문은 가능하면 `original_text`에 보존한다.

## 5. `StructuredRequestBatch` 구현

`StructuredRequestBatch`는 여러 요청을 담는 최종 출력 스키마다.

요청이 하나뿐이어도 반드시 list 안에 넣어야 한다.

```python
StructuredRequestBatch(
    requests=[
        StructuredRequest(...)
    ],
    base_date=current_app_date_iso(),
)
```

이렇게 list로 감싸는 이유는 사용자가 한 문장에서 여러 요청을 할 수 있기 때문이다.

예를 들어:

```text
내일 3시에 회의 잡고, 금요일까지 보고서 작성도 할 일로 추가해줘
```

이 문장은 요청이 두 개다.

```python
requests=[
    StructuredRequest(kind="personal_schedule", ...),
    StructuredRequest(kind="todo", ...),
]
```

`base_date`는 상대 날짜를 해석할 때 기준이 되는 날짜다.

예를 들어 "내일", "다음 주 화요일" 같은 표현은 `base_date`가 있어야 정확히 계산할 수 있다.

## 6. Week 1 tool 연결

`week02_tools()`는 Week 1 tool 목록을 그대로 반환하면 된다.

```python
def week02_tools() -> list[Any]:
    return week01_tools()
```

Week 2에서 tool을 새로 만들 필요는 없다.

특히 개인 일정 생성 요청에서는 Week 1의 `personal_create_schedule` tool 결과가 중요하다.

이 tool은 성공하면 이런 JSON 문자열을 반환한다.

```json
{
  "ok": true,
  "tool_name": "personal_create_schedule",
  "created_schedule": {
    "title": "회의",
    "date": "2026-07-14",
    "start_time": "15:00",
    "end_time": "미정",
    "attendees": ["철수"]
  }
}
```

Week 2 prompt에는 이 `created_schedule`을 읽어서 `StructuredRequest` 필드를 채우라고 알려줘야 한다.

매핑은 대략 다음과 같다.

| Week 1 tool payload | Week 2 field |
| --- | --- |
| `created_schedule.title` | `title` |
| `created_schedule.date` | `date` |
| `created_schedule.start_time` | `start_time` |
| `created_schedule.end_time` | `end_time` |
| `created_schedule.attendees` | `members` |

단, `end_time`이 `"미정"`이면 Week 2 구조에서는 `None`으로 두는 것이 자연스럽다.

## 7. Week 2 prompt 작성

`week02_prompt_parts()`는 Week 1 prompt를 먼저 가져오고, 그 뒤에 Week 2 규칙을 추가한다.

```python
def week02_prompt_parts() -> list[str]:
    return [
        *week01_prompt_parts(),
        f"""
        ...
        """,
    ]
```

추가할 내용은 다음과 같다.

- 너는 Week 2 요청 구조화 agent다.
- 현재 기준 날짜는 `current_app_date_iso()`다.
- 최종 출력은 `StructuredRequestBatch`다.
- 자연어 요청을 `StructuredRequest` 필드로 나눈다.
- 요청이 하나여도 `requests` list 안에 넣는다.
- 확실하지 않은 값은 만들지 않는다.
- 날짜는 `YYYY-MM-DD`, 시간은 `HH:MM` 형식을 사용한다.
- 모르는 값은 `None` 또는 빈 리스트로 둔다.
- Week 1 tool 결과 JSON이 있으면 `created_schedule`을 근거로 사용한다.
- Week 2에서는 SQLite 저장, RAG, 외부 멤버 일정 조율을 하지 않는다.

## 8. `week02_system_prompt()` 작성

`week02_system_prompt()`는 `join_system_prompt(...)`를 사용해서 prompt 조각들을 합치면 된다.

구조는 다음과 같다.

```python
def week02_system_prompt() -> str:
    return join_system_prompt(
        [
            *week02_prompt_parts(),
            """
            최종 응답은 반드시 StructuredRequestBatch structured_response로 만든다.
            요청이 하나뿐이어도 requests 목록에 StructuredRequest 하나를 담는다.
            personal_create_schedule tool 결과가 있으면 created_schedule 값을 우선 근거로 사용한다.
            """,
        ]
    )
```

여기서 중요한 점은 `StructuredRequestBatch`가 최종 출력 계약이라는 것을 prompt에서도 명확히 말해주는 것이다.

## 9. `build_week02_agent()` 작성

Week 1의 `build_week01_agent()`와 거의 같은 패턴으로 작성하면 된다.

차이점은 `response_format=StructuredRequestBatch`가 추가된다는 점이다.

```python
def build_week02_agent() -> object:
    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")

    global _WEEK02_AGENT
    if _WEEK02_AGENT is None:
        _WEEK02_AGENT = create_agent(
            model=chat_model(),
            tools=week02_tools(),
            system_prompt=week02_system_prompt(),
            response_format=StructuredRequestBatch,
        )
    return _WEEK02_AGENT
```

`response_format=StructuredRequestBatch`가 있어야 LangChain agent가 최종 결과를 해당 Pydantic 스키마에 맞춰 만들려고 한다.

## 10. 예약 함수 처리

아래 함수들은 현재 Week 2의 중심 흐름은 아니다.

```python
_coerce_structured_request(value: Any) -> StructuredRequest
extract_structured_request(text: str) -> StructuredRequest
extract_schedule_request(query: str) -> str
```

중심 흐름은 `build_week02_agent()` 안의 `response_format=StructuredRequestBatch`다.

다만 이 함수들이 나중 회차에서 import되거나 호출될 수 있으므로, 가능하면 `...`만 남겨두지 않는 편이 좋다.

최소 구현 방향은 다음과 같다.

- 이미 `StructuredRequest`면 그대로 반환한다.
- dict면 `StructuredRequest.model_validate(value)`로 변환한다.
- 문자열이면 `kind="unknown"`, `original_text=text`인 `StructuredRequest`를 만든다.
- `extract_schedule_request()`는 JSON 문자열을 반환한다.

## 11. 검증 방법

먼저 문법을 확인한다.

```bash
uv run python -m py_compile student_parts/week02_structure_natural_language_requests.py
```

그 다음 Week 2 앱을 실행한다.

```bash
./run.sh --week2
```

테스트 입력:

```text
다음 주 화요일 오후 3시에 철수랑 회의 잡아줘
```

확인할 것:

- Week 2 agent가 실행된다.
- 최종 결과에 `structured_response`가 있다.
- `structured_response`가 `StructuredRequestBatch` 형태다.
- `requests`가 list다.
- 요청이 하나면 `requests` 안에 항목이 하나 있다.
- `kind`, `title`, `date`, `start_time`, `members`가 의도대로 채워진다.
- `base_date`가 `current_app_date_iso()` 기준으로 들어간다.

## 12. 구현하지 않아야 할 것

Week 2에서는 아래 작업을 하지 않는다.

- SQLite 저장
- RAG 검색
- 외부 캘린더 연동
- 멤버별 일정 조율
- Week 1 tool 재구현

Week 2는 저장 단계가 아니라 구조화 단계다.

따라서 목표는 "일정을 실제로 저장했다"가 아니라 "저장할 수 있는 형태로 요청을 정리했다"에 가깝다.
