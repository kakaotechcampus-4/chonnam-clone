# Week 5 트러블슈팅 기록

대상 파일: `student_parts/week05_load_kanas_past_conversations.py`
TODO를 구현하다가 막힌 문제와 해결 과정을 발생할 때마다 여기에 추가합니다.

## 방금 등록한 공유 일정을 `list_shared_schedules`로 확인하면 "없다"고 잘못 답하고, 나중엔 "삭제됐다"고 착각함

- 증상: `create_shared_schedule`로 8월 5일 일정을 등록한 직후 "방금 등록한 공유 일정 목록에 있는지 확인해줘"라고 물으면 agent가 "등록되어 있지 않습니다"라고 답함. 이후 "방금 그 일정 삭제해줘"라고 해도 tool을 호출하지 않고, 다시 "삭제됐는지 확인해줘"라고 물으면 실제로는 삭제 호출을 한 적도 없는데 "삭제된 상태로 보입니다"라고 답함(실제로는 DB에 그대로 남아있었음, `member_names=['철수']`로 직접 조회해 확인).
- 원인: `fixed/external_people_store.py:356~359`에서 `list_shared_schedules()`를 필터 없이 호출하면 외부 실습용 기본 날짜 범위(`JULY_PRACTICE_DATE_FROM`~`JULY_PRACTICE_DATE_TO`, 2026-07-07~2026-07-17)로 자동 대체됨. 방금 등록한 8월 일정은 이 기본 범위 밖이라, agent가 "확인해줘"에 인자 없이 `list_shared_schedules()`를 불렀을 때 결과에 안 나온 것. `week05_prompt_parts()`에 이 기본 필터 동작에 대한 안내가 없어서 agent가 "없음"과 "필터 범위 밖"을 구분하지 못하고 잘못된 결론(미등록/삭제됨)을 내림.
- 해결: `student_parts/week05_load_kanas_past_conversations.py`의 `week05_prompt_parts()`에 다음 두 규칙 추가.
  1. `list_shared_schedules`를 인자 없이 호출하면 기본 날짜 범위만 조회되므로, 특정 일정(방금 등록한 것 등) 존재 여부는 반드시 `member_names`/`date_from`/`date_to`를 명시해서 확인하고, 필터 없는 결과에 없다고 존재하지 않거나 삭제됐다고 단정하지 않는다.
  2. `create_shared_schedule` 결과에 이미 있는 `schedule_id`를 같은 대화에서 재확인/삭제할 때 그대로 재사용하고, 굳이 `list_shared_schedules`를 다시 부르지 않는다.
  적용 후 동일 시나리오(등록→확인→삭제→재확인)를 실제 agent 대화로 재실행: 확인 단계에서 `list_shared_schedules(member_names=['철수'], date_from='2026-08-05', date_to='2026-08-05')`로 정확히 조회, 삭제 단계에서 올바른 `schedule_id`로 `delete_shared_schedule` 호출, 최종 확인에서 정상적으로 "빠져 있음" 확인. PASS.

## `collect_member_schedules`를 실제로 실행하면 `AttributeError: 'list' object has no attribute 'get'`

- 증상: Week6 `find_common_available_slots_dict`(추가과제)에서 처음으로 `collect_member_schedules.invoke(...)`를 실제 실행하자 `_dedupe_schedule_rows([*my_rows, *external_rows.get("rows", [])])` 줄에서 `AttributeError: 'list' object has no attribute 'get'` 발생. Week5 때는 이 경로가 agent 전체 대화로만 검증돼서 (`docs/evals/week5-tasks.md` G3/G4) 발견 못 했던 버그.
- 원인: `_collect_member_schedules`(`student_parts/week05_load_kanas_past_conversations.py:387~389`)에서 `external_rows = result_dict["rows"]`로 받은 값을 dict로 착각하고 `external_rows.get("rows", [])`를 호출함. 실제로는 MCP 서버(`mcp_server/sqlite_mcp_server.py:53~69`)의 `extract_schedules_from_history`가 `{"ok":..., "rows": rows}` 형태로 반환하고, 그 `rows`는 이미 평평한 list임 — 그 안에 또 `"rows"` 키가 있는 게 아님. G3(2026-07-29 검증)는 agent가 `collect_member_schedules`를 통해서가 아니라 마침 이 함수를 안 거치는 경로로 답을 냈던 거라 이 버그를 못 잡았던 것.
- 해결: `_collect_member_schedules` 389행을 `external_rows.get("rows", [])` → `external_rows`로 수정(이미 리스트이므로 그대로 펼쳐 씀). 수정 후 `find_common_available_slots_dict(member_names=['철수'], date_from='2026-07-07', date_to='2026-07-17')`를 직접 호출해 에러 없이 내 일정("나")과 철수 일정이 합쳐진 `busy_rows`가 정상 반환되는 것 확인. PASS. `collect_member_schedules`는 `kana_tools()`에도 그대로 들어있어 Kana가 직접 호출하는 경로(G4)도 같이 고쳐짐.

<!-- 아래 형식으로 항목을 추가합니다.

## 문제 제목

- 증상:
- 원인:
- 해결:
-->
