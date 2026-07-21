# Week3 Eval Task 목록

이 목록은 실행 코드가 아니라 사람이 `./run.sh --week3`로 Gradio 채팅창에 직접 쳐보고 "상세" 탭 trace JSON으로 확인하기 위한 체크리스트다. 실제 자동화 스크립트가 필요해지면 `roadmap.md`의 Step 4/5를 참고해 하네스를 만든다.

이 파일은 최초 task 세트(week3까지)다. week4 이상이 추가되면 이 파일을 복사하지 않고 `week4-tasks.md`를 새로 만들어 "이 파일 전체를 이어받는다"고 명시한 뒤 week4에서 새로 생긴 기능에 대한 task만 추가한다 (`README.md`/`roadmap.md` Step 8 참고).

각 task는 `골든 패스 / 경계 사례 / 멀티 인텐트 / 오픈 이슈 / 회귀 방지 / 부정 사례` 중 하나로 분류한다. 채점은 tool 호출 순서가 아니라 **최종 응답 내용 + trace의 저장/조회 결과**를 기준으로 한다.

총 44개 (골든 4 / 경계 22 / 멀티 인텐트 2 / 이슈 4, 전부 해결됨 / 회귀 5 / 부정 3). 경계 사례 B1~B5, 부정 사례 N1~N3는 1차로 만든 task, B6 이후는 2차로 늘린 task — `extract_structured_request()`를 직접 호출해 실제 결과를 확인한 뒤 적었다(지어낸 예시 없음). I1/I2/I3/I4는 발견 → 원인 확정 → `week02_prompt_parts()` 규칙 추가 → 재실행 검증까지 끝난 해결 완료 이슈. I4는 I3를 고치다가 새로 생긴 2차 회귀였음 — 규칙 추가가 또 다른 규칙을 깨뜨릴 수 있다는 걸 보여주는 사례라 그대로 기록해둠.

---

## 골든 패스 (kind별 생성 → 저장 → 조회)

### G1 — personal_schedule 생성/조회
- 입력: `"내일 3시에 병원 예약"`
- 기대 결과: `extract_schedule_request`→`save_structured_request`로 저장, `kind=personal_schedule`, `members=[]`. 이어서 `"내일 일정 뭐야"` 물으면 병원 예약이 조회됨.
- 분류: golden

### G2 — group_schedule 생성/조회
- 입력: `"철수, 영희랑 저녁 7시에 만나"`
- 기대 결과: `kind=group_schedule`, `members=[철수, 영희]`로 저장. `"오늘 일정 뭐야"` 물으면 조회됨.
- 분류: golden

### G3 — todo 생성/조회
- 입력: `"이번 주 안에 보고서 초안 써야 함"`
- 기대 결과: `kind=todo`로 저장(날짜/시간 없어도 저장 성공). `"할 일 뭐 있어"` 물으면 `list_saved_requests(kind='todo')`로 조회됨.
- 분류: golden

### G4 — reminder 생성/조회
- 입력: `"약 먹을 시간 됐다고 8시에 알려줘"`
- 기대 결과: `kind=reminder`, `end_time=None`으로 저장. `"리마인더 뭐 있어"` 물으면 조회됨.
- 분류: golden

---

## 경계 사례 (kind 분류 기준선 — 이번 세션에서 실제 검증한 문장)

### B1 — 참석자 1명, group 판정
- 입력: `"철수랑 치킨 먹기 저녁 8시"`
- 기대 결과: `kind=group_schedule`, `members=[철수]` (참석자 1명이어도 personal 아님 — 합의된 정책).
- 분류: boundary

### B2 — 참석자 2명, group 판정
- 입력: `"철수, 영희랑 저녁 7시에 만나"`
- 기대 결과: `kind=group_schedule`, `members=[철수, 영희]`.
- 분류: boundary

### B3 — few-shot에 없는 새 표현으로 일반화 확인
- 입력: `"이따 6시에 스터디원들이랑 카페에서 잠깐 얘기 좀 하자"`
- 기대 결과: `kind=group_schedule`, `members=[스터디원들]` (프롬프트 few-shot 예시에 없는 문장인데도 정책대로 분류되는지).
- 분류: boundary

