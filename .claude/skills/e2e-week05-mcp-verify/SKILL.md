---
name: e2e-week05-mcp-verify
description: Runs real-LLM E2E regression scenarios against the Week 5 MCP wrapper agent (student_parts/week05_load_kanas_past_conversations.py) to check that it follows docs/week05-implementation-plan.md's intended tool-call ORDER (search_previous_conversations -> extract_schedules_from_history -> optional load_conversation_messages), doesn't fabricate schedules/conversation_ids when extraction returns nothing, and that collect_member_schedules merges "나" + external member rows in the standard 6-field shape without redundantly re-calling extract_schedules_from_history. Use after editing student_parts/prompts/week05.py or the tool bodies in week05_load_kanas_past_conversations.py, before considering the change done. Korean triggers: "week5 회귀 테스트", "MCP tool 호출 순서 확인", "5주차 프롬프트 수정 검증". English triggers: "run the week5 e2e scenarios", "verify the week5 MCP tool order".
---

# Week 5 MCP wrapper agent E2E 회귀 테스트

## 이 스킬이 존재하는 이유

`docs/week05-implementation-plan.md`의 핵심 요구사항은 최종 답변 문구가 아니라 **agent가
tool을 어떤 순서로 호출했는가**다. Week 5는 Agent와 외부 SQLite 접근 권한을 분리하는 주차라서,
system prompt(`student_parts/prompts/week05.py`)가 만드는 판단 실수는 유닛 테스트로 잡을 수
없다 — `search_previous_conversations`를 건너뛰고 바로 `load_conversation_messages`를
부르거나, `collect_member_schedules`를 쓰면 되는데 `extract_schedules_from_history`를 중복
호출하거나, extract 결과가 없는데도 임의의 `conversation_id`를 지어내는 것 모두 코드 버그가
아니라 prompt가 만든 행동이다. 이 스킬은 `.claude/skills/e2e-week05-mcp-verify/`에서 실제
LLM 호출로 이 순서를 재생해서 확인한다.

기존 `e2e-schedule-verify` 스킬은 Week 3/4의 "저장/조회 tool을 불렀는가"(집합 여부)를
확인하고, 이 스킬은 Week 5의 "어떤 순서로 불렀는가"와 "합쳐진 rows 구조가 맞는가"를 확인한다는
점이 다르다.

## 언제 실행하는가

- `student_parts/prompts/week05.py`의 `WEEK05_*_PROMPT` 상수를 수정한 뒤
- `student_parts/week05_load_kanas_past_conversations.py`의 tool 본문(특히
  `_collect_member_schedules`, `week05_tools`, `week05_prompt_parts`)을 수정한 뒤
- 사용자가 "load를 먼저 부른다", "일정을 지어낸다", "나 일정이 안 섞인다", "중복으로 두 번
  조회한다" 같은 증상을 보고했을 때 원인을 고치고 나서
- 커밋하기 전 마지막 확인으로

## 실행 방법

```bash
uv run python .claude/skills/e2e-week05-mcp-verify/run_scenarios.py
```

특정 시나리오만 돌리려면:

```bash
uv run python .claude/skills/e2e-week05-mcp-verify/run_scenarios.py --only integrate-personal-and-external-schedules
```

- 실제 LLM을 호출하므로 `.env`의 `PROXY_TOKEN`이 유효해야 한다. `AuthenticationError`/
  `expired_key`가 나오면 그건 이 스킬이나 prompt의 문제가 아니라 키 문제이니, 사용자에게 키
  갱신을 요청하고 넘어간다.
- 실행마다 임시 디렉터리에 새 앱 SQLite/Chroma/외부 SQLite를 만들어 쓰고 끝나면 지운다.
  `data/kanana_app.sqlite3`나 실제 개발용 외부 DB는 건드리지 않는다(`fixed/config.py`의
  경로를 패치하고 `KANANA_EXTERNAL_DB_PATH` 환경 변수로 MCP subprocess의 외부 DB도
  격리한다 — `fixed/`, `mcp_server/` 코드는 수정하지 않는다).
