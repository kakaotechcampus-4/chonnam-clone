# Week 6 트러블슈팅 기록

대상 파일: `student_parts/week06_kanamate_decides_schedule.py`
TODO를 구현하다가 막힌 문제와 해결 과정을 발생할 때마다 여기에 추가합니다.

## "내 일정 보여줘"처럼 외부 멤버 언급이 전혀 없는 개인 조회 요청이 kana_agent로 잘못 위임됨

- 증상: "내 이번 주 일정 보여줘"라고 물으면 supervisor가 `nana_agent`가 아니라 `kana_agent`를 호출함. `kana_agent`는 tool도 안 부르고 "이번 주가 며칠부터인지 알려달라"고 되물었음. 골든 패스 스트레스 테스트 중 발견(`docs/evals/week6-tasks.md` G3 대응).
- 원인: `week06_prompt_parts()`의 위임 few-shot 예시가 전부 "일정 **생성**"(치과 예약 추가) 아니면 외부 멤버가 등장하는 조회/조율 예시뿐이었고, "개인 일정 **조회**"에 해당하는 few-shot이 하나도 없었음. CoT 규칙(1번: 외부 멤버 없으면 nana_agent)은 있었지만 예시가 뒷받침을 안 해줘서 LLM이 "일정 보여줘" 같은 조회 표현을 외부 조율 쪽으로 헷갈려함.
- 해결: `week06_prompt_parts()`에 "내 이번 주 일정 보여줘", "오늘 일정 뭐 있어" 같은 소유격("내/제")만 있고 외부 멤버가 없는 요청은 조회든 생성이든 항상 nana_agent라는 규칙과 few-shot 예시를 추가. 재실행 결과: "내 이번 주 일정 보여줘", "오늘 내 일정 뭐 있어?", "이번 달 내 일정 확인해줘" 3가지 표현 모두 `nana_agent`로 정확히 위임됨(2026-08-05 `AgentRuntime(active_week=6).run_agent(...)` 실행 확인). PASS.

## 혼합 요청에서 supervisor가 "정확히 하나만 호출" 규칙을 안 지키고 nana_agent+kana_agent를 같은 턴에 둘 다 호출함

- 증상: "내 일정도 보여주고 철수랑 시간도 맞춰줘"처럼 개인+외부 요청이 한 메시지에 섞이면, supervisor 프롬프트에 "정확히 하나를 호출"이라고 명시했는데도 `nana_agent`와 `kana_agent`를 같은 턴에 둘 다 호출함.
- 원인: LLM이 "사용자 요청을 다 처리해주는 게 낫다"는 판단을 프롬프트 규칙보다 우선시함. 프롬프트 텍스트를 세 단계로 강화해봐도(①규칙 재강조 ②"잘못된 예/올바른 예" 반례 추가 ③"충동이 들면 규칙 위반 신호" 경고) 총 7회 재시도 전부 여전히 tool 2개 호출(0/7 개선). 심지어 반례를 추가한 뒤에는 "내 일정 조회는 다음 메시지로 다시 요청해주세요"라며 규칙을 지킨 것처럼 말하면서 실제 trace에는 이미 두 tool을 다 호출한 경우도 있었음 — 말과 실제 tool 호출이 어긋남. 프롬프트 텍스트만으로는 이 판단을 못 뒤집는 것으로 결론.
- 해결: "정확히 하나"로 강제하는 대신 규칙을 완화 — "가능하면 하나만 호출하되, 개인+외부 내용이 명확히 섞여 있으면 필요한 tool을 순서대로 둘 다 호출하고 결과를 합쳐서 답해도 된다"로 수정. 완화 후에도 답변 품질은 정상(날짜 범위를 합리적으로 되물음, 두 결과 다 반영)이고 개인 조회 단독 요청(회귀 확인)은 여전히 nana_agent만 호출됨을 확인. tool 2개 호출 자체를 막는 것은 prompt 레벨에서는 포기하고, 코드 레벨(tool 호출 횟수 제한 등)로 막으려면 이 파일 범위를 벗어남.

## `find_common_available_slots`가 실제로 존재하는 공통 시간을 "없다"고 자주 잘못 답함 (재현율 낮음)