### B4 — reminder/todo 어투가 섞인 문장
- 입력: `"다음 주 화요일까지 발표자료 준비하는거 잊지 말라고 알려줘"`
- 기대 결과: `kind=reminder` ("잊지 말라고 알려줘" 알림 어투가 "준비하는거"라는 todo 어투보다 우선 판정됨).
- 분류: boundary

### B5 — 멤버 있음 + 시간 없음 + "해야 해" 어투 (정책 충돌 지점)
- 입력: `"민수랑 이야기 좀 해야해"`
- 기대 결과: `kind=group_schedule`, `members=[민수]` (멤버 존재가 "해야 해"라는 todo 어투보다 우선 — 정책상 group이 이김).
- 분류: boundary

### B6 — 집단명사 멤버(팀/동아리/가족), 개별 이름 없음
- 입력: `"다음 주 화요일에 팀 전체랑 회의 있어"`
- 기대 결과: `kind=group_schedule`, `members=['팀 전체']` (개별 이름 없이 집단명사만 있어도 group으로 감).
- 분류: boundary

### B7 — 집단명사 + 요일 지정 날짜 계산
- 입력: `"동아리 사람들이랑 다 같이 저녁 먹기로 함, 이번 금요일 6시"`
- 기대 결과: `kind=group_schedule`, `members=['동아리 사람들']`, 날짜가 "이번 금요일"에 맞게 계산됨.
- 분류: boundary

### B8 — 멤버 3명 + 시작/종료 시간 둘 다 있는 경우
- 입력: `"지훈이, 서연이, 민지 셋이랑 스터디 하기로 함 오후 2시부터 4시까지"`
- 기대 결과: `kind=group_schedule`, `members=['지훈','서연','민지']`, `start_time=14:00`, `end_time=16:00`.
- 분류: boundary

### B9 — "가족"도 group으로 감
- 입력: `"가족이랑 이번 주말에 여행가"`
- 기대 결과: `kind=group_schedule`, `members=['가족']`.
- 분류: boundary

### B10 — "혼자"라는 표현이 있어도 personal 정확히 감
- 입력: `"나 혼자 오늘 저녁 8시에 헬스장 가"`
- 기대 결과: `kind=personal_schedule`, `members=[]`.
- 분류: boundary

### B11 — 먼 미래 날짜("다음 달 N일") 계산
- 입력: `"다음 달 3일에 치과 예약 있어"`
- 기대 결과: `kind=personal_schedule`, `date`가 현재 월+1의 3일로 정확히 계산됨.
- 분류: boundary

### B12 — 심야 시각 + 알림 어투
- 입력: `"오늘 밤 11시에 쓰레기 버리라고 알려줘"`
- 기대 결과: `kind=reminder`, `start_time=23:00`.
- 분류: boundary

### B13 — 상대 시각 계산("N분 전")이 낀 reminder
- 입력: `"회의 시작 10분 전에 알림 줘, 회의는 3시야"`
- 기대 결과: `kind=reminder`, `start_time=14:50` (3시에서 10분 뺀 값으로 정확히 계산됨).
- 분류: boundary

### B14 — 반복성 알림, 날짜 특정 안 됨
- 입력: `"매일 아침 7시에 일어나라고 알려줘"`
- 기대 결과: `kind=reminder`, `date=None`(반복이라 특정 날짜 없음이 맞음), `start_time=07:00`.
- 분류: boundary

### B15 — 시간/날짜 전혀 없는 todo
- 입력: `"장 보러 가야 하는데 언제 갈지는 아직 모르겠음"`
- 기대 결과: `kind=todo`, `date=None`, `start_time=None` (억지로 날짜를 지어내지 않음).
- 분류: boundary

### B16 — "오늘 안에" 같은 상대 마감의 todo
- 입력: `"이메일 답장 오늘 안에 보내야 함"`
- 기대 결과: `kind=todo`, `date=오늘 날짜`.
- 분류: boundary

### B17 — 월 단위 마감의 todo
- 입력: `"책 다 읽기 이번 달까지"`
- 기대 결과: `kind=todo`, `date=이번 달 말일`.
- 분류: boundary

### B18 — 진짜 애매해서 unknown이 맞는 경우 (시간/약속 여부 다 불명확)
- 입력: `"다음에 만나서 얘기하자"`
- 기대 결과: `kind=unknown` (날짜/시간/구체적 의도 없음 — 억지로 personal/group/todo로 우기지 않음).
- 분류: boundary

