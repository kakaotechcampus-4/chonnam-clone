# Week 5 — Kana's Past Conversations / MCP Wrapper 도구

## Context

`student_parts/week05_load_kanas_past_conversations.py`는 외부 SQLite/MCP 서버(`mcp_server/sqlite_mcp_server.py`, 학생이 직접 수정하지 않음)에 있는 Kana의 과거 대화와 공유 일정을 LangChain agent가 tool로 쓸 수 있게 감싸는 주차입니다. 학생이 SQL을 새로 짜는 게 아니라, 이미 존재하는 MCP tool을 올바른 인자로 호출하고 결과를 정리해 agent에 넘기는 wrapper를 완성하는 것이 핵심입니다.

이번 작업 범위는 **메인과제만**입니다 — 추가 과제(`create_shared_schedule`/`delete_shared_schedule`)는 구현하지 않기로 확정했습니다.

## 확인된 핵심 시그니처/데이터 구조 (소스에서 직접 확인)

- `call_mcp_tool_sync(tool_name, args, db_path=None) -> str` — MCP tool이 만든 **원본 JSON 문자열**을 그대로 반환(이미 `ok`/`tool_name`/데이터 키 포함). 그대로 반환해도 됨.
- `call_external_tool_payload(tool_name, args) -> dict` (`fixed/external_mcp.py`) — 위와 동일하지만 이미 `json.loads`된 dict.
- MCP tool 반환 구조(모두 `call_mcp_tool_sync`로 호출, 이미 `ok`/`tool_name` 포함):
  - `search_previous_conversations(query, member_names=None, limit=5)` → `rows: [{conversation_id, member_name, title, content, created_at}]`
  - `load_conversation_messages(conversation_id)` → `rows: [{role, sender, content, created_at}]`
  - `extract_schedules_from_history(member_names: list[str](필수), date_from, date_to)` → `rows: [{member_name, title, date, start_time, end_time, notes, source_conversation_id}]`, `schedule_summary: str`
  - `list_shared_schedules(member_names=None, date_from=None, date_to=None, source_conversation_id=None, limit=50)` → `rows: [{schedule_id, member_name, title, date, start_time, end_time, notes, source_conversation_id}]`, `schedule_summary: str` — **필터를 아무것도 안 주면 store가 임의로 실습용 기본(7월) fixture 조건으로 대체함**.
- `fixed/external_people_store.py`: `normalize_external_member_names(names|None) -> list[str]`(alias 적용, 공백 제거, `None`→`[]`), `normalize_external_schedule_date_bounds(names, date_from, date_to) -> (str, str)`(ISO 날짜시간에서 날짜만 추출, `None`→`""`), `external_schedule_summary(rows) -> str`(빈 rows→"조회된 외부 일정이 없습니다."), `PERSONAL_SHARED_MEMBER_NAME = "나"`.
- `AppSQLiteStore(CONFIG.app_db_path).list_schedules(limit, kind=None, date_from=None, date_to=None) -> list[dict]` — `schedule_id, request_id, owner, title, date, start_time, end_time, attendees(list), source, created_at, request_kind`. `ORDER BY date ASC` + `LIMIT`이므로 **limit을 넉넉히(200) 줘야** 미래 일정이 안 잘림.
- `PERSONAL_SCHEDULES`(week01, in-memory list) 각 row: `id, title, date, start_time, end_time, attendees(list), created_at, session_id`. Week3의 `save_structured_request(..., source_schedule_id=<week1 id>)`로 영구 저장되면 **SQLite `schedule_id`가 그 Week1 `id`와 같아짐** — 이걸로 중복 탐지.
- **중요 발견(Plan 검증 단계에서 확인)**: Week3+ 개인/그룹 일정 저장 시 `fixed/external_mcp.py`가 자동으로 외부 공유 저장소에도 `member_name="나"`로 사본을 동기화합니다. 따라서 `collect_member_schedules`에서 `member_names`에 "나"가 포함된 채로 그대로 외부 MCP(`extract_schedules_from_history`)를 호출하면, 이미 앱 SQLite에서 읽은 내 일정이 외부 사본으로 **중복 반환**됩니다 → 외부 조회 시 "나"는 반드시 제외해야 합니다.

## 구현 대상 

1. **`_personal_schedules_for_current_scope()`** — `AppSQLiteStore(CONFIG.app_db_path).list_schedules(limit=200)`로 저장된 내 일정을 읽고, `schedule_id` 집합을 만든 뒤, `PERSONAL_SCHEDULES`에서 현재 세션(`_schedule_scope(row) == current_session_scope()`) 범위이면서 그 `id`가 SQLite `schedule_id` 집합에 없는 임시 일정만 골라 합쳐서 반환. 날짜 필터는 여기서 하지 않음(파라미터가 없음 — 호출자가 함).

