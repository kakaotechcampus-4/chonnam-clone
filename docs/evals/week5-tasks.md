# Week5 Eval Task 목록

골든 패스/경계 사례/회귀 방지/부정 사례는 `week4-tasks.md`를 그대로 이어받는다 (10개, 전부 여전히 유효). 이 파일에는 Week5에서 새로 생긴 기능(외부 SQLite/MCP의 이전 대화 검색·로드, 외부 멤버 일정 추출, 내 일정+외부 멤버 일정 통합, 공유 일정 저장소 조회·등록·삭제)에 대한 task만 추가한다.

TODO 구현 전에 먼저 정의한 task 목록이다 (`docs/evals/roadmap.md` Step 8, eval-driven development). 각 task의 "검증"은 Week5 구현 완료 후 `./run.sh --week5` 실제 agent 대화 또는 격리된 store로 직접 호출해 채운다 — 지금은 전부 미검증.

총 8개 (골든 5 / 경계 1 / 부정 1 / 추가과제 1) — 구현 전, 전부 미검증.

---

## 골든 패스

### G1 — 외부 이전 대화 검색
- 입력: `search_previous_conversations(query="게임", member_names=["철수"], limit=5)`
- 기대 결과: `call_mcp_tool_sync("search_previous_conversations", ...)` 결과 문자열이 그대로 반환됨 (wrapper에서 멤버 이름 재정규화 안 함).
- 검증: (Week5 구현 완료 후 진행 예정)
- 분류: golden

### G2 — 특정 대화의 전체 메시지 로드, 순서 보존
- 입력: G1에서 찾은 `conversation_id`로 `load_conversation_messages(conversation_id=...)` 호출.
- 기대 결과: sender/content/created_at이 원본 순서 그대로인 메시지 목록이 JSON으로 반환됨.
- 검증: (Week5 구현 완료 후 진행 예정)
- 분류: golden

### G3 — 외부 멤버 이전 대화에서 일정/바쁜 시간 추출
- 입력: `extract_schedules_from_history(member_names=["철수"], date_from="2026-08-01", date_to="2026-08-07")`
- 기대 결과: rows에 member_name/title/date/start_time/end_time/notes 필드가 모두 유지됨.
- 검증: (Week5 구현 완료 후 진행 예정)
- 분류: golden

### G4 — 내 일정 + 외부 멤버 일정 통합 (`collect_member_schedules`)
- 입력: 내 SQLite 저장 일정 1건 + 현재 대화 임시 일정(`PERSONAL_SCHEDULES`) 1건이 있는 상태에서 `collect_member_schedules(member_names=["철수"], date_from=..., date_to=...)` 호출.
- 기대 결과: 반환 rows에 "나"의 두 일정(SQLite+임시, 중복 없이)과 외부 멤버 busy-time이 같은 필드 구조로 섞여 있고, `schedule_summary` 문자열도 함께 반환됨.
- 검증: (Week5 구현 완료 후 진행 예정)
- 분류: golden

### G5 — 공유 일정 저장소 조회 (`list_shared_schedules`)
- 입력: `list_shared_schedules()` (필터 없음)
- 기대 결과: 공유 일정 저장소 rows가 반환됨 (필터 없으면 외부 실습용 기본 row가 우선 반환될 수 있음 — 파일 가이드 87~90행 참고).
- 검증: (Week5 구현 완료 후 진행 예정)
- 분류: golden

---

## 경계 사례

### B1 — SQLite 저장 일정과 현재 대화 임시 일정 중복 제거
- 입력: 어떤 일정을 SQLite에 저장한 뒤(Week3+ 자동 동기화), 같은 일정이 `PERSONAL_SCHEDULES`(Week1 임시 저장소)에도 남아 있는 상태에서 `_personal_schedules_for_current_scope()` 호출.
- 기대 결과: 그 일정이 두 번이 아니라 한 번만 나온다 (`schedule_id`/`id` 기준으로 걸러짐).
- 검증: (Week5 구현 완료 후 진행 예정)
- 분류: boundary

---

## 부정 사례 (agent 전체 대화로만 검증 가능)

### N1 — 인사말에 Week5 외부 검색/일정 tool이 오발동 안 함
- 입력: `"안녕"`
- 기대 결과: `search_previous_conversations`/`load_conversation_messages`/`extract_schedules_from_history`/`list_shared_schedules`/`collect_member_schedules` 중 어느 것도 호출되지 않고 인사로만 응답.
- 검증: (Week5 구현 완료 후 `./run.sh --week5` 실제 trace로 진행 예정)
- 분류: negative

---

## 추가과제 (구현 시에만 적용)

### E1 — 공유 일정 등록 후 조회에 나타나고, 삭제 후 사라짐
- 입력: `create_shared_schedule(member_name="철수", title="회의", date="2026-08-05", start_time="14:00")` 호출 후 `list_shared_schedules()`로 확인, 이후 `delete_shared_schedule(schedule_id=...)` 호출 후 다시 `list_shared_schedules()`로 확인.
- 기대 결과: 등록 직후 조회에 나타나고, 삭제 후에는 더 이상 나타나지 않음. `schedule_id`/`source_conversation_id`가 등록 시점과 동일하게 유지됨.
- 검증: (추가과제 구현 시 진행 예정 — 구현 안 하면 이 task는 skip)
- 분류: golden (추가과제)
