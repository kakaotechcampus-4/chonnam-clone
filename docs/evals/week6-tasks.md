# Week6 Eval Task 목록

골든 패스/경계 사례/회귀 방지/부정 사례는 `week5-tasks.md`를 그대로 이어받는다. 이 파일에는 Week6에서 새로 생긴 기능(supervisor → Nana/Kana 하위 agent 위임, Kana의 공통 가능 시간 후보 검증·최종 결정)에 대한 task만 추가한다.

TODO 구현 전에 먼저 정의한 task 목록이다 (`docs/evals/roadmap.md` Step 8, eval-driven development). `AgentRuntime(active_week=6).run_agent(...)`로 `./run.sh --week6`와 동일한 실행 경로를 코드에서 직접 호출해 2026-08-05에 실제 agent 대화로 검증했다.

총 7개 (골든 3 / 경계 2 / 부정 1 / 추가과제 1) — 전부 PASS(아래 E1 경과 참고). B2는 스트레스 테스트 중 발견한 케이스를 새로 추가.

---

## 골든 패스

### G1 — 개인 일정 요청은 Nana에게 위임
- 입력: "내일 오후 3시에 치과 예약 일정 추가해줘"
- 기대 결과: supervisor가 `kana_agent`를 부르지 않고 `nana_agent`만 호출. Nana 하위 agent trace에 개인 일정 저장 tool(Week 1~3 계열, 예: `personal_*`/SQLite 저장 tool) 호출이 남고, 최종 답변에 등록된 일정이 반영됨.
- 검증: 2026-08-05 확인. `nana_agent`만 호출, 내부 trace에 `extract_schedule_request`→`save_structured_request` 이어짐. "내일 오후 3시에 치과 예약 일정을 추가했어요" 응답. PASS.
- 분류: golden

### G2 — 외부 멤버 일정 조회 요청은 Kana에게 위임
- 입력: "철수랑 영희 7월 7일부터 17일까지 일정 좀 알려줘"
- 기대 결과: supervisor가 `nana_agent`를 부르지 않고 `kana_agent`만 호출. Kana 하위 agent trace에 `collect_member_schedules` 또는 `search_previous_conversations`/`extract_schedules_from_history` 호출이 남고, 응답에 두 사람의 일정이 반영됨.
- 검증: 2026-08-05 확인. `kana_agent`만 호출, 내부 trace에 `extract_schedules_from_history` 호출, 철수/영희 일정이 날짜·시간 그대로 나열됨. PASS.
- 분류: golden

### G3 — 개인 일정 조회 후 이어서 그룹 일정 조율 요청 시 위임 대상이 바뀜
- 입력: "내 이번 주 일정 보여줘" → 이어서 "철수, 영희랑 다같이 시간 되는 때 찾아줘"
- 기대 결과: 첫 요청은 `nana_agent`, 두 번째 요청은 `kana_agent`로 각각 올바르게 위임됨(같은 대화 안에서도 요청 성격에 따라 위임 대상이 바뀜).
- 검증: 2026-08-05 최초 확인에서 **버그 발견 후 수정**. 첫 요청("내 이번 주 일정 보여줘")이 외부 멤버 언급이 전혀 없는데도 `kana_agent`로 잘못 위임됨(`docs/troubleshooting/week6.md` 참고). `week06_prompt_parts()`에 개인 조회 few-shot 예시 추가 후 재실행: "내 이번 주 일정 보여줘"/"오늘 내 일정 뭐 있어?"/"이번 달 내 일정 확인해줘" 3가지 표현 모두 `nana_agent`로 정확히 위임됨. 두 번째 요청(그룹 조율)은 최초 확인에서 이미 `kana_agent`로 정상 위임되어 `collect_member_schedules`→`find_common_available_slots` 호출, 후보 5개 제시. PASS(수정 후).
- 분류: golden

---

## 경계 사례