### B19 — 먼 미래 상대 날짜("다다음주 O요일") 계산
- 입력: `"다다음주 수요일에 세미나 있어"`
- 기대 결과: `kind=personal_schedule`, `date`가 2주 뒤 수요일로 정확히 계산됨.
- 분류: boundary

### B20 — duration 있어도 알림 어투면 reminder 우선
- 입력: `"3시부터 5시까지 회의니까 안 잊게 알려줘"`
- 기대 결과: `kind=reminder` (`start_time`/`end_time` 둘 다 있어도 "안 잊게"라는 알림 어투가 이겨서 personal_schedule 아닌 reminder로 감. reminder 기준 중 "duration 없음"이 절대 규칙이 아니라는 걸 보여주는 경계 사례).
- 분류: boundary

### B21 — "~한테"로 언급된 사람은 참석자(member)가 아니라 todo 대상일 뿐
- 입력: `"철수한테 자료 보내줘야 하는데 아직 안 보냄"`
- 기대 결과: `kind=todo`, `members=[]` (철수는 수신 대상이지 참석자가 아니므로 group_schedule로 잘못 분류되면 안 됨).
- 분류: boundary

### B22 — 의미 없는 요청도 unknown으로 안전하게 fallback
- 입력: `"음 그냥 아무거나 기록해줘"`
- 기대 결과: `kind=unknown`.
- 분류: boundary

---

## 멀티 인텐트 사례 (주의: bridge 함수 단독 호출로는 검증 불가)

`extract_structured_request()`는 문서상 "한 번에 StructuredRequest 하나만" 반환하는 bridge 함수다. 아래 두 task를 `extract_structured_request` 하나로 직접 테스트하면 앞쪽 의도 하나만 뽑고 뒤쪽은 버린다 — 이건 이 함수의 설계된 범위 밖이라 버그로 취급하면 안 된다. **반드시 `./run.sh --week3` 전체 agent 대화로 검증**해야 한다 (agent가 한 메시지 안 여러 의도를 감지해 `extract_schedule_request`/`save_structured_request`를 여러 번 호출하는지가 관건).

### M1 — 개인 일정 + 그룹 일정이 한 메시지에 섞임
- 입력: `"내일 2시에 병원 예약이랑, 3시엔 철수랑 커피 마시기로 했어"`
- 기대 결과: 병원 예약(`personal_schedule`)과 철수와 커피(`group_schedule`) 둘 다 각각 저장됨. (bridge 단독 호출 시엔 병원 예약만 뽑고 철수/커피는 누락되는 걸 이미 확인함 — 전체 agent에서도 누락되면 진짜 버그.)
- 분류: 멀티 인텐트 (전체 agent로만 검증)

### M2 — todo + reminder가 한 메시지에 섞임
- 입력: `"이번 주까지 보고서 써야 하고, 8시에 약 먹으라고 알려줘"`
- 기대 결과: 보고서(`todo`)와 약 먹기(`reminder`) 둘 다 각각 저장됨. (bridge 단독 호출 시엔 todo만 뽑고 reminder는 누락되는 걸 이미 확인함.)
- 분류: 멀티 인텐트 (전체 agent로만 검증)

---

## 오픈 이슈 → 해결 완료 (I1/I2/I3)

`week02_prompt_parts()`에 아래 세 줄을 추가해 세 이슈 전부 해결 확인함 (각 케이스 5회씩 재실행, 전부 안정):
```python
"원문에 명시된 이름이 없으면 members를 비워두거나 원문 표현 그대로(예: '다른 친구들') 둔다",
"'빼고/제외하고' 같은 표현의 제외 대상은 members에 넣지 않는다",
"unknown은 kind 자체(약속/할 일/알림 중 뭔지)를 전혀 판단할 수 없을 때만 쓴다.",
"날짜/시간 정보가 없다는 이유만으로 unknown으로 후퇴하지 않는다.",
"members/어투로 kind가 판단되면 kind는 확정하고 date/start_time만 None으로 둔다."
```
기존 few-shot의 "철수+영희" 고정 짝 자체는 그대로 두고(다양화는 안 함), 위 명시적 금지 규칙만 추가한 것으로 충분히 억제됨 — few-shot 패턴보다 명시적 규칙이 우선 적용된 것으로 보임. 골든 4개(personal/group/todo/reminder)와 진짜 unknown 케이스("음 그냥 아무거나 기록해줘")도 회귀 없이 그대로 유지됨.

