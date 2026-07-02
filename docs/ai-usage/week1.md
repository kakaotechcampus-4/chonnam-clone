# Week 1 — AI 활용 기록

대상 파일: `student_parts/week01_wake_up_nana.py`
PR 본문의 "AI 활용 내역" 제출본과 별개로, 매주 누적해서 남기는 개인 기록입니다.

## 방향성 힌트 → 직접 구현

`personal_create_schedule` / `personal_list_schedules` / `personal_delete_schedule`의
TODO를 채우는 과정에서 AI에게 구현 방향에 대한 힌트를 받고, 실제 코드는 직접 작성했습니다.

- 물어본 것: 세션 스코프별로 일정을 격리하려면 어떤 방식으로 필터링하면 좋을지,
  `PERSONAL_SCHEDULES` 리스트를 함수 밖에서 in-place로 교체할 때 주의할 점
- 직접 작성한 것: 딕셔너리 구성 순서, 필터 조건문, `PERSONAL_SCHEDULES[:]` 슬라이스 대입
- AI가 만든 코드를 그대로 붙여넣지 않고, 힌트만 참고해 [수강생 구현 가이드] 주석에 맞춰 판단

## 개념 질문 — tool calling 파이프라인과 `deleted` 값

`personal_delete_schedule`에서 `deleted` 개수를 왜 반환해야 하는지 궁금해서,
LangChain tool calling이 내부적으로 어떤 흐름으로 동작하는지 물어봤습니다.

- 질문: tool의 반환값은 어디로 가는가? LLM이 tool을 어떻게 고르고 결과를 어떻게 쓰는가?
- 배운 것: 흐름은 `LLM이 tool 선택 → 인자 바인딩 → 함수 실행 → 실행 결과(JSON)를 다시 LLM에 전달
  → LLM이 그 결과를 보고 자연어 응답 생성` 순서. tool의 반환값은 사람이 아니라 LLM이 먼저 읽는
  중간 결과라서, "삭제가 실제로 일어났는지"를 텍스트가 아니라 명시적인 값(`deleted` 개수)으로
  줘야 LLM이 "삭제됐습니다"와 "해당 일정을 못 찾았습니다"를 헷갈리지 않고 구분해서 답할 수 있음
- 적용: before/after 길이 비교로 `deleted` 값을 계산해 반환 JSON에 포함

## 리뷰 피드백 반영 메모

1주차 PR 리뷰에서 받은 피드백(Python 컨벤션 확인, Conventional Commit 확인, AI 활용 내역 문서화)에
따라 이 파일과 PR 본문의 "AI 활용 내역" 섹션을 함께 관리하기 시작함.
