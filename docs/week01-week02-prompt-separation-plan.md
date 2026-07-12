# Week 1·2 프롬프트 분리 계획

## 1. 배경

리팩터링 전 Week 2 프롬프트는 `week01_prompt_parts()`의 반환값 전체를 상속한 뒤 Week 2 규칙을 추가했다.
또한 재질문 여부와 완료된 구조화 결과를 함께 표현하기 위해 LLM의 직접 출력 계약으로
`Week02Response`를 사용하고, 완료된 경우에만 내부 `StructuredRequestBatch`를 앱에 노출한다.

```python
def week02_prompt_parts() -> list[str]:
    return [
        *week01_prompt_parts(),
        WEEK02_PROMPT,
    ]
```

이 방식은 Week 1에서 만든 동작을 빠르게 재사용할 수 있다는 장점이 있다. 하지만 Week 2의 핵심 역할은 자연어 요청을 `StructuredRequestBatch`로 구조화하는 것이므로, Week 1의 모든 CRUD 세부 규칙을 항상 물려받을 필요는 없다.

현재 구조에는 다음 문제가 있다.

- 현재 날짜, 날짜·시간 형식, 값 추측 금지, LLM 재질문 규칙이 여러 번 반복된다.
- `week02_prompt_parts()`와 `week02_system_prompt()`가 유사한 Week 2 규칙을 각각 가지고 있다.
- Week 2에 필요하지 않을 수 있는 삭제 후보 선택과 자정 경계 처리 규칙까지 상속된다.
- 같은 규칙을 여러 위치에서 수정하면 문구나 의미가 서로 달라질 수 있다.
- LLM이 Week 1의 CRUD 수행 역할과 Week 2의 구조화 출력 역할 중 무엇을 우선해야 하는지 추가로 판단해야 한다.

프롬프트를 별도 파일로 옮기는 행위 자체는 LLM 동작에 영향을 주지 않는다. LLM은 소스 파일 구조가 아니라 최종적으로 조합된 system prompt 문자열을 읽는다. 따라서 이번 분리의 핵심은 파일 수를 늘리는 것이 아니라, 최종 프롬프트에서 중복과 역할 충돌을 줄이는 것이다.

현재는 이 계획에 따라 `student_parts/prompts/common.py`, `week01.py`, `week02.py`로
정책을 분리했다. Week 1과 Week 2는 필요한 조각을 명시적으로 선택하고,
`week02_system_prompt()`는 `week02_prompt_parts()`의 조합만 담당한다.

## 2. 목표

이번 리팩터링의 목표는 다음과 같다.

1. 공통 규칙을 한 곳에서 관리한다.
2. Week 1과 Week 2가 자신의 역할에 필요한 프롬프트 조각만 선택한다.
3. 하나의 규칙이 최종 프롬프트에 불필요하게 반복되지 않도록 한다.
4. `weekXX_system_prompt()`는 프롬프트 조합만 담당하게 한다.
5. 기존 Week 1 일정 CRUD와 Week 2의 `needs_clarification -> complete` 상태 전이를 유지한다.
6. 이후 주차도 같은 방식으로 프롬프트를 누적하거나 선택할 수 있게 한다.

## 3. 권장 구조

프롬프트를 역할별 조각으로 나누고 주차별 파일에서 필요한 조각을 명시적으로 조합한다.

```text
student_parts/
├── prompts/
│   ├── __init__.py
│   ├── common.py
│   ├── week01.py
│   └── week02.py
├── week01_wake_up_nana.py
└── week02_structure_natural_language_requests.py
```

각 파일의 책임은 다음과 같다.

| 파일 | 책임 |
| --- | --- |
| `prompts/common.py` | Nana 공통 응답 방식, 현재 날짜, 상대 날짜, 형식, LLM 재질문 원칙, 대화 기억 |
| `prompts/week01.py` | 개인 일정 생성·조회·삭제 tool 선택과 결과 처리 |
| `prompts/week02.py` | 요청 분류, `Week02Response` 상태 판단, `StructuredRequestBatch` 작성, unknown 처리, tool 결과 매핑 |
| `week01_wake_up_nana.py` | Week 1에 필요한 프롬프트 조각 선택 및 agent 생성 |
| `week02_structure_natural_language_requests.py` | Week 2에 필요한 프롬프트 조각 선택 및 agent 생성 |

프로젝트 규모가 작아 파일 증가가 부담스럽다면 먼저 `student_parts/prompts.py` 한 파일로 시작해도 된다. 다만 프롬프트가 이후 주차에도 계속 늘어날 예정이라면 `prompts/` 패키지가 더 적합하다.

