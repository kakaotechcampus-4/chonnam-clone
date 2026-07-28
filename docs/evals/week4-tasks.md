# Week4 Eval Task 목록

골든 패스/경계 사례/멀티 인텐트/오픈 이슈/회귀 방지/부정 사례는 `week3-tasks.md`를 그대로 이어받는다 (44개, 전부 여전히 유효). 이 파일에는 Week4에서 새로 생긴 기능(개인 참고자료 RAG 저장/검색, SQLite 구조화 요청 검색, 앱 대화 발화 agentic RAG 검색, 호환용 통합 검색)에 대한 task만 추가한다.

Tool 함수 단위(golden/boundary/regression 대부분)는 임시 `chroma_dir`/`sqlite` 경로로 격리한 store를 만들어 `search_personal_reference_hits` 등 내부 함수를 직접 호출해 실제로 검증했다 — 프로덕션 `data/` 디렉터리는 건드리지 않았고, 실행 후 임시 디렉터리는 삭제했다. LLM 라우팅이 관여하는 task(어떤 tool을 고르는지)는 `./run.sh --week4` 전체 agent 대화로만 검증 가능하다 (week3의 멀티 인텐트 task와 동일한 제약) — I1/N1은 2026-07-28 실제 agent 대화 trace로 검증 완료.

총 10개 (골든 4 / 경계 1 / 회귀 3 / 라우팅 회귀 1 / 부정 1) — 전부 PASS.

---

## 골든 패스

### G1 — 개인 참고자료 저장 후 유사 문구로 검색됨
- 입력: `add_personal_reference(title="집중 회의 선호", content="나는 오전 10시에서 12시 사이에 집중도가 높아서 중요한 회의는 오전 중반을 선호한다.", tags=["preference","meeting"])` 저장 후 `search_personal_references(query="오전 회의 선호")`.
- 기대 결과: `hits`에 저장한 참고자료가 포함되고 `metadata.tags`가 문자열이 아니라 `["preference","meeting"]` list로 나옴.
- 검증: 격리된 임시 store로 `add_personal_reference_dict`/`search_personal_reference_hits`를 직접 호출해 확인. PASS.
- 분류: golden

### G2 — SQLite 구조화 요청 검색
- 입력: 개인 일정(`title="치과 예약"`, `date="2026-07-27"`, `start_time="15:00"`) 저장 후 `search_saved_requests(query="치과")`.
- 기대 결과: `rows`에 저장한 일정이 1건 포함됨.
- 검증: `save_structured_request` + `search_saved_request_rows` 직접 호출. PASS (rows 1건).
- 분류: golden

### G3 — 지나간 대화 발화 검색, 현재 세션은 제외
- 입력: 이전 대화에서 `"나는 스타듀밸리라는 게임을 제일 좋아해"` 발화가 있었고, 현재 대화에서 `"내가 예전에 어떤 게임 좋아한다고 말한 적 있었나?"`라고 물음. `search_conversation_messages(query="좋아하는 게임")` 호출.
- 기대 결과: `hits`에 스타듀밸리 발화가 포함되고, 현재 대화 자신은 `exclude_conversation_id`로 제외됨. top-level `hits`/`rows`가 같은 리스트.
- 검증: `search_conversation_messages_dict` 직접 호출. PASS (hits 2건, hits == rows).
- 분류: golden

### G4 — 호환용 통합 검색(`search_nana_memory`)
- 입력: G1의 참고자료가 저장된 상태에서 `search_nana_memory(query="회의 선호")`.
- 기대 결과: 반환 JSON의 `context` 문자열에 참고자료 내용(`"...오전 중반을 선호..."`)이 포함되고 `reference_backend` 키도 함께 반환됨.
- 검증: module-level `REFERENCE_STORE`/`SQLITE_STORE`를 테스트 동안만 격리 store로 바꿔치기하고(끝나고 원복) `search_nana_memory.invoke(...)` 호출. PASS.
- 분류: golden

---

## 경계 사례

### B1 — tags 없이 저장해도 검색 결과 tags가 빈 list (빈 문자열 split 함정 없음)
- 입력: `add_personal_reference(title="태그 없는 메모", content="태그 없이 저장한 메모입니다.", tags=None)` 후 검색.
- 기대 결과: `metadata.tags == []` (`"".split(",")`가 `['']`이 되는 함정에 안 걸림).
- 검증: PASS (`metadata.tags=[]`).
- 분류: boundary

