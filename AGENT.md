# Week 1 Nana 구현 계획

이 문서는 `student_parts/week01_wake_up_nana.py`를 구현하는 순서와 각 단계의 완료 기준을 정의한다.
세부 설계와 예시는 `docs/` 문서를 따른다.

## 목표

- 현재 대화 범위에서만 유지되는 개인 일정 생성·조회·삭제 tool을 완성한다.
- LLM이 사용자의 의도에 맞는 tool을 선택하고, 필요한 값이 부족하면 추측하지 않고 추가로 질문하게 한다.
- tool의 성공·실패 결과를 일관된 JSON 문자열로 반환하여 trace에서 확인할 수 있게 한다.
- Week 1 범위를 지켜 SQLite나 이후 주차 저장소에는 일정을 저장하지 않는다.

## 구현 원칙

1. system prompt는 agent 전체의 행동 원칙과 tool 조합 순서만 설명한다.
2. 각 tool의 docstring은 해당 tool의 선택 조건과 인자 의미를 설명한다.
3. 함수 시그니처는 필수값, 선택값, 타입을 표현한다.
4. Python 코드는 입력 형식과 값 사이의 관계를 최종 검증한다.
5. 성공 payload의 기존 계약인 `created_schedule`, `schedules`, `deleted`를 유지한다.
6. 모든 tool 결과는 `_json(...)`을 사용한 JSON 문자열로 반환한다.

## 구현 순서

### 1. 반환 계약과 일정 데이터 구조 확정

- 일정 dict의 필드를 확정한다.
- 성공 및 입력 오류 payload 형식을 확정한다.
- `session_id`가 저장·조회·삭제 전 과정에 포함되는지 확인한다.

완료 기준:

- 생성, 조회, 삭제의 예상 입출력 JSON을 설명할 수 있다.
- SQLite 저장 데이터와 Week 1 임시 일정의 차이를 설명할 수 있다.

세부 문서: [docs/week01-data-and-tool-contracts.md](docs/week01-data-and-tool-contracts.md)

### 2. CRUD tool 본문 구현

- `personal_create_schedule`에서 현재 session의 일정을 생성한다.
- `personal_list_schedules`에서 현재 session 일정만 날짜 범위로 조회한다.
- `personal_delete_schedule`에서 현재 session의 일치하는 ID만 삭제한다.
- 삭제 시 `PERSONAL_SCHEDULES[:]` 슬라이스 대입으로 리스트 객체를 유지한다.

완료 기준:

- 직접 `.invoke()`했을 때 세 tool이 JSON 문자열을 반환한다.
- 다른 session의 일정이 조회되거나 삭제되지 않는다.
- 조회가 원본 리스트를 변경하지 않는다.

### 3. 입력 검증 helper 구현

- 필수 문자열의 공백 입력을 검사한다.
- 날짜가 실제 `YYYY-MM-DD` 날짜인지 검사한다.
- 시간이 실제 `HH:MM` 시간인지 검사한다.
- 종료 시간이 있으면 시작 시간보다 늦은지 검사한다.
- 실패 시 저장하지 않고 구조화된 오류를 반환한다.

완료 기준:

- 잘못된 날짜와 시간은 `ok: false`로 반환된다.
- 오류 결과가 `missing_fields`와 `invalid_fields`로 재질문 대상을 알려준다.
- 유효하지 않은 입력으로 `PERSONAL_SCHEDULES`가 변경되지 않는다.

세부 문서: [docs/week01-input-validation.md](docs/week01-input-validation.md)

### 4. tool docstring 개선

- 생성, 조회, 삭제 각각의 사용 시점을 적는다.
- 날짜와 시간 등 인자 형식을 적는다.
- 삭제 tool에는 정확한 `schedule_id`가 필요함을 적는다.
- 구현 방식처럼 LLM의 선택에 불필요한 세부사항은 넣지 않는다.

완료 기준:

- 함수명, docstring, 타입 힌트만 보고도 tool의 목적과 필수 인자를 구분할 수 있다.

### 5. system prompt 작성

- 생성·조회·삭제 의도를 각 tool에 연결한다.
- tool 호출 전 필수 인자를 확인하도록 한다.
- 누락되거나 모호한 값은 추측하지 않고 필요한 항목만 한 번에 질문하게 한다.
- tool의 `ok: false` 결과를 읽고 필요한 값을 재질문하게 한다.
- 삭제 ID가 없으면 조회 후 삭제하도록 순서를 지정한다.
- 일정과 무관한 요청에는 tool을 호출하지 않도록 한다.

완료 기준:

- 프롬프트가 개별 예외 목록이 아니라 일반적인 판단 규칙 중심이다.
- tool docstring과 system prompt의 역할이 불필요하게 중복되지 않는다.
- 상대 날짜 계산 기준으로 `current_app_date_iso()`가 제공된다.

세부 문서: [docs/week01-agent-prompt.md](docs/week01-agent-prompt.md)

### 6. 직접 tool 검증

- API 키 없이 각 tool을 `.invoke()`하여 정상 CRUD를 확인한다.
- 날짜 경계와 실패 입력을 확인한다.
- `conversation_session_scope(...)`로 두 session을 만들어 격리를 확인한다.

완료 기준:

- 문서의 테스트 행렬을 모두 통과한다.
- 반환 문자열을 `json.loads()`로 파싱할 수 있다.

### 7. agent 통합 검증

- `./run.sh --week1`로 앱을 실행한다.
- 생성, 조회, 삭제, 누락값 재질문, 모호한 삭제 요청을 채팅으로 확인한다.
- trace의 `tool_call.arguments`와 `tool_result.content`를 확인한다.

완료 기준:

- 요청 의도에 맞는 tool이 선택된다.
- 정보가 부족할 때 임의 값을 만들거나 tool을 성급히 호출하지 않는다.
- 성공하지 않은 작업을 성공했다고 답하지 않는다.

세부 문서: [docs/week01-test-plan.md](docs/week01-test-plan.md)

## 작업 범위

기본 수정 대상:

- `student_parts/week01_wake_up_nana.py`

계획 및 검증 문서:

- `AGENT.md`
- `docs/week01-data-and-tool-contracts.md`
- `docs/week01-input-validation.md`
- `docs/week01-agent-prompt.md`
- `docs/week01-test-plan.md`

수정하지 않을 대상:

- `fixed/` 아래의 런타임, 저장소, trace 기준 코드
- `app.py`
- Week 2 이후 기능

