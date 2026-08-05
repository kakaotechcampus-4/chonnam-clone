# Week6 Eval Task 목록

골든 패스/경계 사례/회귀 방지/부정 사례는 `week5-tasks.md`를 그대로 이어받는다. 이 파일에는 Week6에서 새로 생긴 기능(supervisor → Nana/Kana 하위 agent 위임, Kana의 공통 가능 시간 후보 검증·최종 결정)에 대한 task만 추가한다.

TODO 구현 전에 먼저 정의한 task 목록이다 (`docs/evals/roadmap.md` Step 8, eval-driven development). 아직 `student_parts/week06_kanamate_decides_schedule.py`의 TODO가 구현되지 않았으므로 전부 미검증 상태이며, 구현 완료 후 `AgentRuntime(active_week=6).run_agent(...)` 또는 `./run.sh --week6` 실제 agent 대화로 하나씩 검증한다.

총 6개 (골든 3 / 경계 1 / 부정 1 / 추가과제 1) — 전부 미검증(Week6 구현 전).

---

## 골든 패스

### G1 — 개인 일정 요청은 Nana에게 위임
- 입력: "내일 오후 3시에 치과 예약 일정 추가해줘"
- 기대 결과: supervisor가 `kana_agent`를 부르지 않고 `nana_agent`만 호출. Nana 하위 agent trace에 개인 일정 저장 tool(Week 1~3 계열, 예: `personal_*`/SQLite 저장 tool) 호출이 남고, 최종 답변에 등록된 일정이 반영됨.
- 검증: 미검증 — Week6 구현 완료 후 진행.
- 분류: golden

### G2 — 외부 멤버 일정 조회 요청은 Kana에게 위임
- 입력: "철수랑 영희 7월 7일부터 17일까지 일정 좀 알려줘"
- 기대 결과: supervisor가 `nana_agent`를 부르지 않고 `kana_agent`만 호출. Kana 하위 agent trace에 `collect_member_schedules` 또는 `search_previous_conversations`/`extract_schedules_from_history` 호출이 남고, 응답에 두 사람의 일정이 반영됨.
- 검증: 미검증 — Week6 구현 완료 후 진행.
- 분류: golden

### G3 — 개인 일정 조회 후 이어서 그룹 일정 조율 요청 시 위임 대상이 바뀜
- 입력: "내 이번 주 일정 보여줘" → 이어서 "철수, 영희랑 다같이 시간 되는 때 찾아줘"
- 기대 결과: 첫 요청은 `nana_agent`, 두 번째 요청은 `kana_agent`로 각각 올바르게 위임됨(같은 대화 안에서도 요청 성격에 따라 위임 대상이 바뀜).
- 검증: 미검증 — Week6 구현 완료 후 진행.
- 분류: golden

---

## 경계 사례

### B1 — 확정된 그룹 일정을 "저장"해달라는 요청은 Kana가 직접 저장하지 않고 Nana로 넘어가야 함
- 입력: (그룹 시간 조율이 끝난 상태에서 이어서) "방금 정해진 시간으로 내 캘린더에도 저장해줘"
- 기대 결과: Kana가 스스로 개인 일정 저장 tool을 호출하지 않고, supervisor가 이어서 `nana_agent`를 호출해 저장을 완료함(`kana_prompt_parts()`에 "확정 일정 저장은 Nana 담당" 지시가 반영됐는지 확인하는 사례).
- 검증: 미검증 — Week6 구현 완료 후 진행.
- 분류: boundary

---

## 부정 사례 (agent 전체 대화로만 검증 가능)

### N1 — 인사말에 nana_agent/kana_agent 둘 다 오발동 안 함
- 입력: `"안녕"`
- 기대 결과: `nana_agent`/`kana_agent` 중 어느 것도 호출되지 않고 인사로만 응답.
- 검증: 미검증 — Week6 구현 완료 후 진행.
- 분류: negative

---

## 추가과제 (구현 시에만 적용)

### E1 — 공통 가능 시간 후보 검증 → 최종 결정까지 체이닝
- 입력: "철수, 영희랑 7월 7일부터 17일까지 1시간짜리 회의 잡을 수 있는 시간 찾아서 확정해줘"
- 기대 결과: Kana 하위 agent trace에 `collect_member_schedules`(또는 동등 조회) → `find_common_available_slots`(agent가 직접 고른 `candidate_slots` 전달) → `decide_final_slot`(agent가 직접 고른 `final_slot` 전달) 순서로 이어지고, `kana_agent` 반환값의 `final_slot_payload`가 최종 답변에 안내된 확정 시간과 일치함.
- 검증: 미검증 — Week6 구현 완료 후 진행.
- 분류: golden (추가과제)
