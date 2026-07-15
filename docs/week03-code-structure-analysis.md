# week03_build_nanas_logbook.py 구조 분석

> [week03-learning-log.md](./week03-learning-log.md)에서 정리한 개념(구조화된 출력 → tool argument → DB 저장, 대화 저장과 데이터 저장의 구분)이 실제 코드에서 어떻게 배치되는지 뜯어본 노트.

## 1. 이 파일의 목적 한 줄 요약

Week 2가 만든 `StructuredRequest`(자연어를 구조화한 결과)를 **SQLite에 실제로 저장하고, 다시 꺼내 보고, 고치고, 지우는** tool들을 정의하는 파일. Week 1의 `PERSONAL_SCHEDULES` 리스트(메모리, 프로세스 재시작하면 사라짐)를 대체하는 "영속 기록장(logbook)"을 만드는 단계다.

파일 맨 앞의 TODO 두 줄(`SQLITE_MEMORY_PROMPT`, `WEEK03_TOOL_CALL_PROMPT`)과 각 함수 본문의 `...`가 비어 있는 걸 보면, 이 파일은 **수강생이 채워야 하는 템플릿**이다. 즉 지금 파일만 보면 "동작하는 코드"가 아니라 "설계도 + 주석 가이드"에 가깝다.

## 2. Import로 보는 의존 관계

```
fixed/config.py        → CONFIG (OpenAI 키, DB 경로)
fixed/llm.py            → chat_model()
fixed/runtime_clock.py  → current_app_date_iso()  (오늘 날짜)
fixed/app_store.py      → AppSQLiteStore  (진짜 SQL 실행 담당)

student_parts/week01_wake_up_nana.py
  → join_system_prompt, week01_personal_create_schedule, week01_tools

student_parts/week02_structure_natural_language_requests.py
  → RequestKind, StructuredRequest, extract_schedule_request,
    extract_structured_request, week02_prompt_parts
```

핵심은 이 파일이 **SQL을 직접 짜지 않는다**는 것. SQL/스키마 생성/외부 공유 저장소 동기화는 전부 `fixed/app_store.py`의 `AppSQLiteStore`가 담당하고, `week03_build_nanas_logbook.py`는 "LLM이 준 값 → store 메서드 호출 → JSON 문자열로 응답"만 하는 **얇은 tool 계층**이다. (learning-log 3장에서 말한 "DB 구성은 에이전트와 직접 상관없는 백엔드 설계 영역"이 코드에서 이렇게 분리돼 있다.)

## 3. 레이어 구조

```
┌─────────────────────────────────────────────┐
│ LangChain Agent (create_agent)               │
│  - system_prompt: week03_system_prompt()     │
│  - tools: week03_tools()                     │
└───────────────┬───────────────────────────────┘
                │ LLM이 tool arguments를 채워서 호출
                ▼
┌─────────────────────────────────────────────┐
│ @tool(args_schema=...) 함수들                │  ← 이 파일이 담당
│  - Pydantic 스키마가 입력을 먼저 검증        │
│  - 함수 본문은 검증된 값을 정리만 함         │
└───────────────┬───────────────────────────────┘
                │ dict/필터 값 전달
                ▼
┌─────────────────────────────────────────────┐
│ AppSQLiteStore (fixed/app_store.py)          │  ← SQL 실행 담당
│  - save_structured_request / list_schedules  │
│  - update_schedule / delete_schedule 등      │
└───────────────┬───────────────────────────────┘
                │
                ▼
        SQLite 파일 (CONFIG.app_db_path)
   structured_requests / schedules / todos / reminders
```

## 4. 핵심 데이터 흐름 (메인과제 경로)

