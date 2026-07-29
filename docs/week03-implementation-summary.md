# Week 3 (Nana's Logbook) 구현 정리

> `student_parts/week03_build_nanas_logbook.py` 구현을 4단계로 나눠 진행한 기록. 계획 원문은 `week03-implementation-plan.md`, 코드 구조 분석은 `week03-code-structure-analysis.md`, 초기 학습 메모는 `week03-learning-log.md` 참고.

## 개요

- **목표**: Week 2가 만든 구조화된 요청(`StructuredRequest`)을 SQLite에 실제로 저장하고, 조회·수정·삭제까지 되는 "영속 기록장"을 완성한다.
- **브랜치**: `jinmina/week3` (origin에 push 완료)

## 핵심 아키텍처 결정

| 구분 | Week 2 | Week 3 |
|---|---|---|
| agent 타입 | `response_format=ToolStrategy(Week02Response)` 구조화 응답 계약형 | `response_format` 없는 순수 ReAct 도구 호출형 (Week 1과 동일 패턴) |
| 구조화 위치 | agent의 **최종 응답** | `save_structured_request`의 **tool 호출 인자** (`args_schema`) + SQLite 컬럼 |
| 사용자에게 보이는 것 | `StructuredRequestBatch` 구조 자체 | 자연어 확인 답변 ("저장했어요") |

**근거**: `fixed/week_agent_registry.py`의 `agent.invoke({"messages": messages})` 호출과 `extract_final_text()`가 `structured_response`를 최우선으로 `repr()` 노출하는 동작, 그리고 week03 파일 주석에 `response_format` 언급이 전혀 없다는 점(grep 결과 0건)에서 확인.

---

## 1단계 — 프롬프트 계층 구현

**변경 파일**: `student_parts/prompts/week03.py`(신설), `student_parts/week03_build_nanas_logbook.py`

- `week03_prompt_parts()`가 `week02_prompt_parts()` 전체를 spread하던 방식을 제거하고, `common.py` / `week02.py` / `week03.py`에서 필요한 조각만 명시적으로 선택하도록 재작성.
- `WEEK02_SCOPE_PROMPT`("SQLite 저장을 하지 않는다")처럼 Week 3와 모순되는 문장은 애초에 선택하지 않음.
- `WEEK02_CLARIFICATION_STATE_PROMPT` / `WEEK02_STRUCTURED_OUTPUT_PROMPT`는 `Week02Response` 계약 언어가 섞여 있어 재사용하지 않고, 계약-무관 버전인 `WEEK03_FIELD_FILLING_PROMPT`를 새로 작성.
- 신규 상수 4개: `SQLITE_MEMORY_PROMPT`, `WEEK03_FIELD_FILLING_PROMPT`, `WEEK03_TOOL_CALL_PROMPT`, `WEEK03_SCOPE_PROMPT`.
- 부수 발견: `week03_tools()`가 Week 1의 세션 메모리 조회/삭제 tool과 Week 3의 SQLite 조회/삭제 tool을 동시에 노출하므로, "조회·삭제는 SQLite 버전을 우선 사용"하라는 규칙을 `WEEK03_TOOL_CALL_PROMPT`에 명시.

**커밋**: `feat: week03 시스템 프롬프트를 명시적 선택 구조로 구현` (`d7cd151`)

---

## 2단계 — 메인과제 tool 구현

**구현 대상**

- `SaveStructuredRequestInput.unwrap_legacy_payload` — `{"payload": {...}}` / `{"structured_request": {...}}` wrapper를 평평한 dict로 정규화
- `_save_input_from` — dict / JSON 문자열 / 자연어 / `StructuredRequest` / `SaveStructuredRequestInput` 어떤 입력이든 `SaveStructuredRequestInput`으로 통일
- `save_structured_request_payload` — 검증 후 `AppSQLiteStore.save_structured_request(...)` 호출
- `save_structured_request` (`@tool(args_schema=...)`) — Week 3 핵심 저장 tool
- `list_saved_requests` / `get_saved_request` — 원본 구조화 요청 조회
- `personal_list_saved_schedules` — 저장 일정 목록 조회 (기본 `kind="personal_schedule"`)

