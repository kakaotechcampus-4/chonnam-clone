# Week 6 — supervisor + Nana/Kana 하위 agent 구현 계획

## Context

`student_parts/week06_kanamate_decides_schedule.py`는 Week 1~5까지 하나의 agent가 모든 tool을
직접 골라 쓰던 구조를, "supervisor → nana_agent/kana_agent 하위 agent 위임" 구조로 바꾸는 주차입니다.
파일에는 이미 상세한 구현 가이드 주석(1~186행), 완성된 공통 헬퍼(`_tool_call_names`,
`extract_langchain_trace`, `tool_name`, `propose_group_schedule`, `kana_tools`, `supervisor_tools`,
`agent_tool_names`, `build_langchain_supervisor_agent`, `build_week_agent`), 그리고 Pydantic 입력
스키마가 모두 준비되어 있습니다. 비어 있는 것은 **prompt 함수 4개, tool description 상수 2개,
tool 본문 5개**뿐입니다. 이 계획은 그 빈 자리를 어떤 계약(contract)에 맞춰 채울지 정리합니다.

가이드가 메인/추가 과제를 나눠 설명하지만, 이미 `kana_tools()`가 `find_common_available_slots`/
`decide_final_slot`을 조건 없이 포함하고 있고 `kana_prompt_parts()` TODO에도 "추가 과제를
구현했다면"이라는 조건부 문구가 있을 뿐 별도 분기가 없습니다. 즉 이 파일의 최종 상태는 메인+추가
과제가 모두 구현된 상태를 전제로 하므로, **이번 구현은 메인과제와 추가과제를 한 번에 채웁니다.**
(가이드의 "추가 과제 미구현 시 kana_tools()에서 빼고 확인"은 디버깅용 중간 점검 옵션이지 최종
목표가 아니라고 판단했습니다.)

## 확인된 핵심 계약 (조사 결과)

- `agent.invoke(...)`는 항상 `{"messages": [{"role": "user", "content": "..."}]}` 형식
  (`fixed/week_agent_registry.py:112` 패턴과 동일하게 하위 agent도 이 형식으로 invoke).
- `fixed/langchain_trace.py`의 `extract_agent_events(result)`는 tool_call/tool_result 이벤트
  리스트를, `extract_final_text(result)`는 최종 답변 문자열을 만듦 — 하위 agent 결과를 그대로 이
  두 함수에 넘기면 됨.
- 이 파일 자체의 `extract_langchain_trace(result)`(250~278행, 이미 구현됨)는 **supervisor**
  실행 결과를 다시 훑어서, `tool_result` 이벤트의 `content`(=nana_agent/kana_agent가 반환한 JSON을
  파싱한 dict)에서 `inner_tool_names`, `final_slot_payload`, `final_decision_payload` 키를
  읽어 올립니다. → **nana_agent/kana_agent가 반환하는 JSON에 이 키 이름을 정확히 써야** 이 파일의
  supervisor-level trace 추출이 제대로 동작합니다.
- `fixed/schedule_decision.py`의 `find_common_available_slots_payload(...)`는
  `{ok, tool_name, members, busy_rows, candidate_slots, slot_source, payload_source, llm_reason}`을,
  `decide_final_slot_payload(...)`는 top-level `{final_slot, reason, candidates, needs_agent_selection}`
  + 조건부 `{selected_index, selected_slot, members, date_from, date_to, busy_rows, candidate_slots}`를
  반환 — 이 두 함수에 인자를 그대로 넘기고 JSON으로 감싸기만 하면 됨 (직접 겹침 계산 로직을 새로
  만들 필요 없음).
- `collect_member_schedules`(Week5)는 `@tool`이라 `.invoke({...})`로 호출.

## 구현 대상 파일

`student_parts/week06_kanamate_decides_schedule.py` 한 곳만 수정합니다. import 줄에
`PERSONAL_SHARED_MEMBER_NAME`을 `fixed.external_people_store`에서 추가로 가져와야 합니다
(현재는 `normalize_external_member_names`만 import되어 있음).

