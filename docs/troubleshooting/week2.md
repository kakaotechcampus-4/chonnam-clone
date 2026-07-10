# Week 2 트러블슈팅 기록

대상 파일: `student_parts/week02_structure_natural_language_requests.py`
TODO를 구현하다가 막힌 문제와 해결 과정을 발생할 때마다 여기에 추가합니다.

<!-- 아래 형식으로 항목을 추가합니다.

## 문제 제목

- 증상:
- 원인:
- 해결:
-->

## 일정을 등록했다고 답했는데 조회하면 "등록된 일정이 없다"고 나옴

- 증상: "오늘 진석이랑 포켓몬게임하기로 했고 오후8시에 할거야"라고 하면 "등록했어요"라고 답하지만, 바로 이어서 "오늘 일정 말해봐"라고 물으면 "오늘 일정이 아직 등록되어 있지 않아요"라고 답함.
- 원인:
  1. `./run.sh`를 인자 없이 실행하면 `KANANA_ACTIVE_WEEK`가 기본값 `1`로 세팅되어 실제로는 Week 2가 아니라 **Week 1 agent**가 응답하고 있었음 (`./run.sh --week2`로 실행해야 Week 2가 뜸).
  2. Week 1의 시스템 프롬프트(`student_parts/week01_wake_up_nana.py`의 `CHAT_MEMORY_PROMPT`)에는 오늘 날짜 정보가 전혀 없음. `fixed/runtime_clock.py`의 `current_app_date_iso()`가 있는데도 참조하지 않아서, LLM이 "오늘"을 매 턴 다르게 추측함.
  3. 실제로 재현해보니 등록 시엔 "오늘" → `date="2024-06-06"`, 조회 시엔 "오늘" → `date_from=date_to="2023-11-24"`로 서로 다르게 해석되어 `personal_list_schedules`의 날짜 필터에 걸려 빈 리스트가 반환됨.
  4. Week 2 시스템 프롬프트(`week02_prompt_parts()`)는 `current_app_date_iso()`를 명시적으로 프롬프트에 넣고 있어서, `./run.sh --week2`로 정상 실행하면 이 날짜 불일치 문제는 재현되지 않음.
- 해결: `./run.sh --week2`로 실행해서 Week 2 agent를 사용하도록 함. (Week 1의 `CHAT_MEMORY_PROMPT`에 날짜 정보가 없는 것 자체는 별도 잠재 이슈로 남겨둠.)

## 채팅 답변이 자연스러운 대화체가 아니라 `StructuredRequestBatch(...)` Python object 그대로 출력됨

- 증상: `./run.sh --week2`로 정상 실행한 뒤에는 날짜 문제는 해결됐지만, 채팅창에 `StructuredRequestBatch(requests=[StructuredRequest(kind='personal_schedule', ...)], base_date='2026-07-09')` 같은 raw object 문자열이 그대로 표시됨. 일정 관리 챗봇이라면 "네, 등록했어요" 같은 대화체로 답해야 하는데 그렇지 않음.
- 원인:
  1. `week02_system_prompt()`의 `"StructuredRequest의 필드 규칙을 기반으로 최종 답변한다."` 라는 지시 문구가 모델에게 "최종 답변 = 구조화된 필드"로 읽혀서, 모델이 대화체 문장 대신 구조화된 내용을 그대로 답변으로 생성함.
  2. `fixed/langchain_trace.py`의 `extract_final_text()`가 `structured_response`가 존재하면 무조건 `repr(value)`로 변환해 채팅 답변으로 사용함. `app.py`의 "상세" 탭(`trace_json`)에 이미 `structured_response`가 별도로 표시되고 있어서, 채팅 답변칸에까지 raw object가 중복 노출되는 구조.
- 해결: 아래 `ToolStrategy` 적용으로 해결함 (다음 항목 참고).

## system prompt에 "자연스럽게 답변하라"를 추가했더니 `StructuredOutputValidationError` 발생

- 증상: 위 문제를 고치려고 `week02_system_prompt()`에 "최종 답변은 자연스러운 대화체로 하라"는 지시를 추가하고 다시 테스트하니, 아예 응답을 못 받고 아래 오류가 발생함.
  ```
  Week 2 agent 실행 중 오류가 발생했습니다: StructuredOutputValidationError: Failed to parse structured output for tool 'StructuredRequestBatch': Native structured output expected valid JSON for StructuredRequestBatch, but parsing failed: Extra data: line 2 column 1 (char 439).
  ```
