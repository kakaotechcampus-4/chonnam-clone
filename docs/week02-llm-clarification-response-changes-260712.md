# Week 2 LLM 재질문 및 구조화 응답 변경 정리

## 1. 변경 배경

기존 Week 2의 최종 목표는 사용자의 자연어 요청을 `StructuredRequestBatch`로 변환하는 것이었다.

하지만 일정 생성에 필요한 `title`, `date`, `start_time`이 부족한 요청도 바로
`StructuredRequestBatch`로 만들려고 하면 다음 문제가 생긴다.

- 사용자가 말하지 않은 날짜나 시간을 LLM이 추측해서 채울 수 있다.
- 정보가 부족한 상태에서 구조화 결과를 확정할 수 있다.
- 재질문을 일반 문장으로 반환하라는 프롬프트와
  `response_format=StructuredRequestBatch` 계약이 충돌할 수 있다.
- 이전 요청 뒤에 사용자가 `오후 3시야`처럼 짧게 보충했을 때 앞선 일정 정보와 합쳐야 한다.

처음에는 Python 정규표현식으로 일정 의도와 날짜·시간 표현을 검사한 뒤,
필드가 부족하면 LLM을 호출하기 전에 고정 질문을 반환했다.

이 방식은 빠르고 결정적이지만 자연어 표현이 늘어날수록 정규표현식을 계속 추가해야 한다.
또한 일정 의도, 문맥, 모호성을 판단하는 로직이 프롬프트와 Python 코드에 나뉘는 문제가 있었다.

따라서 다음 원칙으로 구조를 변경했다.

1. 자연어 의도, 누락값, 모호성, 이전 대화 병합은 LLM이 판단한다.
2. 실제 날짜·시간 형식과 시작·종료 일시 관계는 Python이 최종 검증한다.
3. 정보가 부족하면 구조화를 확정하지 않고 필요한 값만 다시 질문한다.
4. 필요한 정보가 모두 모인 뒤에만 기존 `StructuredRequestBatch`를 최종 결과로 노출한다.

## 2. 수정 전 흐름

수정 전에는 Python 재질문 래퍼가 LLM보다 먼저 실행됐다.

```text
사용자 메시지
    ↓
Python 정규표현식 검사
    ├─ 필드 부족 → Python이 만든 고정 질문 반환
    └─ 필드 충족 → Week 2 LLM 실행
                         ↓
                  StructuredRequestBatch
```

Python은 다음 항목을 정규표현식으로 판단했다.

- 일정 생성 의도가 있는가
- 날짜 표현이 있는가
- 시간 표현이 있는가
- 일정 제목으로 볼 수 있는 표현이 있는가
- 직전 재질문에 대한 후속 답변인가

이 구조에서는 자연어 판단 규칙이 추가될 때마다 Python 패턴과 프롬프트를 함께 수정해야 했다.

## 3. 수정 후 흐름

현재는 Week 2 LLM이 먼저 `Week02Response`를 만든다.

```text
사용자 대화 전체
    ↓
Week 2 LLM
    ↓
Week02Response
    ├─ status="needs_clarification"
    │    └─ 일반 한국어 재질문 반환
    └─ status="complete"
         └─ 내부 StructuredRequestBatch를 최종 결과로 반환
```

예를 들어 다음 요청은 아직 구조화 결과를 확정하지 않는다.

```text
사용자: 내일 프로젝트 회의 잡아줘
```

LLM의 내부 응답 예시는 다음과 같다.

```python
Week02Response(
    status="needs_clarification",
    clarification_question="프로젝트 회의는 몇 시에 시작하나요?",
    missing_fields=["start_time"],
    structured_request=None,
)
```

사용자가 후속 답변을 제공한다.

```text
사용자: 오후 3시야
```

LLM은 대화 전체에서 기존 제목과 날짜를 가져와 새 시간과 합친다.

```python
Week02Response(
    status="complete",
    clarification_question=None,
    missing_fields=[],
    structured_request=StructuredRequestBatch(
        requests=[
            StructuredRequest(
                kind="personal_schedule",
                title="프로젝트 회의",
                date="2026-07-13",
                start_time="15:00",
                ...,
            )
        ],
        base_date="2026-07-12",
    ),
)
```

## 4. `schedule_clarification.py` 변경

공통 모듈에서는 자연어 판단에 사용하던 정규표현식을 제거했다.

제거된 책임은 다음과 같다.

- 일정 의도 판단
- 자연어에서 날짜·시간 표현 검색
- 일정 제목 추출
- 이전 발화와 후속 답변 결합
- 자연어 누락 필드 선판단

