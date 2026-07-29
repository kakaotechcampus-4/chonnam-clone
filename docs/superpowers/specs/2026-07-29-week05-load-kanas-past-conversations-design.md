# Week 5 — Kana의 이전 대화 불러오기 설계

> 작성일: 2026-07-29 · 브랜치: `kimdaewon/week5` (826877f)

## 목표

`student_parts/week05_load_kanas_past_conversations.py`의 TODO를 채워서, Nana가 외부 SQLite/MCP 서버에 있는 다른 사람들의 이전 대화와 공유 일정을 사용할 수 있게 만든다. 이 주차는 직접 SQL을 쓰는 주차가 아니라, 이미 완성된 MCP tool을 호출하고 그 결과를 agent용 JSON으로 전달하는 wrapper를 만드는 주차다.

## 아키텍처

완성된 두 계층 위에 얇은 `@tool` wrapper를 얹는다.

```
LangChain agent (week05_tools() — tool 21개)
        │
        ├── Week 1/3/4 tool 14개 (기존)
        │
        └── Week 5 wrapper 7개  ← 이번 구현 대상
                │
                ├── call_mcp_tool_sync ──→ mcp_server/sqlite_mcp_server.py (stdio subprocess)
                │                               └── ExternalPeopleSQLiteStore
                │                                       └── data/kanana_external_people.sqlite3
                │
                └── AppSQLiteStore ──→ data/kanana_app.sqlite3
                    PERSONAL_SCHEDULES (현재 대화 임시 메모리)
```

wrapper의 책임은 두 가지뿐이다: 검증된 인자를 MCP/store에 넘기고, 결과 JSON을 그대로 전달한다. 직접 SQL이나 중복 정규화 helper를 두지 않는다.

## Tech Stack

LangChain `@tool` / `create_agent`, Pydantic `args_schema`, MCP stdio(`langchain_mcp_adapters`), SQLite.

## 범위

**메인과제 + 추가과제 전부** 구현한다.

| 티어 | 대상 |
|---|---|
| 메인 | `search_previous_conversations`, `load_conversation_messages`, `extract_schedules_from_history`, `list_shared_schedules`, `collect_member_schedules`, helper `_personal_schedules_for_current_scope`, `_collect_member_schedules` |
| 추가 | `create_shared_schedule`, `delete_shared_schedule` |
| 공통 | `week05_prompt_parts()` |

추가과제 2개는 각각 `call_mcp_tool_sync` 한 줄이라 구현 비용이 거의 없고, 대신 "등록 → 조회로 확인 → 삭제" 왕복이 가능해져 `list_shared_schedules` 검증이 훨씬 튼튼해진다.

## 전역 제약

- `fixed/*`, `mcp_server/*`, `data/*`는 수정하지 않는다.
- 신규 의존성 추가 금지.
- **레포에 테스트 파일을 추가하지 않는다** — Week 1-4 관행(레포에 추적된 테스트 파일이 0개다). 검증은 임시 스크립트로 애드혹 실행해 증거를 남긴다.
- 변경은 `student_parts/week05_load_kanas_past_conversations.py` 한 파일에 국한.
- 커밋은 매 체크포인트 승인 후 1개씩, `kimdaewon/week5`에. 완료 후 PR base는 `kimdaewon/final`.
- import 블록에 `PERSONAL_SHARED_MEMBER_NAME`(`fixed/external_people_store.py`) 한 줄만 추가한다. `"나"` 하드코딩을 피하기 위한 것으로, 같은 모듈에서 이미 3개를 가져오고 있다.
- Python 실행은 프로젝트 환경을 쓴다(`.venv/bin/python` 또는 `uv run python`). 시스템 python에는 의존성이 없다.

## 조사에서 확인한 사실

설계 판단의 근거가 된, 코드/데이터에서 직접 확인한 사실들.

### 1. 정규화 helper는 store가 이미 호출한다

`EXTERNAL_MEMBER_ALIAS`는 빈 dict이므로(`external_people_store.py:20`) `normalize_external_member_names()`는 현재 공백 제거·빈 값 탈락만 한다. `normalize_external_schedule_date_bounds()`는 `member_names`를 받지만 쓰지 않고 ISO datetime의 날짜 부분만 남긴다. 그리고 store의 `extract_schedules_from_history()`가 내부에서 두 helper를 모두 호출한다(`:457-458`).

