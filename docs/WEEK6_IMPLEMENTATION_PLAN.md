# Week 6 메인 과제 구현 계획

## 1. 목표

Week 6의 단일 agent 구조를 supervisor와 Nana/Kana 하위 agent 구조로 분리한다.

- supervisor는 사용자 업무를 직접 처리하지 않고 Nana 또는 Kana에 위임한다.
- Nana는 개인 일정·저장·개인 RAG를 담당한다.
- Kana는 외부 멤버의 이전 대화·일정과 공유 일정 조회를 담당한다.
- 각 하위 agent의 실제 tool 호출과 결과를 trace에서 확인할 수 있게 한다.

## 2. 시작 상태

- 작업 브랜치: `junyoung/week6`
- `junyoung/final`에는 Week 5 PR과 최신 강의자료가 반영되어 있다.
- `student_parts/week06_kanamate_decides_schedule.py`는 강의자료의 초기 stub 상태로 롤백했다.
- `student_parts/week05_load_kanas_past_conversations.py`에는 공지 A~E 패치만 남아 있다.
- `fixed/`, `run.sh`, baseline 파일은 수정하지 않는다.

## 3. 과제 범위

### 포함하는 메인 과제

1. supervisor/Nana/Kana 역할별 system prompt 작성
2. `nana_agent` 위임 wrapper 구현
3. `kana_agent` 위임 wrapper 구현
4. 역할별 tool 목록 구성과 경계 검증
5. 하위 agent의 answer, trace, 내부 tool 이름 반환
6. supervisor trace에서 선택된 하위 agent와 내부 tool 호출 확인
7. agent 객체를 한 번 생성한 뒤 재사용하는 cache 연결

### 제외하는 추가 과제

다음 항목은 구현하지 않는다.

- `FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION`
- `DECIDE_FINAL_SLOT_DESCRIPTION`
- `find_common_available_slots_dict`
- `find_common_available_slots`
- `decide_final_slot`
- Kana가 공통 가능 시간 후보를 만들거나 최종 시간을 확정하는 흐름

추가 과제 tool이 미완성 상태로 호출되지 않도록 `kana_tools()`에서
`find_common_available_slots`와 `decide_final_slot`을 제외한다. Kana prompt에서도 두 tool을
언급하지 않는다.

## 4. 역할과 tool 경계

### Supervisor

노출 tool은 다음 두 개로 제한한다.

- `nana_agent`
- `kana_agent`

Supervisor는 사용자 요청을 직접 해결하지 않고 다음 기준으로 위임한다.

- 개인 일정 CRUD, 할 일·알림 저장, 개인 참고자료, 앱 내부 대화 검색 → Nana
- 외부 멤버의 이전 대화, 외부 busy-time, 공유 일정 row, 내 일정과 외부 일정 통합 조회 → Kana
- 이미 날짜와 시간이 정해진 일정의 앱 DB 저장 → Nana
- 여러 사람의 공통 가능 시간 계산 및 최종 시간 확정 → 이번 범위에서 지원하지 않음을 설명

### Nana

`week04_tools()`를 그대로 사용한다.

- 개인 일정 생성·조회·수정·삭제
- 일정·할 일·알림 구조화 및 SQLite 저장
- 개인 참고자료 RAG
- 앱 내부 대화 RAG

외부 멤버 일정이나 공유 저장소를 추측하거나 조회하지 않는다.

### Kana

다음 main tool만 사용한다.

- `extract_schedule_request`
- `search_previous_conversations`
- `load_conversation_messages`
- `extract_schedules_from_history`
- `list_shared_schedules`
- `collect_member_schedules`

Kana는 조회된 rows와 `schedule_summary`를 근거로 외부 일정 정보를 설명한다. 공통 후보를
계산하거나 최종 회의 시간을 확정하지 않는다.

## 5. Prompt 구현 계획

### `week06_prompt_parts()`

- `week05_prompt_parts()`를 누적한다.
- Week 6에서는 supervisor 역할이 우선한다는 점을 명확히 한다.
- 개인 영역과 외부 멤버 영역의 위임 기준을 적는다.

### `nana_prompt_parts()`

- `week04_prompt_parts()`를 누적한다.
- Nana가 개인 일정·저장·RAG만 담당하도록 범위를 제한한다.
- 외부 멤버 일정 요청을 직접 처리하지 않게 한다.

### `kana_prompt_parts()`

- 이전 주차 prompt를 누적하지 않고 Kana의 역할을 처음부터 작성한다.
- 현재 날짜를 기준으로 상대 날짜를 ISO 날짜로 해석하게 한다.
- 외부 대화 검색 시 `query`와 `member_names`를 분리하게 한다.
- 외부 일정만 필요하면 `extract_schedules_from_history`, 내 일정까지 필요하면
  `collect_member_schedules`를 사용하게 한다.
- 추가 과제 tool이나 최종 시간 확정을 지시하지 않는다.

### `supervisor_system_prompt()`

- 반드시 Nana 또는 Kana 중 하나를 호출한 뒤 그 결과만 근거로 답하게 한다.
- 하위 agent 결과가 비어 있거나 실패한 경우 성공으로 추측하지 않게 한다.
- 요청 범위가 메인 과제를 넘으면 지원 범위를 설명하게 한다.