- `ExternalPeopleSQLiteStore`는 생성 시 항상 같은 "7월 실습" fixture(철수/영희/민준/서연/
  지훈/하린, 2026-07-07~17 busy-time과 대화)를 다시 심으므로, 시나리오는 이 고정 데이터를
  근거로 결정적으로 검증할 수 있다. `scenarios.json`에 새 케이스를 추가할 때도 이 멤버/날짜
  범위를 그대로 활용한다.
- 실패하면 어느 turn에서 어떤 tool이 어떤 "순서"로 불렸어야/불리면 안 됐어야 하는지, rows에
  어떤 필드/멤버가 있어야 하는지를 구체적으로 출력한다.

## 결과 해석

- `PASS`: 모든 turn의 tool 호출 순서/rows 조건과 답변 조건이 기대와 일치.
- `FAIL` + "agent 실행 자체가 실패함": LLM 호출 자체가 에러(주로 키 만료/네트워크). prompt
  문제가 아니므로 다른 실패와 분리해서 취급한다.
- `FAIL` + 그 외 사유: 실제 회귀. `student_parts/prompts/week05.py`나
  `week05_load_kanas_past_conversations.py`를 다시 살펴본다. 특히 순서 실패는
  `WEEK05_HISTORY_WORKFLOW_PROMPT`를, rows 구조 실패는 `_collect_member_schedules`를
  먼저 확인한다.

## 새로운 회귀 케이스를 발견했을 때

새로운 "MCP tool 호출 경계/순서" 버그를 고치고 나면, 같은 문제가 다시 생기지 않도록
`scenarios.json`에 케이스를 하나 추가한다. 스키마(각 필드는 전부 선택 사항, 필요한 것만
채운다):

```json
{
  "id": "짧고 설명적인 kebab-case id",
  "description": "이 케이스가 무엇을 지키는지 한국어 한 문장",
  "week": 5,
  "turns": [
    {
      "message": "사용자 turn 텍스트",
      "expect_tool_called": ["이 turn에서 반드시 호출돼야 하는 tool 이름들"],
      "expect_any_tool_called": ["이 중 하나는 호출돼야 함"],
      "expect_no_tool_called": ["이 turn에서 호출되면 안 되는 tool 이름들"],
      "expect_tool_order": ["이 순서대로(첫 등장 기준 index 증가) 호출돼야 함"],
      "expect_tool_prefix": ["처음 N개 호출이 정확히 이 목록과 같아야 함"],
      "expect_tool_calls_exact": ["불필요한 호출 없이 전체 호출 목록이 정확히 이 목록이어야 함"],
      "expect_tool_call_arguments": [
        {
          "tool_name": "인자를 검사할 tool",
          "occurrence": 0,
          "arguments": {"member_names": ["철수"], "date_from": "2026-07-07"}
        }
      ],
      "expect_answer_contains_any": ["답변에 이 중 하나는 있어야 함"],
      "expect_answer_contains_all": ["답변에 이 문구들이 모두 있어야 함"],
      "expect_answer_not_contains": ["답변에 있으면 안 되는 문구들"],
      "expect_tool_result_rows_empty": ["이 tool의 마지막 결과 rows가 비어 있어야 함"],
      "expect_tool_result_row_keys": [
        {"tool_name": "load_conversation_messages", "keys": ["sender", "content", "created_at"]}
      ],
      "expect_tool_result_members": [
        {"tool_name": "extract_schedules_from_history", "members": ["철수", "영희"]}
      ],
      "expect_load_uses_extract_source_id": true,
      "expect_collect_member_schedules_rows": {
        "must_include_members": ["나", "철수"],
        "required_row_fields": ["member_name", "title", "date", "start_time", "end_time", "notes"],
        "external_rows_require_source_conversation_id": true
      }
    }
  ]
}
```

새 케이스를 추가한 뒤에는 반드시 `--only <새 id>`로 한 번 돌려서 스키마가 맞는지 확인한다.