**결론:** wrapper에서 MCP에 넘길 값을 재정규화하는 것은 진짜 중복이다. 가이드가 `_collect_member_schedules`에서 helper를 쓰라고 한 이유는 MCP 인자용이 아니라, **내 일정을 외부와 동일한 날짜 기준으로 필터**하기 위한 것이다. 이렇게 읽으면 가이드 74·84행("중복 정규화 금지")과 148행("helper 사용")의 긴장이 해소된다.

### 2. 임시 일정 ID와 SQLite `schedule_id`는 같은 값이 된다

`app_store.py:353`이 `schedule_id = source_schedule_id or new_id("sch")`이고, week03이 저장 시 `source_schedule_id=schedule.get("id")`를 넘긴다(`week03_build_nanas_logbook.py:405`). 따라서 Week 1 임시 일정이 SQLite로 승격되면 두 ID가 일치하며, 가이드가 말한 "`schedule_id`/`id` 기준 중복 제거"가 실제로 정확히 동작한다.

### 3. 공유 저장소에 고아 행이 대량 누적되어 있다

`data/kanana_external_people.sqlite3`의 `external_schedules` 43행 중 `member_name='나'`가 18행이다. 그런데 앱 DB(`data/kanana_app.sqlite3`)에 남은 일정은 3행(팀 회의 07-17, 치과예약 07-20, 등산 07-25)뿐이고, 18행 중 앱과 실제로 연결된 것은 `shared_sch_1a7a96ba27` ↔ `sch_1a7a96ba27`(치과예약) **1행**이다. **17행이 고아다.**

원인은 두 단계다.

- **중복 삽입** — 공유 저장소의 갱신 판정 키는 `schedule_id`이고, `sync_personal_schedule_to_shared()`가 이를 `f"shared_{앱_schedule_id}"`로 만든다(`external_mcp.py:51`). 앱은 저장할 때마다 새 `schedule_id`를 발급하므로(위 사실 2의 `or new_id("sch")` 분기), 같은 일정을 두 번 저장하면 키가 달라져 갱신이 아니라 삽입이 된다. 실제로 "코칭 미팅 2026-07-16 10:00"이 10행이고 각각 `app:req_*`가 모두 다르다. ID prefix가 `shared_sch_*`와 `shared_personal_*` 두 종류인 것도 저장 경로가 둘(신규 저장 / Week 1 임시 일정 승격)임을 보여준다.
- **삭제 누락** — `delete_personal_schedule_from_shared()`는 `source_conversation_id = app:{request_id}`가 일치하는 행만 지우고, 이는 삭제가 앱 store의 삭제 경로를 타야 발동한다. 앱 DB 리셋이나 그 경로를 타지 않은 삭제는 공유 사본을 영구히 남긴다.

같은 일이 외부 멤버에게도 일어났다. 철수는 seed 3행(`extsch_july_cs_1..3`) 외에 앱 그룹 일정 동기화 사본 4행을 갖고 있고, 그중 "팀 회의 2026-07-17 14:00"이 3행 중복이다.

**이 사실이 설계 결정 1·2의 근거다.**

## 설계 결정

### 결정 1 — 내 일정의 진실 출처는 앱 DB 하나로 고정한다

`collect_member_schedules`는 MCP 호출 전에 `member_names`에서 `PERSONAL_SHARED_MEMBER_NAME`(`"나"`)을 제거한다. 내 일정은 오직 `_personal_schedules_for_current_scope()`(앱 SQLite + 현재 대화 임시 메모리)에서만 온다.

**대안 검토:** 그대로 넘기고 결과에서 중복 제거하는 방법도 있으나, 고아 17행 때문에 앱에서 삭제된 "코칭 미팅"이 되살아난다. 결정 1은 그 위험이 구조적으로 없다. 또한 "앱이 원본, 공유 저장소는 사본"이라는 `external_mcp.py`의 설계 의도와 일치한다.

### 결정 2 — 외부 멤버 rows는 중복을 접는다

`(member_name, title, date, start_time)`을 키로 첫 행만 남긴다.

**비대칭이 근거다.** 되살아남 위험은 `"나"`에만 있다. 외부 멤버 행은 앱이 원본을 삭제해도 "그 멤버가 그 시간에 바빴다"는 근거로 여전히 유효하므로, 중복을 접어도 정보가 사라지지 않는다. 접지 않으면 철수의 "팀 회의"가 3행으로 보여 `schedule_summary`가 오해를 유발한다.

