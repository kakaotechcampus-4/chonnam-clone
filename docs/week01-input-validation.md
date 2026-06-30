# Week 1 입력 검증 설계

## 책임 분리

- system prompt: 누락되거나 모호한 값을 추측하지 말라는 행동 원칙
- tool schema: 필수 인자, 선택 인자, Python 타입
- Python validator: 문자열 형식, 실제 날짜·시간, 값 사이의 관계

함수 시그니처에서 `title`, `date`, `start_time`은 필수이고 `end_time`,
`attendees`는 선택이다. 필수 인자가 tool call에서 완전히 빠지면 LangChain의 schema
검증이 함수 실행 전에 실패할 수 있으므로, agent가 호출 전에 누락값을 질문하도록
프롬프트에도 원칙을 둔다.

## 검증 helper

구현 시 다음과 같이 작은 helper로 분리한다.

```python
def _is_valid_date(value: str) -> bool:
    ...


def _is_valid_time(value: str) -> bool:
    ...


def _validate_schedule_input(
    title: str,
    date: str,
    start_time: str,
    end_time: str,
) -> dict[str, Any]:
    ...
```

날짜와 시간은 `datetime.strptime`으로 검증한다. 정규식만 사용하면
`2026-13-40`처럼 모양만 맞고 실제로 존재하지 않는 값을 허용할 수 있다.

## 검증 순서

1. `title`, `date`, `start_time`의 공백 여부를 확인한다.
2. 값이 존재하는 날짜와 시간만 형식을 검증한다.
3. `end_time != "미정"`일 때 종료 시간 형식을 검증한다.
4. 시작과 종료가 모두 유효하면 `end_time > start_time`인지 확인한다.
5. 오류가 하나라도 있으면 저장하지 않고 오류 payload를 반환한다.
6. 오류가 없을 때만 일정 dict를 만들고 append한다.

## 필드별 정책

### title

- `strip()` 결과가 비어 있으면 누락으로 처리한다.
- 저장할 때 앞뒤 공백을 제거한다.

### date

- `YYYY-MM-DD` 형식의 실제 달력 날짜여야 한다.
- 상대 날짜 해석은 LLM이 현재 앱 날짜를 기준으로 수행한다.
- tool은 `"내일"` 같은 자연어 날짜를 직접 해석하지 않는다.

### start_time과 end_time

- 24시간제 `HH:MM`을 사용한다.
- `end_time`은 `"미정"`을 허용한다.
- 종료 시간이 지정됐다면 시작 시간보다 늦어야 한다.
- 자정을 넘기는 일정은 Week 1 범위에서 다루지 않고 재확인을 요청한다.

### attendees

- `None`은 빈 리스트로 정규화한다.
- 리스트 원소의 상세 정제는 Week 1 필수 범위에 포함하지 않는다.

## 실패 시 불변 조건

- `PERSONAL_SCHEDULES` 길이가 변하지 않는다.
- 부분적으로 작성된 일정 dict를 저장하지 않는다.
- `ok`는 `false`다.
- LLM이 재질문할 수 있는 필드 단위 정보를 제공한다.

## 과제 범위와 확장 구현

입력 검증 helper는 학습 품질을 높이는 확장 구현이다. 우선 CRUD의 기본 반환 계약을
완성한 뒤 추가한다. 자동 평가가 기본 payload만 엄격히 확인할 가능성에 대비해 성공
payload의 키와 구조는 변경하지 않는다.