### I1 — 원문에 없는 멤버 이름을 지어냄 (hallucination, 원인 확정 → 해결됨)
- 입력: `"철수 빼고 다른 친구들이랑 저녁 먹기로 함"`
- 실제 결과 (10/10 재현, non-determinism 아니고 일관됨): `kind=group_schedule`, `members=['영희']` — **원문에 "영희"라는 이름 자체가 없는데 모델이 지어냄.**
- 원인 확정: `week02_prompt_parts()`의 few-shot 예시가 매번 "철수, 영희랑 저녁 7시에 만나" → `members=[철수,영희]`처럼 **"철수"와 "영희"를 항상 짝으로만** 보여줌. 그래서 입력에 "철수"만 나와도 모델이 few-shot의 철수+영희 패턴을 그대로 끌어옴. 검증: "철수"를 "민수"로 바꾼 `"민수 빼고 다른 친구들이랑 저녁 먹기로 함"`은 `members=['친구들']`로 나오고 "영희"가 안 나옴(3/3) — "철수"라는 특정 토큰이 방아쇠였음이 확인됨.
- 왜 문제인가: `members`는 SQLite `schedules.attendees_json`에 그대로 저장되는 필드 — 없는 사람 이름이 참석자로 박히면 이후 공유 동기화(`personal_update_saved_schedule`의 `shared_sync`)에서 실제로 없는 사람과 일정을 공유하려 시도하는 부작용으로 이어질 수 있음.
- 해결 확인: 규칙 추가 후 동일 문장 5회 재실행 → `members=['다른 친구들']`로 5/5 안정, "영희" 재현 안 됨.
- 분류: 해결됨

### I2 — "빼고"(제외) 의미를 무시하고 제외 대상을 멤버로 넣음 (I1보다 심각 → 해결됨)
- 입력: `"지훈이 빼고 다른 사람들이랑 저녁 먹기로 함"`
- 실제 결과 (3회 중 2회): `kind=group_schedule`, `members=['지훈이']` — **제외하라고 명시한 사람을 오히려 유일한 참석자로 넣음.** 나머지 1회는 `members=['다른 사람들']`로 더 합리적이었음 — 즉 이 문장은 run마다 결과가 갈리는 non-deterministic 케이스.
- 왜 I1보다 심각한가: I1은 "없는 사람을 지어내는" 문제고, I2는 "빼라고 한 사람을 넣는" 문제 — 사용자가 명시적으로 제외 의도를 밝혔는데 정반대로 처리됨. 저장/공유 단계까지 가면 실제 피해(제외하고 싶은 사람에게 공유됨) 방향이 뚜렷함.
- 해결 확인: 규칙 추가 후 동일 문장 5회 재실행 → `members=['다른 사람들']`로 5/5 안정, 제외 대상("지훈이") 재현 안 됨.
- 분류: 해결됨

### I3 — 제외 대상 언급 없이 멤버만 모호하면 kind 자체가 run마다 흔들림 (해결됨)
- 입력: `"다른 친구들이랑 저녁 먹기로 함"` (제외 대상 언급 없음)
- 실제 결과 (3회): `unknown` 2회, `group_schedule`(`members=['친구들']`) 1회.
- "unknown은 kind 판단 자체가 불가능할 때만" 규칙 추가 후 동일 문장 5회 재실행 → `group_schedule`, `date=None`으로 5/5 안정, unknown으로 안 흔들림.
- 분류: 해결됨

### I4 — I3 수정이 과해서 진짜 unknown 케이스(B22)까지 personal_schedule로 밀어버린 새 회귀
- 입력: `"음 그냥 아무거나 기록해줘"` (B22, 원래 정답은 unknown)
- 실제 결과 (I3 수정 직후, 8/8 재현): `kind=personal_schedule`, `title='기록된 일정'`이라는 **없는 제목까지 지어냄**. I1의 멤버 hallucination이 title 필드에서 재발한 셈.
- 원인: I3 수정 규칙("날짜/시간 정보가 없다는 이유만으로 unknown으로 후퇴하지 않는다")이 "날짜만 없는 경우"와 "내용 자체가 없는 경우"를 구분 못 하고 후자까지 kind를 억지로 확정시킴.
- 해결: 규칙에 한 줄 추가해 범위를 좁힘 — "title이나 구체적인 행동/약속 대상이 전혀 없으면 unknown을 유지한다. unknown 회피 규칙은 날짜/시간만 없고 내용은 명확한 경우에만 적용한다." 추가 후 동일 문장 3회 재실행 → `unknown`, `title=None`으로 3/3 복구, 나머지 golden/I1/I2/I3 케이스도 전부 회귀 없이 유지 확인.
- 분류: 해결됨 (I3 수정의 부작용으로 발견된 2차 회귀)

