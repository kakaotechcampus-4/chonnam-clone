# Week 1 student_parts 구현 계획

## Context

`student_parts/week01_wake_up_nana.py`는 Kanana Schedule Agent 강의의 Week 1 실습 파일로, 학생이 LangChain `@tool` 3개를 직접 완성해야 하는 스텁 상태다. 현재 세 함수 모두 `# TODO` + `...`(Ellipsis)만 있어 앱을 실행해도 LLM이 일정 생성/조회/삭제를 요청하면 tool 호출이 실패한다. 목표는 파일 상단의 `[수강생 구현 가이드]`(라인 43-137)가 명시한 사양대로 세 함수를 완성해서, `./run.sh --week1` 실행 후 채팅으로 개인 일정 CRUD가 동작하고 "상세" 탭 trace에서 올바른 tool 호출/결과 JSON이 보이도록 하는 것이다. 추가로 사용자는 `week01_prompt_parts()`/`CHAT_MEMORY_PROMPT` TODO(필수 구현 대상은 아니지만 비워두면 system prompt가 헤더 한 줄만 남음)도 최소한의 내용으로 채우기로 결정했다.

가상환경은 이미 `uv sync`로 설정 완료(Python 3.11.15, `.venv`), `run.sh`의 CRLF 줄바꿈 문제도 수정 완료된 상태다.

## 대상 파일

`student_parts/week01_wake_up_nana.py` 단 하나만 수정한다. `fixed/`는 참고만 하고 수정하지 않는다 (커리큘럼 운영 기준: "fixed/는 수업에서 별도 지시가 없으면 수정하지 않습니다").

이미 준비된 헬퍼(그대로 재사용, 새로 만들지 않음):
- `_json(payload)` — dict → JSON 문자열 (`ensure_ascii=False`)
- `_new_personal_id()` — `"personal_<hex10>"` ID 생성
- `_now_iso()` — timezone 포함 ISO 타임스탬프
- `_schedule_scope(schedule)` / `_current_session_schedules()` — 세션 스코프 필터링
- `current_session_scope()` (from `fixed/session_scope.py`) — 현재 conversation_id 반환

참고 패턴: `mcp_server/sqlite_mcp_server.py`의 `create_shared_schedule`/`delete_shared_schedule` — 항상 `{"ok": True, "tool_name": "<func>", ...}` 형태로 `json.dumps(..., ensure_ascii=False)` 반환하는 동일한 컨벤션을 따른다.

## 구현 내용

### 1. `personal_create_schedule` (라인 163-174)

```python
@tool
def personal_create_schedule(
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    attendees: list[str] | None = None,
) -> str:
    """Nana의 개인 일정을 현재 대화의 임시 메모리에 생성합니다."""

    schedule = {
        "id": _new_personal_id(),
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "attendees": attendees or [],
        "created_at": _now_iso(),
        "session_id": current_session_scope(),
    }
    PERSONAL_SCHEDULES.append(schedule)
    return _json({"ok": True, "tool_name": "personal_create_schedule", "created_schedule": schedule})
```

### 2. `personal_list_schedules` (라인 177-182)

```python
@tool
def personal_list_schedules(date_from: str | None = None, date_to: str | None = None) -> str:
    """선택한 시작일과 종료일 범위에 포함되는 Nana의 개인 일정을 조회합니다."""

    schedules = _current_session_schedules()
    if date_from:
        schedules = [s for s in schedules if s.get("date", "") >= date_from]
    if date_to:
        schedules = [s for s in schedules if s.get("date", "") <= date_to]
    return _json({"ok": True, "tool_name": "personal_list_schedules", "schedules": schedules})
```

`PERSONAL_SCHEDULES`나 `_current_session_schedules()`의 반환 리스트를 in-place로 수정하지 않고, 새 리스트만 만들어 필터링한다 (가이드: "직접 수정하지 않고 조회").

### 3. `personal_delete_schedule` (라인 185-190)

```python
@tool
def personal_delete_schedule(schedule_id: str) -> str:
    """일정 ID에 해당하는 개인 일정을 삭제합니다."""

    session_id = current_session_scope()
    before = len(PERSONAL_SCHEDULES)
    PERSONAL_SCHEDULES[:] = [
        s for s in PERSONAL_SCHEDULES
        if not (s.get("id") == schedule_id and _schedule_scope(s) == session_id)
    ]
    deleted = len(PERSONAL_SCHEDULES) < before
    return _json({"ok": True, "tool_name": "personal_delete_schedule", "deleted": deleted})
```

`PERSONAL_SCHEDULES[:] = ...` 슬라이스 대입으로 리스트 객체 identity를 유지한다 (가이드 요구사항 — 다른 곳에서 같은 리스트 객체를 참조 중일 수 있음). 다른 세션의 동일 `schedule_id`는 조건에 `_schedule_scope(s) == session_id`가 걸려 삭제되지 않는다.

### 4. `CHAT_MEMORY_PROMPT` (라인 30) + `week01_prompt_parts()` (라인 205-210)

필수 구현 대상은 아니지만, 비워두면 LLM에게 tool 사용 지침이 전혀 없어 tool 선택이 불안정해질 수 있어 최소한으로 채운다.

```python
CHAT_MEMORY_PROMPT = (
    "이 대화에서 만든 개인 일정은 현재 대화에서만 유지되는 임시 데이터다. "
    "다른 대화에서 만든 일정은 이 대화에 보이지 않는다."
)
```

```python
def week01_prompt_parts() -> list[str]:
    """1주차부터 누적되는 system prompt 조각입니다."""

    return [
        (
            "너는 Kanana의 일정 비서 Nana다. 사용자의 개인 일정 생성·조회·삭제 요청에는 "
            "personal_create_schedule, personal_list_schedules, personal_delete_schedule tool을 사용한다. "
            "일정 생성 시 date는 YYYY-MM-DD, start_time/end_time은 HH:MM 형식을 사용하고, "
            "tool 호출 없이 일정 정보를 지어내지 않는다."
        ),
        CHAT_MEMORY_PROMPT,
    ]
```

## 검증 방법

1. `./run.sh --week1`로 앱 실행 (Gradio 로컬 URL 접속).
2. 채팅에 "내일 오후 2시에 팀 미팅 일정 만들어줘" 같은 생성 요청 입력 → "상세" 탭에서 `tool_call: personal_create_schedule`과 `tool_result` JSON에 `created_schedule`(id가 `personal_` 접두어, session_id 포함) 확인.
3. "내 일정 보여줘" 입력 → `personal_list_schedules` 호출, 결과 JSON에 `schedules` 배열로 방금 만든 일정이 나오는지 확인.
4. 날짜 범위를 좁혀 조회(예: 오늘 이후만) 요청해 `date_from`/`date_to` 필터가 정상 동작하는지 확인.
5. "방금 만든 일정 삭제해줘" 입력 → `personal_delete_schedule` 호출, `deleted: true` 확인 후 다시 목록 조회해 사라졌는지 확인.
6. (세션 격리 확인, 선택) 새 대화(New Conversation)를 시작해 이전 대화에서 만든 일정이 보이지 않는지 확인.
7. `ensure_demo_personal_schedule()`과 `list_personal_schedule_dicts()`는 내부적으로 `personal_create_schedule.invoke(...)` / `personal_list_schedules.invoke(...)`를 호출하므로, 구현 후 이 경로들이 예외 없이 동작하는지도 앱 정상 기동 여부로 간접 확인된다.
