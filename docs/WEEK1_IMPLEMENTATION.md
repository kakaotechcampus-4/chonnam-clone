# 1주차 과제 구현 및 세부 코드 해설

본 문서는 `student_parts/week01_wake_up_nana.py` 파일의 1주차 과제 구현 내용과 **상세한 코드 작성 근거**, 대화 간에 나누었던 **파이썬 문법 및 핵심 개념 Q&A**, 그리고 1주차 과제의 **출제 의도 분석**을 종합적으로 정리한 문서입니다.

---

## 1. 핵심 공통 개념 해설 (세션 분리)

**💡 Q: `session_id = current_session_scope()` 와 `_current_session_schedules()`는 대체 뭔가요? 왜 쓰나요?**

- **A (놀이공원 입장 팔찌 비유)**: 
  파이썬에서 여러 사용자가 동시에 챗봇에 접속하면 여러 개의 작업 줄(Thread)이 동시에 돌아갑니다. 만약 채팅방 번호를 평범한 전역 변수에 저장하면, A 사용자와 B 사용자의 일정이 뒤죽박죽 섞이는 대참사가 일어납니다.
  이를 막기 위해 내부적으로 **`ContextVar` (컨텍스트 변수)**라는 문법이 사용되었습니다. 
  - 사용자가 채팅방에 들어오면 서버는 보이지 않는 **고유한 입장 팔찌(채팅방 번호)**를 채워줍니다.
  - 일정 생성/조회/삭제 함수들은 사용자에게 "채팅방 번호가 뭐예요?"라고 직접 묻지 않고, `current_session_scope()`를 호출해 **현재 작업 줄에 채워져 있는 팔찌 번호를 슬쩍 훔쳐봅니다.**
  - 이 팔찌 번호를 `session_id`로 저장해 두면, 다른 채팅방 사람들의 일정과 완벽하게 격리(분리)시킬 수 있습니다!

---

## 2. 상세 코드 해설 및 질의응답(Q&A)

### 2.1 일정 생성 기능 (`personal_create_schedule`)

```python
@tool
def personal_create_schedule(...) -> str:
    schedule = {
        "id": _new_personal_id(),
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "attendees": attendees if attendees is not None else [],
        "created_at": _now_iso(),
        "session_id": current_session_scope()
    }
    PERSONAL_SCHEDULES.append(schedule)
    return _json({
        "ok": True,
        "tool_name": "personal_create_schedule",
        "created_schedule": schedule
    })
```

**💡 Q: `"created_schedule": schedule` 부분은 대체 뭔가요? 왜 똑같은 데이터를 또 반환하나요?**
- **A (사장님과 비서 비유)**: 
  사장님(AI)이 비서(파이썬 도구)에게 "일정 추가해"라고 지시했을 때, 비서가 그냥 `"ok": True`(네 완료했습니다)라고만 답하면 사장님은 정작 새로 만들어진 고유 ID나 생성 시간이 무엇인지 모릅니다.
  우리가 딕셔너리 원본(`schedule`)을 통째로 넘겨주면, 사장님(AI)은 그 데이터를 눈으로 확인하고 **"네, 일정(ID: personal_123)이 성공적으로 추가되었습니다!"** 라고 완벽하게 팩트에 기반한 구체적인 문장을 사용자에게 대답할 수 있게 됩니다.

### 2.2 일정 조회 기능 (`personal_list_schedules`)

```python
@tool
def personal_list_schedules(...) -> str:
    schedules = _current_session_schedules()
    filtered_schedules = []
    for schedule in schedules:
        schedule_date = schedule.get("date", "")
        if date_from and schedule_date < date_from:
            continue
        if date_to and schedule_date > date_to:
            continue
        filtered_schedules.append(schedule)
    return _json({
        "ok": True,
        "tool_name": "personal_list_schedules",
        "schedules": filtered_schedules
    })
```

**💡 Q: `continue`는 왜 쓰인 건가요?**
- **A (놀이기구 키 제한 비유)**: 
  파이썬의 `continue`는 반복문(`for`) 안에서 **"이번 데이터는 패스(건너뛰기)! 밑에 코드는 무시하고 바로 다음 데이터로 넘어가!"** 라는 뜻입니다. 
  `date_from`보다 과거이거나 `date_to`보다 미래인 일정들은 우리가 찾던 범위에 안 맞으므로, `continue`를 쳐서 결과 리스트(`filtered_schedules`)에 추가되지 못하도록 입구컷(Guard Clause)을 시키는 안전하고 깔끔한 필터링 기법입니다.

### 2.3 일정 삭제 기능 (`personal_delete_schedule`)

