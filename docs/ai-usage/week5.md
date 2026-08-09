# Week 5 — 이전 대화와 공유 일정 불러오기

대상 파일: `student_parts/week05_load_kanas_past_conversations.py`

## 목표

외부 SQLite/MCP 서버의 이전 대화와 공유 일정을 agent용 tool로 감싸고, 내 일정과 외부 멤버의 busy-time을 하나의 rows 목록으로 합친다.

## 이전 주차와의 연결

Week 4 tool 목록을 이어받고, Week 1의 임시 개인 일정과 Week 3+ SQLite 저장 일정을 함께 사용한다.

## TODO 목록

- [x] `search_previous_conversations`, `load_conversation_messages`, `extract_schedules_from_history`, `list_shared_schedules`, `collect_member_schedules` — 메인 MCP wrapper와 일정 병합 — 상태: 완료
- [x] (줄 422) `create_shared_schedule` — 공유 일정 생성/갱신 MCP wrapper — 상태: 완료
- [x] (줄 450) `delete_shared_schedule` — 공유 일정 삭제 MCP wrapper — 상태: 완료

## 이미 구현되어 있는 함수

- `_personal_schedules_for_current_scope` — SQLite 일정과 현재 대화의 중복되지 않은 임시 일정을 합친다.
- `_collect_member_schedules` — 내 일정과 외부 멤버 일정 row를 한 목록으로 합친다.
- `_my_schedule_notes` — 앱 DB 일정의 개인/그룹 종류와 그룹 참석자를 설명한다.
- `_dedupe_schedule_rows` — 앱 DB와 공유 저장소에서 함께 들어온 같은 일정을 한 번만 남긴다.

## 검증 방법

- `collect_member_schedules` 결과에 내 일정과 외부 멤버 일정이 같은 row 구조로 들어가는지 확인한다.
- ISO datetime 날짜 범위에서도 시작일의 내 일정이 제외되지 않는지 `tests/test_week05_mcp_tools.py`의 회귀 테스트로 확인한다.
- 저장된 그룹 일정의 참석자 목록에 `"나"`가 없어도 내 busy-time으로 포함되는지 확인한다.
- 조율 대상에 `"나"`가 포함돼 앱 DB row와 공유 복사본이 함께 조회돼도 일정과 `members`가 중복되지 않는지 확인한다.