- 원인: `build_week02_agent()`에서 `response_format=StructuredRequestBatch`처럼 pydantic class를 그대로 넘기면, LangChain(`create_agent`, v1.3)이 기본적으로 `AutoStrategy` → 모델이 지원하면 `ProviderStrategy`(OpenAI native structured output/JSON mode)를 사용함. 이 모드는 모델의 마지막 응답이 **스키마에 맞는 순수 JSON 하나여야만** 파싱에 성공함. 그런데 시스템 프롬프트가 "자연어로도 답하라"고 지시하니 모델이 `JSON` 뒤에 자연어 문장을 이어 붙여서 응답했고, 이게 "Extra data" 파싱 에러로 이어짐. 즉 **prompt 문구만으로는 구조적으로 해결 불가** — 같은 메시지 안에 순수 JSON과 자연어를 동시에 담을 수 없는 구조.
- 해결: `build_week02_agent()`의 `response_format`을 bare pydantic class 대신 `ToolStrategy`로 감싸서 해결함.

  ```python
  from langchain.agents.structured_output import ToolStrategy

  # response_format=StructuredRequestBatch  # 기존: native structured output(순수 JSON 강제) 사용
  response_format=ToolStrategy(StructuredRequestBatch)  # 변경: 구조화 결과를 별도 hidden tool call로 분리
  ```

  `ToolStrategy`로 감싸면 구조화 데이터(`StructuredRequestBatch`)를 별도의 hidden tool call 결과로 채우고, 모델의 메인 대화 응답은 자연어 텍스트를 그대로 유지할 수 있게 된다. 즉 "최종 답변 메시지 = 순수 JSON 한 덩어리"라는 native structured output 제약에서 벗어나서, 자연어 답변과 구조화 데이터를 동시에 얻을 수 있다.

  검토했던 다른 방법(`StructuredRequestBatch`에 `reply: str` 필드를 추가하고 화면 표시 로직에서 그 필드만 꺼내 쓰는 방법)은 `fixed/langchain_trace.py`의 공통 추출 로직까지 수정해야 해서 채택하지 않음. `ToolStrategy` 방식은 `student_parts/week02_structure_natural_language_requests.py` 한 파일 수정만으로 해결됨.

## "OpenAI API를 쓰니까 `ProviderStrategy`가 더 낫지 않을까" 싶어서 다시 바꿔봤다가 같은 에러 재현

- 증상: 위 항목에서 `ToolStrategy`로 문제를 해결한 뒤, "우리 모델이 결국 OpenAI 계열(`openai/gpt-4.1-mini`)이니 provider의 native structured output(`ProviderStrategy`)이 tool-calling 흉내(`ToolStrategy`)보다 더 견고하지 않을까"라는 생각으로 다시 `ProviderStrategy(StructuredRequestBatch)`로 바꿔서 `./run.sh --week2`를 테스트함. 결과는 동일 계열의 에러 재발생:
  ```
  Week 2 agent 실행 중 오류가 발생했습니다: StructuredOutputValidationError: Failed to parse structured output for tool 'StructuredRequestBatch': Native structured output expected valid JSON for StructuredRequestBatch, but parsing failed: Extra data: line 2 column 1 (char 438)..
  ```
- 원인:
  1. 위 항목과 근본 원인이 동일함. `week02_system_prompt()`(`week02_prompt_parts()` 안)에 `"사용자에게 보여줄 답변은 챗봇처럼 자연스러운 한국어 대화체 문장으로 말해라."`라는 지시가 여전히 남아있는데, `ProviderStrategy`는 모델의 마지막 응답 메시지 전체가 스키마에 맞는 **순수 JSON 하나**여야만 파싱에 성공함(`langchain/agents/structured_output.py`의 `ProviderStrategyBinding.parse()`가 `json.loads(raw_text)`를 그대로 호출). "자연스러운 대화체로 말해라"와 "순수 JSON만 반환해라"는 같은 메시지 안에서 동시에 만족할 수 없는 상호 모순되는 지시라서, 모델이 JSON을 낸 뒤 그 뒤에 자연어 문장을 이어 붙였고 `json.loads`가 "Extra data"로 실패함.
  2. `openai/gpt-4.1-mini`라는 모델명 자체는 `_supports_provider_strategy()`(`langchain/agents/factory.py`)의 fallback 목록(`FALLBACK_MODELS_WITH_STRUCTURED_OUTPUT`에 포함된 `"gpt-4.1"`이 부분 문자열로 매칭)에 걸려 `ProviderStrategy` 사용 자체는 가능한 것으로 판정됨. 즉 "모델이 native structured output을 지원하는가"는 문제가 아니었고, **system prompt가 자연어 답변을 요구하는 한 `ProviderStrategy`는 이 프로젝트 구조와 근본적으로 안 맞음**.