```python
@tool
def personal_delete_schedule(schedule_id: str) -> str:
    session_id = current_session_scope()
    initial_length = len(PERSONAL_SCHEDULES)
    
    PERSONAL_SCHEDULES[:] = [
        schedule for schedule in PERSONAL_SCHEDULES
        if not (schedule.get("id") == schedule_id and _schedule_scope(schedule) == session_id)
    ]
    deleted_count = initial_length - len(PERSONAL_SCHEDULES)
    
    return _json({
        "ok": True,
        "tool_name": "personal_delete_schedule",
        "deleted": deleted_count
    })
```

**💡 Q: `PERSONAL_SCHEDULES[:]` 이건 무슨 문법이지?**
- **A (공용 과자 박스 비유)**: 
  `PERSONAL_SCHEDULES = [...]` 로 덮어쓰면 기존 과자 박스(메모 주소)를 버리고 새 박스를 두는 것과 같아 버그가 납니다. 반면 `[:]` 슬라이싱 문법을 쓰면 **기존 공용 과자 박스(메모리 껍데기)는 원래 자리에 유지하면서, 안의 내용물만 쏟아버리고 새 과자로 채워 넣는 것**과 같습니다.

**💡 Q: `if not (...)` 조건문은 어떤 원리인가요?**
- **A (썩은 사과 골라내기 비유)**: 
  바구니에서 타겟(지워야 할 일정)을 직접 `remove()`로 빼내려다 보면 리스트 순서가 꼬일 수 있습니다. 대신 빈 바구니(새 리스트)를 옆에 두고 하나씩 검사합니다.
  - **1단계 (`id == schedule_id`)**: "이 사과가 내가 찾던 그 번호인가?"
  - **2단계 (`scope == session_id`)**: "내 채팅방 사과가 맞나? (남의 것 지우면 안 됨)"
  - **3단계 (`not`)**: 위 두 조건을 모두 만족하면 100% 우리가 찾던 **'지워야 할 썩은 사과'**입니다. 이 녀석이 새 바구니에 들어가는 것을 막기 위해 `not (True)`를 적용해 `False`로 뒤집어 버립니다. 반대로 정상적인 일정들은 `not (False)`가 되어 `True`가 되므로 무사히 새 바구니에 담깁니다.

**💡 Q: `deleted_count = initial_length - len(...)` 원리가 뭐지?**
- **A (작업 전후 무게 달아보기 비유)**: 
  삭제 작업을 시작하기 전의 전체 박스 사과 개수(`initial_length`)를 적어두고, 필터링 작업 후의 사과 개수(`len`)를 빼면 "방금 썩은 사과를 몇 개나 버렸는지" 굳이 세어보지 않아도 정확한 숫자가 나옵니다.

### 2.4 에이전트 시스템 프롬프트 (`week01_prompt_parts`)

```python
def week01_prompt_parts() -> list[str]:
    return [
        f"오늘의 날짜는 {datetime.now().strftime('%Y-%m-%d')} 입니다.",
        "당신은 사용자의 일정을 효율적이고 꼼꼼하게 관리해 주는 친절한 개인 비서 'Nana'입니다.",
        "제공된 도구를 활용하여 사용자의 일정 생성, 조회, 삭제 요청을 처리하고, 항상 한국어로 상냥하고 예의 바르게 답변해 주세요.",
        "일정을 생성할 때는 어떤 일정이 등록되었는지 명확히 알려주고, 조회할 때는 일정 목록을 보기 좋게 정리해서 보여주세요."
    ]
```

**💡 Q: 왜 프롬프트를 이런 구조로 작성했나요?**
- **A (프롬프트 엔지니어링의 3단 정석)**: 
  1. **페르소나 (역할 부여)**: *"당신은 친절한 개인 비서입니다."* ➡️ AI에게 명확한 정체성을 부여해 말투와 태도를 고정시킵니다.
  2. **수행 작업 (Task)**: *"도구를 활용해 생성, 조회, 삭제를 처리하고..."* ➡️ 행동 지침을 줍니다.
  3. **출력 형식 및 제약 (Format)**: *"항상 한국어로... 보기 좋게 정리해서..."* ➡️ 날것의 코드나 영어로 대답하는 할루시네이션을 막아줍니다.

### 2.5 재미있는 AI 행동 분석 (할루시네이션과 자가 추론)

**💡 Q: 일정 등록을 방금 했는데 "이번 주 일정이 없다"고 하고, 지워달라니까 "없어서 못 지운다"고 합니다. 왜 이러는 걸까요?**
- **A1. 날짜 착각 (할루시네이션)**: 
  AI는 컴퓨터 시계를 스스로 볼 줄 모릅니다. 초반 프롬프트에 오늘 날짜를 알려주지 않았을 때 AI는 임의로 과거 날짜(예: 2023년)를 오늘이라고 착각했습니다. 그래서 "이번 주 일정 보여줘"라고 했을 때 엉뚱한 과거를 검색하여 빈 리스트(`[]`)를 돌려받고 "일정이 없습니다"라고 대답한 것입니다.
  *(해결책: 이를 방지하기 위해 시스템 프롬프트 맨 앞에 파이썬의 `datetime.now()`를 이용해 오늘 날짜를 강제로 주입해 두었습니다.)*

