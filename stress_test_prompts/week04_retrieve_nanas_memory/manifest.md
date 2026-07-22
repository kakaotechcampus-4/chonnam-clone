# week04_retrieve_nanas_memory 스트레스 테스트 프롬프트 세트

생성 시각: 2026-07-22T19:50:00+09:00
대상 tool 14개 (week01~04 누적): personal_create_schedule, personal_list_schedules,
personal_delete_schedule, extract_schedule_request, save_structured_request,
list_saved_requests, get_saved_request, personal_list_saved_schedules,
personal_update_saved_schedule, personal_delete_saved_schedules,
add_personal_reference, search_personal_references, search_saved_requests,
search_conversation_messages

## 카테고리별 개수
- direct: 28개
- boundary: 15개
- ambiguous: 31개
- multi_turn: 14개
- off_topic: 12개

## 이번 세트가 초점 둔 것
- week04에서 새로 발견된 충돌: `search_saved_requests` vs `personal_list_saved_schedules`
  vs `list_saved_requests` — 날짜 조건 유무로 갈리는지 집중 검증 (ambiguous 카테고리
  절반 이상 이 축).
- week1 임시 메모리(`personal_list_schedules`/`personal_delete_schedule`)와 week3
  영속 저장(`personal_list_saved_schedules`/`personal_delete_saved_schedules`) 혼동 여부.
- `personal_create_schedule` vs `save_structured_request`: 우선순위/긴급도 표현
  유무로 갈리는 week03 규칙이 실제로 지켜지는지.
- `search_personal_references` vs `search_conversation_messages`: "적어둔 메모"
  vs "나눴던 대화" 표현 차이로 잘 갈리는지.
- 현재 대화 제외 로직(scenario_rag_a/scenario_rag_b 멀티턴 그룹)이 실제로 동작하는지.
- 삭제 안전장치("있으면 지워줘" 같은 모호 삭제 요청, scenario_delete_guard)가
  바로 삭제로 새지 않는지.

## 재사용 정보
- 최초 생성 (캐시 없음, 100개 전량 신규).
- `tool_signatures` 해시는 args_schema 필드/제약 + docstring 기준. 다음 실행 때
  이 파일들의 구조가 안 바뀐 tool은 이 세트를 재사용한다.