이 책임은 이제 LLM 프롬프트와 `Week02Response` 출력 계약이 담당한다.

공통 모듈에는 결정적으로 검사할 수 있는 로직을 유지했다.

- `YYYY-MM-DD`가 실제 날짜인지 검사
- `HH:MM`이 실제 시간인지 검사
- 필수 도구 인자가 비어 있는지 검사
- 종료 일시가 시작 일시보다 늦은지 검사
- 도구 검증 결과의 누락·오류 필드를 질문으로 변환

자연어 이해는 LLM이 더 유연하게 처리하고, 잘못된 값의 저장은 Python 검증이 막는 구조다.

## 5. `Week02Response` 추가

기존에는 LangChain agent의 직접 출력 형식이 `StructuredRequestBatch`였다.

```python
response_format=StructuredRequestBatch
```

현재는 재질문 상태와 완료 상태를 함께 표현하기 위해 상위 스키마를 추가했다.

```python
class Week02Response(BaseModel):
    status: Literal["needs_clarification", "complete"]
    clarification_question: str | None
    missing_fields: list[str]
    structured_request: StructuredRequestBatch | None
```

각 필드의 역할은 다음과 같다.

| 필드 | 역할 |
| --- | --- |
| `status` | 재질문이 필요한지 구조화가 완료됐는지 표현한다. |
| `clarification_question` | 사용자에게 보여줄 자연스러운 한국어 질문이다. |
| `missing_fields` | 부족하거나 모호한 필드 목록이다. |
| `structured_request` | 완료된 경우에만 제공되는 기존 `StructuredRequestBatch`다. |

LangChain agent의 출력 형식도 다음과 같이 변경했다.

```python
response_format=Week02Response
```

## 6. `Week02ResponseAgent` 추가

`Week02ResponseAgent`는 자연어를 직접 판단하지 않는다.

이 클래스의 역할은 LLM이 반환한 `Week02Response`를 기존 앱이 이해하는 결과로 변환하는 것이다.

재질문 문장은 Python의 고정 문자열로 만들지 않는다. LLM이 현재 대화와
`missing_fields`를 근거로 `clarification_question`을 직접 생성해야 한다.

### 재질문이 필요한 경우

```python
{
    "messages": [
        {
            "role": "assistant",
            "content": "회의는 몇 시에 시작하나요?",
        }
    ]
}
```

이때는 `structured_response`를 제공하지 않는다. 아직 일정 요청이 완성되지 않았기 때문이다.

### 구조화가 완료된 경우

```python
{
    "messages": [...],
    "structured_response": StructuredRequestBatch(...),
}
```

내부 LLM 출력은 `Week02Response`지만, 앱에 노출되는 완료 결과는 기존과 동일한
`StructuredRequestBatch`다.

따라서 UI와 trace가 사용하는 최종 완료 계약은 유지된다.

## 7. 상태별 스키마 검증

`Week02Response`에는 Pydantic `model_validator`를 적용했다.

| status | clarification_question | missing_fields | structured_request |
| --- | --- | --- | --- |
| `needs_clarification` | LLM이 만든 질문 필수 | 한 개 이상 | `None` |
| `complete` | `None` | 빈 목록 | 필수 |

고정 fallback 질문을 사용하지 않는 이유는 다음과 같다.

- 일반적인 고정 질문은 어떤 필드가 부족한지 구체적으로 알려주지 못한다.
- LLM의 잘못된 출력을 fallback 문장으로 숨기면 출력 계약 위반을 발견하기 어렵다.
- 대화에 나온 일정 제목을 반영한 질문은 LLM이 더 자연스럽게 만들 수 있다.
- Python은 질문을 작성하는 대신 상태 계약만 결정적으로 검증하는 편이 역할 분리에 맞다.

따라서 `needs_clarification`인데 LLM 질문이 없거나 `missing_fields`가 비어 있으면
검증 오류가 발생한다. 반대로 `complete` 상태에 질문이나 누락 필드가 남아 있거나
`structured_request`가 없을 때도 검증 오류가 발생한다.

## 8. `invoke()` 처리

일반 실행에서는 내부 agent를 호출한 후 `_translate()`로 결과를 변환한다.

```python
def invoke(self, payload, *args, **kwargs):
    return self._translate(
        self._agent.invoke(payload, *args, **kwargs)
    )
```

`_translate()`는 다음 순서로 동작한다.

