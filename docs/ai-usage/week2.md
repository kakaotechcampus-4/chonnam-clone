# Week 2 튜터링 가이드

대상 파일: `student_parts/week02_structure_natural_language_requests.py`

이 문서는 수강생이 TODO를 **직접** 작성하고, Claude는 정답 코드를 대신 써주지 않고 힌트/설계 방향만 제시하는 튜터링 세션을 위한 참고 문서다. 튜터링할 때마다 이 파일을 먼저 읽고 현재 진행 상태와 힌트 포인트를 확인한다.

## 배경

Week 1(`student_parts/week01_wake_up_nana.py`)은 이미 구현되어 있고 아래 패턴을 그대로 참고할 수 있다.

- 개인 일정 CRUD tool: `personal_create_schedule`, `personal_list_schedules`, `personal_delete_schedule`
- `join_system_prompt`, `week01_prompt_parts`, `week01_tools`, `build_week01_agent`

Week 2는 Week 1 tool 결과 JSON이나 사용자의 한국어 자연어를("내일 오후 3시" 등) `StructuredRequest`/`StructuredRequestBatch`로 구조화하는 단계다. 이 단계에서는 SQLite 저장, RAG, 외부 멤버 일정 조율을 하지 않는다.

## TODO 목록 (진행 순서)

1. **`StructuredRequest` 스키마** (라인 160~195)
   - `kind`: `RequestKind` 타입, `Field(description=...)`
   - `title/date/start_time/end_time`: `str | None`, 기본값 `None`
   - `members`: `list[str]`, `default_factory=list` (현재 코드에 `deafult_factory` 오타 있음 — 발견하도록 유도)
   - `priority/reason`: `str | None`, 기본값 `None`
   - `original_text`: `str`, 기본값 `""`
   - 모든 필드에 LLM이 이해할 한국어 `description` 작성

2. **`StructuredRequestBatch` 스키마** (라인 196~211)
   - `requests: list[StructuredRequest]`, `default_factory=list`
   - `base_date: str`, `default_factory=current_app_date_iso`
   - 각각 한국어 description

3. **`week02_tools()`** (라인 240~246)
   - 현재 버그: `personal_list_schedules()`/`personal_delete_schedule()`를 **호출**하고 있음
   - 올바른 방향: Week 1의 `week01_tools()`를 그대로 반환

4. **`week02_prompt_parts()`** (라인 262~278)
   - `week01_prompt_parts()` 뒤에 이어붙일 Week 2 지시 내용:
     - 구조화 agent 역할, `current_app_date_iso()` 기준일 명시
     - 자연어를 `StructuredRequest` 필드로 구조화하라는 지시
     - Week 1 tool JSON(`created_schedule`)을 받았으면 다시 tool을 호출하지 말고 payload를 읽어 구조화
     - SQLite 저장, RAG, 외부 멤버 일정 조율은 하지 않는다고 명시

5. **`week02_system_prompt()`** (라인 247~261)
   - `join_system_prompt(week02_prompt_parts())` 형태로 합치기
   - `StructuredRequestBatch` 형식으로 최종 답변, `requests`는 요청이 하나여도 list 유지
   - `personal_create_schedule` 결과의 `created_schedule` JSON을 읽어 필드를 채우도록 지시

6. **`build_week02_agent()`** (라인 279~299)
   - `CONFIG.has_openai_key` 없으면 `RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")`
   - 전역 `_WEEK02_AGENT` 캐시 재사용, 없을 때만 생성
   - `create_agent(model=chat_model(), tools=week02_tools(), response_format=ToolStrategy(StructuredRequestBatch), system_prompt=week02_system_prompt())`
   - Week 1의 `build_week01_agent()`와 거의 동일한 패턴 + `response_format` 추가
   - `response_format`은 bare `StructuredRequestBatch`나 `ProviderStrategy`가 아니라 `ToolStrategy`로 감싸야 함 — 이유는 `docs/troubleshooting/week2.md`의 관련 항목들 참고 (같은 메시지 안에 자연어 답변 + 순수 JSON을 동시에 담을 수 없어서 생기는 문제)

