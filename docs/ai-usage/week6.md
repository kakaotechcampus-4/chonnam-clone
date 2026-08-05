# Week 6 — 카나메이트가 약속을 결정하다

대상 파일: `student_parts/week06_kanamate_decides_schedule.py`

## 목표

한 agent가 모든 기능을 직접 처리하던 구조를 supervisor와 Nana/Kana 하위 agent로 분리한다. Supervisor는 요청을 적절한 하위 agent에 위임하고, Nana는 개인 일정·저장·RAG를, Kana는 외부 멤버 일정·그룹 조율을 담당한다.

## 이전 주차와의 연결

- Supervisor prompt는 `week05_prompt_parts()`를 누적한다.
- Nana prompt와 도구는 `week04_prompt_parts()`, `week04_tools()`를 재사용한다.
- Kana는 Week 2의 `extract_schedule_request`와 Week 5의 외부 대화·공유 일정 도구를 역할에 맞게 조립한다.
- 실행 trace는 `fixed.langchain_trace`의 `extract_agent_events()`, `extract_final_text()`를 사용한다.

## TODO 목록

### 메인과제

- [x] (195~251줄) `week06_prompt_parts`, `nana_prompt_parts`, `kana_prompt_parts`, `supervisor_system_prompt` — Supervisor/Nana/Kana의 위임 규칙과 역할 경계를 정의한다. — 상태: 완료
- [x] (488줄 부근) `nana_agent` — Week 4 도구를 가진 Nana 하위 agent를 한 번 생성해 재사용하고 실행 결과를 JSON으로 반환한다. — 상태: 완료
- [x] (511줄 부근) `kana_agent` — Kana 하위 agent를 한 번 생성해 재사용하고 trace와 최종 일정 payload를 JSON으로 반환한다. — 상태: 완료

### 추가과제

- [ ] (286, 298줄 부근) 공통 시간·최종 선택 tool description을 작성한다. — 상태: 미시작
- [ ] (380줄 부근) `find_common_available_slots_dict`를 구현한다. — 상태: 미시작
- [ ] (403줄 부근) `find_common_available_slots`를 구현한다. — 상태: 미시작
- [ ] (423줄 부근) `decide_final_slot`을 구현한다. — 상태: 미시작

## 이미 구현되어 있는 함수

- `week06_system_prompt`, `nana_system_prompt`, `kana_system_prompt`: prompt 조각을 최종 문자열로 조립한다.
- `extract_langchain_trace`: supervisor 실행 결과를 UI trace payload로 변환한다.
- `_tool_call_names`, `tool_name`, `agent_tool_names`: tool 호출 이름을 추출한다.
- `propose_group_schedule`: 이전 실습 흐름과 호환되는 그룹 일정 제안 helper다.
- `build_langchain_supervisor_agent`, `build_week_agent`: supervisor를 생성·재사용하고 표준 entry point를 제공한다.

## 메인과제 구현 내용

- Supervisor는 업무 도구를 직접 처리하지 않고 개인 업무는 `nana_agent`, 외부 멤버·그룹 업무는 `kana_agent`에 위임한다.
- Nana는 `week04_tools()`를 가진 하위 agent를 최초 한 번만 만들고 재사용한다.
- Kana는 구현이 끝난 Week 2/5 그룹 도구만 사용한다. 미구현 추가과제 도구는 `kana_tools()`에서 제외했다.
- 두 wrapper는 최종 답변, 내부 trace, 실제 tool 호출 이름을 JSON으로 반환한다.
- Kana wrapper는 trace에 최종 시간 또는 최종 결정 payload가 있으면 상위 supervisor가 사용할 수 있도록 끌어올린다.

## 검증 방법

- `.venv\Scripts\python.exe`에서 import, prompt 조립, supervisor/Kana 도구 목록을 확인했다.
- fake agent 단위 검증으로 하위 agent 생성 인자, 캐시 재사용, JSON 응답, trace 및 payload 추출을 확인했다. 결과: PASS.
- `.venv\Scripts\python.exe -m unittest discover -s tests -v`로 공개 테스트 16개를 실행했다. 결과: 16개 모두 통과.
- 실제 모델 연결 환경에서는 `./run.sh --week6`으로 supervisor 위임 trace를 확인한다.
