# Week5 Eval Task 목록

골든 패스/경계 사례/회귀 방지/부정 사례는 `week4-tasks.md`를 그대로 이어받는다 (10개, 전부 여전히 유효). 이 파일에는 Week5에서 새로 생긴 기능(외부 SQLite/MCP의 이전 대화 검색·로드, 외부 멤버 일정 추출, 내 일정+외부 멤버 일정 통합, 공유 일정 저장소 조회·등록·삭제)에 대한 task만 추가한다.

TODO 구현 전에 먼저 정의한 task 목록이다 (`docs/evals/roadmap.md` Step 8, eval-driven development). LLM 라우팅이 관여하는 task는 `AgentRuntime(active_week=5).run_agent(...)`로 `./run.sh --week5`와 동일한 실행 경로를 코드에서 직접 호출해 2026-07-29에 실제 agent 대화로 검증했다(Gradio 없이 `fixed/agent_runtime.py`의 같은 진입점을 사용).

총 8개 (골든 5 / 경계 1 / 부정 1 / 추가과제 1) — 골든 5·부정 1·추가과제 1 PASS, 경계 1(B1)은 이번 라운드에서 미검증(아래 사유 참고).

---

## 골든 패스

### G1 — 외부 이전 대화 검색
- 입력: "철수가 예전에 API 연동 얘기한 적 있어?"
- 기대 결과: `search_previous_conversations(query="API 연동", member_names=["철수"], limit=5)`가 호출되고, 시드된 `ext_cs` 대화(철수의 "API 연동 실습" 발화)가 rows에 포함됨.
- 검증: 2026-07-29 `AgentRuntime(active_week=5).run_agent(...)` 실제 agent 대화로 확인. trace에 `search_previous_conversations` 1회만 호출, `rows`에 `conversation_id="ext_cs"` 포함. PASS.
- 분류: golden

### G2 — 특정 대화의 전체 메시지 로드, 순서 보존
- 입력: G1과 같은 대화에서 이어서 "그 대화 전체 내용 보여줘"
- 기대 결과: `load_conversation_messages(conversation_id="ext_cs")`가 호출되고, sender/content/created_at이 보존된 메시지가 반환됨.
- 검증: 2026-07-29 동일 세션으로 확인. trace에 `load_conversation_messages` 호출, `rows`에 `sender="철수"`, 원본 content 그대로. PASS.
- 분류: golden

### G3 — 외부 멤버 이전 대화에서 일정/바쁜 시간 추출
- 입력: "철수랑 영희 7월 7일부터 17일까지 일정 좀 알려줘"
- 기대 결과: 철수/영희의 시드된 busy-time(7/7, 7/9, 7/10, 7/15, 7/16)이 member_name/title/date/start_time/end_time 필드 그대로 응답에 반영됨.
- 검증: 2026-07-29 확인. agent가 `extract_schedules_from_history`를 직접 부르지 않고 `collect_member_schedules(member_names=["철수","영희"], date_from="2026-07-07", date_to="2026-07-17")`를 호출(내부적으로 `extract_schedules_from_history` 결과를 그대로 사용하므로 필드 구조는 동일). 응답에 6건 일정 전부 정확히 나열됨. PASS(라우팅은 예상과 다르지만 최종 결과는 기대와 일치 — `docs/evals/roadmap.md` Step5 "흐름보다 결과에 집중" 원칙에 따라 PASS 처리).
- 분류: golden

### G4 — 내 일정 + 외부 멤버 일정 통합 (`collect_member_schedules`)
- 입력: "나랑 철수, 영희 다같이 언제 시간 되는지 확인해줘, 7월 7일부터 17일까지"
- 기대 결과: 반환 rows에 "나"의 일정과 철수/영희 busy-time이 같은 필드 구조로 섞여 있고, 겹치는 시간대가 없으면 그렇게 안내함.
- 검증: 2026-07-29 확인. `collect_member_schedules` 호출, rows에 `member_name="나"` 항목과 철수/영희 항목이 동일 구조로 포함. 응답이 "이 외 시간대는 세 분 모두 일정이 비어 있습니다"로 정확히 안내함. PASS.
- 분류: golden