2. **`_collect_member_schedules(*, member_names, date_from, date_to, personal_schedules)`** — 이 함수 안에서 딱 한 번 `normalize_external_member_names`/`normalize_external_schedule_date_bounds`로 정규화. 정규화된 날짜 범위로 `personal_schedules`를 필터링(날짜 없는 row는 건너뜀, 빈 문자열 bound는 비교 생략)해 `_structured_request_from_schedule_row`로 변환 후 `member_name="나"`인 통일된 row로 만듦. 외부 멤버 조회 시에는 `member_names`에서 **"나"를 제외**한 뒤(비어 있으면 MCP 호출 자체를 생략), `call_mcp_tool_sync("extract_schedules_from_history", {...})` 결과의 `rows`를 그대로 합침. 최종 `{"rows": my_rows + external_rows, "schedule_summary": external_schedule_summary(rows)}` 반환.

3. **`search_previous_conversations` tool** — `{"query", "member_names", "limit"}`을 그대로 `call_mcp_tool_sync("search_previous_conversations", args)`에 넘기고 결과 문자열을 그대로 반환(재정규화/재래핑 없음 — 가이드가 명시).

4. **`load_conversation_messages` tool** — `call_external_tool_payload("load_conversation_messages", {"conversation_id": conversation_id})`로 dict를 받아 `json_payload(payload)`로 감싸 반환.

5. **`extract_schedules_from_history` tool** — `{"member_names", "date_from", "date_to"}`를 그대로 `call_mcp_tool_sync(...)`에 넘기고 결과 문자열을 그대로 반환.

6. **`list_shared_schedules` tool** — 5개 필터 인자를 그대로 `call_mcp_tool_sync("list_shared_schedules", args)`에 넘기고 결과 문자열을 그대로 반환.

7. **`collect_member_schedules` tool** — `_personal_schedules_for_current_scope()` 호출 후 `_collect_member_schedules(member_names=, date_from=, date_to=, personal_schedules=)` 호출, 결과를 `json_payload({"ok": True, "tool_name": "collect_member_schedules", **result})`로 반환.

8. **`week05_prompt_parts()`** — 다음 내용을 담은 prompt 조각 추가:
   - `collect_member_schedules`는 다른 사람들 이름만 넣어도 "나"가 항상 포함됨, 날짜는 `YYYY-MM-DD`.
   - 과거 대화 조회 흐름: `search_previous_conversations`(짧은 핵심어) → `load_conversation_messages(conversation_id)` → `extract_schedules_from_history`.
   - `list_shared_schedules`는 공유 저장소 자체를 확인할 때 쓰고, 필터 없이 부르면 실습용 기본 fixture가 반환될 수 있음.
   - busy-time 답변은 `rows`/`schedule_summary` 근거로만 하고, 여러 사람 최종 회의 시간 확정은 Week 6 범위(week04 prompt의 "assistant 발화만으로 사실 단정 않기" 톤과 동일하게).
   - `create_shared_schedule`/`delete_shared_schedule`는 언급하지 않음(week05_tools()에 없음).

## 범위 제외

- `create_shared_schedule` / `delete_shared_schedule` — 현재 `...` stub 그대로 둠. `week05_tools()`는 이미 이 둘을 포함하지 않으므로 추가 수정 불필요.

## 검증 방법

- `python -c "import ast; ast.parse(...)"`로 구문 확인 후 모듈 import 스모크 테스트.
- `search_previous_conversations`, `load_conversation_messages`, `extract_schedules_from_history`, `list_shared_schedules`를 각각 `.invoke(...)`로 직접 호출해 JSON 구조(rows/schedule_summary 등)를 확인.
- `collect_member_schedules`를 `member_names=["나", "<외부멤버>"]`와 `member_names=["<외부멤버>"]` 두 경우로 직접 호출해서 **"나" 일정이 중복 반환되지 않는지** 확인 (이번에 발견한 버그의 회귀 테스트).
- `_personal_schedules_for_current_scope()`가 SQLite 일정과 임시 일정을 중복 없이 합치는지 직접 호출로 확인.
- `build_week05_agent()`로 자연어 질의 1~2개를 실행해 trace에서 올바른 tool이 호출되는지 확인(예: "철수랑 나랑 이번 주 일정 겹치는 거 있어?").
- 이 과정에서 생성한 테스트 데이터(있다면)는 정리하고, `fixed/*.py`, `mcp_server/*.py`, 다른 week 파일은 건드리지 않았는지 확인 — 범위는 `week05_load_kanas_past_conversations.py`로 한정.
