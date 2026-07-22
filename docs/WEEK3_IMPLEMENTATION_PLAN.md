# Week 3 구현 계획 — 구조화 결과를 SQLite에 저장·조회 (Nana의 기록장)

> 대상 파일: `student_parts/week03_build_nanas_logbook.py`
> 이 문서는 구현 전 계획서다. 이번엔 메인 + 추가(수정/삭제/Week1 호환 생성/레거시 정규화)까지 **전부 구현**한다.

---

## 0. 한눈에 보기

Week2가 "말 → `StructuredRequest`(구조화)"까지였다면, Week3는 그 결과를 **SQLite에 저장**하고 **다시 조회/수정/삭제**한다. Nana가 Week1의 임시 메모리 대신 앱 DB에 남는 **"기록장"**을 갖게 되는 주차다.

핵심 흐름:
```
사용자 요청
  └─▶ LLM이 extract_schedule_request(query)로 자연어를 StructuredRequest로 구조화 (Week2 재사용)
        └─▶ save_structured_request(@tool, args_schema로 검증) 호출
              └─▶ AppSQLiteStore.save_structured_request(payload) 로 SQLite 저장
                    └─▶ 이후 personal_list_saved_schedules로 조회 (앱 재시작·새 대화에도 유지)
```

---

## 1. 과제 범위

- **메인 과제**: `save_structured_request`, `list_saved_requests`, `get_saved_request`, `personal_list_saved_schedules` + 프롬프트 3곳 + `build_week03_agent`. → **"저장 → 조회 → 새 대화에서도 유지"**가 되는 최소 기록장.
- **추가 과제**: `personal_update_saved_schedule`, `personal_delete_saved_schedules`(+`_delete_saved_schedules` guard), `personal_create_schedule`(Week1 호환)+`structured_request_from_week01_schedule`, 레거시 정규화(`unwrap_legacy_payload`/`_save_input_from`/`save_structured_request_payload`), `delete_saved_schedules_dict`.

---

## 2. 사전 확인 — 연동 지점 (모두 검증함)

- **registry/실행**: `fixed/week_agent_registry.py`가 week 3 → 이 모듈, `build_week_agent()` 표준 진입점. `./run.sh --week3` 지원 확인.
- **저장소**: `fixed/app_store.py`의 `AppSQLiteStore`. `_store()` = `AppSQLiteStore(CONFIG.app_db_path)` (`DATA_DIR/kanana_app.sqlite3`). tool은 store 메서드를 부르는 **얇은 입구** 역할만.
- **재사용 import**: Week1(`join_system_prompt`, `week01_personal_create_schedule`, `week01_tools`), Week2(`RequestKind`, `StructuredRequest`, `extract_schedule_request`, `extract_structured_request`, `week02_prompt_parts`).
- **AppSQLiteStore 메서드 시그니처** (본문에서 그대로 호출):
  - `save_structured_request(payload: dict) -> dict` — kind에 따라 `structured_requests` + `schedules`/`todos`/`reminders`에 저장, 개인/그룹 일정은 외부 공유 저장소에도 복사.
  - `list_saved_requests(kind=None, date_from=None, date_to=None, limit=20) -> list[dict]`
  - `get_saved_request(request_id) -> dict | None`
  - `list_schedules(limit=12, kind=None, date_from=None, date_to=None) -> list[dict]`
  - `update_schedule(schedule_id, title=None, date=None, start_time=None, end_time=None, attendees=None) -> dict | None`
  - `find_schedules(schedule_ids, date, title, start_time, time_unspecified, limit=100)` — 삭제/수정 전 후보 좁히기
  - `delete_schedule(schedule_id) -> dict | None`
  - `delete_schedules_by_filter(schedule_ids, date, title, start_time, time_unspecified, limit=100) -> list[dict]`
  - `delete_all_schedules() -> list[dict]`
- **반환 규칙**: 모든 `@tool`은 **JSON 문자열** 반환. `ok`+`tool_name` 기본, 조회는 `rows`/`row`, 삭제는 `deleted_count`/`filters`/`deleted` 유지. 이미 있는 `json_payload()`/`tool_result()` helper 사용.

---

## 3. 구현 순서 (메인 먼저 — 의존성 순)

### Step 1 — `save_structured_request` (@tool, args_schema=SaveStructuredRequestInput) [메인 핵심]
- args_schema가 입력을 이미 검증하므로 **본문에서 Pydantic 재생성 금지**.
- 함수 인자(kind/title/date/start_time/end_time/members/priority/reason/original_text/source_schedule_id)를 dict로 모으고 **None 값 제외** → `_store().save_structured_request(payload)`.
- `tool_result("save_structured_request", ok=True, **저장결과)` → `json_payload(...)` 반환.
- 자연어 문자열이나 `ok/tool_name/base_date` wrapper를 직접 저장하지 않는다.

### Step 2 — `list_saved_requests` / `get_saved_request` [메인]
- list: `_store().list_saved_requests(kind, date_from, date_to)` → `rows`.
- get: `_store().get_saved_request(request_id)` → `row`(없으면 `None` 유지, 예외 X).
- 둘 다 `ok/tool_name` + `rows`/`row` JSON 문자열.