```
사용자: "내일 10시 개인 코칭 저장해줘"
   │
   ▼
① extract_schedule_request(query="...")         [Week 2 tool]
   → StructuredRequest(kind="personal_schedule", title="개인 코칭",
                        date="2026-07-16", start_time="10:00", ...)
   │  (LLM이 자연어를 구조화된 필드로 변환)
   ▼
② LLM이 위 필드를 그대로 save_structured_request(...)의 인자로 전달
   │
   ▼
③ @tool(args_schema=SaveStructuredRequestInput)
   → Pydantic이 kind/title/date/... 타입과 Literal 값 범위를 검증
   │  (learning-log 2장: "타입이 description보다 확실하게 값 범위를 통제")
   ▼
④ save_structured_request() 함수 본문
   → 검증된 인자를 dict로 정리 (None 값 제외)
   → AppSQLiteStore(CONFIG.app_db_path).save_structured_request(payload)
   │
   ▼
⑤ AppSQLiteStore.save_structured_request()
   → structured_requests 테이블에 원본 저장
   → kind가 personal_schedule/group_schedule이면 schedules 테이블에도 정규화 저장
   → 개인/그룹 일정이면 외부 공유 저장소에도 동기화 (shared_sync)
   │
   ▼
⑥ JSON 문자열 반환 { ok, tool_name, request_id, saved_rows, shared_sync }
```

이후 "내 일정 보여줘"라고 하면 `personal_list_saved_schedules`가 `AppSQLiteStore.list_schedules(...)`를 호출해서 새 대화·재시작 이후에도 값이 남아 있는지 확인하는 것이 메인과제 검증 포인트다.

## 5. 입력 스키마(Pydantic) 관계

```
StructuredRequest (week02)               ← LLM 구조화 출력의 원형
   │  상속
   ▼
SaveStructuredRequestInput (week03)      ← 저장 직전 검증용
   + source_schedule_id: Week 1 임시 일정과 연결할 때만 사용
   + unwrap_legacy_payload(): 예전 trace의 payload wrapper를 정규화 (TODO)
```

나머지 스키마는 각 tool 전용 입력이며 서로 상속 관계는 없다:

| 스키마 | 용도 | 과제 티어 |
|---|---|---|
| `SavedRequestListInput` | structured_requests 목록 필터(kind/date_from/date_to) | 메인 |
| `SavedRequestGetInput` | request_id 단건 조회 | 메인 |
| `SavedScheduleListInput` | schedules 목록 필터 + limit | 메인 |
| `SavedScheduleUpdateInput` | schedule_id로 부분 수정 (None=수정 안 함) | 추가 |
| `SavedScheduleDeleteInput` | schedule_ids 또는 날짜/제목/시간 필터 삭제 | 추가 |

## 6. 함수 목록과 책임 (파일 내 주석의 [메인]/[추가]/[공통] 티어 기준)

**공통 인프라**
- `_store()` — `AppSQLiteStore` 인스턴스 생성 (매번 `CONFIG.app_db_path` 기준)
- `_tool_name(item)` — LangChain tool 객체든 일반 함수든 이름을 안전하게 추출
- `json_payload(payload)` — 한글 깨짐 없이 JSON 문자열로 직렬화
- `tool_result(tool_name, ok, **payload)` — `{ok, tool_name, ...}` 응답 껍데기 생성

**메인과제 — 저장 + 조회**
- `save_structured_request(...)` — `@tool(args_schema=SaveStructuredRequestInput)`. Week 3의 핵심 tool. 검증된 인자를 dict로 만들어 `AppSQLiteStore.save_structured_request()`에 전달.
- `list_saved_requests(...)` / `get_saved_request(...)` — `structured_requests` 원본 테이블 목록/단건 조회.
- `personal_list_saved_schedules(...)` — `schedules` 테이블 조회. 조회/수정/삭제 전 후보 확인용.