## 4. 프롬프트 분류 기준

### 4.1 공통 프롬프트

두 주차에서 실제로 동일한 의미로 사용하는 규칙만 공통으로 분리한다.

- 현재 앱 기준 날짜
- 상대 날짜 해석 기준
- 날짜 `YYYY-MM-DD`, 시간 `HH:MM` 형식
- 확실하지 않은 값 추측 금지
- 필요한 값만 LLM이 자연스러운 한국어로 한 번에 질문
- 이미 받은 대화 정보 재사용
- 한국어로 간결하고 친절하게 응답

예상 상수는 다음과 같다.

```python
NANA_IDENTITY_PROMPT
DATE_TIME_PROMPT
MISSING_FIELDS_PROMPT
CHAT_MEMORY_PROMPT
```

동적 날짜가 포함되므로 단순 상수 대신 함수로 만들어도 된다.

```python
def date_time_prompt() -> str:
    return f"""
    현재 앱 기준 날짜는 {current_app_date_iso()}다.
    상대 날짜는 이 날짜를 기준으로 해석한다.
    날짜는 YYYY-MM-DD, 시간은 HH:MM 형식을 사용한다.
    """
```

### 4.2 Week 1 전용 프롬프트

다음 내용은 일정 CRUD tool을 실제로 수행하는 Week 1의 책임으로 둔다.

- 생성·조회·삭제 요청에 맞는 tool 선택
- 일반 대화에서는 tool을 호출하지 않는 규칙
- 자정을 넘는 일정의 `end_date` 확인
- 정확한 `schedule_id` 기반 삭제
- 삭제 후보가 여러 개일 때 사용자 선택 요청
- tool 응답의 `ok`, `missing_fields`, `invalid_fields` 처리

예상 상수는 다음과 같다.

```python
WEEK01_PERSONAL_SCHEDULE_TOOL_PROMPT
WEEK01_OVERNIGHT_SCHEDULE_PROMPT
WEEK01_DELETE_SCHEDULE_PROMPT
WEEK01_TOOL_RESULT_PROMPT
```

### 4.3 Week 2 전용 프롬프트

다음 내용은 구조화 출력이 핵심인 Week 2의 책임으로 둔다.

- 자연어 또는 tool JSON을 `Week02Response`로 변환
- 부족하거나 모호한 값이 있으면 `status="needs_clarification"`로 판단
- `clarification_question`은 Python 고정 문장이 아니라 LLM이 대화 맥락에 맞게 생성
- 필드가 모두 채워지면 `status="complete"`와 내부 `StructuredRequestBatch`를 반환
- 하나의 요청도 `requests` 목록에 저장
- `kind` 분류 기준과 `unknown` 처리
- 각 `StructuredRequest` 필드 작성 기준
- 확실하지 않은 scalar는 `None`, list는 빈 목록으로 처리
- `base_date`의 의미
- `created_schedule`에서 구조화 필드로 매핑
- Week 2에서 수행하지 않는 SQLite, RAG, 외부 일정 조율 범위 명시

예상 상수는 다음과 같다.

```python
WEEK02_CLASSIFICATION_PROMPT
WEEK02_CLARIFICATION_STATE_PROMPT
WEEK02_STRUCTURED_OUTPUT_PROMPT
WEEK02_TOOL_PAYLOAD_MAPPING_PROMPT
WEEK02_SCOPE_PROMPT
```

## 5. Week 2의 Week 1 규칙 상속 범위

Week 2가 Week 1 tool을 그대로 노출하므로, Week 1 규칙 전체를 제거해서는 안 된다. 대신 실제 tool 호출에 필요한 최소 규칙만 선택한다.

Week 2에서도 유지할 규칙:

- 일정 생성 요청의 필수값 확인
- 부족하거나 모호한 필드를 `missing_fields`에 담고 LLM이 `clarification_question` 생성
- 상대 날짜 및 날짜·시간 형식
- tool 결과가 실패했을 때 성공으로 답하지 않기
- 이전 대화에서 받은 일정 정보 재사용

Week 2에서 제외를 검토할 규칙:

- 삭제 기능을 Week 2 평가 범위에서 사용하지 않는다면 상세 삭제 후보 선택 규칙
- Week 2 구조화 테스트와 무관한 자정 일정 확인 대화의 세부 절차
- 자연어 응답만을 전제로 한 설명 중 structured response와 충돌하는 규칙

제외 여부는 Week 2의 테스트 요구사항을 기준으로 결정한다. Week 2에서도 삭제와 자정 일정 생성을 실제 평가한다면 해당 규칙을 선택적으로 포함해야 한다.