- 해결: `response_format=ProviderStrategy(StructuredRequestBatch)`는 유지한 채, `week02_system_prompt()`에서 원인이었던 `"사용자에게 보여줄 답변은 챗봇처럼 자연스러운 한국어 대화체 문장으로 말해라."` 지시를 제거함. 에러가 사라짐.
  - 근본 원인 재확인: 이 지시 문구는 애초에 Week 2 과제 지시사항에 없는, 내가 지시사항을 제대로 안 보고 임의로 추가한 문구였음. 파일 상단 가이드의 검증 방법(`# 검증 방법 ... 최종 답변이 StructuredRequestBatch class 형식의 structured_response로 나오는지 확인합니다.`)에도 나와 있듯, Week 2 agent의 최종 응답은 애초부터 자연어 대화체가 아니라 `structured_response`(StructuredRequestBatch) 자체여야 함. 즉 이전 항목("채팅 답변이 자연스러운 대화체가 아니라 `StructuredRequestBatch(...)` 그대로 출력됨")에서 "문제"라고 판단했던 현상도 사실은 문제가 아니라 Week 2의 의도된 동작이었고, 그걸 "문제"로 오인해서 넣은 대화체 지시가 이번 `ProviderStrategy` 충돌의 진짜 원인이었음.
  - 결론: `ToolStrategy`로 우회했던 이전 해결책은 증상(라우팅 실패)은 없앴지만 원인(지시사항 오독)은 그대로 둔 임시방편이었음. 지시사항을 다시 확인해 불필요한 대화체 지시를 제거하는 것이 정확한 해결책.

## `ProviderStrategy` import를 지워도 실제로는 여전히 같은 전략이 쓰임 (원인 판단은 처음부터 대화체 지시였음)

- 증상: 위 항목에서 대화체 지시를 지운 뒤, `from langchain.agents.structured_output import ProviderStrategy` import를 주석 처리하고 `response_format=ProviderStrategy(StructuredRequestBatch)` 대신 `response_format=StructuredRequestBatch`(순수 pydantic class)로 바꿔서 다시 테스트함. 정상 응답이 옴.
  - 판단: 애초에 "`ProviderStrategy`를 지워서 해결됐다"고 결론 내린 적은 없음. 처음부터 "내가 프롬프트에 넣은 한국어 대화체 강제 지시가 `ProviderStrategy`의 순수 JSON 요구와 충돌해서 지금까지 에러가 나고 있었다"고 판단했고, 이번 테스트는 그 판단을 다시 확인해본 것.
- 기술적으로 짚어둘 점: `response_format`에 `ToolStrategy`/`ProviderStrategy`로 감싸지 않은 순수 schema class를 넘기면, `create_agent`가 내부적으로 `AutoStrategy(schema=response_format)`로 감쌈(`langchain/agents/factory.py:877-878`). `AutoStrategy`는 `_supports_provider_strategy(model, tools)`로 모델을 보고 `ProviderStrategy`/`ToolStrategy` 중 하나를 자동으로 골라 그대로 적용함(`factory.py:1219-1229`). 이 프로젝트의 모델명 `openai/gpt-4.1-mini`는 fallback 목록의 `"gpt-4.1"`과 부분 문자열로 매칭되어 `_supports_provider_strategy()`가 `True`를 반환하므로, `ProviderStrategy` import를 지워도 `AutoStrategy`가 내부적으로 여전히 `ProviderStrategy`를 선택하고 있을 가능성이 높음. 즉 `response_format`을 bare `StructuredRequestBatch`로 두는 것과 `ProviderStrategy(StructuredRequestBatch)`로 명시하는 것은 이 프로젝트 모델 기준으로 결과적으로 같은 전략이 선택됨.
- 해결/결론: 두 번의 테스트(명시적 `ProviderStrategy` + 대화체 지시 제거, bare schema + 대화체 지시 제거)가 모두 정상 응답으로 이어진 것은 결국 같은 원인 하나 — "대화체 강제 지시 제거" — 때문. `ProviderStrategy`를 명시했는지 여부는 이 모델 기준으로는 결과에 영향이 없었다는 걸 재확인함.