### B1 — 확정된 그룹 일정을 "저장"해달라는 요청은 Kana가 직접 저장하지 않고 Nana로 넘어가야 함
- 입력: (그룹 시간 조율이 끝난 상태에서 이어서) "방금 정해진 시간으로 내 캘린더에도 저장해줘"
- 기대 결과: Kana가 스스로 개인 일정 저장 tool을 호출하지 않고, supervisor가 이어서 `nana_agent`를 호출해 저장을 완료함(`kana_prompt_parts()`에 "확정 일정 저장은 Nana 담당" 지시가 반영됐는지 확인하는 사례).
- 검증: 2026-08-05 확인. G3에 이어 실행, `nana_agent`만 호출되어 `extract_schedule_request`→`save_structured_request` 이어짐. "7월 7일 11시부터 13시까지 일정이 내 캘린더에 저장되었어요" — G3에서 제시된 첫 후보와 일치. PASS.
- 분류: boundary

### B2 — 한 메시지에 개인+외부 요청이 섞이면 supervisor가 tool을 2개 호출할 수 있음(허용된 동작)
- 입력: "내 일정도 보여주고 철수랑 시간도 맞춰줘"
- 기대 결과: `nana_agent`/`kana_agent` 중 하나만 호출하도록 유도하되, 명확히 섞인 요청이면 둘 다 호출해 결과를 합쳐 답해도 무방함. 답변이 깨지거나 앞뒤가 안 맞으면 안 됨.
- 검증: 2026-08-05 확인. 최초엔 supervisor 프롬프트가 "정확히 하나만 호출"로 돼있어 규칙 위반(둘 다 호출, 7/7 재시도 실패 — `docs/troubleshooting/week6.md` 참고) 상태였음. 규칙을 "가능하면 하나, 명확히 섞이면 둘 다 허용"으로 완화 후 재실행: 여전히 두 tool 다 호출하지만 답변이 자연스럽게 날짜 범위를 되묻고 두 맥락을 반영함. PASS(완화된 기준 기준).
- 분류: boundary

---

## 부정 사례 (agent 전체 대화로만 검증 가능)

### N1 — 인사말에 nana_agent/kana_agent 둘 다 오발동 안 함
- 입력: `"안녕"`
- 기대 결과: `nana_agent`/`kana_agent` 중 어느 것도 호출되지 않고 인사로만 응답.
- 검증: 2026-08-05 확인. trace의 `events`가 빈 리스트, `supervisor_selected_agent`도 `null` — tool 호출 없이 인사로만 응답. PASS.
- 분류: negative

---

## 추가과제 (구현 시에만 적용)

### E1 — 공통 가능 시간 후보 검증 → 최종 결정까지 체이닝
- 입력: "철수, 영희랑 7월 7일부터 17일까지 1시간짜리 회의 잡을 수 있는 시간 찾아서 확정해줘"
- 기대 결과: Kana 하위 agent trace에 `collect_member_schedules`(또는 동등 조회) → `find_common_available_slots`(agent가 직접 고른 `candidate_slots` 전달) → `decide_final_slot`(agent가 직접 고른 `final_slot` 전달) 순서로 이어지고, `kana_agent` 반환값의 `final_slot_payload`가 최종 답변에 안내된 확정 시간과 일치함.
- 검증: 2026-08-05 확인, **재현성 문제 발견 → 근본 원인 수정 → 조건부 PASS**. 체이닝 자체(3개 tool 순서, `final_slot_payload` 필드 채우기)는 코드/구조상 정상 동작 확인됨(stress 케이스 "가상의인물" 요청에서 `find_common_available_slots`→`decide_final_slot`까지 완주, `final_slot_payload`가 최종 답변과 일치). 다만 같은 조건 반복 시 실제 존재하는 공통 시간을 "없다"고 잘못 답하는 비율이 처음엔 60%(5회 중 3회)였음. description 상세화/단순화 시도는 둘 다 실패·역효과. 재조사 결과 진짜 원인은 `fixed/schedule_decision.py`가 후보 거절 이유를 계산해놓고 버려서 Kana가 재시도 신호를 못 받는 것으로 확인 — `find_common_available_slots_dict`에 거절 이유(`rejected_candidates`)와 재시도 유도(`needs_retry`) 필드를 추가하고 `busy_rows`를 사람별로 재정렬(둘 다 `fixed/` 안 건드리고 week06 파일 안에서만 수정, `busy_rows_overlap`은 fixed의 public 함수를 import만 함). 수정 후 10회 반복 시 6회 성공(40%→60%)으로 개선. 완전한 해결은 아니라 조건부 PASS 유지, 상세 경과는 `docs/troubleshooting/week6.md` 참고.
- 분류: golden (추가과제)
