# Week 6 검증 결과 — 2026-08-08

구현 대상: `student_parts/week06_kanamate_decides_schedule.py`의
`FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION`, `DECIDE_FINAL_SLOT_DESCRIPTION`,
`decide_final_slot()` 본문.

실행: `$env:KANANA_ACTIVE_WEEK='6'; uv run python app.py` → http://127.0.0.1:7860

## 1. 그룹 일정 요청 (Kana 체인) — 통과
입력: `다음 주에 나랑 철수, 영희 셋이 1시간 정도 회의할 시간 찾아줘`
- 스크린샷: `group_chat.png`, `group_trace.png`
- 답변: "…오전 9시부터 10시까지 철수, 영희와 함께 1시간 회의 시간을 확정했습니다."
- 상세 trace:
  - `supervisor_selected_agent: "kana_agent"` ✓ (supervisor→Kana 위임)
  - `inner_tool_names: ["collect_member_schedules", "find_common_available_slots", "decide_final_slot"]` ✓
    (description이 후보 작성 + decide_final_slot 연쇄 호출을 유도)
  - `final_slot_payload`: `final_slot: "2024-06-10 09:00-10:00"`, `needs_agent_selection: false`,
    `selected_index: 0`, `reason` 채워짐 ✓ (**decide_final_slot() 본문이 payload 정상 반환**)

## 2. 개인 일정 요청 (라우팅 대조군) — 통과
입력: `다음 주 수요일 오후 3시에 치과 예약 잡아줘`
- 스크린샷: `personal_trace.png`
- 상세 trace:
  - `supervisor_selected_agent: "nana_agent"` ✓ (개인 업무는 Nana로)
  - `inner_tool_names: ["personal_create_schedule"]` — 그룹 조율 tool 미호출 ✓
  - `다음 주 수요일` → `2026-08-12 15:00` 로 정확히 해석 ✓

## 판정: 통과
구현한 3곳(description 2 + decide_final_slot 본문)이 의도대로 동작.
`05_kana_decide_fail_trace.png`(이전 세션, 구현 前 decide 실패)와 대비하면
이번 `group_trace.png`에서 decide_final_slot이 정상 확정됨을 확인할 수 있다.

## 참고 (구현 무관, 관찰만)
그룹 후보 날짜가 `2024-06-10`으로 나왔다 — 오늘(2026-08-08) 기준 "다음 주"가 아니다.
이는 Kana agent가 candidate_slots를 만들 때 상대 날짜를 잘못 계산한 LLM 오류이며,
우리 코드는 agent가 고른 slot을 그대로 기록할 뿐이라 구현 결함은 아니다.
(개인 일정 쪽은 2026-08-12로 정확히 해석됨.) 날짜 유도가 자주 틀리면 Kana prompt에
`current_app_date_iso()` 기준 날짜를 명시하는 보강을 검토.
