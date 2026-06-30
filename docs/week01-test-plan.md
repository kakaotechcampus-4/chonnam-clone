# Week 1 검증 계획

## 1. 직접 Tool 테스트

API 키와 LLM 판단을 제외하고 CRUD 코드 자체를 먼저 확인한다.

| 구분 | 입력 | 기대 결과 |
| --- | --- | --- |
| 생성 | 모든 필수값과 참석자 | `ok=true`, 일정 한 건 추가 |
| 생성 | 참석자 `None` | `attendees=[]` |
| 생성 | 종료 시간 생략 | `end_time="미정"` |
| 생성 | 종료 시각이 시작보다 늦고 종료일 생략 | `end_date=date` |
| 생성 | 다음 날 종료일 지정 | 종료 일시 기준 `ok=true` |
| 생성 실패 | 빈 제목 | 저장하지 않고 누락 필드 반환 |
| 생성 실패 | `2026-13-40` | 잘못된 날짜 반환 |
| 생성 실패 | `25:70` | 잘못된 시간 반환 |
| 생성 실패 | 종료가 시작보다 빠르고 종료일 생략 | 종료 날짜 확인 오류 반환 |
| 전체 조회 | 양쪽 날짜 경계 생략 | 현재 session 전체 반환 |
| 시작일 조회 | `date_from`만 전달 | 시작일 포함 이후 일정 반환 |
| 종료일 조회 | `date_to`만 전달 | 종료일 포함 이전 일정 반환 |
| 범위 조회 | 양쪽 경계 전달 | 경계 날짜를 포함한 결과 반환 |
| 삭제 | 존재하는 현재 session ID | `deleted=true` |
| 삭제 | 존재하지 않는 ID | `deleted=false` |

모든 결과에 대해 다음을 확인한다.

- 반환 타입이 `str`이다.
- `json.loads()`로 파싱할 수 있다.
- `tool_name`이 실제 함수명과 일치한다.

## 2. Session 격리 테스트

`conversation_session_scope("session-a")`에서 일정 A를 만들고
`conversation_session_scope("session-b")`에서 일정 B를 만든다.

검증:

- session A 조회에서는 A만 보인다.
- session B 조회에서는 B만 보인다.
- session A에서 B의 ID를 삭제해도 `deleted=false`다.
- 한 session의 삭제가 다른 session 일정에 영향을 주지 않는다.

직접 scope 없이 호출한 일정은 `_schedule_scope()` 규칙에 따라
`DEFAULT_SESSION_SCOPE`에 속하는지도 확인한다.

## 3. Agent 통합 시나리오

### 생성

```text
2026년 7월 3일 오후 2시부터 3시까지 민수와 프로젝트 회의 잡아줘.
```

기대:

- `personal_create_schedule` 호출
- 정규화된 날짜와 시간 전달
- trace에 `created_schedule` 표시

### 누락값 재질문

```text
프로젝트 회의 잡아줘.
```

기대:

- 날짜와 시작 시간을 요청
- 임의 날짜나 시간을 생성하지 않음
- 필요한 값이 채워지기 전 생성 tool을 호출하지 않음

후속 입력:

```text
7월 3일 오후 2시야.
```

기대:

- 이전 턴의 제목을 재사용
- 생성 tool 호출

### 조회

```text
7월 첫째 주 내 일정 보여줘.
```

기대:

- `personal_list_schedules` 호출
- 올바른 `date_from`, `date_to` 전달

### 명확한 삭제

조회 결과에 일정이 하나인 상태에서:

```text
그 프로젝트 회의 취소해줘.
```

기대:

- 필요한 경우 조회 후 실제 ID로 삭제
- 제목 문자열을 `schedule_id`로 전달하지 않음

### 모호한 삭제

동일 제목의 일정이 여러 개인 상태에서:

```text
회의 일정 삭제해줘.
```

기대:

- 후보 조회
- 임의 삭제 없이 사용자에게 날짜나 시간을 확인

### 비일정 요청

```text
안녕, 네가 할 수 있는 일을 알려줘.
```

기대:

- tool을 호출하지 않고 직접 답변

## 4. Trace 확인 항목

- `event="tool_call"`의 `tool_name`
- `arguments`에 전달된 날짜, 시간, ID
- `event="tool_result"`의 `content.ok`
- 생성의 `created_schedule`
- 조회의 `schedules`
- 삭제의 `deleted`
- 오류 발생 시 `missing_fields`, `invalid_fields`

## 5. 회귀 확인

- `week01_tools()`가 정확히 세 CRUD tool을 반환한다.
- `build_week_agent()`가 `build_week01_agent()` 연결을 유지한다.
- `list_personal_schedule_dicts()`가 조회 결과의 `schedules`를 읽을 수 있다.
- `ensure_demo_personal_schedule()`이 빈 저장소에서 정상 생성된다.
- `fixed/`와 `app.py` 수정 없이 동작한다.
