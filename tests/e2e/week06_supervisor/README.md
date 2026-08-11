# Week 06 Supervisor E2E

실제 LLM을 호출해 Supervisor의 Nana/Kana 위임과 하위 tool workflow를 검증한다.

## 실행

```bash
make e2e-week06
```

특정 시나리오만 실행할 수 있다.

```bash
uv run python tests/e2e/week06_supervisor/run_scenarios.py \
  --scenario group-collect-find-decide-confirmed
```

이 테스트는 repository의 system prompt, tool description, 시나리오 입력과 격리된
runtime tool 결과를 설정된 외부 모델 endpoint로 전송한다. 해당 전송이 허용된
환경에서만 실행한다.

## 검증 범위

- 개인 일정 CRUD와 todo/reminder 저장의 Nana routing
- 개인 참고자료, 저장 요청 기록, 앱 일반 대화 RAG의 출처별 Nana routing
- 외부 일정, 원문, 공유 일정의 Kana routing
- 멤버·날짜 누락 재질문과 후속 턴 복원
- 외부 일정 `search → extract → load` traceability
- 나 포함 일정 수집 시 `collect_member_schedules` 단독 사용
- `collect → find → decide` 그룹 결정
- `search → extract → find → decide` 외부 멤버 그룹 결정
- busy rows와 검증된 candidate slots의 다음 tool 전달
- source busy rows가 `find`와 `decide`까지 동일하게 전달되는지
- 후보 필드·날짜/시간 형식과 60분/90분 duration 계약
- ISO datetime 날짜 범위의 `YYYY-MM-DD` 정규화
- 후보 없음 시 미확정 payload와 답변에 임의 확정 시간이 없는지
- Supervisor wrapper 정확히 한 번 호출 및 wrapper JSON 필드 계약
- 확정 시간이 검증 후보 및 selected index/slot과 일치하는지
- 외부 멤버 전용 결정에 `나`가 포함되지 않는지
- 최종 답변과 `final_slot_payload.final_slot` 일치

각 scenario는 별도의 conversation scope를 사용하며, 앱 DB·Chroma·외부 SQLite는
실행별 임시 디렉터리로 격리된다.
