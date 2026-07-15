# Week 3 튜터링 가이드

대상 파일: `student_parts/week03_build_nanas_logbook.py`

이 문서는 수강생이 TODO를 **직접** 작성하고, Claude는 정답 코드를 대신 써주지 않고 힌트/설계 방향만 제시하는 튜터링 세션을 위한 참고 문서다. 튜터링할 때마다 이 파일을 먼저 읽고 현재 진행 상태와 힌트 포인트를 확인한다.

## 배경

Week 1(`student_parts/week01_wake_up_nana.py`)과 Week 2(`student_parts/week02_structure_natural_language_requests.py`)는 이미 구현되어 있고 Week 3에서 그대로 재사용한다.

- Week 1: 개인 일정 CRUD tool(`personal_create_schedule`, `personal_list_schedules`, `personal_delete_schedule`), `join_system_prompt`, `week01_tools`
- Week 2: 자연어/Week 1 tool 결과를 구조화하는 `StructuredRequest` / `StructuredRequestBatch` 스키마, bridge 함수 `extract_structured_request` / `extract_schedule_request`, `week02_prompt_parts`

Week 3는 Week 2가 만든 구조화 데이터를 **SQLite에 영속 저장**하고, 새 대화 세션에서도 일정/할일/리마인더를 조회·수정·삭제할 수 있게 만드는 단계다("나나의 로그북"). 실제 DB 접근은 `fixed/app_store.py`의 `AppSQLiteStore`를 사용한다 — Week 3 코드는 이 store를 호출하는 tool과 프롬프트를 채우는 것이 핵심이다.

> 파일 상단 37~189행의 `[3주차 수강생 구현 가이드]` 주석 블록에 목표·메인/추가 과제 구분·핵심 흐름·역할 태그(`[메인]`/`[추가]`/`[공통]`)·반환값 규칙이 이미 상세히 적혀 있다. 이 문서는 그 내용을 반복하지 않고, TODO를 순서대로 짚어가는 체크리스트 역할만 한다. 막히면 먼저 그 주석 블록을 다시 읽는다.

## TODO 목록 (진행 순서)