### 결정 3 — 프롬프트는 Week 4 원칙을 그대로 적용한다

*"새 tool이 이전 주차 지시와 **반대 방향**일 때만 명시적 override를 쓰고, 겹치기만 하면 구분 예시로 해결한다."*

Week 5 agent는 tool 21개를 노출한다(W1 3 + W3 7 + W4 4 + W5 7). 그중 위험한 쌍이 둘이다.

- **위험 1 — 이름이 거의 같은 두 검색 tool.** `search_conversation_messages`(W4, 내 앱 대화 RAG) vs `search_previous_conversations`(W5, 외부 사람들 대화 SQLite).
- **위험 2 — `create_shared_schedule`이 저장 경로를 가로챌 수 있다.** 사용자가 "내일 3시에 회의 잡아줘"라고 할 때 LLM이 이 tool을 고르면, 공유 저장소에만 쓰고 앱 DB는 비는 반쪽 저장이 된다. 위 사실 3의 고아 행 문제를 직접 재생산하는 셈이다. 이는 "반대 방향"에 해당하므로 예시가 아니라 override로 막는다.

나머지 세 쌍(`collect_member_schedules` ↔ `personal_list_saved_schedules` / `extract_schedules_from_history` / `list_shared_schedules`)은 겹치지만 반대 방향은 아니므로 구분 예시로 처리한다.

## 컴포넌트

### pass-through wrapper 6개

MCP 서버가 이미 `{"ok", "tool_name", "rows", "schedule_summary"}`를 완성해 JSON 문자열로 반환한다. wrapper는 인자만 넘기고 결과를 그대로 반환한다.

```python
@tool(args_schema=SearchPreviousConversationsInput)
def search_previous_conversations(query, member_names=None, limit=5) -> str:
    return call_mcp_tool_sync("search_previous_conversations",
        {"query": query, "member_names": member_names, "limit": limit})
```

`extract_schedules_from_history`, `list_shared_schedules`, `create_shared_schedule`, `delete_shared_schedule`도 동일한 모양이다. 각 tool의 `args_schema`에 선언된 인자를 그대로 dict로 만들어 넘긴다.

### `load_conversation_messages`

가이드(78행)가 `call_external_tool_payload`를 지정한다. 실질 차이는 dict로 한 번 왕복하는 것뿐이다.

```python
@tool(args_schema=LoadConversationMessagesInput)
def load_conversation_messages(conversation_id: str) -> str:
    payload = call_external_tool_payload("load_conversation_messages",
        {"conversation_id": conversation_id})
    return json_payload(payload)
```

`rows`를 정렬·필터·가공하지 않으므로 `sender`/`content`/`created_at` 순서가 보존된다.

### `_personal_schedules_for_current_scope()`

```python
def _personal_schedules_for_current_scope() -> list[dict[str, Any]]:
    saved = AppSQLiteStore(CONFIG.app_db_path).list_schedules(limit=200)
    saved_ids = {row.get("schedule_id") for row in saved}
    scope = current_session_scope()
    pending = [
        schedule for schedule in PERSONAL_SCHEDULES
        if _schedule_scope(schedule) == scope and schedule.get("id") not in saved_ids
    ]
    return [*saved, *pending]
```

- **`limit=200`** — 기본값 12는 날짜 범위 전체를 봐야 하는 조율에 너무 작다.
- **날짜 필터를 여기서 하지 않는다** — helper 시그니처가 인자를 받지 않아 날짜를 알 수 없다. 필터는 정규화된 범위를 가진 `_collect_member_schedules`가 담당한다.
- 중복 제거는 위 사실 2에 근거해 `id` ↔ `schedule_id`로 한다.

`list_schedules()`가 반환하는 키는 확인했다: `schedule_id`, `request_id`, `owner`, `title`, `date`, `start_time`, `end_time`, `source`, `created_at`, `request_kind`, `attendees`. `_structured_request_from_schedule_row()`가 읽는 키와 정확히 맞는다. 단 `end_time`은 현재 3행 모두 `None`이므로 `or "미정"` 처리가 필요하다.

### `_collect_member_schedules(...)`