메인과제는 여기까지. 아래는 이번에 새로 추가된 **추가 과제**(bridge 함수) TODO.

## 추가 과제: bridge 함수 (Week 3 이상에서 재사용)

> 이 세 함수는 Week 2 agent에 노출되는 tool이 아니다(`week02_tools()`에 추가하지 않는다). Week 3 이상의 저장/조율 agent가 자연어나 Week 1 tool JSON을 구조화할 때 재사용하는 독립적인 bridge 코드다.

7. **`_coerce_structured_request(value)`** (라인 212~218)
   - `value`가 이미 `StructuredRequest` 인스턴스면 그대로 반환
   - `value`가 `dict`면 `StructuredRequest.model_validate(value)`로 검증해서 반환
   - 위 두 경우가 아니면 `RuntimeError`를 던지기 — 잘못된 LLM 응답을 조용히 통과시키지 않는 게 포인트
   - 힌트: `isinstance(value, StructuredRequest)` / `isinstance(value, dict)`로 분기하면 됨

8. **`extract_structured_request(text)`** (라인 221~227)
   - agent 전체를 새로 만드는 게 아니라, `chat_model().with_structured_output(StructuredRequest, method="function_calling")`로 **model 하나**만 구조화 모드로 바인딩
   - system 메시지에는 `join_system_prompt(week02_prompt_parts())`, user 메시지에는 `text`를 넣어서 `.invoke(...)`
   - `with_structured_output(...)`의 반환값을 바로 return하지 말고, `_coerce_structured_request(...)`를 한 번 거쳐서 반환 — 실제로 dict가 오는지 pydantic 인스턴스가 오는지 직접 확인해보도록

9. **`extract_schedule_request(query)`** (라인 231~237, `@tool` 데코레이터 있음)
   - `extract_structured_request(query)`를 호출
   - `ok`/`tool_name`/`base_date`/`structured_request` 키를 가진 dict 구성
     - `structured_request`에는 `.model_dump()` 결과를 넣기
     - `base_date`를 어디서 가져올지 생각해보게 하기 (`StructuredRequest`에는 `base_date` 필드가 없다는 점 — `current_app_date_iso()`를 직접 쓸지, 다른 방법이 있을지 스스로 판단하도록 유도)
   - `json.dumps(..., ensure_ascii=False)`로 반환 — Week 1 tool들의 `_json(...)` 패턴과 동일

## 튜터링 진행 방식

- 위 순서대로 한 항목씩 진행. 사용자가 먼저 시도하고, 막히면 개념/방향 힌트(pydantic Field 문법, list/None 기본값 함정, langchain `response_format` 연결 지점 등)를 질문 형태나 참고 위치 pointer로 제공.
- 완성 코드를 대신 작성하지 않는다. 사용자가 작성한 코드를 Read로 확인하고 Week 1 패턴과의 일관성, 오타, 필드 타입만 짚어준다.
- 각 항목 완료 후 다음 항목으로 넘어가되, 사용자가 순서를 바꾸길 원하면 따른다.
- 코드 수정은 사용자가 직접 하거나, 명시적으로 "이 부분은 대신 써줘"라고 요청할 때만 Edit 사용.

## 검증 방법

- 메인과제(1~6): `./run.sh --week2`로 실행하고 "다음 주 화요일 오후 3시에 철수랑 회의 잡아줘" 같은 문장을 입력해 `StructuredRequestBatch` 형식의 structured_response가 나오는지 확인한다.
- 추가 과제(7~9): 아직 Week 2 agent에 연결되는 tool이 아니라서 `./run.sh --week2` 화면만으로는 직접 검증이 안 됨. `extract_structured_request("내일 오후 3시에 철수랑 회의")` 처럼 함수를 직접 호출해보거나, python REPL/임시 스크립트로 `_coerce_structured_request`에 pydantic 인스턴스/dict/그 외 값을 각각 넣어보며 분기를 확인하는 걸 권장. Week 3 파일이 공개되면 그때 실제 agent에서 `extract_schedule_request` 호출 후 트레이스에 `ok/tool_name/base_date/structured_request`가 제대로 들어있는지로 최종 검증.
