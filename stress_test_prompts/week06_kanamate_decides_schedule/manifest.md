# week06_kanamate_decides_schedule 스트레스 테스트 매니페스트

## 대상 구조

- 진입점: `build_week_agent()` -> `build_langchain_supervisor_agent()` -> `supervisor_tools()`
- supervisor가 실제로 노출하는 tool은 `nana_agent`, `kana_agent` 2개뿐 (delegate tool).
  하위 subagent(week04_tools/kana_tools)가 부르는 내부 tool은 top-level trace
  event에 안 잡히므로(`extract_langchain_trace`가 supervisor 자신의 tool_call만
  events로 남김), 이 세트는 **라우팅(nana_agent vs kana_agent) 정확도** 검증에
  집중한다. args_schema가 `query: str` 하나뿐이라 경계값(숫자 제약 등) 카테고리는
  비중을 작게 잡았다.

## 이번 세트가 초점을 둔 지점

이번 세션에서 실제로 두 번 겪은 misrouting 버그(외부 멤버가 등장해도 날짜가
이미 구체적이면 nana_agent로 잘못 감)를 고치면서 라우팅 규칙을 "날짜 명시
여부"에서 "타인 등장 여부"로 바꿨다. 이 변경이 **새로운 과잉 적용**을 만들지
않는지가 이번 세트의 핵심 검증 대상이다. 특히:

- **ambiguous 그룹 b (8개, p039-p046)**: 외부 멤버 이름이 있어도 "이미 내가
  저장한 일정 조회/수정/삭제"는 Nana 담당인데, 새 규칙이 이걸 kana_agent로
  잘못 보낼 위험이 가장 크다.
- **ambiguous 그룹 d (6개, p053-p058)**: 이름이 등장하지만 그 사람과의 조율이
  목적이 아닌 경우(선물 아이디어, 레시피 등) - 오탐 검증용.
- **ambiguous 그룹 a (8개, p031-p038)**: 원래 버그가 재현되던 조건(날짜 확정 +
  외부 멤버) 자체의 회귀 검증.

## 카테고리별 개수

- direct: 20개
- boundary: 10개
- ambiguous: 45개
- multiturn: 15개
- offtopic: 10개

합계: 100개

## 캐시 상태

첫 생성 (재사용 0개, 신규 100개, 폐기 0개).

## 검색 품질형(retrieval) 미포함 사유

week06이 노출하는 tool은 nana_agent/kana_agent 델리게이트뿐이라, 내부
search_personal_references 등의 raw 검색 결과가 top-level event에 직접
노출되지 않는다(중첩된 tool_result 문자열 안에는 있지만). 이번 라운드는
라우팅 정확도가 최우선 검증 대상이라 검색 품질형은 이번엔 생성하지 않았다 -
불가능해서가 아니라 범위 밖으로 미룬 것.