```python
def _collect_member_schedules(*, member_names, date_from, date_to, personal_schedules) -> dict[str, Any]:
    members = normalize_external_member_names(member_names)
    bound_from, bound_to = normalize_external_schedule_date_bounds(member_names, date_from, date_to)
    external_members = [name for name in members if name != PERSONAL_SHARED_MEMBER_NAME]

    rows: list[dict[str, Any]] = []
    for schedule in personal_schedules:
        request = _structured_request_from_schedule_row(schedule)
        if not request.date or not (bound_from <= request.date <= bound_to):
            continue
        rows.append({
            "member_name": PERSONAL_SHARED_MEMBER_NAME,
            "title": request.title or "제목 없음",
            "date": request.date,
            "start_time": request.start_time or "미정",
            "end_time": request.end_time or "미정",
            "notes": "앱에 저장된 내 일정",
        })

    if external_members:
        payload = json.loads(call_mcp_tool_sync("extract_schedules_from_history",
            {"member_names": external_members, "date_from": bound_from, "date_to": bound_to}))
        seen: set[tuple[Any, ...]] = set()
        for row in payload.get("rows", []):
            key = (row.get("member_name"), row.get("title"), row.get("date"), row.get("start_time"))
            if key in seen:
                continue
            seen.add(key)
            rows.append({field: row.get(field) for field in
                ("member_name", "title", "date", "start_time", "end_time", "notes")})

    return {"rows": rows, "schedule_summary": external_schedule_summary(rows)}
```

결정 1은 `external_members` 필터로, 결정 2는 `seen` set으로 구현된다.

날짜 비교는 `YYYY-MM-DD` 문자열 기준으로 충분하다(Week 1도 같은 방식). `date_from="2026-07-07T00:00"` 같은 값이 와도 `bound_from`이 `"2026-07-07"`이 되어 비교가 성립한다. `CollectMemberSchedulesInput`이 `date_from`/`date_to`를 필수로 선언하므로 빈 범위는 스키마 단계에서 걸러진다.

외부 row에서 6개 필드만 남기므로 `source_conversation_id`가 빠지고, 두 출처의 row 구조가 완전히 동일해진다. 이는 Week 6 추가과제(`find_common_available_slots`)가 이 rows를 `busy_rows` 근거로 쓸 수 있게 하는 조건이다.

### `collect_member_schedules` tool

```python
@tool(args_schema=CollectMemberSchedulesInput)
def collect_member_schedules(member_names, date_from, date_to) -> str:
    result = _collect_member_schedules(
        member_names=member_names, date_from=date_from, date_to=date_to,
        personal_schedules=_personal_schedules_for_current_scope(),
    )
    return json_payload({"ok": True, "tool_name": "collect_member_schedules", **result})
```

### `week05_prompt_parts()`

`week04_prompt_parts()` 위에 다음을 누적한다. 총 4~6문장.

- **override (위험 2)** — 일정 생성·수정·삭제는 항상 앱 저장 tool(`save_structured_request` / `personal_update_saved_schedule` / `personal_delete_saved_schedules`)로 한다. `create_shared_schedule`·`delete_shared_schedule`은 사용자의 일정 요청으로 부르지 않는다. 공유 저장소 행이 앱과 어긋난 것을 확인하고 보정할 때만 쓴다.
- **구분 (위험 1)** — `search_conversation_messages`는 내가 Nana와 나눈 대화를, `search_previous_conversations`는 다른 사람들이 남긴 외부 대화를 찾는다.
- **구분 예시** — "내 일정 보여줘" → `personal_list_saved_schedules` / "철수 언제 바빠?" → `extract_schedules_from_history` / "우리 다 언제 비어?" → `collect_member_schedules` / 공유 저장소 자체 점검 → `list_shared_schedules`.

## 데이터 흐름

"철수랑 영희랑 7월 둘째 주에 회의 언제 할 수 있어?" 요청의 경로:

```
사용자 입력
  → agent가 collect_member_schedules(member_names=["나","철수","영희"],
                                     date_from="2026-07-07", date_to="2026-07-17")
      → _personal_schedules_for_current_scope()
          → AppSQLiteStore.list_schedules(limit=200)   → 3행
          → PERSONAL_SCHEDULES 중 현재 scope · 미저장  → 0행
      → _collect_member_schedules(...)
          → "나" 제거 → external_members = ["철수","영희"]
          → 내 일정 날짜 필터 → 팀 회의 07-17만 통과 (치과예약 07-20·등산 07-25 탈락)
          → MCP extract_schedules_from_history(["철수","영희"], ...)
              → 중복 접기: 철수 "팀 회의" 3행 → 1행
          → rows + external_schedule_summary(rows)
  → JSON 문자열 → LLM이 빈 시간을 자연어로 설명
```

