# Week 1 데이터 및 Tool 계약

## 저장 범위

Week 1 일정은 `PERSONAL_SCHEDULES` 전역 리스트에만 저장한다. 앱 SQLite는 채팅 기록을
저장하지만 Week 1 개인 일정의 저장소로 사용하지 않는다. 따라서 일정은 프로세스를
재시작하면 사라진다.

전역 리스트를 여러 대화가 공유하므로 각 일정에 `session_id`를 저장한다. 생성 시
`current_session_scope()`를 사용하고, 조회와 삭제에서도 동일한 scope만 대상으로 한다.

## 일정 dict

```python
{
    "id": "personal_ab12cd34ef",
    "title": "프로젝트 회의",
    "date": "2026-07-03",
    "start_time": "14:00",
    "end_date": "2026-07-03",
    "end_time": "15:00",
    "attendees": ["민수"],
    "created_at": "2026-06-30T10:30:00.000000+09:00",
    "session_id": "conv_ab12cd34ef",
}
```

필드 규칙:

- `id`: `_new_personal_id()`로 생성한다.
- `title`: 공백을 제거한 비어 있지 않은 문자열이다.
- `date`: `YYYY-MM-DD` 형식의 실제 날짜다.
- `start_time`: `HH:MM` 형식의 실제 시간이다.
- `end_date`: `YYYY-MM-DD` 형식의 실제 날짜다. 입력을 생략하면 `date`와 같다.
- `end_time`: `HH:MM` 또는 `"미정"`이다.
- `attendees`: 입력이 `None`이면 빈 리스트다.
- `created_at`: `_now_iso()`로 생성한다.
- `session_id`: `current_session_scope()`의 반환값이다.

## 생성 계약

성공:

```json
{
  "ok": true,
  "tool_name": "personal_create_schedule",
  "created_schedule": {}
}
```

일정은 검증이 모두 성공한 뒤 한 번만 append한다. Week 1 결과에는
`structured_request`나 `sqlite_save`를 넣지 않는다.

## 조회 계약

성공:

```json
{
  "ok": true,
  "tool_name": "personal_list_schedules",
  "schedules": []
}
```

조회 순서:

1. `_current_session_schedules()`로 현재 session만 선택한다.
2. `date_from`이 있으면 `schedule["date"] >= date_from`을 적용한다.
3. `date_to`가 있으면 `schedule["date"] <= date_to`를 적용한다.
4. 원본 `PERSONAL_SCHEDULES`는 수정하지 않는다.

날짜가 정규화된 `YYYY-MM-DD`이므로 문자열 비교를 사용할 수 있다.

## 삭제 계약

성공:

```json
{
  "ok": true,
  "tool_name": "personal_delete_schedule",
  "deleted": true
}
```

삭제 대상은 ID와 session scope가 모두 일치하는 일정이다. 목록 갱신에는 다음 형태를
사용하여 리스트 객체를 유지한다.

```python
PERSONAL_SCHEDULES[:] = remaining_schedules
```

일치하는 일정이 없으면 오류가 아니라 `deleted: false`를 반환한다.

## 입력 오류 계약

```json
{
  "ok": false,
  "tool_name": "personal_create_schedule",
  "error": "invalid_input",
  "missing_fields": ["start_time"],
  "invalid_fields": {
    "date": "YYYY-MM-DD 형식의 실제 날짜여야 합니다."
  }
}
```

프롬프트는 오류 종류별 예외 문구를 모두 포함하지 않는다. 대신 `missing_fields`와
`invalid_fields`를 읽고 해당 값만 사용자에게 요청한다는 일반 규칙을 둔다.
