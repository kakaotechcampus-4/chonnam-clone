# docs/evals/ 인덱스

이 폴더는 Eval 로드맵 참고 문서와 주차별 task 목록을 모아둔다. 실행 코드는 없다 — 사람이 `./run.sh --weekN`으로 직접 확인하는 체크리스트다.

- [`roadmap.md`](./roadmap.md) — Week 무관, 영구 참고용 Eval 로드맵 (Step 0~8).
- [`week3-tasks.md`](./week3-tasks.md) — Week3(SQLite 로그북) agent용 task 44개. 골든 패스 4 / 경계 사례 22 / 멀티 인텐트 2 / 이슈 4(멤버 hallucination/제외-무시/unknown 흔들림 + 그 수정이 유발한 2차 회귀, 전부 원인 확정 후 프롬프트 규칙 추가로 해결 확인) / 회귀 방지 5 / 부정 사례 3.
- [`week4-tasks.md`](./week4-tasks.md) — Week4(개인 참고자료/대화 발화 RAG) 신규 기능 task 10개, 전부 PASS. 골든 패스 4 / 경계 사례 1 / 회귀 방지 3(코드 리뷰로 고친 tags 타입 불일치·전역 store 의존성 + 기존 빈 쿼리 400 회귀 재확인) / 라우팅 회귀 1 / 부정 사례 1(둘 다 2026-07-28 `./run.sh --week4` 실제 agent 대화 trace로 검증 완료). week1~3 task는 `week3-tasks.md`를 그대로 이어받음.
- [`week5-tasks.md`](./week5-tasks.md) — Week5(외부 SQLite/MCP 이전 대화·공유 일정) 신규 기능 task 8개. 골든 패스 5 / 부정 사례 1 / 추가과제 1은 2026-07-29 실제 agent 대화로 PASS 확인(추가과제 테스트 중 `list_shared_schedules` 기본 필터 관련 버그 발견 후 프롬프트 수정으로 해결). 경계 사례 1(B1)은 미검증. week1~4 task는 `week4-tasks.md`를 그대로 이어받음.
- [`week6-tasks.md`](./week6-tasks.md) — Week6(supervisor→Nana/Kana 하위 agent 위임, 공통 가능 시간 후보 검증·최종 결정) 신규 기능 task 7개. 골든 3·경계 2·부정 1은 2026-08-05 실제 agent 대화로 PASS 확인(스트레스 테스트 중 라우팅 버그 1건 발견 후 프롬프트 수정으로 해결, 경계 사례 1건 신규 추가). 추가과제 1(E1)은 재현성 문제로 조건부 PASS. week1~5 task는 `week5-tasks.md`를 그대로 이어받음.

## 새 주차 추가할 때

1. `week{N}-tasks.md`를 새로 만든다. 이전 주차 파일 내용을 복사하지 말고, 맨 위에 "골든 패스/회귀 task는 `week{N-1}-tasks.md`를 그대로 이어받는다"고 한 줄만 적는다.
2. 그 주차에서 새로 생긴 기능/tool에 대한 task만 추가한다.
3. 아래 표에 한 줄 추가한다.
4. 예전 주차에서 이미 고쳤던 버그가 재발하면, 새 파일에 새 task를 만들지 말고 **원래 발견됐던 `week{N}-tasks.md`의 해당 task**를 찾아 갱신한다 (`docs/troubleshooting/`가 같은 문제를 이어붙이는 방식과 동일).

| 파일 | 대상 | task 수 |
|---|---|---|
| `week3-tasks.md` | Week1~3 누적 agent (개인/그룹 일정, 할 일, 리마인더 SQLite 저장/조회/수정/삭제) | 44 |
| `week4-tasks.md` | Week4 신규 기능 (개인 참고자료 RAG, SQLite 구조화 요청 검색, 대화 발화 agentic RAG, 호환용 통합 검색) | 10 |
| `week5-tasks.md` | Week5 신규 기능 (외부 SQLite/MCP 이전 대화 검색·로드, 외부 멤버 일정 추출, 내 일정+외부 일정 통합, 공유 일정 조회·등록·삭제) | 8 |
| `week6-tasks.md` | Week6 신규 기능 (supervisor→Nana/Kana 위임, 공통 가능 시간 후보 검증·최종 결정) | 7 |