### G5 — 공유 일정 저장소 조회 (`list_shared_schedules`)
- 입력: "공유 일정 저장소에 등록된 거 다 보여줘"
- 기대 결과: 공유 일정 저장소 rows가 반환됨 (필터 없으면 외부 실습용 기본 row가 우선 반환될 수 있음 — 파일 가이드 87~90행 참고).
- 검증: 2026-07-29 확인. `list_shared_schedules()` 인자 없이 호출, 시드된 6명(철수/영희/민준/서연/지훈/하린) 일정이 날짜순으로 전부 반환됨. PASS.
- 분류: golden

---

## 경계 사례

### B1 — SQLite 저장 일정과 현재 대화 임시 일정 중복 제거
- 입력: 어떤 일정을 SQLite에 저장한 뒤(Week3+ 자동 동기화), 같은 일정이 `PERSONAL_SCHEDULES`(Week1 임시 저장소)에도 남아 있는 상태에서 `_personal_schedules_for_current_scope()` 호출.
- 기대 결과: 그 일정이 두 번이 아니라 한 번만 나온다 (`schedule_id`/`id` 기준으로 걸러짐).
- 검증: 미검증. 코드 리뷰로 로직은 확인함(`fixed/app_store.py:353`의 `schedule_id = source_schedule_id or new_id("sch")`로 SQLite `schedule_id`가 원래 임시 `id`와 동일해짐을 튜터링 중 직접 추적) — `save_structured_request(..., source_schedule_id=schedule["id"])` 흐름을 격리된 SQLite 경로로 재현하는 별도 테스트가 필요해 이번 라운드에서는 스킵. 다음에 진행.
- 분류: boundary

---

## 부정 사례 (agent 전체 대화로만 검증 가능)

### N1 — 인사말에 Week5 외부 검색/일정 tool이 오발동 안 함
- 입력: `"안녕"`
- 기대 결과: `search_previous_conversations`/`load_conversation_messages`/`extract_schedules_from_history`/`list_shared_schedules`/`collect_member_schedules` 중 어느 것도 호출되지 않고 인사로만 응답.
- 검증: 2026-07-29 확인. trace의 `events`가 빈 리스트 — tool 호출 없이 인사로만 응답. PASS.
- 분류: negative

---

## 추가과제 (구현 시에만 적용)

### E1 — 공유 일정 등록 후 조회에 나타나고, 삭제 후 사라짐
- 입력: "철수랑 8월 5일 14시에 회의 일정 공유 저장소에 등록해줘" → "방금 등록한 공유 일정 목록에 있는지 확인해줘" → "방금 그 일정 삭제해줘" → "다시 목록 확인해줘, 방금 삭제한 거 빠졌는지"
- 기대 결과: 등록 직후 조회에 나타나고, 삭제 후에는 더 이상 나타나지 않음. `schedule_id`가 등록 시점과 동일하게 유지됨.
- 검증: 2026-07-29 확인. **최초 실행에서 버그 발견 후 수정** — `list_shared_schedules()`를 필터 없이 부르면 기본 날짜 범위(2026-07-07~07-17)만 조회돼 8월 일정이 안 보였고, agent가 이를 "미등록"으로, 나중엔 "삭제됨"으로 잘못 판단함(`docs/troubleshooting/week5.md` 참고). `week05_prompt_parts()`에 필터 명시 규칙과 schedule_id 재사용 규칙을 추가한 뒤 재실행: `create_shared_schedule` → `list_shared_schedules(member_names=["철수"], date_from="2026-08-05", date_to="2026-08-05")`로 정확히 확인 → 올바른 schedule_id로 `delete_shared_schedule` → 최종 확인에서 정상적으로 "빠져 있음" 응답. PASS.
- 분류: golden (추가과제)