## "조회" 요청("내일 일정알려줘")에서 대화체 지시 없이도 같은 `StructuredOutputValidationError` 재현 → `ToolStrategy`로 최종 확정

- 증상: 대화체 지시를 지운 상태(위 두 항목)에서 "등록" 요청은 문제없이 동작했지만, "내일 일정알려줘" 같은 **조회** 요청을 보내니 프롬프트에 대화체 지시가 전혀 없는데도 다시 같은 에러가 재현됨.
  ```
  Week 2 agent 실행 중 오류가 발생했습니다: StructuredOutputValidationError: Failed to parse structured output for tool 'StructuredRequestBatch': Native structured output expected valid JSON for StructuredRequestBatch, but parsing failed: Extra data: line 2 column 1 (char 239)..
  ```
- 원인: 앞의 두 항목과 근본 원인은 같지만(= `ProviderStrategy`의 "최종 메시지 = 순수 JSON 하나" 제약과 자연어 응답이 충돌), 이번엔 트리거가 프롬프트 문구가 아니라 **요청 종류** 자체였음.
  1. "등록" 요청은 `kind=personal_schedule`, `title`, `date`, `start_time` 등으로 자연스럽게 매핑되는 요청이라, 대화체 지시만 없으면 모델이 JSON 하나만 깔끔하게 반환함.
  2. "조회" 요청은 흐름이 다름: 모델이 `personal_list_schedules` tool을 호출 → 일정 목록 JSON을 받음 → 사용자의 질문("내일 일정이 뭐야?")에 답해야 하는데, `StructuredRequest` 스키마(`kind/title/date/.../priority/reason/original_text`)에는 "조회 결과를 사람이 읽을 답으로 알려주는" 필드가 아예 없음.
  3. 그래서 프롬프트에 아무 지시가 없어도, 모델이 사용자의 질문에 답하려는 자연스러운 동기로 JSON 뒤에 "내일 일정은 OO입니다" 같은 설명을 이어 붙이고, `json.loads`가 그 뒤에 남은 텍스트를 "Extra data"로 인식해 실패함.
  4. 즉 "JSON 대신 텍스트를 내려는" 게 아니라 "**JSON + 텍스트를 같이 내려다가**" 충돌한 것. `ProviderStrategy`는 메시지 전체가 스키마에 맞는 JSON 하나여야만 허용하고, JSON 뒤에 조금이라도 텍스트가 붙는 걸 허용하지 않음.
  5. 대화체 지시 제거로 등록 케이스가 해결됐던 건 등록 요청이 우연히 스키마와 깔끔히 맞아떨어진 경우였을 뿐이고, 조회처럼 애초에 사람에게 답해야 하는 요청 유형에는 프롬프트를 아무리 손봐도 구조적으로 통하지 않는 임시 봉합이었음이 이번에 드러남.
- 해결: `response_format`을 다시 `ToolStrategy(StructuredRequestBatch)`로 되돌림. 조회 요청 재시도 시 정상 출력됨.
  - `ToolStrategy`는 구조화 데이터(`StructuredRequestBatch`)를 별도 hidden tool call 결과로 채우고, 메인 응답 메시지는 JSON 순수성 제약 없이 자연어로 자유롭게 답할 수 있음. 그래서 등록/조회/삭제 등 어떤 요청 유형이든(사람에게 답이 필요한 요청이든 아니든) 안전하게 처리됨.
  - **최종 결론**: 이 프로젝트(Week 1 tool + Week 2 구조화 agent를 한 agent로 합쳐서, 최종 메시지에 자연어 답변과 구조화 데이터를 동시에 담아야 하는 구조)에서는 provider나 모델 종류와 무관하게 `ToolStrategy`가 구조적으로 맞는 선택이고, `ProviderStrategy`/`AutoStrategy`(bare schema)는 이 구조에서 계속 재발할 수 있는 근본적인 부적합이므로 채택하지 않음.
