# Week 5 — Troubleshooting

## ISO datetime 범위의 시작일 개인 일정이 `collect_member_schedules` 결과에서 제외됨

- 증상: `date_from="2026-07-07T00:00:00"`와 `date_to="2026-07-10T23:59:59"`로 조회하면, 날짜가 `2026-07-07`인 내 일정이 결과 rows에서 빠진다. `test_collect_member_schedules_includes_personal_schedule_on_iso_datetime_start_date`가 이 경우를 재현하며 실패한다.
- 원인: `student_parts/week05_load_kanas_past_conversations.py:302`의 `_collect_member_schedules()`가 내 일정의 `date` (`YYYY-MM-DD`)를 정규화하지 않은 `date_from`/`date_to` (`YYYY-MM-DDTHH:MM:SS`)와 문자열로 직접 비교했다. 외부 MCP 저장소는 전달받은 날짜를 정규화하지만, 로컬 필터는 그렇지 않았다.
- 해결: MCP에 넘기는 `date_from`/`date_to`는 원본 그대로 유지하고, 내 일정 필터 전용으로 `T` 앞의 날짜 부분을 `personal_date_from`/`personal_date_to`에 분리했다. `tests.test_week05_mcp_tools` 13개가 모두 통과했고, 시작일 ISO datetime 회귀 테스트도 통과했다.

## 날짜 경계 및 검색 메타데이터 테스트가 현재 `collect_member_schedules` 구현과 맞지 않음

- 증상: `tests.test_week05_mcp_tools` 전체 실행 시 ISO datetime 시작일 개인 일정과 `searched_member_names`/출처별 일정 수를 검증하는 테스트 3개가 실패한다.
- 원인: `35714cb` 커밋이 `_collect_member_schedules()`를 이전 상태로 덮어쓰면서 `1ee7aa0`의 날짜 경계 정규화와 `6bcad6f`의 검색 메타데이터 반환이 사라졌다. 이어진 `40ac12a`에서는 프롬프트의 검색 메타데이터 안내도 사라졌다.
- 해결: 날짜 비교용 `personal_date_from`/`personal_date_to`와 `searched_member_names`·출처별 일정 수를 다시 적용하고, Week 5 프롬프트에는 공유 일정 생성·삭제 안내와 빈 검색 결과 안내를 모두 유지했다. 관련 회귀 테스트로 각 동작을 함께 검증한다.
