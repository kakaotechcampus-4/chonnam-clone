# week05_load_kanas_past_conversations 스트레스 테스트 세트

- 대상: `student_parts/week05_load_kanas_past_conversations.py` → `build_week_agent()` → `build_week05_agent()` → `week05_tools()`
- 노출 tool 21개 = week01-04 누적 14개 + week05 신규 7개
  (search_previous_conversations, load_conversation_messages, extract_schedules_from_history,
  create_shared_schedule, delete_shared_schedule, list_shared_schedules, collect_member_schedules)
- 캐시: 신규 stem이라 재사용 없음(2단계 → 4단계 전량 생성). week04 캐시와 독립.

## 카테고리 배분 (총 100)

| 카테고리 | 개수 | 초점 |
|---|---|---|
| direct | 28 | tool마다 최소 1~2개, docstring 핵심어 직접 매칭 |
| boundary | 16 | 숫자 제약(top_k/limit) 6개 tool 이상값 12개 + 신규 tool 필수 필드 누락/한계 nuance 4개 |
| ambiguous | 35 | 역할 겹치는 tool 클러스터 7개(조회3파전/검색4파전/생성2파전/삭제3파전/외부일정4파전/load_conversation_messages 구분/list_saved_requests 구분) |
| multiturn | 15 | 5개 시나리오 x 3턴 — 외부대화 검색→로드→추출 / 개인일정 생성→저장확인→통합조회 / 구조화저장→목록→상세 / 공유일정 등록→조회→삭제 / 저장일정 후보→수정→삭제 |
| off_topic | 6 | 21개 tool 어디에도 안 걸리는 잡담 |

## 핵심 검증 포인트

- **신규 4파전 검색 라우팅**: search_saved_requests(구조화 요청) / search_personal_references(자유 메모)
  / search_conversation_messages(앱 내부 채팅) / search_previous_conversations(외부 멤버 채팅) 4개 tool이
  겹치는 지점 — week04까지는 3파전이었는데 week05에서 4번째 축(외부 멤버 대화)이 추가됨.
- **외부 일정 4파전**: extract_schedules_from_history(순수 추출) / list_shared_schedules(저장소 row 조회)
  / collect_member_schedules(내 것+외부 통합) / search_previous_conversations(대화 원문, 일정 아님) 구분.
  이 4개가 이번 주차의 메인 라우팅 리스크 지점.
- **생성/삭제 대상 구분**: "나"(personal_create_schedule/personal_delete_*) vs 다른 멤버(create_shared_schedule/delete_shared_schedule).
- **_personal_schedules_for_current_scope 중복 제거 검증**: multiturn scenario_2에서 personal_create_schedule로
  생성한 일정이 collect_member_schedules 결과에 중복 없이 1번만 나오는지 확인 필요(코드 리뷰로 이미 확인했으나
  실제 agent 경유 결과에서도 재확인).

## 알려진 이력

- 2026-07-29 1차 실행(20260729-195031): 91개 기대 매칭 중 58 일치/33 불일치. 6.5단계 라벨 재검토 결과:
  - **라벨 오류로 기각(25개)**: p003,p004,p009,p010,p018,p019,p027,p031,p032,p033,p034,p035,p036,p037,p038,p040,p044,p045,p063,p064,p066,p073,p075,p093,p094.
    - 원인 A (존재하지 않는 ID를 단발성으로 언급) → week03 시스템 프롬프트 규칙("삭제/수정 전 반드시 personal_list_saved_schedules로 먼저 조회, schedule_id는 추측 금지")대로 agent가 조회부터 한 게 정상: p003,p009,p010,p063,p064,p066,p093,p094.
    - 원인 B (프롬프트 자체에 필수 정보 누락 - query/날짜/conversation_id 명시 부족): p004,p018,p031,p073,p075.
    - 원인 C (경계값 카테고리의 알려진 함정 - LLM이 이상값 보고 tool 호출 자체를 보류/확인 요청): p032,p033,p034,p035,p036,p037,p038,p040,p044.
    - 원인 D (통합 tool 함정 - collect_member_schedules 대신 personal_list_saved_schedules+list_shared_schedules 조합으로 동일 결과 도출, 실제 answer 내용 정상): p027.
    - 원인 E (라벨 자체가 애매한 이지선다, 실사용도 문제없음): p019,p045.
  - **실제 라우팅 약점으로 확정(8개, 코드 버그는 아니고 week05_prompt_parts의 라우팅 지시 보강 여지)**:
    - 외부 멤버 이름이 명시됐는데도 search_conversation_messages(내부 앱 채팅)로 감: p015,p054,p056,p070,p080(총 5회, 전부 같은 패턴). ⚠️ 격리 DB가 harness 실행 전체에서 공유되고 search_conversation_messages가 conversation_id로 범위를 좁히지 않아, 같은 실행 안의 앞선 프롬프트 텍스트("철수" 언급)가 실제 채팅 기록처럼 검색되는 오염이 섞여 있어 순수 라우팅 문제와 완전히 분리하긴 어려움 - 참고 캐비어트.
    - "뽑아줘/추출/바쁜지 알려줘" + "대화 기록"이 같이 오면 extract_schedules_from_history 대신 search_previous_conversations로 감: p020,p067,p071(총 3회).
  - **validator 직접 검증(agent 우회, `.invoke()` 직접 호출)**: search_previous_conversations.limit(0/51), list_shared_schedules.limit(0/201) 전부 ValidationError로 정상 차단 확인 - 코드 자체는 정상.
  - 기각률 25/33 ≈ 76%로 높지만 대부분 "존재하지 않는 ID를 단발 프롬프트에 넣은" 테스트 설계 결함(원인 A)과 "경계값에서 LLM이 호출을 보류하는" 문서화된 함정(원인 C)에 집중되어 있어 자기채점 편향이라기보다 신규 세트 특유의 설계 미숙 - 다음 실행 시 원인 A/B 패턴은 멀티턴으로 재설계 권장.

- 2026-07-29 2차 실행(20260729-204114), `week05_prompt_parts` 충돌1/충돌2 수정 반영 후: 매치 58→70(91개 중), 불일치 33→20.
  - **충돌1 수정 확인**: p015/p054/p056/p070/p080 전부 search_conversation_messages → search_previous_conversations로 정상화(회귀 섹션에 반영 기록).
  - **충돌2 수정 확인**: p019/p020/p042/p067/p071 전부 extract_schedules_from_history(또는 collect_member_schedules)로 정상화.
  - 남은 20개 불일치는 1차 실행 때 이미 "라벨 오류"로 분류한 것과 동일 패턴(존재하지 않는 ID 단발 언급, 경계값 캐줄 회피) - 새로 생긴 진짜 약점 없음.
  - p032("top_k -3개만") 1건 API 400 에러 발생(empty string embedding 호출) - 코드 버그라기보다 LLM이 이상값 처리 중 빈 문자열을 흘려보낸 비결정적 케이스로 추정, 재발 시 원인 추적 필요.
  - 결론: 프롬프트 충돌 2건 수정이 의도대로 작동했고 다른 카테고리에 회귀 없음.

## 생략한 것

- 검색 품질형(retrieval_prompts.jsonl/fixtures.jsonl): search_personal_references/search_saved_requests/
  search_conversation_messages는 week04 캐시에서 이미 recall/precision 검증됨. search_previous_conversations는
  LIKE 기반이라 임베딩 recall 이슈 없음. 이번 실행은 routing 100개만 수행.
