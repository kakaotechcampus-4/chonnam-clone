---
name: e2e-schedule-verify
description: Runs real-LLM E2E regression scenarios against the Week 3/4 Nana schedule agent (student_parts/week03_build_nanas_logbook.py, week04_retrieve_nanas_memory.py) to catch tool-call-boundary bugs — e.g. the agent extracting a schedule but never calling save_structured_request, or answering from chat memory instead of actually calling a save/search/list tool. Use after editing prompts in student_parts/prompts/week02.py, week03.py, week04.py, or common.py, or the tool bodies in week01-04 student_parts files, before considering the change done. Korean triggers: "회귀 테스트 돌려줘", "저장 안 되던 문제 재발했는지 확인", "프롬프트 수정 검증", "E2E 시나리오 실행". English triggers: "run the e2e scenarios", "verify the prompt fix", "check for regressions".
---

# Week 3/4 일정 agent E2E 회귀 테스트

## 이 스킬이 존재하는 이유

2026-07 PR 회고에서 나온 실제 버그: "내일 3시에 철수랑 회의 잡아줘"처럼 필요한 값이
문장에 이미 다 있는데도 agent가 `extract_schedule_request`만 부르고 `save_structured_request`는
안 부른 채 "제목이 뭐냐"고 되물었다. 또한 4턴 중 3턴은 tool을 아예 안 부르고 직전 대화
내용만으로 답했다. 이건 코드 버그가 아니라 system prompt가 만든 판단 실수라서, 유닛 테스트로는
못 잡고 실제 LLM 호출로 재생해야만 재발을 감지할 수 있다. `.claude/skills/e2e-schedule-verify/`가
그 재생 하네스다.

## 언제 실행하는가

- `student_parts/prompts/week02.py`, `week03.py`, `week04.py`, `common.py`의 아무 prompt든 수정한 뒤
- `student_parts/week01_wake_up_nana.py` ~ `week04_retrieve_nanas_memory.py`의 tool 본문을 수정한 뒤
- 사용자가 "저장이 안 됐다", "tool을 안 부른다", "되묻기만 한다" 같은 증상을 보고했을 때 원인을 고치고 나서
- 커밋하기 전 마지막 확인으로

## 실행 방법

```bash
uv run python .claude/skills/e2e-schedule-verify/run_scenarios.py
```

특정 시나리오만 돌리려면:

```bash
uv run python .claude/skills/e2e-schedule-verify/run_scenarios.py --only save-when-fields-already-known
```

- 실제 LLM을 호출하므로 `.env`의 `PROXY_TOKEN`이 유효해야 한다. `AuthenticationError`/`expired_key`가
  나오면 그건 이 스킬이나 prompt의 문제가 아니라 키 문제이니, 사용자에게 키 갱신을 요청하고 넘어간다.
- 실행마다 임시 디렉터리에 새 SQLite/Chroma를 만들어 쓰고 끝나면 지운다. `data/kanana_app.sqlite3`나
  실제 공유 외부 DB는 건드리지 않는다 (내부적으로 `fixed.config.CONFIG`의 경로를 패치하고,
  `KANANA_EXTERNAL_DB_PATH` 환경변수로 외부 MCP 저장소도 격리한다 — `fixed/` 코드는 수정하지 않는다).
- 실패하면 어느 turn에서 어떤 tool이 불렸어야/불리면 안 됐어야 하는지, 답변에 어떤 문구가
  있으면/없으면 안 되는지, DB에 어떤 row가 있어야 하는지를 구체적으로 출력한다.

## 결과 해석

- `PASS`: 모든 turn의 tool 호출/답변 조건과 최종 DB 상태가 기대와 일치.
- `FAIL` + "agent 실행 자체가 실패함": LLM 호출 자체가 에러(주로 키 만료/네트워크). prompt 문제가
  아니므로 다른 실패와 분리해서 취급한다.
- `FAIL` + 그 외 사유: 실제 회귀. 관련 prompt(`student_parts/prompts/week02.py`/`week03.py`/`week04.py`/
  `common.py`)나 tool 코드를 다시 살펴본다.

## 새로운 회귀 케이스를 발견했을 때

사용자가 보고한 새로운 "tool 호출 경계" 버그를 고치고 나면, 같은 문제가 다시 생기지 않도록
`scenarios.json`에 케이스를 하나 추가한다. 스키마:

```json
{
  "id": "짧고 설명적인 kebab-case id",
  "description": "이 케이스가 무엇을 지키는지 한국어 한 문장",
  "week": 3,
  "turns": [
    {
      "message": "사용자 turn 텍스트",
      "expect_tool_called": ["이 turn에서 반드시 호출돼야 하는 tool 이름들"],
      "expect_any_tool_called": ["이 중 하나는 호출돼야 함"],
      "expect_no_tool_called": ["이 turn에서 호출되면 안 되는 tool 이름들"],
      "expect_answer_contains_any": ["답변에 이 중 하나는 있어야 함"],
      "expect_answer_not_contains": ["답변에 있으면 안 되는 문구들"]
    }
  ],
  "db_check": {
    "kind": "personal_schedule",
    "title_contains": "부분 문자열",
    "date_offset_days": 1,
    "start_time": "HH:MM"
  }
}
```

`turns`의 각 필드는 전부 선택 사항이며 필요한 것만 채운다. `db_check`은 시나리오 마지막에
`AppSQLiteStore.list_schedules(kind=...)`로 실제 저장 여부를 확인할 때만 추가한다(저장 시나리오 전용).
새 케이스를 추가한 뒤에는 반드시 `--only <새 id>`로 한 번 돌려서 스키마가 맞는지 확인한다.