## 6. Wrapper 반환 계약

### `nana_agent(query)`

Nana 하위 agent를 실행하고 다음 JSON 문자열을 반환한다.

- `selected_agent`: `"nana_agent"`
- `answer`: 하위 agent의 최종 답변
- `trace`: 하위 agent의 tool call/result event 목록
- `inner_tool_names`: 호출된 내부 tool 이름 목록

### `kana_agent(query)`

Kana 하위 agent를 실행하고 다음 JSON 문자열을 반환한다.

- `selected_agent`: `"kana_agent"`
- `answer`: 하위 agent의 최종 답변
- `trace`: 하위 agent의 tool call/result event 목록
- `inner_tool_names`: 호출된 내부 tool 이름 목록
- `final_slot_payload`: 추가 과제를 구현하지 않으므로 `null`
- `final_decision_payload`: 추가 과제를 구현하지 않으므로 `null`

두 wrapper 모두 `extract_agent_events()`와 `extract_final_text()`를 사용하고 한글을 보존하는
JSON 문자열을 반환한다.

## 7. 구현 순서

1. 역할별 prompt 네 곳을 작성한다.
2. `kana_tools()`에서 추가 과제 tool 두 개를 제외한다.
3. `nana_agent`를 구현하고 Week 4 tool/cache/trace 연결을 확인한다.
4. `kana_agent`를 구현하고 main tool/cache/trace 연결을 확인한다.
5. supervisor가 위임 wrapper 두 개만 노출하는지 확인한다.
6. 정적 검사와 자동 테스트를 통과시킨다.
7. 실제 앱에서 Nana/Kana 라우팅과 내부 tool argument를 trace로 확인한다.
8. 전체 diff를 코드 리뷰한 뒤 모든 변경을 한 번에 커밋한다.

## 8. 검증 계획

### 정적·자동 검증

- Week 6 파일에 메인 과제 대상 `TODO`나 `...`가 남지 않았는지 확인
- 추가 과제 함수는 stub으로 유지되고 `kana_tools()`에 노출되지 않는지 확인
- `supervisor_tools()`가 `nana_agent`, `kana_agent`만 반환하는지 확인
- Nana tool 목록에 Week 4 개인 저장/RAG tool이 포함되는지 확인
- Kana tool 목록에 Week 5 외부 조회 tool만 포함되는지 확인
- 가짜 LangChain message로 wrapper의 answer/trace/inner tool 반환 검증
- Week 5 공지 패치의 그룹 일정 포함과 `"나"` 중복 제거 회귀 검증
- Ruff, format check, compileall, `git diff --check`, unittest 실행

### 실제 앱 trace 검증

수업용 proxy token 사용을 확인한 뒤 `./run.sh --week6`으로 실행한다.

1. 개인 일정 조회
   - 예시: `이번 주 내 일정 보여줘`
   - 기대: supervisor → `nana_agent`
   - Nana 내부 trace: `personal_list_saved_schedules`
2. 외부 멤버 일정 조회
   - 예시: `하린과 민준의 이번 주 바쁜 시간 보여줘`
   - 기대: supervisor → `kana_agent`
   - Kana 내부 trace: `extract_schedules_from_history` 또는 `collect_member_schedules`
3. 공유 일정 row 조회
   - 예시: `공유 일정 저장소에 등록된 일정 보여줘`
   - 기대: supervisor → `kana_agent`
   - Kana 내부 trace: `list_shared_schedules`
4. 추가 과제 범위 요청
   - 예시: `하린과 민준의 공통 회의 시간을 확정해줘`
   - 기대: `find_common_available_slots`와 `decide_final_slot`을 호출하지 않음
   - 최종 답변: 조회 가능한 busy-time과 이번 구현 범위를 구분해 설명

각 사례에서 supervisor tool 이름, wrapper에 전달된 `query`, 내부 tool arguments, tool result rows,
최종 답변의 근거 일치 여부를 확인한다.

## 9. 변경 파일 계획

제출 변경은 다음 파일로 제한한다.

- `student_parts/week05_load_kanas_past_conversations.py`: 공지 A~E 패치
- `student_parts/week06_kanamate_decides_schedule.py`: Week 6 메인 과제
- `docs/WEEK6_IMPLEMENTATION_PLAN.md`: 본 계획과 검증 기준

로컬 자동 테스트는 저장소의 기존 `.gitignore` 정책에 따라 제출 대상에 포함하지 않는다.

## 10. 완료 기준

- supervisor가 직접 업무 tool을 갖지 않는다.
- 개인 요청은 Nana, 외부 멤버/공유 일정 요청은 Kana로 위임된다.
- 하위 trace에서 실제 내부 tool 이름과 arguments를 확인할 수 있다.
- 추가 과제 tool 두 개가 Kana에 노출되지 않는다.
- 최종 시간 확정을 구현하거나 성공한 것처럼 답하지 않는다.
- Week 5 패치와 기존 Week 1~4 기능 회귀 테스트가 통과한다.
- 변경 파일 정적 검사와 diff 검증이 통과한다.
- 전체 변경을 하나의 커밋으로 만든다.
