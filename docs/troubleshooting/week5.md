# Week 5 — Troubleshooting

## ISO datetime 범위의 시작일 개인 일정이 `collect_member_schedules` 결과에서 제외됨

- 증상: `date_from="2026-07-07T00:00:00"`와 `date_to="2026-07-10T23:59:59"`로 조회하면, 날짜가 `2026-07-07`인 내 일정이 결과 rows에서 빠진다. `test_collect_member_schedules_includes_personal_schedule_on_iso_datetime_start_date`가 이 경우를 재현하며 실패한다.
- 원인: `student_parts/week05_load_kanas_past_conversations.py:302`의 `_collect_member_schedules()`가 내 일정의 `date` (`YYYY-MM-DD`)를 정규화하지 않은 `date_from`/`date_to` (`YYYY-MM-DDTHH:MM:SS`)와 문자열로 직접 비교했다. 외부 MCP 저장소는 전달받은 날짜를 정규화하지만, 로컬 필터는 그렇지 않았다.
- 해결: MCP에 넘기는 `date_from`/`date_to`는 원본 그대로 유지하고, 내 일정 필터 전용으로 `T` 앞의 날짜 부분을 `personal_date_from`/`personal_date_to`에 분리했다. `tests.test_week05_mcp_tools` 13개가 모두 통과했고, 시작일 ISO datetime 회귀 테스트도 통과했다.

## 날짜 경계 및 검색 메타데이터 테스트가 현재 `collect_member_schedules` 구현과 맞지 않음

- 증상: `tests.test_week05_mcp_tools` 전체 실행 시 ISO datetime 시작일 개인 일정과 `searched_member_names`/출처별 일정 수를 검증하는 테스트 3개가 실패한다.
- 원인: `35714cb` 커밋이 `_collect_member_schedules()`를 이전 상태로 덮어쓰면서 `1ee7aa0`의 날짜 경계 정규화와 `6bcad6f`의 검색 메타데이터 반환이 사라졌다. 이어진 `40ac12a`에서는 프롬프트의 검색 메타데이터 안내도 사라졌다.
- 해결: 날짜 비교용 `personal_date_from`/`personal_date_to`와 `searched_member_names`·출처별 일정 수를 다시 적용하고, Week 5 프롬프트에는 공유 일정 생성·삭제 안내와 빈 검색 결과 안내를 모두 유지했다. 관련 회귀 테스트로 각 동작을 함께 검증한다.

## Wrapper에서 날짜 정규화 규칙을 중복 구현함

- 증상: `student_parts/week05_load_kanas_past_conversations.py:296-297`에서 `split("T", 1)[0].strip()`으로 날짜를 직접 정규화해, store의 날짜 규칙이 바뀌면 개인 일정 필터와 외부 일정 조회가 서로 달라질 수 있다.
- 원인: 파일 상단 가이드가 지정한 `fixed/external_people_store.py`의 `normalize_external_schedule_date_bounds()`를 import하지 않고 동일한 규칙을 wrapper 안에 다시 작성했다. 수정 전에는 세 helper 중 `external_schedule_summary()`만 import하고 있었다.
- 해결: `normalize_external_schedule_date_bounds`를 import하고 `(member_names, date_from, date_to)`를 전달해 개인 일정 필터용 날짜 두 값을 받도록 교체했다. MCP 호출에는 원본 날짜를 그대로 넘겨 store 경계의 정규화 책임을 유지했으며, `tests.test_week05_mcp_tools` 13개가 모두 통과했다.

## 공유 일정 조회가 공용 멤버·날짜 정규화 helper를 재사용하지 않음

- 증상: `fixed/external_people_store.py:361-374`의 `list_shared_schedules()`가 멤버 이름 alias/공백 제거와 ISO datetime 날짜 분리를 직접 구현해, 공용 정규화 규칙이 바뀌면 공유 일정 조회만 다른 규칙을 적용할 수 있다.
- 원인: 같은 파일에 있는 `normalize_external_member_names()`와 `normalize_external_schedule_date_bounds()`를 호출하지 않고 두 규칙을 메서드 내부에 중복 작성했다.
- 해결: 보류. Week 5 wrapper는 원본 멤버 이름을 MCP에 전달하는 현재 책임을 유지해야 하며, `fixed/`는 학생 구현 대상이 아니다. 강사 코드 수정 범위가 허용될 때 `list_shared_schedules()`가 두 공용 helper를 사용하도록 바꾸고 alias·공백·ISO datetime 필터 테스트로 검증한다.

## `collect_member_schedules`의 멤버 이름 공백 유무에 따라 검색 메타데이터가 달라짐

- 증상: `member_names=["철수"]`와 `member_names=[" 철수 "]`로 같은 일정 범위를 조회하면 rows와 일정 수는 같아도 `searched_member_names`와 MCP 전달 인자가 달라졌다. `test_collect_member_schedules_normalizes_member_name_whitespace_consistently`가 수정 전 이 차이로 실패했다.
- 원인: `student_parts/week05_load_kanas_past_conversations.py:288`의 `_collect_member_schedules()`가 입력받은 `member_names`를 공용 규칙으로 정규화하지 않고 외부 일정 조회와 반환 메타데이터에 그대로 사용했다.
- 해결: `normalize_external_member_names()`로 만든 `normalized_member_names`를 날짜 helper, 외부 일정 조회 인자, `searched_member_names`에 함께 사용했다. 공백이 있는 이름과 없는 이름의 결과 및 MCP 호출 인자가 동일한지 검증하는 회귀 테스트를 추가했고, `tests.test_week05_mcp_tools` 14개가 모두 통과했다.

## 본인이 참석하지 않는 그룹 회의가 `collect_member_schedules`에서 내 일정으로 계산됨

- 증상: 2026-08-04에 `내일 10시에 철수랑 영희 회의 잡아줘`라는 요청을 `members=["철수", "영희"]`인 그룹 일정으로 저장한 뒤 2026-08-05를 조회하면, 본인이 참석자에 없는데도 `personal_schedule_count=1`이고 해당 row의 `member_name`이 `"나"`로 반환된다.
- 원인: 수정 전 `_personal_schedules_for_current_scope()`가 AppSQLiteStore의 개인·그룹 일정을 참석 여부와 관계없이 모두 반환하고, `_collect_member_schedules()`가 이 일정들을 전부 `member_name="나"`로 변환했다.
- 해결: `student_parts/week05_load_kanas_past_conversations.py:190`에 `_is_current_user_busy_schedule()`을 추가해 개인 일정과 `"나"`가 참석자인 그룹 일정만 내 busy-time으로 선택했다. Week 2 구조화 프롬프트에도 사용자 참석 여부에 따른 `members` 규칙을 명시하고, 미참석 일정 제외 및 참석 일정 포함 테스트를 각각 추가했으며 Week 5 테스트 16개가 모두 통과했다.
