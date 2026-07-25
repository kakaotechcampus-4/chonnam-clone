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

## 검색 품질 세트 (retrieval_prompts.jsonl + fixtures.jsonl, 2026-07-26 추가)

"올바른 tool을 골랐나"와 별개 축인 "그 tool이 관련 있는 결과를 반환했나"를 잰다.

- fixture 10개: 참고자료 5 (f001~f005, 회의록 유사쌍 f001/f002 포함) +
  SQLite 일정/할일/알림 5 (f101~f105, '회의' 키워드 유사쌍 f101/f105 포함)
- 프롬프트 10개: 직접 매칭 4, 패러프레이즈 1, 유사쌍 순위 2, 빈 결과가 정답 1,
  SQLite 키워드 2, 통합(라우팅 평가 제외) 1
- fixture 판정: id 값 스캔 (seed 시 fixture_map_*.json에 발급 id 기록,
  집계 시 --fixture-map 필수. 초기 마커 [FXT:] 방식은 폐기 — 하위호환 스캔만 유지)
- 격리 DB에 앱 초기화 데모 데이터 존재 → 배경 코퍼스로 간주, 삭제하지 않음.
  fixture는 top_k 슬롯을 배경 문서와 경쟁하므로 expected_hits는 보수적으로 설계.

### 라벨 변경 이력
- 2026-07-26 r010: expected_tool search_nana_memory → null (호환 tool이라 개별
  tool 조합도 정답 — 라벨 오류 분류). expected_hits 4개 → 2개 (참고자료 쪽은
  top_k 2 + 배경 경쟁으로 구조적 회수 불가. 관련도 컷 도입 후 재검토).

### 참고: 과제 코드 변경 (2026-07-26)
- search_personal_references / search_saved_requests docstring 및
  week04_prompt_parts 라우팅 규칙 수정 (스트레스 테스트가 찾은 라우팅 실패 대응).
  → 다음 스킬 실행 시 이 두 tool의 시그니처 해시가 달라져 관련 라우팅 프롬프트가
  재생성 대상이 되는 것이 정상 동작임.
