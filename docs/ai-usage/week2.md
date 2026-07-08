# Week 2 튜터링 가이드

대상 파일: `student_parts/week02_structure_natural_language_requests.py`

이 문서는 수강생이 TODO를 **직접** 작성하고, Claude는 정답 코드를 대신 써주지 않고 힌트/설계 방향만 제시하는 튜터링 세션을 위한 참고 문서다. 튜터링할 때마다 이 파일을 먼저 읽고 현재 진행 상태와 힌트 포인트를 확인한다.

## 배경

Week 1(`student_parts/week01_wake_up_nana.py`)은 이미 구현되어 있고 아래 패턴을 그대로 참고할 수 있다.

- 개인 일정 CRUD tool: `personal_create_schedule`, `personal_list_schedules`, `personal_delete_schedule`
- `join_system_prompt`, `week01_prompt_parts`, `week01_tools`, `build_week01_agent`

Week 2는 Week 1 tool 결과 JSON이나 사용자의 한국어 자연어를("내일 오후 3시" 등) `StructuredRequest`/`StructuredRequestBatch`로 구조화하는 단계다. 이 단계에서는 SQLite 저장, RAG, 외부 멤버 일정 조율을 하지 않는다.

## TODO 목록 (진행 순서)

1. **`StructuredRequest` 스키마** (라인 107~121)
   - `kind`: `RequestKind` 타입, `Field(description=...)`
   - `title/date/start_time/end_time`: `str | None`, 기본값 `None`
   - `members`: `list[str]`, `default_factory=list` (현재 코드에 `deafult_factory` 오타 있음 — 발견하도록 유도)
   - `priority/reason`: `str | None`, 기본값 `None`
   - `original_text`: `str`, 기본값 `""`
   - 모든 필드에 LLM이 이해할 한국어 `description` 작성

2. **`StructuredRequestBatch` 스키마** (라인 130~131)
   - `requests: list[StructuredRequest]`, `default_factory=list`
   - `base_date: str`, `default_factory=current_app_date_iso`
   - 각각 한국어 description

3. **`week02_tools()`** (라인 156~158)
   - 현재 버그: `personal_list_schedules()`/`personal_delete_schedule()`를 **호출**하고 있음
   - 올바른 방향: Week 1의 `week01_tools()`를 그대로 반환

4. **`week02_prompt_parts()`** (라인 173~179)
   - `week01_prompt_parts()` 뒤에 이어붙일 Week 2 지시 내용:
     - 구조화 agent 역할, `current_app_date_iso()` 기준일 명시
     - 자연어를 `StructuredRequest` 필드로 구조화하라는 지시
     - Week 1 tool JSON(`created_schedule`)을 받았으면 다시 tool을 호출하지 말고 payload를 읽어 구조화
     - SQLite 저장, RAG, 외부 멤버 일정 조율은 하지 않는다고 명시

5. **`week02_system_prompt()`** (라인 164~167)
   - `join_system_prompt(week02_prompt_parts())` 형태로 합치기
   - `StructuredRequestBatch` 형식으로 최종 답변, `requests`는 요청이 하나여도 list 유지
   - `personal_create_schedule` 결과의 `created_schedule` JSON을 읽어 필드를 채우도록 지시

6. **`build_week02_agent()`** (라인 185~190)
   - `CONFIG.has_openai_key` 없으면 `RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")`
   - 전역 `_WEEK02_AGENT` 캐시 재사용, 없을 때만 생성
   - `create_agent(model=chat_model(), tools=week02_tools(), response_format=StructuredRequestBatch, system_prompt=week02_system_prompt())`
   - Week 1의 `build_week01_agent()`와 거의 동일한 패턴 + `response_format` 추가

> `_coerce_structured_request`, `extract_structured_request`, `extract_schedule_request` tool은 이후 회차 예약 함수라 이번 범위가 아님. `...` 그대로 유지.

## 튜터링 진행 방식

- 위 순서대로 한 항목씩 진행. 사용자가 먼저 시도하고, 막히면 개념/방향 힌트(pydantic Field 문법, list/None 기본값 함정, langchain `response_format` 연결 지점 등)를 질문 형태나 참고 위치 pointer로 제공.
- 완성 코드를 대신 작성하지 않는다. 사용자가 작성한 코드를 Read로 확인하고 Week 1 패턴과의 일관성, 오타, 필드 타입만 짚어준다.
- 각 항목 완료 후 다음 항목으로 넘어가되, 사용자가 순서를 바꾸길 원하면 따른다.
- 코드 수정은 사용자가 직접 하거나, 명시적으로 "이 부분은 대신 써줘"라고 요청할 때만 Edit 사용.

## 검증 방법

전체 TODO 완료 후 `./run.sh --week2`로 실행하고 "다음 주 화요일 오후 3시에 철수랑 회의 잡아줘" 같은 문장을 입력해 `StructuredRequestBatch` 형식의 structured_response가 나오는지 확인한다.