### Step 3 — `personal_list_saved_schedules` [메인]
- 기본 `kind`를 `"personal_schedule"`로 두고 `_store().list_schedules(limit, kind, date_from, date_to)`.
- `filters`(적용한 조건)와 `schedules`(결과)를 담아 JSON 반환. limit으로 과다 조회 방지.

### Step 4 — 프롬프트 (`SQLITE_MEMORY_PROMPT`, `WEEK03_TOOL_CALL_PROMPT`, `week03_prompt_parts`) [메인]
- `SQLITE_MEMORY_PROMPT`: "일정/할 일/알림은 SQLite에 영속 저장되어 **새 대화·앱 재시작에도 조회 가능**"이라는 규칙.
- `WEEK03_TOOL_CALL_PROMPT`: 저장 요청은 `extract_schedule_request`로 구조화 → `save_structured_request`로 저장, 조회는 `personal_list_saved_schedules`/`list_saved_requests` 순서 안내.
- `week03_prompt_parts`: `*week02_prompt_parts()` 상속 + 위 두 규칙 + (현재 날짜 기준·tool 선택 기준·이번 주 범위=저장/조회, 수정·삭제는 추가) 지시.

### Step 5 — `build_week03_agent` [메인]
- `CONFIG.has_openai_key` 없으면 `RuntimeError`.
- 전역 `_WEEK03_AGENT` 재사용, 없을 때만 `create_agent(model=chat_model(), tools=week03_tools(), system_prompt=week03_system_prompt())`.
- **`response_format` 없음** (Week2와 차이). Week3 agent는 tool로 저장/조회하고 최종 답은 자연어. `week03_tools()`는 이미 구현돼 있음(Week1+2+3 tool 조립).
- → **여기까지가 메인.** `./run.sh --week3` 검증(§5).

### Step 6+ — 추가 과제
- `personal_update_saved_schedule`: `None`=미변경. `_store().update_schedule(...)`; 못 찾으면 `ok=False`, 찾으면 `updated_schedule`+`shared_sync` 반환.
- `_delete_saved_schedules`(guard) + `personal_delete_saved_schedules`: 조건 전부 비면 **거부**(ok=False). `delete_all`이면 `delete_all_schedules()`, 아니면 `delete_schedules_by_filter(...)`. `deleted_count`/`filters`/`deleted` 반환.
- `structured_request_from_week01_schedule` + `personal_create_schedule`(호환): week01 임시 생성 → 변환(`attendees`→`members`, `id`→`source_schedule_id`) → SQLite 저장. `created`+`structured_request`+`sqlite_save` 합쳐 반환.
- 레거시 정규화: `unwrap_legacy_payload`(payload/structured_request wrapper 풀기), `_save_input_from`(dict/JSON/자연어/StructuredRequest → `SaveStructuredRequestInput`; 자연어면 `extract_structured_request` 먼저), `save_structured_request_payload`, `delete_saved_schedules_dict`.

---

## 4. 주의·설계 포인트

- `@tool(args_schema=...)`가 검증을 끝냈으니 본문은 **store 호출 + 응답 정리**만(얇게).
- 저장 dict는 **None 필드 제외**하고 구성.
- 조회 결과가 없어도 **예외 금지** — `rows=[]` / `row=None` 유지.
- 삭제는 **안전 guard 필수** — 조건 없으면 거부, 전체 삭제는 `delete_all` 명시일 때만.
- `week03_tools()`는 Week1의 `personal_create_schedule`을 Week3 호환 버전으로 교체하고, `personal_update_saved_schedule`·`personal_delete_saved_schedules`도 함께 노출한다. **이 3개(생성/수정/삭제)를 이번에 모두 구현**하므로 노출된 도구 중 스텁이 남지 않는다.

---

## 5. 검증 계획

**메인**: `./run.sh --week3` → `"내일 10시 개인 코칭 저장해줘"` 입력 → trace에서 `extract_schedule_request` → `save_structured_request` 순서 확인 → `"내 일정 보여줘"` → `personal_list_saved_schedules` 조회 → **앱 재시작/새 대화에도 저장 유지**되면 메인 통과.
**추가**: 저장 후 `personal_list_saved_schedules`로 `schedule_id` 확인 → `personal_update_saved_schedule`로 시간 변경 → `personal_delete_saved_schedules`(schedule_ids/필터)로 삭제되어 목록에서 사라지는지 확인.
**오프라인(LLM 불필요)**: 임시 SQLite db로 store를 직접 호출해 **저장→조회 왕복**을 테스트(예: `save_structured_request_payload` / `delete_saved_schedules_dict` helper 활용). tool 함수는 `.invoke({...})`로 단독 호출 가능.

---

## 6. 결정 사항 (해소됨)

1. **범위**: 메인 + 추가 **전부** 구현하기로 확정.
2. **스텁 노출**: create/update/delete를 모두 구현 → `week03_tools()`가 노출하는 도구에 스텁이 남지 않음.
3. **브랜치**: PR #58(week2)은 이미 `junyoung/final`에 merge됨(`6690910`)을 git 히스토리로 확인. `junyoung/week3`는 merge된 최신 final 위에서 파생 → week2 중복/충돌 없음.
4. **git 상태**: `week01/02/03`가 modified로 뜨는 건 CRLF(줄바꿈) 노이즈로 확인(내용 변경 아님). 커밋 직전에만 정리하면 됨.