---

## 회귀 방지 (docs/troubleshooting/week3.md 기반)

### R1 — 그룹 일정 저장 후 조회 안 되는 중복 저장 버그
- 입력: `"오늘 철수랑 7시30분부터 10시까지 놀거야 그리고 내일은 모각코를 팀원들이랑 오후3시부터 6시까지 할거야"` 저장 → 이어서 `"내일 일정 뭐야"`
- 기대 결과: 저장 직후 "저장된 일정이 없다"고 잘못 답하며 재저장(중복 row)하지 않음. `"내일 일정 뭐야"`에 모각코(그룹 일정)가 정상 조회됨. `structured_requests`/`schedules`에 같은 일정이 두 번 이상 들어가지 않음.
- 분류: regression (원인: `personal_list_saved_schedules`가 kind 기본값을 personal_schedule로 강제하던 버그)

### R2 — kind 미지정 조회 시 개인 일정만 나오던 버그
- 입력: 그룹 일정 하나 저장 후, kind를 언급하지 않고 `"저장된 일정 보여줘"`
- 기대 결과: `personal_list_saved_schedules`가 kind를 넘기지 않았을 때 개인+그룹 일정이 전부 조회됨 (`kind=None`을 `personal_schedule`로 바꿔치기하지 않음).
- 분류: regression

### R3 — "일정 알려줘"가 할 일/리마인더를 빠뜨리는 라우팅 버그
- 입력: personal_schedule/group_schedule/todo/reminder 각 1개씩 저장해둔 상태에서 `"일정 알려줘"`
- 기대 결과: 4종 전부 응답에 언급됨 (`list_saved_requests`를 kind 없이 호출해 전체 조회). `"개인 일정만 보여줘"`처럼 명시적으로 좁히면 그때만 `personal_list_saved_schedules`로 좁혀짐.
- 분류: regression

### R4 — Week1 호환 생성 경로에서 kind가 무조건 personal_schedule로 찍히던 버그
- 입력: 참석자가 있는 일정을 `personal_create_schedule`(Week1 호환 tool) 경로로 생성 (예: `"철수랑 내일 4시부터 5시까지 코딩 스터디 잡아줘"`가 이 tool로 라우팅되는 경우)
- 기대 결과: 저장된 `request_kind`가 `attendees` 유무에 따라 `group_schedule`/`personal_schedule`로 정확히 갈림 (예전엔 attendees와 무관하게 항상 `personal_schedule`이었음).
- 분류: regression

### R5 — 일정 수정 응답에 물결표(~)로 인한 취소선 표시 버그
- 입력: 기존 일정 저장 후 `"7/16 풋살 일정 시간을 20:00부터 22:00까지로 바꿔줘"`
- 기대 결과: 응답 문장에 `~` 기호를 쓰지 않고 "~부터/까지"로 시간 범위를 표현 (Gradio Chatbot 마크다운이 `~...~`를 취소선으로 오인하는 걸 피함).
- 분류: regression

---

## 부정 사례 (undertriggering/overtriggering 균형)

### N1 — 인사말에 저장 tool 오발동 안 함
- 입력: `"안녕"`
- 기대 결과: `save_structured_request`/`personal_create_schedule` 등 저장 tool이 호출되지 않음. 인사로만 응답.
- 분류: negative

### N2 — 일정과 무관한 질문에 저장 tool 오발동 안 함
- 입력: `"오늘 날씨 어때"`
- 기대 결과: 일정/할 일/리마인더 저장 tool이 호출되지 않음 (agent가 날씨 정보를 모른다고 답하거나 관련 없다고 답함 — 핵심은 tool 미호출).
- 분류: negative

### N3 — 메타 질문에 저장 tool 오발동 안 함
- 입력: `"너는 무슨 모델이야?"`
- 기대 결과: 저장/조회 tool이 호출되지 않음.
- 분류: negative