## 단계별 구현

### 1. Prompt 함수 4개 (메인과제)

**`week06_prompt_parts()`** — `week05_prompt_parts()`에 supervisor 위임 기준 추가:
- 개인 일정 생성/조회/수정/삭제, todo/알림 저장, 개인 참고자료·앱 대화 RAG → `nana_agent`
- 외부 멤버 대화/일정 조회, 공유 일정 저장소 확인, 공통 가능 시간 조율/최종 확정 → `kana_agent`
- supervisor는 직접 tool을 호출하지 않고 반드시 둘 중 하나로 위임

**`nana_prompt_parts()`** — `week04_prompt_parts()`에 Nana 역할 한 조각 추가: 개인 일정/저장/RAG만
담당하고, 그룹 조율 요청이 오면 처리하지 않고 Kana 담당이라고 짧게 알림.

**`kana_prompt_parts()`** — 누적 없이 새로 작성. Kana의 tool 사용 순서를 명시:
`extract_schedule_request`(요청 구조화) → `search_previous_conversations`/`load_conversation_messages`
(외부 대화) 또는 `extract_schedules_from_history`/`collect_member_schedules`(busy-time) →
`list_shared_schedules`(공유 저장소 확인) → `find_common_available_slots`(겹치지 않는 후보를
직접 골라 candidate_slots+busy_rows로 전달) → `decide_final_slot`(최종 선택 기록). 확정 일정을
앱 DB에 저장하는 건 Nana 담당이라고 명시.

**`supervisor_system_prompt()`** — `week06_prompt_parts()` 뒤에 "반드시 nana_agent 또는
kana_agent를 호출한 뒤 그 결과만 근거로 답한다" 지시 한 조각 추가.

### 2. Tool description 상수 2개 (추가과제)

`FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION`/`DECIDE_FINAL_SLOT_DESCRIPTION`을 빈 문자열에서
채웁니다. 핵심은 "이 Python tool은 후보/최종시간을 계산해주지 않는다"는 점과 argument 형식
(`candidate_slots` 항목: date/start_time/end_time/duration_minutes/reason,
`final_slot`: `'YYYY-MM-DD HH:MM-HH:MM'`)을 명시하는 것 — `FindCommonAvailableSlotsInput`/
`DecideFinalSlotInput`의 Field description과 같은 계약을 말로 풀어씀.

### 3. `find_common_available_slots_dict` (추가과제)

```python
def find_common_available_slots_dict(
    member_names, date_from, date_to,
    duration_minutes=60, workday_start="09:00", workday_end="18:00", limit=5,
    busy_rows=None, candidate_slots=None, llm_reason=None,
) -> dict[str, Any]:
    normalized_members = normalize_external_member_names(member_names)
    normalized_date_from = normalize_date_bound(date_from)
    normalized_date_to = normalize_date_bound(date_to)

    if busy_rows is None:
        collected = json.loads(
            collect_member_schedules.invoke(
                {"member_names": normalized_members, "date_from": normalized_date_from, "date_to": normalized_date_to}
            )
        )
        busy_rows = collected.get("rows") or []

    payload_members = [PERSONAL_SHARED_MEMBER_NAME, *[n for n in normalized_members if n != PERSONAL_SHARED_MEMBER_NAME]]
    return find_common_available_slots_payload(
        member_names=payload_members, date_from=normalized_date_from, date_to=normalized_date_to,
        busy_rows=busy_rows, duration_minutes=duration_minutes,
        workday_start=workday_start, workday_end=workday_end, limit=limit,
        candidate_slots=candidate_slots, llm_reason=llm_reason,
    )
```

### 4. `find_common_available_slots` / `decide_final_slot` tool (추가과제)