1. `structured_response`를 `Week02Response`로 검증한다.
2. `needs_clarification`이면 질문 메시지만 반환한다.
3. 상태별 필드 계약이 맞지 않으면 Pydantic 검증 오류로 처리한다.
4. 정상 완료라면 내부 `StructuredRequestBatch`를 최종 `structured_response`로 반환한다.

## 9. `stream()` 처리

스트리밍 실행에서는 일반 tool 및 model chunk는 그대로 전달한다.

최종 `Week02Response`가 포함된 chunk를 발견하면 `_translate()`를 적용한다.

LangChain chunk는 다음 두 형태로 올 수 있다.

```python
{"structured_response": response}
```

```python
{"model": {"structured_response": response}}
```

`_structured_response_from_chunk()`는 두 형태를 모두 확인한다.

## 10. 프롬프트 변경

Week 2 프롬프트에는 다음 판단 순서를 추가했다.

1. 현재 발화만 보지 않고 대화 전체를 읽는다.
2. 이전 턴에서 받은 제목, 날짜, 시간과 후속 답변을 합친다.
3. 처리 가능한 요청 의도가 명확한지 판단한다.
4. 일정 생성 요청에는 `title`, `date`, `start_time`이 필요하다.
5. 부족하거나 모호한 필드가 있으면 값을 추측하지 않는다.
6. 필요한 필드만 한 번에 묻는다.
7. 필드가 모두 채워지면 `StructuredRequestBatch`를 완성한다.
8. 일정과 관련 없는 불명확한 표현은 재질문하지 않고 `kind="unknown"`으로 구조화한다.

## 11. 기존 구현 계획과 달라진 점

`week02-structured-output-implementation-plan.md`는 LLM의 직접 출력 계약을
`StructuredRequestBatch`로 정의한다.

현재 구현은 재질문 상태를 표현하기 위해 내부 계약을 확장했다.

| 항목 | 기존 계획 | 현재 구현 |
| --- | --- | --- |
| LLM `response_format` | `StructuredRequestBatch` | `Week02Response` |
| 정보 부족 상태 | 명확한 상위 상태 없음 | `needs_clarification` |
| 완료 상태 | 바로 구조화 결과 반환 | `complete` 안에 구조화 결과 포함 |
| 앱의 최종 완료 결과 | `StructuredRequestBatch` | `StructuredRequestBatch` |
| 자연어 필드 판단 | 프롬프트 중심 | 프롬프트와 `Week02Response` 계약 |

따라서 현재 구현은 기존 계획을 버린 것이 아니라, 재질문 과정을 표현할 수 있도록
내부 출력 계약을 한 단계 확장한 것이다.

## 12. 테스트한 항목

API 키 없이 다음 동작을 단위 테스트했다.

- 공통 일정 입력 검증이 누락 필드와 잘못된 날짜·시간을 반환하는지
- `needs_clarification`이 일반 질문 메시지로 변환되는지
- `complete`의 내부 결과가 `StructuredRequestBatch`로 노출되는지
- `base_date`가 유지되는지
- 중첩된 streaming `structured_response`가 변환되는지
- `needs_clarification`에 LLM 질문이 없으면 검증에 실패하는지
- `complete`에 질문이나 누락 필드가 남아 있으면 검증에 실패하는지

실제 LLM 판단 품질은 다음 실행으로 별도 확인해야 한다.

```bash
./run.sh --week1
./run.sh --week2
```

대표 확인 시나리오는 다음과 같다.

```text
프로젝트 회의 잡아줘
```

```text
내일 프로젝트 회의 잡아줘
→ 오후 3시야
```

```text
다음 주 화요일 오후 3시에 철수랑 회의 잡아줘
```

## 13. 남은 보완 사항

현재 구조에서 추가로 보완할 수 있는 항목은 다음과 같다.

### 스트리밍 메시지 보존

최종 `structured_response`와 `messages`가 같은 chunk에 들어오면 변환 과정에서 메시지가
누락되지 않도록 원래 chunk의 메시지도 함께 넘기는 보완이 필요하다.

### 실제 LLM 통합 테스트

단위 테스트는 가짜 agent 응답을 사용한다. 실제 모델이 다음 항목을 안정적으로 지키는지
통합 테스트가 필요하다.

- 누락 필드 전체를 한 번에 질문하는가
- 이전 턴의 값을 다시 묻지 않는가
- 정보가 모두 모이기 전에 `complete`를 반환하지 않는가
- 완료 후 `StructuredRequestBatch` 필드를 정확히 채우는가