## 오류 처리

MCP 호출 실패는 wrapper에서 잡지 않고 전파한다. `call_local_mcp_tool_sync`가 subprocess를 띄우고 예외를 그대로 올리며, LangChain agent가 tool 오류를 trace에 기록한다. 이는 `fixed/external_mcp.py`의 동기화 helper가 실패를 payload로 감싸는 것과 다른데, 그쪽은 "앱 DB 저장 자체가 깨지지 않게" 하는 목적이 있고 wrapper는 그런 보호 대상이 없기 때문이다. Week 1-4 wrapper도 같은 방식이다.

`extract_schedules_from_history`의 `member_names`가 `None`이면 store가 전체 멤버를 조회하고, 빈 list면 빈 rows를 반환한다(`external_people_store.py:461-463`). `_collect_member_schedules`는 `external_members`가 비면 MCP를 아예 호출하지 않아 내 일정만 반환한다 — `member_names=["나"]`로 부른 경우가 이에 해당한다.

## 검증

레포에 테스트 파일을 추가하지 않고 임시 스크립트로 애드혹 검증한다. Week 5 tool은 LLM 없이 `.invoke()`로 직접 부를 수 있어 대부분 API 비용이 들지 않는다(프롬프트 검증만 실제 실행 필요).

**쓰기 검증은 임시 DB로 우회한다.** `fixed/mcp_client.py:86`이 `db_path or env.get("KANANA_EXTERNAL_DB_PATH") or CONFIG.external_db_path` 순서로 DB를 고르고, wrapper는 `db_path`를 넘기지 않는다. 따라서 검증 스크립트에서 seed DB를 임시 경로로 복사한 뒤 `os.environ["KANANA_EXTERNAL_DB_PATH"]`를 그 경로로 세팅하면 `data/`를 전혀 건드리지 않는다. 읽기 전용 검증(1~3)은 실제 DB를 그대로 써도 안전하다.

1. **wrapper 6개** — 각 tool `.invoke()` 후 `ok`/`tool_name`/`rows` 존재 확인. `load_conversation_messages("ext_cs")`가 철수 메시지를 순서대로 반환하는지.
2. **`_personal_schedules_for_current_scope()`** — SQLite 3행이 나오는지. `PERSONAL_SCHEDULES`에 같은 `id`를 넣어 중복 제거가 작동하는지, 다른 `session_id`는 배제되는지.
3. **`collect_member_schedules(["나","철수","영희"], "2026-07-07", "2026-07-17")`** — 결정적 검증. 기대: `"나"` 행에 고아 "코칭 미팅"이 **없고** 앱 일정(팀 회의 07-17)만 있음. 철수 "팀 회의" 07-17이 **1행**으로 접힘. `schedule_summary` 존재.
4. **추가과제 왕복 (임시 DB)** — `create_shared_schedule` → `list_shared_schedules`로 나타남 확인 → `delete_shared_schedule` → 사라짐 확인.
5. **프롬프트** — `./run.sh --week5`로 실제 실행. "내일 3시 회의 잡아줘"에 `create_shared_schedule`이 **아닌** 앱 저장 tool이 불리는지 trace로 확인(override 검증). 외부 팀원 일정 조회 요청으로 `search_previous_conversations` / `load_conversation_messages` / `extract_schedules_from_history` 호출 순서 확인.

## 범위에서 제외

- **`data/kanana_external_people.sqlite3` 고아 행 청소** — 위 사실 3의 근본 증상이지만 seed 데이터 변경은 다른 주차 검증에 영향을 줄 수 있는 별개 작업이다. 이 문서에 발견 사항으로 기록만 남긴다.
- **`app_store.py:353`의 `schedule_id` 재발급** — 고아 행을 만든 진짜 원인이지만 `fixed/`는 수정 대상이 아니다.
- **`search_nana_memory`** — Week 4에서 범위 제외된 호환용 tool. Week 5에서도 다루지 않는다.
- **여러 사람의 최종 회의 시간 선택** — Week 6 범위다. Week 5는 busy-time 수집까지만 한다.