두 tool 모두 얇은 wrapper — 각각 `find_common_available_slots_dict(...)` 결과를
`json.dumps(..., ensure_ascii=False)`로, `decide_final_slot_payload(...)` 결과를
`{"ok": True, "tool_name": "decide_final_slot", **payload}` 형태로 감싸 반환.
Python이 후보/최종시간을 대신 고르지 않는다는 가이드 원칙대로, 인자를 그대로 전달하기만 함
(자체 계산 로직 추가 금지).

### 5. `nana_agent` / `kana_agent` (메인과제, 위임 wrapper)

```python
@tool(args_schema=AgentQueryInput)
def nana_agent(query: str) -> str:
    global _NANA_SUBAGENT
    if _NANA_SUBAGENT is None:
        _NANA_SUBAGENT = create_agent(model=chat_model(), tools=week04_tools(), system_prompt=nana_system_prompt())
    result = _NANA_SUBAGENT.invoke({"messages": [{"role": "user", "content": query}]})
    events = extract_agent_events(result)
    payload = {
        "ok": True, "tool_name": "nana_agent",
        "answer": extract_final_text(result),
        "trace": {"events": events},
        "inner_tool_names": _tool_call_names(events),
    }
    return json.dumps(payload, ensure_ascii=False)
```

`kana_agent`는 동일한 골격에 `_KANA_SUBAGENT`/`kana_tools()`/`kana_system_prompt()`를 쓰고,
자기 트레이스의 `tool_result` 이벤트를 훑어 `tool_name == "decide_final_slot"`인 content를
`final_slot_payload`로, `tool_name == "propose_group_schedule"`이고 `content["final_decision"]`이
있으면 `final_decision_payload`로 끌어올려 반환 JSON에 추가 (없으면 `None`).

이 두 함수가 반환하는 JSON의 `inner_tool_names`/`final_slot_payload`/`final_decision_payload`
키 이름은 이 파일의 기존 `extract_langchain_trace()`(수정 안 함, 이미 완성됨)가 그대로 읽어가는
계약이므로 정확히 일치시켜야 합니다.

### 건드리지 않는 것

`kana_tools()`, `supervisor_tools()`, `agent_tool_names()`, `_tool_call_names()`,
`extract_langchain_trace()`, `tool_name()`, `propose_group_schedule()`,
`build_langchain_supervisor_agent()`, `build_week_agent()`, 모든 Pydantic 입력 클래스는 이미
완성된 상태이므로 수정하지 않습니다.

## 검증 방법

1. 수정 직후 `python -c "import ast; ast.parse(open(...).read())"`로 문법 확인.
2. `python -c "from student_parts.week06_kanamate_decides_schedule import find_common_available_slots_dict; print(find_common_available_slots_dict(['하린'], '2026-07-14', '2026-07-14', busy_rows=[...]))"` 처럼
   LLM 없이 결정론적인 `find_common_available_slots_dict`/`decide_final_slot_payload` 경로를 직접
   호출해 겹침 계산과 반환 키를 눈으로 확인 (실제 LLM 호출 없이 가능한 유일한 자동 검증).
3. `.env`에 `PROXY_TOKEN`이 있으면 `./run.sh --week6` 실행:
   - "내일 3시에 회의 잡아줘"처럼 개인 일정 요청 → trace에서 `supervisor_selected_agent == "nana_agent"`,
     하위 trace에 `personal_create_schedule` 또는 `save_structured_request` 계열 호출이 남는지 확인.
   - "하린이랑 이번 주 일정 맞춰줘"처럼 그룹 조율 요청 → `supervisor_selected_agent == "kana_agent"`,
     `inner_tool_names`에 `collect_member_schedules`/`find_common_available_slots`/
     `decide_final_slot`이 순서대로 남고 `final_slot_payload.final_slot`이 최종 답변과 일치하는지 확인.
   - 위임이 엉뚱한 agent로 가면 tool 코드가 아니라 `week06_prompt_parts`/`supervisor_system_prompt`의
     판단 기준 문구부터 다시 봄 (가이드 124행 지침).