## 6. 목표 코드 형태

`week01_prompt_parts()`는 Week 1에 필요한 조각만 반환한다.

```python
def week01_prompt_parts() -> list[str]:
    return [
        nana_identity_prompt(),
        date_time_prompt(),
        MISSING_FIELDS_PROMPT,
        CHAT_MEMORY_PROMPT,
        WEEK01_PERSONAL_SCHEDULE_TOOL_PROMPT,
        WEEK01_OVERNIGHT_SCHEDULE_PROMPT,
        WEEK01_DELETE_SCHEDULE_PROMPT,
        WEEK01_TOOL_RESULT_PROMPT,
    ]
```

`week02_prompt_parts()`는 `week01_prompt_parts()` 전체를 가져오지 않고 필요한 공통 규칙과 Week 2 전용 규칙을 조합한다.

```python
def week02_prompt_parts() -> list[str]:
    return [
        nana_identity_prompt(),
        date_time_prompt(),
        MISSING_FIELDS_PROMPT,
        CHAT_MEMORY_PROMPT,
        WEEK02_CLASSIFICATION_PROMPT,
        WEEK02_CLARIFICATION_STATE_PROMPT,
        WEEK02_STRUCTURED_OUTPUT_PROMPT,
        WEEK02_TOOL_PAYLOAD_MAPPING_PROMPT,
        WEEK02_SCOPE_PROMPT,
    ]
```

Week 2에서도 일정 생성 tool 호출 규칙이 필요하다면 별도의 최소 조각을 추가한다.

```python
WEEK02_PERSONAL_CREATE_TOOL_PROMPT
```

각 system prompt 함수는 추가 규칙을 넣지 않고 조합만 담당한다.

```python
def week01_system_prompt() -> str:
    return join_system_prompt(week01_prompt_parts())


def week02_system_prompt() -> str:
    return join_system_prompt(week02_prompt_parts())
```

이렇게 하면 Week 2 규칙이 `week02_prompt_parts()`와 `week02_system_prompt()`에 나뉘어 중복되는 문제를 없앨 수 있다.

Week 2의 출력 계약은 다음 상태 관계를 반드시 유지해야 한다.

| status | clarification_question | missing_fields | structured_request |
| --- | --- | --- | --- |
| `needs_clarification` | LLM이 만든 질문 필수 | 한 개 이상 | `None` |
| `complete` | `None` | 빈 목록 | `StructuredRequestBatch` 필수 |

이 관계는 프롬프트만으로 기대하지 않고 `Week02Response`의 Pydantic
`model_validator`에서도 검증한다. Python은 질문 문장을 직접 만들지 않고 상태 계약만 검사한다.

## 7. 구현 단계

### 1단계: 현재 프롬프트 동작 고정

- Week 1과 Week 2의 대표 입력과 기대 결과를 정리한다.
- 현재 최종 system prompt 문자열을 테스트 또는 임시 출력으로 확인한다.
- 생성, 조회, 삭제, 필수값 누락, unknown, structured output 사례를 확보한다.

### 2단계: 프롬프트 조각 추출

- 기존 문구의 의미를 바꾸지 않고 공통·Week 1·Week 2 조각으로 이동한다.
- 이 단계에서는 문구 개선보다 위치 이동에 집중한다.
- `CHAT_MEMORY_PROMPT`와 `join_system_prompt()`의 위치도 함께 정리한다.

### 3단계: 주차별 명시적 조합

- Week 1은 공통 조각과 Week 1 전용 조각을 조합한다.
- Week 2는 공통 조각과 Week 2 전용 조각을 조합한다.
- Week 2에서 필요한 Week 1 tool 규칙만 최소 단위로 선택한다.

### 4단계: Week 2 내부 중복 제거

- `week02_system_prompt()`에 직접 작성된 추가 프롬프트를 제거한다.
- 해당 규칙 중 필요한 내용은 `week02_prompt_parts()`가 참조하는 Week 2 전용 조각 한 곳에 합친다.
- 같은 예시가 여러 번 반복되면 가장 명확한 예시 하나만 남긴다.

### 5단계: 충돌 검토

- `needs_clarification`의 자연어 질문과 `complete`의 structured response가 동시에 나오지 않도록 한다.
- `unknown`으로 구조화할 상황과 누락 필드를 질문할 상황을 구분한다.
- tool 호출 전 LLM 재질문 판단과 `Week02Response`의 Pydantic 상태 검증이 충돌하지 않는지 확인한다.
- 헤더의 “더 높은 주차 또는 뒤의 지시 우선” 규칙이 계속 필요한지 검토한다.

