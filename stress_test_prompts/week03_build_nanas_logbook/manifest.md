# week03_build_nanas_logbook 스트레스 테스트 프롬프트 세트

생성 시각: 2026-07-22T21:45:00+09:00
대상 tool 10개 (week01~03 누적): personal_create_schedule, personal_list_schedules,
personal_delete_schedule, extract_schedule_request, save_structured_request,
list_saved_requests, get_saved_request, personal_list_saved_schedules,
personal_update_saved_schedule, personal_delete_saved_schedules

## 카테고리별 개수
- direct: 30개
- boundary: 14개
- ambiguous: 25개
- multi_turn: 21개
- off_topic: 10개

## 이번 세트가 초점 둔 것
- week04와 구조가 다른 파일(tool 14개 -> 10개, search_* RAG tool 없음)에서
  assignment-stress-test 스킬이 제네릭하게 동작하는지 검증하는 첫 실행.
- `extract_schedule_request`가 실제로는 미구현 스텁(`...`, 항상 None 반환)임을
  오늘 별도로 확인함 — scenario_extract_then_save 그룹(구조화 후 그 결과로 저장)이
  이 버그를 직접 드러낼 것으로 예상.
- week1 임시 메모리 vs week3 영속 저장 tool 혼동 여부(ambiguous 카테고리).
- 삭제/수정 전 안전 확인 규칙(schedule_id 추측 금지, 조건 없는 삭제 거부)이
  실제로 지켜지는지.

## 재사용 정보
- 최초 생성 (week03용 캐시 없음, 100개 전량 신규).
