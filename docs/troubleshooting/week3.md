# Week 3 트러블슈팅 기록

대상 파일: `student_parts/week03_build_nanas_logbook.py`
TODO를 구현하다가 막힌 문제와 해결 과정을 발생할 때마다 여기에 추가합니다.

## `./run.sh --week3` 실행 시 AttributeError: 'NoneType' object has no attribute 'stream'

- 증상: `./run.sh --week3`로 메인과제(저장/조회 tool) 테스트 중 대화창에 아래 trace payload와 함께 오류가 출력됨.
  ```json
  {"mode": "active_week_agent", "active_week": 3, "events": [], "error": "'NoneType' object has no attribute 'stream'", "error_type": "AttributeError", "conversation_id": "conv_eab713b634"}
  ```
  화면 메시지: `Week 3 agent 실행 중 오류가 발생했습니다: AttributeError: 'NoneType' object has no attribute 'stream'`
- 원인: `build_week03_agent()`의 TODO가 아직 구현되지 않아(`...`로 남음) `_WEEK03_AGENT`가 실제 LangChain agent로 채워지지 않고 `None`인 채로 반환됨. 실행기가 `None` 객체에 `.stream(...)`을 호출하면서 발생.
- 해결: `build_week03_agent()`에서 `_WEEK03_AGENT`가 `None`일 때 `create_agent(model=chat_model(), tools=week03_tools(), system_prompt=week03_system_prompt())`로 실제 agent를 생성해 대입하도록 구현 (Week1 `build_week01_agent()`와 동일한 패턴).

## `week03_prompt_parts()` 리스트 수정 중 SyntaxError: invalid syntax. Perhaps you forgot a comma?

- 증상: `week03_prompt_parts()`의 반환 리스트에 안내 문자열을 추가하던 중 아래 오류 발생.
  ```json
  {"mode": "active_week_agent", "active_week": 3, "events": [], "error": "invalid syntax. Perhaps you forgot a comma? (week03_build_nanas_logbook.py, line 527)", "error_type": "SyntaxError", "conversation_id": "conv_24a8a56d16"}
  ```
- 원인: 리스트 안에 문자열 항목을 새로 추가하면서 이전 항목 뒤에 콤마(`,`)를 빠뜨림. 파이썬이 콤마 없는 인접한 두 문자열을 암묵적 문자열 이어붙이기(implicit string concatenation)로 해석하려다 리스트 문법이 깨짐.
- 해결: 누락된 콤마를 추가해 각 문자열이 리스트의 별도 원소로 인식되도록 수정.

## 그룹 일정을 저장했는데 "내일 일정 뭐야"에 안 보이고 중복 저장됨

- 증상: "오늘 예린이랑 7시30분부터 10시까지 놀거야 그리고 내일은 모각코를 팀원들이랑 오후3시부터 6시까지 할거야"처럼
  한 메시지에 개인 일정 + 그룹 일정을 같이 요청하면:
  1. 저장 직후 "내일 일정은?"이라고 물으면 "저장된 일정이 없습니다. 다시 저장할까요?"라고 답함 (분명히 저장을 요청했는데도).
  2. "저장해"라고 다시 답해도 여전히 "내일 일정 뭐야"에 "저장된 일정이 없습니다"로 답함.
  3. SQLite를 직접 열어보면 같은 "모각코" 일정이 `structured_requests`에 여러 번 중복 저장돼 있었음.
- 원인: `personal_list_saved_schedules`는 `kind`를 지정하지 않으면 기본값 `"personal_schedule"`로만 조회하도록 구현했는데
  (가이드가 요구한 기본 동작), "팀원들이랑" 모각코처럼 여러 명이 참여하는 일정은 `extract_schedule_request`가
  `kind="group_schedule"`로 정확히 분류함. 그 결과:
  - 그룹 일정은 실제로 잘 저장됐지만, 개인 일정만 보는 기본 조회에는 안 잡힘.
  - LLM이 조회 결과가 비어 있는 걸 보고 "저장이 안 됐다"고 착각해 같은 일정을 또 저장 → 중복 row 발생.
  - `sqlite3`로 `structured_requests`/`schedules` 테이블을 직접 조회해 같은 일정이 `kind=group_schedule`로
    여러 번 들어가 있는 것으로 원인을 확정함.
- 해결: 코드(tool 기본값)는 그대로 두고, `WEEK03_TOOL_CALL_PROMPT`에 아래 지시를 추가해 프롬프트 레벨에서 해결.
  ```python
   "일정 조회시 개인/그룹 구분 없이 보여달라고 하면 kind를 지정하지 말고 개인+그룹 모두 확인해."
  ```
  적용 후 같은 시나리오를 새 대화로 재현했을 때, "내일 일정 뭐야"에 그룹 일정("오후 3시부터 6시까지 팀원들과 모각코")이
  정상적으로 조회됨을 확인함.

<!-- 아래 형식으로 항목을 추가합니다.

## 문제 제목

- 증상:
- 원인:
- 해결:
-->
