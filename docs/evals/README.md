# docs/evals/ 인덱스

이 폴더는 Eval 로드맵 참고 문서와 주차별 task 목록을 모아둔다. 실행 코드는 없다 — 사람이 `./run.sh --weekN`으로 직접 확인하는 체크리스트다.

- [`roadmap.md`](./roadmap.md) — Week 무관, 영구 참고용 Eval 로드맵 (Step 0~8).
- [`week3-tasks.md`](./week3-tasks.md) — Week3(SQLite 로그북) agent용 task 44개. 골든 패스 4 / 경계 사례 22 / 멀티 인텐트 2 / 이슈 4(멤버 hallucination/제외-무시/unknown 흔들림 + 그 수정이 유발한 2차 회귀, 전부 원인 확정 후 프롬프트 규칙 추가로 해결 확인) / 회귀 방지 5 / 부정 사례 3.

## 새 주차 추가할 때

1. `week{N}-tasks.md`를 새로 만든다. 이전 주차 파일 내용을 복사하지 말고, 맨 위에 "골든 패스/회귀 task는 `week{N-1}-tasks.md`를 그대로 이어받는다"고 한 줄만 적는다.
2. 그 주차에서 새로 생긴 기능/tool에 대한 task만 추가한다.
3. 아래 표에 한 줄 추가한다.
4. 예전 주차에서 이미 고쳤던 버그가 재발하면, 새 파일에 새 task를 만들지 말고 **원래 발견됐던 `week{N}-tasks.md`의 해당 task**를 찾아 갱신한다 (`docs/troubleshooting/`가 같은 문제를 이어붙이는 방식과 동일).

| 파일 | 대상 | task 수 |
|---|---|---|
| `week3-tasks.md` | Week1~3 누적 agent (개인/그룹 일정, 할 일, 리마인더 SQLite 저장/조회/수정/삭제) | 44 |
