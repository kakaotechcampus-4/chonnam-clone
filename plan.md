# Plan: Week 1 Personal Schedule LangChain Tools

## Context
Nana 챗봇이 사용자의 개인 일정 요청("만들어줘 / 보여줘 / 지워줘")을 처리할 수 있도록
LangChain @tool 3개를 구현한다. Week 1 일정은 앱 DB에 저장하지 않고
PERSONAL_SCHEDULES 리스트(대화 전용 임시 메모리)에만 보관한다.

---

## 구현 대상 파일
`student_parts/week01_wake_up_nana.py` — 스텁 3개(`...`)를 채우는 것이 전부

---

## 사용할 기존 헬퍼 (수정 없이 그대로 사용)
| 헬퍼 | 역할 |
|------|------|
| `PERSONAL_SCHEDULES` | 임시 저장소 `list[dict]` |
| `_new_personal_id()` | `"personal_{uuid10hex}"` 형태 ID |
| `_now_iso()` | 로컬 타임존 ISO 8601 타임스탬프 |
| `_json(payload)` | `dict → JSON 문자열` (ensure_ascii=False) |
| `_current_session_schedules()` | 현재 session_id 일정만 필터링한 리스트 반환 (읽기 전용) |
| `current_session_scope()` | 현재 대화 범위 문자열 반환 (`fixed/session_scope.py`) |

---

## 구현 내용

### 1. `personal_create_schedule`
```python
@tool
def personal_create_schedule(
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    attendees: list[str] | None = None,
) -> str:
    schedule = {
        "id": _new_personal_id(),
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "attendees": attendees if attendees is not None else [],
        "created_at": _now_iso(),
        "session_id": current_session_scope(),
    }
    PERSONAL_SCHEDULES.append(schedule)
    return _json({"ok": True, "tool_name": "personal_create_schedule", "created_schedule": schedule})
```

### 2. `personal_list_schedules`
```python
@tool
def personal_list_schedules(
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    result = _current_session_schedules()   # 이미 session_id 필터 적용됨
    if date_from:
        result = [s for s in result if s["date"] >= date_from]
    if date_to:
        result = [s for s in result if s["date"] <= date_to]
    return _json({"ok": True, "tool_name": "personal_list_schedules", "schedules": result})
```
- `_current_session_schedules()`는 PERSONAL_SCHEDULES를 직접 수정하지 않음

### 3. `personal_delete_schedule`
```python
@tool
def personal_delete_schedule(schedule_id: str) -> str:
    scope = current_session_scope()
    before = len(PERSONAL_SCHEDULES)
    PERSONAL_SCHEDULES[:] = [
        s for s in PERSONAL_SCHEDULES
        if not (s["id"] == schedule_id and s["session_id"] == scope)
    ]
    deleted = before - len(PERSONAL_SCHEDULES)
    return _json({"ok": True, "tool_name": "personal_delete_schedule", "deleted": deleted})
```
- `PERSONAL_SCHEDULES[:] = ...` 슬라이스 대입으로 리스트 객체 유지
- `deleted`는 실제 삭제된 항목 수 (int)
- 다른 세션의 같은 ID는 삭제되지 않음

---

## 주의사항
- SQLite/App store 호출 없음 — 순수 메모리 조작만
- `structured_request` / `sqlite_save` 반환 필드 없음
- 날짜 비교는 `YYYY-MM-DD` 문자열 대소 비교로 충분

---

## 검증 방법
1. `build_week01_agent()` 로 에이전트 생성
2. "오늘 오후 2시에 팀 미팅 일정 만들어줘" → `personal_create_schedule` 호출, `created_schedule` 확인
3. "내 일정 보여줘" → `personal_list_schedules` 호출, 방금 생성한 일정 포함 확인
4. "방금 만든 일정 지워줘" → `personal_delete_schedule` 호출, `deleted: 1` 확인
5. "내 일정 보여줘" 재확인 → `schedules: []` 반환 확인