**검증**: 임시 SQLite 파일로 스모크 테스트 — 저장 → 목록 조회 → 단건 조회 → 존재하지 않는 id 조회(`row=None`) → 일정 저장 → 일정 목록 조회, 전부 통과.

**커밋**: `feat: week03 저장/조회 메인과제 tool 구현` (`78beb29`)

---

## 3단계 — 추가과제 tool + 조립부 구현

**구현 대상**

- `_delete_saved_schedules` — 삭제 조건이 전혀 없으면 `ok=False, error="no_delete_condition"`으로 거부하는 guard부터 확인 후 `delete_all` 또는 필터 삭제 수행
- `structured_request_from_week01_schedule` — Week 1 임시 일정 dict → Week 3 저장 입력 변환 (`end_time="미정"` → `None`)
- `personal_create_schedule` (Week 1 호환) — Week 1 임시 생성 + SQLite 이중 저장을 한 번에 수행
- `delete_saved_schedules_dict` / `personal_update_saved_schedule` / `personal_delete_saved_schedules`
- `build_week03_agent()` — `create_agent(model=chat_model(), tools=week03_tools(), system_prompt=week03_system_prompt())` (`response_format` 없음)

**검증 (스모크 테스트)**

- Week 1 호환 생성 시 `AppSQLiteStore`의 멱등성 처리를 활용해 Week 1 임시 id를 그대로 Week 3 `schedule_id`로 재사용하는 것 확인
- 조건 없는 삭제 요청 거부 확인
- 수정 성공/실패(없는 id) 케이스 확인
- `schedule_ids` 지정 삭제, `delete_all=True` 삭제 확인
- `week03_tools()` 조립 결과에 Week 1 메모리 tool과 SQLite tool이 의도대로 공존하는 것 확인

**커밋**: `feat: week03 추가과제 tool과 agent 조립부 구현` (`ab507f7`)

---

## 4단계 — 검증 및 문서화

**검증 결과**

| 항목 | 결과 |
|---|---|
| `py_compile` (전체 `student_parts/*.py`, `prompts/*.py`) | ✅ 통과 |
| 저장/조회/수정/삭제 SQL 로직 (스모크 테스트) | ✅ 통과 |
| tool 조립(`week03_tools()`) / 프롬프트 조립(`week03_system_prompt()`) | ✅ 통과 |
| 실제 LLM이 자연어 → tool 호출 순서·인자를 올바르게 만드는지 (`./run.sh --week3` 실사용 시나리오) | ⚠️ **미검증** — `.env`의 `PROXY_TOKEN` 만료(401 Authentication Error)로 실행 불가 |

**문서 커밋**: `docs: week03 구조 분석 및 구현 문서 추가` (`3281b3e`) — `week03-code-structure-analysis.md`, `week03-implementation-plan.md`, `week03-learning-log.md`

---

## 커밋 히스토리

| 커밋 | 메시지 |
|---|---|
| `d7cd151` | feat: week03 시스템 프롬프트를 명시적 선택 구조로 구현 |
| `78beb29` | feat: week03 저장/조회 메인과제 tool 구현 |
| `ab507f7` | feat: week03 추가과제 tool과 agent 조립부 구현 |
| `3281b3e` | docs: week03 구조 분석 및 구현 문서 추가 |

`origin/jinmina/week3`까지 push 완료.

---

## 남은 할 일 (체크리스트)

- [ ] `.env`의 `PROXY_TOKEN` 갱신
- [ ] `./run.sh --week3`에서 실제 시나리오 검증
  - [ ] "내일 10시 개인 코칭 저장해줘" → trace에서 `extract_schedule_request` 다음 `personal_create_schedule` 호출 확인
  - [ ] "내 일정 보여줘" → `personal_list_saved_schedules` 호출, 저장된 항목 확인
  - [ ] 새 대화/앱 재시작 후에도 저장된 일정이 유지되는지 확인
  - [ ] 저장된 일정 수정 요청 → `personal_update_saved_schedule` 반영 확인
  - [ ] 저장된 일정 삭제 요청 → `personal_delete_saved_schedules` 반영 확인
  - [ ] 조건 불명확한 삭제 요청 → 후보 확인 절차를 거치는지 확인