1. **`SQLITE_MEMORY_PROMPT`** (30~31행) — 일정/할일/리마인더가 세션이 끝나도 SQLite에 남아 다음 대화에서도 조회 가능하다는 걸 LLM에게 알려주는 프롬프트 규칙을 작성
2. **`WEEK03_TOOL_CALL_PROMPT`** (33~34행) — 자연어 → 구조화 → SQLite 저장/조회/수정/삭제로 이어지는 tool 호출 순서를 LLM에게 안내하는 프롬프트 규칙을 작성
3. **`SaveStructuredRequestInput.unwrap_legacy_payload`** (218~224행) — `StructuredRequest` 인스턴스와 `payload`/`structured_request`로 감싸진 레거시 dict 형태를 저장 입력 하나의 모양으로 정규화
4. **`_save_input_from(value)`** (227~231행, 현재 `...`) — dict / JSON 문자열 / 자연어 문자열 / `StructuredRequest` 등 다양한 입력을 검증해 `SaveStructuredRequestInput`으로 변환. Week 2의 `_coerce_structured_request` 패턴을 참고
5. **`save_structured_request_payload(...)`** (234~242행, 현재 `...`) — 위 함수로 입력을 정규화한 뒤 `AppSQLiteStore.save_structured_request(...)`를 호출하고 tool 결과 dict를 구성
6. **`_delete_saved_schedules(...)`** (290~304행, 현재 `...`) — 삭제 조건이 비어 있으면 거부, `delete_all` 여부에 따라 store의 다른 삭제 메서드를 호출, 반환값에 `deleted_count`/`filters`/`deleted` 포함
7. **`structured_request_from_week01_schedule(schedule)`** (307~311행, 현재 `...`) — Week 1의 임시 일정 dict(`attendees`/`id` 등)를 Week 3의 `members`/`source_schedule_id` 필드로 변환
8. **`personal_create_schedule`(Week1-호환 tool)** (314~326행, 현재 `...`) — Week 1 tool을 호출하고 결과를 `StructuredRequest`로 변환한 뒤 SQLite에도 저장, `created`+`structured_request`+`sqlite_save`를 하나의 JSON으로 합쳐 반환
9. **`save_structured_request(...)`** (329~346행, 현재 `...`) — 검증된 인자로 저장용 dict를 구성(`None` 값 제외)하고 SQLite에 저장, `ok`/`tool_name` + 결과 JSON 반환
10. **`list_saved_requests(...)`** (349~358행, 현재 `...`) — `kind`/`date_from`/`date_to`로 조회하고 `rows`를 JSON으로 반환
11. **`get_saved_request(request_id)`** (361~366행, 현재 `...`) — id로 단건 조회, 없으면 `row=None` 유지한 채 JSON 반환
12. **`personal_list_saved_schedules(...)`** (369~380행, 현재 `...`) — 기본 `kind=personal_schedule`, 날짜/종류/limit으로 필터링해 `filters`+`schedules` JSON 반환
13. **`delete_saved_schedules_dict(...)`** (383~395행, 현재 `...`) — 전달받은(또는 기본) store로 `_delete_saved_schedules(...)` 호출
14. **`personal_update_saved_schedule(...)`** (398~411행, 현재 `...`) — `None`이 아닌 필드만 `AppSQLiteStore.update_schedule(...)`에 전달, id를 못 찾으면 `ok=False`, 찾으면 `updated_schedule`/`shared_sync` JSON 반환
15. **`personal_delete_saved_schedules(...)`** (414~426행, 현재 `...`) — 필터를 `_delete_saved_schedules(...)`로 그대로 전달해 JSON 반환
16. **`week03_prompt_parts()` 내 인라인 TODO 2곳** (458행, 461행) — (a) Week 2 구조화 출력과 Week 3 SQLite 저장 흐름을 잇는 지시문, (b) 현재 날짜·Week 3 tool 선택 기준·이번 주차 범위를 설명하는 지시문을 각각 추가
17. **`build_week03_agent()`** (465~474행, 현재 `...`, OpenAI 키 체크만 있는 상태) — `chat_model()`, `week03_tools()`, `week03_system_prompt()`로 LangChain agent를 구성 (Week 1/Week 2의 `build_week0Xn_agent()`와 같은 패턴)

## 원문·트러블슈팅 기록

- AI에게 물어본 질문과 답변 **원문 그대로**는 `docs/ai-conversations/week3.md`에 남긴다 (이 파일의 요약과는 별개).
- 코드 작성 중 막힌 문제와 해결 과정은 `docs/troubleshooting/week3.md`에 기록한다.

## 튜터링 진행 방식

- 위 순서대로 한 항목씩 진행. 사용자가 먼저 시도하고, 막히면 개념/방향 힌트(예: `AppSQLiteStore`의 어떤 메서드를 쓸지, dict/JSON/자연어 입력을 어떻게 분기할지, Week 1·2 패턴과의 일관성 등)를 질문 형태나 참고 위치 pointer로 제공.
- 완성 코드를 대신 작성하지 않는다. 사용자가 작성한 코드를 Read로 확인하고 Week 1·2 패턴과의 일관성, 반환 JSON 형태, 예외 처리만 짚어준다.
- 각 항목 완료 후 다음 항목으로 넘어가되, 사용자가 순서를 바꾸길 원하면 따른다.
- 코드 수정은 사용자가 직접 하거나, 명시적으로 "이 부분은 대신 써줘"라고 요청할 때만 Edit 사용.

## 검증 방법

- `./run.sh --week3`로 실행하고, 일정/할일을 등록한 뒤 **다른 대화(세션)를 새로 시작해서** 조회했을 때도 남아있는지 확인한다 (SQLite 영속 저장 여부가 핵심 검증 포인트).
- 등록 → 조회 → 수정 → 삭제 흐름을 각각 자연어로 시도해 tool 호출과 반환 JSON이 파일 상단 가이드 주석의 반환값 규칙과 맞는지 확인한다.
- 파일 상단 가이드 주석에 있는 수동 검증 레시피(`./run.sh --week3` 관련 절)를 참고한다.
