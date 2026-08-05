# Week 6 튜터링 가이드

대상 파일: `student_parts/week06_kanamate_decides_schedule.py`

이 문서는 수강생이 TODO를 **직접** 작성하고, Claude는 정답 코드를 대신 써주지 않고 힌트/설계 방향만 제시하는 튜터링 세션을 위한 참고 문서다. 튜터링할 때마다 이 파일을 먼저 읽고 현재 진행 상태와 힌트 포인트를 확인한다.

## 배경

Week 1~5는 이미 구현되어 있고 Week 6에서 그대로 재사용한다.

- Week 1(`week01_wake_up_nana.py`): 개인 일정 CRUD tool, `join_system_prompt`
- Week 2(`week02_structure_natural_language_requests.py`): `StructuredRequest`/`extract_schedule_request`
- Week 3(`week03_build_nanas_logbook.py`): `AppSQLiteStore` 영속 저장
- Week 4(`week04_retrieve_nanas_memory.py`): 참고자료/SQLite/앱 대화 RAG, `week04_tools()`, `week04_prompt_parts()`
- Week 5(`week05_load_kanas_past_conversations.py`): 외부 SQLite/MCP 이전 대화 검색·로드, 외부 멤버 일정 추출, 공유 일정 조회·등록·삭제, `week05_tools()`, `week05_prompt_parts()`, `collect_member_schedules`

Week 6은 지금까지 **한 agent가 모든 tool을 직접 처리**하던 구조를 깨고, **supervisor가 Nana/Kana 두 하위 agent로 위임**하는 구조로 바꾸는 단계다. Nana는 개인 일정/저장/RAG(Week 1~4 담당 영역), Kana는 외부 멤버 일정/공유 일정/그룹 시간 조율(Week 2, Week 5 담당 영역 + 신규 공통 시간 결정)을 맡는다. supervisor가 직접 볼 수 있는 tool은 `nana_agent`/`kana_agent` 두 개뿐이다.

> 파일 상단 38~186행의 `[6주차 수강생 구현 가이드]` 주석 블록에 목표·과제 구성·핵심 흐름·역할 태그(`[메인]`/`[추가]`/`[공통]`)·검증 방법이 이미 상세히 적혀 있다. 이 문서는 그 내용을 반복하지 않고, TODO를 순서대로 짚어가는 체크리스트 역할만 한다. 막히면 먼저 그 주석 블록을 다시 읽는다.

## TODO 목록 (진행 순서)

메인과제 (supervisor → Nana/Kana 위임 뼈대 완성):

1. **`week06_prompt_parts()` 인라인 TODO** (195~203행, 현재 `week05_prompt_parts()`만 누적) — supervisor는 직접 업무를 처리하지 않고 `nana_agent`/`kana_agent`로만 위임한다는 지시, 어떤 요청이 Nana 담당이고 어떤 요청이 Kana 담당인지 판단 기준을 추가
2. **`nana_prompt_parts()` 인라인 TODO** (206~214행, 현재 `week04_prompt_parts()`만 누적) — Nana 전용 prompt(다른 하위 agent와 공유 안 됨). 개인 일정/저장/RAG 담당, 그룹 조율 요청은 담당이 아니라고 짧게 안내
3. **`kana_prompt_parts()` 인라인 TODO** (217~225행, 현재 `[]` — **누적 없이 처음부터 작성**) — 외부 멤버 일정/공통 가능 시간/그룹 조율 담당, 확정 일정 "저장"은 Nana 담당이라고 답하게 함. 추가과제 구현 시 `find_common_available_slots` → `decide_final_slot` 순서로 이어 호출하도록 지시 포함
4. **`supervisor_system_prompt()` 인라인 TODO** (236~243행, 현재 `week06_prompt_parts()`만 join) — 반드시 `nana_agent` 또는 `kana_agent` 중 하나를 호출한 뒤 그 결과만 근거로 답하라는 최종 실행 지시 추가
5. **`nana_agent(query)`** (tool, 479~489행, 현재 `...`) — `_NANA_SUBAGENT`가 `None`일 때만 `create_agent(model=chat_model(), tools=week04_tools(), system_prompt=nana_system_prompt())`로 만들고 재사용, `query`를 user 메시지로 invoke, `extract_agent_events(...)`/`extract_final_text(...)`로 trace/answer 추출 후 JSON 문자열 반환(`selected_agent`, `answer`, `trace`, `inner_tool_names`)
6. **`kana_agent(query)`** (tool, 492~500행, 현재 `...`) — `_KANA_SUBAGENT`를 `kana_tools()`+`kana_system_prompt()`로 한 번만 만들고 재사용, trace event의 `content`를 훑어 `final_slot`이 든 dict/`final_decision` 값을 끌어올려 JSON으로 반환(`answer`, `trace`, `inner_tool_names`, `final_slot_payload`, `final_decision_payload`)

