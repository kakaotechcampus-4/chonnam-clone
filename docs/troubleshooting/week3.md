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

- 증상: "오늘 철수랑 7시30분부터 10시까지 놀거야 그리고 내일은 모각코를 팀원들이랑 오후3시부터 6시까지 할거야"처럼
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

## 일정 수정 응답에서 시간 일부에 취소선(작대기)이 그어짐

- 증상: "7/16 풋살 일정 시간을 20:00 부터 22:00까지로 바꿔줘"라고 수정 요청하면, 응답이
  "7월 16일 풋살 일정 시간을 15:00~17:00에서 20:00~22:00로 변경했습니다."처럼 나오는데,
  화면에는 `17:00에서 20:00` 부분에 취소선이 그어져 보임.
- 원인: LLM이 시간 범위를 표현할 때 `15:00~17:00`처럼 물결표(`~`)를 구분자로 씀. 응답 문장 안에
  `~`가 두 번(변경 전/후 시간 각각) 등장하면, `gr.Chatbot`이 응답을 마크다운으로 렌더링하는 과정에서
  첫 번째 `~`부터 두 번째 `~`까지를 취소선 문법으로 해석해버림. 즉 코드 버그가 아니라 LLM 출력 문자열과
  마크다운 문법이 우연히 충돌하는 표시 문제.
- 해결: `student_parts` 밖(`app.py`의 Chatbot 렌더링 쪽)을 고치면 확실하지만, 가이드 범위를 벗어난
  코드를 건드리다 다른 곳에서 예상 못한 버그가 생길 수 있어 프롬프트 레벨에서 해결하기로 함.
  `week03_prompt_parts()`에 아래 지시를 추가:
  ```python
  "시간 범위를 말할 때 물결표(~)를 쓰지 말고 '15시부터 17까지'처럼 '부터/까지'로 풀어서",
  "말한다. 마크다운 취소선으로 오해될 수 있는 ~기호는 답변에 쓰지 않는다.",
  ```

## 그룹 일정을 저장했는데 "내일 일정 뭐야"에 안 보임 (코드 레벨 재수정)

- 증상: 위 "그룹 일정을 저장했는데 ... 중복 저장됨" 항목과 같은 현상. `personal_list_saved_schedules`에서
  `kind`를 안 넘기면 그룹 일정이 조회 결과에서 계속 빠짐.
- 원인: `personal_list_saved_schedules`가 `kind is None`일 때 `kind = "personal_schedule"`로
  강제 대입하고 있었음.
  ```python
  if kind is None:
      kind = "personal_schedule"
  ```
  반면 실제 DB 조회를 담당하는 `AppSQLiteStore.list_schedules`(`fixed/app_store.py`)는
  `kind`가 falsy(`None`)면 아래처럼 kind 조건 자체를 SQL WHERE 절에 안 붙여서 이미 전체조회를 지원함.
  ```python
  if kind:
      where.append(...)
      params.append(kind)
  ```
  즉 tool이 `None`을 `"personal_schedule"`로 바꿔치기하는 바람에, store가 원래 지원하던
  "kind 없으면 전체조회" 동작이 막히고 있었던 것.
- 해결: 이전엔 `week03_prompt_parts()`에 "kind를 지정하지 말고 개인+그룹 모두 확인해"라는 지시를 추가해
  프롬프트 레벨에서 우회했었는데, 이번엔 원인이 명확히 tool 코드 쪽이라 코드 레벨에서 근본 수정함.
  `if kind is None: kind = "personal_schedule"` 두 줄을 삭제하고, 받은 `kind`를 그대로
  `store.list_schedules(limit, kind, date_from, date_to)`에 전달하도록 변경. 재현 시나리오로
  "내일 일정 뭐야"를 다시 물었을 때 `kind`를 지정하지 않아도 그룹 일정(모각코)이 바로 조회됨을 확인함.

## group_schedule/reminder 요청도 전부 personal_schedule로 저장됨

- 증상: `personal_list_saved_schedules` trace를 보면 참석자가 있는 일정(예: "철수랑 치킨 먹기", "철수/영희랑 모각코")도
  전부 `request_kind: personal_schedule`로 저장돼 있음. reminder/todo 성격 요청도 마찬가지.
- 원인: 두 군데가 겹쳐서 발생.
  1. `structured_request_from_week01_schedule()`(Week 1 호환 `personal_create_schedule` tool이 타는 경로)가
     `attendees` 값과 무관하게 `kind="personal_schedule"`을 하드코딩하고 있었음. `personal_create_schedule`은
     참석자 있는 일정도 만들 수 있는데, 이 bridge 함수가 그 정보를 무시함.
  2. `StructuredRequest.kind`를 실제로 채우는 LLM 분류 호출(`extract_schedule_request` 내부
     `extract_structured_request()`, system prompt는 항상 `week02_prompt_parts()`)에 kind를 나눌 기준이
     전혀 없었음. Field description이 "5개 중 하나 선택"이라고만 돼 있어서, `personal_` prefix가 붙은
     tool 이름들에 편향돼 거의 항상 personal_schedule로 찍힘. `week03_prompt_parts()`에만 기준을 추가해도
     소용없음 — `week03_prompt_parts()`는 `week02_prompt_parts()`를 상속하긴 하지만, 정작 분류를 담당하는
     `extract_structured_request()`의 system 메시지는 `week02_prompt_parts()`를 직접 참조하므로 그쪽에
     넣어야 실제 분류 호출까지 도달함.
- 해결: 세 군데를 같이 고침.
  1. `structured_request_from_week01_schedule()`의 kind를 attendees 유무로 분기:
     ```python
     kind="group_schedule" if schedule["attendees"] else "personal_schedule",
     ```
     (본인 이외 참석자 1명 이상이면 group_schedule이라는 정책으로 통일.)
  2. `week02_prompt_parts()`에 kind 분류 기준 + 경계 사례 few-shot을 추가:
     ```python
     "RequestKind 값을 정할 때는 아래 기준을 둔다.",
     "'내일 3시에 병원 예약'→ personal_schedule (members=[])",
     "'철수랑 치킨 먹기 저녁 8시' → group_schedule (members=[철수])",
     "'철수, 영희랑 저녁 7시에 만나' → group_schedule (members=[철수,영희])",
     "'약 먹을 시간 됐다고 8시에 알려줘' → reminder (end_time 없음, 알림 어투)",
     "'이번 주 안에 보고서 초안 써야 함' → todo (시간 미지정, 할 일 어투)",
     ```
  3. `WEEK03_TOOL_CALL_PROMPT`에 tool 선택 라우팅 지침 추가 — `personal_create_schedule`은
     날짜/시작 시간이 확실한 일정 생성에만 쓰고, 알림/할 일 어투 요청은 `extract_schedule_request` →
     `save_structured_request` 경로로 가도록 명시.

<!-- 아래 형식으로 항목을 추가합니다.

## 문제 제목

- 증상:
- 원인:
- 해결:
-->