**추가과제 — 수정/삭제 + 호환성**
- `_delete_saved_schedules(...)` — 삭제 조건이 비어있는지 먼저 확인하는 안전장치(guard), 그다음 store의 삭제 메서드 호출.
- `structured_request_from_week01_schedule(schedule)` — Week 1 임시 dict → `SaveStructuredRequestInput` 변환.
- `personal_create_schedule(...)` — Week 1과 이름이 같은 **호환 tool**. Week 1 임시 생성 + SQLite 이중 저장을 함께 수행 (`week03_tools()`에서 Week 1 버전을 이걸로 교체함).
- `personal_update_saved_schedule(...)` / `personal_delete_saved_schedules(...)` — 실제 agent가 호출하는 수정/삭제 tool.
- `delete_saved_schedules_dict(...)` / `save_structured_request_payload(...)` / `_save_input_from(...)` — tool invoke 없이 테스트나 내부 코드에서 직접 호출하는 helper. agent의 정상 경로가 아니다.

**조립부**
- `week03_tools()` — Week 1 tool 목록에서 `personal_create_schedule`만 Week 3 호환 버전으로 갈아끼운 뒤, Week 2의 `extract_schedule_request`와 Week 3 SQLite tool들을 이어붙여 반환.
- `week03_system_prompt()` / `week03_prompt_parts()` — Week 2 프롬프트 조각에 Week 3 전용 지시(현재 비어있는 TODO 두 개)를 추가.
- `build_week03_agent()` / `build_week_agent()` — 싱글턴 패턴으로 agent를 한 번만 만들어 재사용. `build_week_agent()`가 실행기(run.sh)가 찾는 표준 진입점.

## 7. 지금 비어 있는 부분 (TODO 목록)

이 파일은 아직 완성본이 아니다. `...`로 남아있는 함수와 빈 문자열 프롬프트가 수강생이 채워야 할 부분이다.

- `SQLITE_MEMORY_PROMPT`, `WEEK03_TOOL_CALL_PROMPT` — 시스템 프롬프트 내용 (SQLite 조회 규칙, tool 호출 순서 안내)
- `SaveStructuredRequestInput.unwrap_legacy_payload` — 레거시 payload 정규화
- `_save_input_from`, `save_structured_request_payload` — helper 구현
- `_delete_saved_schedules` — 삭제 guard + store 호출 로직
- `structured_request_from_week01_schedule` — Week 1 → Week 3 변환
- `personal_create_schedule` (Week 1 호환) — 이중 기록 로직
- `save_structured_request`, `list_saved_requests`, `get_saved_request`, `personal_list_saved_schedules` — 메인과제 4개 tool 본문
- `delete_saved_schedules_dict`, `personal_update_saved_schedule`, `personal_delete_saved_schedules` — 추가과제 3개 tool 본문
- `week03_prompt_parts()` 안의 마지막 두 TODO 지시문
- `build_week03_agent()` 안의 `create_agent(...)` 호출

## 8. Week 1~3 전체 그림에서 이 파일의 위치

```
Week 1: PERSONAL_SCHEDULES (파이썬 리스트, 메모리) — 대화 끝나면 사라짐
Week 2: StructuredRequest (Pydantic, 아직 저장 안 함) — 구조화만 함
Week 3: AppSQLiteStore (SQLite 파일) — 여기서부터 "기록장"이 생김
         ├─ structured_requests: LLM이 뽑은 원본 감사 로그
         ├─ schedules: 화면/조회/삭제하기 쉬운 정규화 row
         ├─ todos / reminders: kind별 정규화 row
         └─ (개인/그룹 일정은 외부 공유 저장소에도 동기화 → Week 5/6 예고)
```

learning-log 6장에서 정리한 "1주차 임시 저장 → 2주차 구조화 → 3주차 검증 후 DB 저장" 흐름이 그대로 파일 구조에 반영되어 있다. 다만 "검증"은 여기서 Pydantic 스키마 레벨(타입/Literal 강제)까지만 하고 있고, learning-log 5장에서 말한 "사람 확인 / ground-truth 비교 / LLM-as-judge" 같은 결과물 품질 검증은 아직 이 파일 범위 밖이다.