### 6단계: 검증 및 문서 갱신

- 문법 검사와 관련 테스트를 실행한다.
- `./run.sh --week1`, `./run.sh --week2`를 각각 실행해 대표 시나리오를 확인한다.
- 두 명령은 서로 다른 주차 agent를 선택하므로 동시에 실행할 필요가 없다.
- 기존 Week 2 구현 계획 문서의 “Week 1 전체 프롬프트 상속” 설명을 새 조합 방식에 맞게 갱신한다.

## 8. 검증 시나리오

### Week 1

| 입력 | 기대 결과 |
| --- | --- |
| `내일 오후 3시에 병원 일정 잡아줘` | `personal_create_schedule` 호출 |
| `회의 일정 잡아줘` | 날짜와 시작 시간을 한 번에 질문 |
| 자정을 넘는 일정 요청 | 계산한 종료 날짜를 한 번 확인 |
| 제목이 같은 삭제 후보 여러 개 | 임의 삭제 없이 사용자 선택 요청 |
| 일반 대화 | 일정 tool 미호출 |

### Week 2

| 입력 | 기대 결과 |
| --- | --- |
| `다음 주 화요일 오후 3시에 철수랑 회의 잡아줘` | 단일 요청을 포함한 `StructuredRequestBatch` |
| `내일 모임 있음` | `needs_clarification`, LLM이 시작 시간만 질문 |
| `외출 일정 잡아줘` | `needs_clarification`, LLM이 날짜와 시작 시간을 한 번에 질문 |
| `외출` | `kind="unknown"`으로 구조화 |
| 여러 요청이 포함된 문장 | 요청별 `StructuredRequest` 생성 |
| 생성 tool 성공 결과 | `created_schedule` 값을 우선 사용 |
| `end_time="미정"`인 tool 결과 | `end_time=None` |

### 최종 프롬프트 자체 검증

- 현재 날짜 안내가 각 최종 프롬프트에서 한 번만 등장하는지 확인한다.
- 누락값 재질문 규칙이 불필요하게 반복되지 않는지 확인한다.
- `clarification_question`에 Python 고정 fallback 문장을 사용하지 않는지 확인한다.
- `needs_clarification`과 `complete`의 필드 계약이 프롬프트와 Pydantic 검증에서 일치하는지 확인한다.
- Week 2 structured output 규칙이 한 위치에서만 관리되는지 확인한다.
- Week 2 최종 프롬프트에 불필요한 Week 1 삭제·자정 규칙이 포함되지 않았는지 확인한다.
- 프롬프트 조각의 순서가 `공통 규칙 -> 기능 규칙 -> 출력 규칙`으로 읽히는지 확인한다.

## 9. 완료 조건

다음 조건을 모두 만족하면 프롬프트 분리가 완료된 것으로 본다.

- 공통 프롬프트가 별도 모듈에서 한 번만 정의되어 있다.
- Week 1과 Week 2가 필요한 조각을 명시적으로 선택한다.
- Week 2가 `week01_prompt_parts()` 전체에 의존하지 않는다.
- `week02_system_prompt()`가 별도 지시를 추가하지 않고 조합만 수행한다.
- 동일 의미의 Week 2 규칙이 여러 위치에 반복되지 않는다.
- 기존 Week 1 CRUD 시나리오가 정상 동작한다.
- Week 2의 재질문, unknown 판정, structured output 시나리오가 정상 동작한다.
- Week 2 재질문은 LLM이 생성하며, 필요한 값이 모두 채워진 뒤에만 `StructuredRequestBatch`가 노출된다.
- 최종 프롬프트를 출력했을 때 역할과 우선순위가 명확하게 읽힌다.

현재 코드에는 위 구조가 반영되었다. 실제 LLM 통합 시나리오까지 확인한 뒤
동작 검증 항목을 최종 완료로 판단한다.

## 10. 권장 적용 원칙

프롬프트 조각을 지나치게 작은 문장 단위로 나누면 조합 관계를 이해하기 어려워진다. 따라서 상수 하나는 독립적으로 켜거나 끌 수 있는 하나의 정책 단위를 표현하는 것이 좋다.

또한 “주차가 높으면 이전 주차 전체를 상속한다”는 구조보다 “이번 agent가 수행하는 역할에 필요한 정책을 선택한다”는 구조를 우선한다. 주차 정보는 학습 순서를 설명하는 데 사용하고, 실제 system prompt 구성은 agent의 책임을 기준으로 결정한다.
