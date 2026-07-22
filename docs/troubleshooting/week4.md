# Week 4 트러블슈팅 기록

대상 파일: `student_parts/week04_retrieve_nanas_memory.py`
TODO를 구현하다가 막힌 문제와 해결 과정을 발생할 때마다 여기에 추가합니다.

## `WEEK03_TOOL_CALL_PROMPT` 리스트에서 콤마 누락으로 삭제 지침 두 줄이 한 항목으로 합쳐짐

- 증상: "일정 전부 삭제 해"라고 명시적으로 요청해도 "저장된 모든 일정, 할 일, 리마인더 삭제를 시도했으나 삭제된 항목이 없습니다"라며 아무것도 안 지워짐.
- 원인: `student_parts/week03_build_nanas_logbook.py`의 `WEEK03_TOOL_CALL_PROMPT` 리스트에서 삭제 관련 문자열 두 줄 사이에 콤마(`,`)가 빠져 있었음. Python이 이를 암묵적 문자열 이어붙이기로 처리해 두 항목이 하나로 합쳐졌고(문장 사이 공백도 없이 붙음), "명시적으로 전부/모두라고 하면 delete_all=True로 호출한다"는 규칙이 실질적으로 프롬프트에 반영되지 않아 LLM이 항상 `delete_all=False`, 조건 없이 호출 → `_delete_saved_schedules`의 guard(`not delete_all and not has_filter`)에 걸려 거부됨.
- 해결: 두 문자열 사이에 콤마를 추가해 리스트 항목을 분리하고, "전부/모두처럼 명시적 전체 삭제 요청이면 delete_all=True로 호출, 애매하면 먼저 목록 확인 후 조건을 물어본다"는 구분 규칙이 정상적으로 프롬프트에 포함되도록 수정. 이후 "전부 삭제해줘"에 실제로 `delete_all=True`가 호출되어 personal/group 일정이 삭제됨을 확인함.

## todo/reminder는 삭제가 안 됨 (known limitation)

- 증상: "todo랑 reminder 삭제해"처럼 요청하면 항상 "삭제되지 않았습니다"로 실패함. "일정 전부 삭제해"로 personal/group 일정을 지운 뒤에도 todo/reminder는 그대로 남음.
- 원인: `fixed/app_store.py`에 todos/reminders 테이블을 대상으로 하는 delete 메서드가 없음. 존재하는 delete 메서드(`delete_conversation`, `delete_schedule`, `delete_schedules_by_filter`, `delete_all_schedules`)는 전부 `schedules` 테이블 전용이고, `_delete_saved_schedules`(`student_parts/week03_build_nanas_logbook.py`)도 이 메서드들만 호출함. `fixed/app_store.py`는 최초 base-code 동기화(커밋 `645bdac`) 이후 이 부분이 변경된 적이 없어, week3 시점에도 todo/reminder 삭제는 구현되어 있지 않았음 — 당시엔 "일정 알려줘"가 개인/그룹만 보여주고 할 일/리마인더를 놓치던 조회 버그 때문에 삭제된 것처럼 보였을 뿐, 실제로는 처음부터 삭제 기능 자체가 없었던 것으로 추정.
- 해결: 보류. store 레벨 확장(`fixed/app_store.py`에 todos/reminders 삭제 메서드 추가 + `_delete_saved_schedules`를 kind별로 라우팅하도록 확장)이 필요하나 week4 범위 밖. 다음 base-code 동기화 시 `fixed/` 변경이 덮어써질 수 있다는 점도 고려해 어디에 구현할지(store 레벨 vs student_parts 레벨 raw SQL) 다시 판단 필요.

## "참고자료 다 알려줘"에 OpenAI BadRequestError(빈 문자열 임베딩)

- 증상: "참고자료 다 알려줘"라고 물으면 `Week 4 agent 실행 중 오류가 발생했습니다: BadRequestError: Error code: 400 - {'error': {'message': "Invalid 'input[0]': input cannot be an empty string.", ...}}`가 뜸.
- 원인: `PersonalReferenceStore`(`fixed/reference_store.py`)에 참고자료 전체 목록을 조회하는 메서드가 없고 `add_personal_reference`/`search_personal_references` 둘뿐임. "다 알려줘"처럼 특정 키워드가 없는 요청을 받으면 LLM이 `search_personal_references`를 `query=""`(빈 문자열)로 호출했고, 그 요청이 `search_personal_reference_hits` → `reference_store.search_personal_references(query="", ...)` → ChromaDB `collection.query(query_texts=[""])`로 이어져 내부 임베딩 함수가 OpenAI Embeddings API에 빈 문자열을 그대로 넘기면서 API가 400으로 거부함.
- 해결: `search_personal_references` tool(`student_parts/week04_retrieve_nanas_memory.py`) 진입부에 `if not query.strip(): return json_payload({"hits": []})` 가드를 추가해, 빈/공백 쿼리는 store(=OpenAI 임베딩 API)까지 도달하지 않고 빈 `hits`를 바로 반환하도록 수정. 적용 후 같은 질문에 에러 없이 안내 응답이 나오는 것을 확인함. (참고자료 전체 목록 조회 자체는 여전히 미구현 — 위 todo/reminder 삭제 이슈와 같은 종류의 known limitation)

<!-- 아래 형식으로 항목을 추가합니다.

## 문제 제목

- 증상:
- 원인:
- 해결:
-->