추가과제 (Kana의 공통 가능 시간 후보 검증·최종 결정 — 구현하지 않으려면 `kana_tools()`(429~439행) 목록에서 두 tool 제거하고 Kana prompt에서도 언급 삭제):

7. **`FIND_COMMON_AVAILABLE_SLOTS_DESCRIPTION`** (285~294행, 현재 `""`) — 이 Python tool이 후보를 계산하지 않는다는 점, agent가 `busy_rows`를 읽고 `candidate_slots`(date/start_time/end_time/duration_minutes/reason)를 직접 채워 넘겨야 한다는 점, 후보가 busy row와 겹치면 안 된다는 점, 이 결과로 답을 끝내지 말고 `decide_final_slot`을 이어서 호출해야 한다는 점을 명시
8. **`DECIDE_FINAL_SLOT_DESCRIPTION`** (297~305행, 현재 `""`) — 이 Python tool이 최종 시간을 자동 선택하지 않는다는 점, agent가 `selected_index`/`selected_slot`과 `final_slot`(`'YYYY-MM-DD HH:MM-HH:MM'`)을 직접 골라 넘겨야 한다는 점, 미확정 시 `final_slot=null`/`needs_agent_selection=true` 규칙, 근거로 `candidate_slots`/`busy_rows`/`member_names`/`date_from`/`date_to`도 함께 넘기게 함
9. **`find_common_available_slots_dict(...)`** (366~385행, 현재 `...`) — `normalize_external_member_names(...)`/`normalize_date_bound(...)`로 정규화, `busy_rows`가 `None`이면 `collect_member_schedules.invoke({...})`로 수집(내 일정도 근거이므로 `member_names`에 `"나"` 포함), 실제 검증 payload는 `find_common_available_slots_payload(...)`(from `fixed/schedule_decision.py`)에 위임
10. **`find_common_available_slots(...)`** (388~404행, 현재 `...`) — 위 함수 결과를 JSON 문자열로 반환만 하면 됨
11. **`decide_final_slot(...)`** (407~426행, 현재 `...`) — 받은 인자를 그대로 `decide_final_slot_payload(...)`(from `fixed/schedule_decision.py`)에 넘기고 JSON 문자열로 반환 (직접 최종 시간을 고르지 않음)

> `kana_tools()`/`supervisor_tools()`/`agent_tool_names()`(429~453행)와 `build_langchain_supervisor_agent()`/`build_week_agent()`(503~519행)는 이미 구현되어 있다 — agent builder를 새로 작성할 필요가 없다. `propose_group_schedule`(456~476행)도 구현 완료 상태의 호환용 helper이며 `kana_tools()`에는 들어가지 않는다.

## 원문·트러블슈팅 기록

- 코드 작성 중 막힌 문제와 해결 과정은 `docs/troubleshooting/week6.md`에 기록한다.

## 튜터링 진행 방식

- 위 순서대로 한 항목씩 진행. 사용자가 먼저 시도하고, 막히면 개념/방향 힌트(예: 프롬프트에 어떤 판단 기준이 필요한지, `create_agent`에 넘길 인자 조합, trace event에서 값을 끌어올리는 위치, tool description과 Pydantic 스키마의 일관성 등)를 질문 형태나 참고 위치 pointer로 제공한다.
- 사용자가 "모르겠다"고 명시하면 힌트를 한 단계 강화해 의사코드 수준(호출 순서, 분기 조건, 반환 JSON 키 등)까지 알려준다. 이 단계에서도 실행 가능한 완성 코드는 주지 않는다.
- "이 부분은 대신 써줘"라고 명시적으로 요청할 때만 Edit으로 완성 코드를 작성한다. 그 외에는 사용자가 작성한 코드를 Read로 확인하고 반환 JSON 형태, 위임 판단 기준, 예외 처리만 짚어준다.
- 각 항목 완료 후 다음 항목으로 넘어가되, 사용자가 순서를 바꾸길 원하면 따른다.
- 메인과제(1~6번) 전부 완료 후 추가과제(7~11번)로 넘어간다.

## 검증 방법

- 메인과제: `./run.sh --week6`을 실행하고, supervisor trace에서 `nana_agent`/`kana_agent` 중 무엇이 선택됐는지, 개인 일정 조회 요청에서 Nana 하위 agent trace에 `personal_list_saved_schedules` 호출이 남는지 확인한다. 위임이 엉뚱한 agent로 가면 tool 구현이 아니라 prompt의 판단 기준부터 고친다. 추가과제 미구현 상태면 `kana_tools()`에서 `find_common_available_slots`/`decide_final_slot`을 빼고 Kana prompt에서도 언급을 지운 뒤 위임 흐름만 확인한다.
- 추가과제: 그룹 일정 요청에서 하위 trace에 `search_previous_conversations`, `extract_schedules_from_history` 또는 `collect_member_schedules`, `find_common_available_slots`, `decide_final_slot`이 이어지고 `final_slot_payload`가 최종 답변과 일치하는지 확인한다.
- 파일 상단 가이드 주석(121~129행)의 "검증 방법" 절을 참고한다.