---

## 회귀 방지 (오늘 코드 리뷰 피드백으로 고친 버그)

### R1 — `search_personal_reference_hits`의 tags 타입 불일치
- 증상: ChromaDB metadata는 list를 지원하지 않아 `add_personal_reference`가 저장 시 `",".join(tags)`로 문자열로 바꿔서 저장하는데, `search_personal_reference_hits`가 검색 결과의 이 문자열을 다시 list로 복원하지 않고 그대로 반환해서 `add`가 반환하는 tags(list)와 `search`가 반환하는 tags(문자열) 타입이 어긋났음.
- 수정: `student_parts/week04_retrieve_nanas_memory.py:254`에서 `ref["tags"].split(",") if ref["tags"] else []`로 복원.
- 검증: G1/B1에서 `metadata.tags`가 항상 list로 나오는 것 확인. PASS.
- 분류: regression

### R2 — `search_conversation_message_rows`의 전역 `CONVERSATION_RAG_STORE` 직접 참조
- 증상: 코드 리뷰에서 "모듈 전역을 직접 참조해 mock store를 주입할 수 없어 테스트 가능성이 떨어진다"는 지적을 받음. 형제 함수(`search_conversation_messages_dict` 등)는 전부 store를 파라미터로 받는데 이 함수만 예외였음.
- 수정: `conversation_rag_store`를 함수 인자로 추가.
- 검증: 격리된 임시 `ConversationRAGStore`를 파라미터로 직접 주입해 호출 성공 확인 (`search_conversation_messages_dict`와 동일한 결과 집합 반환). PASS.
- 분류: regression

### R3 — 빈 쿼리로 참고자료 검색 시 OpenAI 임베딩 400 에러 (`docs/troubleshooting/week4.md` 기존 회귀, 재발 여부 재확인)
- 증상(원본): `search_personal_references(query="")`가 빈 문자열을 그대로 OpenAI Embeddings API에 넘겨 400 에러가 났었음.
- 기대 결과: `if not query.strip(): return json_payload({"hits": []})` 가드가 여전히 살아있어 에러 없이 빈 hits를 반환.
- 검증: `search_personal_references.invoke({"query": "", "top_k": 2})` 호출. PASS (`{"hits": []}` 반환, API 호출 자체가 안 일어남).
- 분류: regression

---

## 라우팅 회귀 (agent 전체 대화로만 검증 가능 — 참고용, week3 멀티 인텐트와 동일 제약)

### I1 — "예전에 ~라고 말한 적 있나" 같은 지나가는 발화 질문이 `search_personal_references`로 잘못 라우팅되던 문제
- 입력: `"내가 예전에 어떤 게임 좋아한다고 말한 적 있었나?"` (재확인 시 질문: `"게임 좋아한다"`로 tool query 생성)
- 기대 결과: `search_conversation_messages`가 호출되어야 함(`search_personal_references` 아님).
- 상태: `docs/troubleshooting/week4.md`에 이미 원인 확정 + `week04_prompt_parts()`에 few-shot 예시 추가로 해결 확인됨 (커밋 `b8a70b7`). 2026-07-28 `./run.sh --week4` 실제 agent 대화로 재검증: trace에 `search_conversation_messages` tool_call만 있고 `search_personal_references` 호출 없음, 현재 conversation_id(`conv_ce82ae6bc8`)는 hits에서 제외됨, top-level `hits`==`rows` 확인. PASS.
- 분류: regression (agent 전체 대화 필요, 2026-07-28 실제 trace로 검증 완료)

---

## 부정 사례 (agent 전체 대화로만 검증 가능)

### N1 — 인사말에 참고자료/대화/일정 검색 tool이 오발동 안 함
- 입력: `"안녕"`
- 기대 결과: `search_personal_references`/`search_saved_requests`/`search_conversation_messages`/`search_nana_memory` 중 어느 것도 호출되지 않고 인사로만 응답.
- 상태: 2026-07-28 `./run.sh --week4` 실제 agent 대화로 검증: trace의 `events`가 빈 리스트 — tool 호출 없이 인사로만 응답. PASS.
- 분류: negative (agent 전체 대화 필요, 2026-07-28 실제 trace로 검증 완료)