- 증상: "철수, 영희랑 다같이 시간 되는 때 찾아줘, 7월 7일부터 7월 17일까지"를 같은 조건으로 5번 반복 실행하면 3번은 "공통 가능한 시간이 없다"고 답하고 2번만 후보를 제대로 찾음(2026-08-05, `./run.sh --week6` 실제 대화 + `AgentRuntime` 반복 실행으로 확인). `docs/evals/week6-tasks.md` E1(공통 시간 후보→최종 확정 체이닝)에서도 같은 양상으로 재현성 낮음이 이미 기록돼 있었음 — 이번에 같은 문제가 골든 패스 G3 단계(순수 후보 찾기)에서도 그대로 나타남을 확인.
- 원인 (1차 추정, 틀림): `find_common_available_slots`는 설계상 겹침 계산을 Python이 하지 않고 Kana LLM이 `busy_rows`를 직접 훑어 `candidate_slots`를 골라 넘기게 돼 있어서(`FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION`과 모듈 가이드 "추가 과제 구현 대상" 2번에 명시), 이 다단계 추론 자체가 LLM한테 어려운 문제라고 처음엔 판단함.
- 해결 시도 1 (실패): `chat_model()`은 이미 `temperature=0`(기본값, `fixed/llm.py:10`)이라 온도 조정 여지 없음을 확인. description을 절차 상세화(1~6단계)하거나 반대로 대폭 단순화하는 두 방향 다 시도 — 상세화는 역효과(2/5→0/5), 단순화도 개선 없음(0/5). 둘 다 원복.
- 원인 (2차 추정, 부분적으로 틀림): Week1~6 전체 코드와 `fixed/schedule_decision.py`를 재조사한 결과, `fixed/schedule_decision.py:118~125`의 `normalize_llm_candidate_slots()`가 겹치는 후보를 조용히 `continue`로 버리고 이유를 안 남긴다는 걸 발견. "거절 이유를 다시 계산해서 Kana에게 보여주면 재시도할 것"이라 가정하고, week06 파일 안에 `_slot_key`/`_explain_rejected_candidates` 헬퍼를 추가해 `busy_rows`를 사람별로 재정렬하고 `rejected_candidates`/`submitted_count`/`accepted_count`/`needs_retry` 필드를 결과에 붙임(fixed/는 안 건드림, `busy_rows_overlap`은 public 함수라 import만 함). 10회 중 6회 성공(40%→60%)으로 개선은 됐음.
- 진짜 원인 (실제 실패 payload를 직접 확인 후 확정): 개선 후에도 실패한 케이스의 실제 tool 호출 arguments를 보니 `candidate_slots` 키 자체가 통째로 빠져있었음 — Kana가 애초에 후보를 하나도 안 내고 busy_rows만 넘긴 채 "이 tool이 계산해주겠지"하고 기대한 것. 이 경우 `submitted_count=0`이라 "거절 이유"도 없어서(빈 리스트를 낸 게 아니라 아예 안 낸 거라 rejected_candidates도 비어있음) 방금 만든 재시도 유도 로직이 이 케이스는 못 잡았음.
- 최종 해결: `FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION`에 "candidate_slots를 비운 채 호출하지 마라, 반드시 최소 1개 이상 직접 채워서 호출하라"는 문장 한 줄만 추가 — 이걸로 8/8 성공. 이 결과로 2차 추정 때 만든 정렬·거절이유 계산 헬퍼(`_slot_key`, `_explain_rejected_candidates`, `rejected_candidates`/`needs_retry` 등 필드)가 실제로는 불필요했다는 게 확인돼 전부 제거하고 이 description 한 줄만 남김. 최종적으로 `fixed/`는 전혀 안 건드렸고 week06 파일 변경도 description 3줄 추가가 전부. 교훈: 재현성 낮은 LLM 버그는 실제 실패 payload를 눈으로 직접 봐야 진짜 원인을 알 수 있다 — 추정만으로 고치면(2차 시도) 방향은 맞아도 헛다리 짚은 복잡도만 남는다.

<!-- 아래 형식으로 항목을 추가합니다.

## 문제 제목

- 증상:
- 원인:
- 해결:
-->
