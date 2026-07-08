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