- **✅ 프롬프트(오늘 날짜 주입) 수정 후 정상 동작 테스트 결과 (증거 자료)**
  수정 후 다시 테스트해 본 결과, AI가 오늘 날짜를 정확히 인지하여 생성 ➡️ 조회 ➡️ 삭제 플로우가 완벽하게 이어지는 것을 확인했습니다.
  > **사용자**: 내일 오후 2시에 회의 일정 만들어줘
  > **Nana**: 내일 오후 2시에 '회의' 일정이 성공적으로 등록되었습니다. 다른 일정도 도와드릴까요?
  > **사용자**: 이번 주 내 일정 모두 보여줘
  > **Nana**: 이번 주 일정은 다음과 같습니다: 7월 1일 오후 2시부터 '회의' 일정이 있습니다. 더 필요한 일정 관리가 있으시면 언제든 말씀해 주세요!
  > **사용자**: 방금 등록한 일정 취소해줘
  > **Nana**: 방금 등록하신 7월 1일 오후 2시 회의 일정이 취소되었습니다. 다른 일정도 도와드릴까요?

- **A2. 스스로 갇혀버린 논리 (가스라이팅 당한 AI)**: 
  에러가 났던 상황에서 "방금 거 지워줘"라고 했을 때 트레이스 로그에 '삭제 도구 호출' 기록이 아예 없는 이유가 바로 여기에 있습니다. AI가 직전 대화에서 자신의 입으로 "이번 주 일정이 없습니다"라고 확언했기 때문에, "내가 없다고 했는데 뭘 지우라는 거지? 아예 지울 게 없으니까 도구(Tool)를 쓸 필요도 없겠네!"라고 **스스로 논리적 모순을 찾아내어 도구 호출을 생략**해버린 것입니다. 코드가 고장 난 것이 아니라 오히려 AI가 아주 똑똑하게 추론한 결과입니다!

### 2.6 그 외 시스템 동작 원리 (채팅 기록과 트레이스 로그의 차이)

**💡 Q: 웹 브라우저에서 대화한 내용과 우측의 트레이스(Trace) 로그는 로컬에 영구 저장되나요?**
- **A (영구 보관 앨범 vs 일회용 영수증 비유)**:
  - **채팅 내용 (저장 O)**: 텍스트는 즉시 로컬 SQLite 데이터베이스에 영구적으로 차곡차곡 저장됩니다. 따라서 새로고침해도 예전 대화를 완벽하게 불러올 수 있습니다.
  - **트레이스 로그 (저장 X)**: 우측의 JSON 도구 호출 기록은 임시 메모리에만 존재합니다. 실시간 디버깅용이므로 새로고침하면 사라지는 것이 정상입니다.

---

## 3. 주차별 과제 설계 의도 분석 (왜 1주차 과제를 이렇게 냈을까?)

1. **왜 진짜 DB(SQLite)를 안 쓰고 메모리 리스트(`PERSONAL_SCHEDULES`)를 썼을까?**
   - **의도**: 1주차의 핵심은 "AI가 어떻게 파이썬 함수(도구)를 판단해서 호출하는가(Tool Calling)?"를 깨닫는 것입니다. 복잡도를 낮추어 원리에만 집중하게 하려는 의도입니다.
2. **왜 도구 반환값을 무조건 `str` (JSON 문자열)로 묶게 했을까?**
   - **의도**: 개발자가 AI와 소통할 때는 "모든 데이터를 구조화된 텍스트(JSON)로 포장해서 넘겨줘야 한다"는 대원칙을 체득하게 하려는 의도입니다.
3. **왜 `session_id`와 `ContextVar`라는 복잡한 개념을 초반부터 도입했을까?**
   - **의도**: 향후 여러 명이 동시 접속하는 '웹 서비스'로 확장될 것을 대비해 상태(State) 격리를 고려하는 안전한 서버 설계 습관을 길러주기 위함입니다.
4. **왜 프롬프트 작성을 빈칸(`# TODO`)으로 비워뒀을까?**
   - **의도**: 학생이 직접 프롬프트를 작성해 보면서 "내가 쓴 문장 한 줄이 챗봇의 인격과 대답 품질을 어떻게 바꾸는지" 직접 경험해 보게 하려는 의도입니다.

---

## 4. 구현 확인용 로컬 테스트 방법

```bash
./run.ps1 -week1
```
