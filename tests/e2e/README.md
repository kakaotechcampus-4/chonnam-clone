# E2E 회귀 테스트

이 디렉터리는 실제 LLM을 호출해 일정 agent의 tool 선택과 호출 순서를 검증하는 회귀 테스트를 담당합니다. 두 러너 모두 실행할 때 임시 SQLite/Chroma 경로를 사용하며 개발용 `data/` DB를 수정하지 않습니다.

## 요구 사항

- repo 루트의 `.env`에 유효한 `PROXY_TOKEN`이 있어야 합니다.
- E2E 실행 시 agent prompt, 시나리오 메시지, tool 실행 결과가 `.env`의 `CHAT_PROXY_URL`에 설정된 외부 LLM 프록시로 전송됩니다.
- `AuthenticationError` 또는 `expired_key`는 prompt 회귀가 아니라 인증 키 문제로 분류합니다.
- LLM의 tool 선택을 검증하므로 일반 단위 테스트보다 실행 시간과 비용이 더 큽니다.

## 실행

모든 명령은 repo 루트에서 실행합니다. `Makefile`의 타깃은 모두 `.PHONY`로 정의되어 있어 같은 이름의 파일 여부와 관계없이 항상 실행됩니다.

### `make test`

```bash
make test
```

내부적으로 다음 명령을 실행합니다.

```bash
uv run python -m unittest discover -s tests
```

`tests/`에서 `unittest`를 탐색해 일반 로직과 tool wrapper, prompt 조합, E2E 러너의 검증 함수를 빠르게 검증합니다. 이 타깃은 `tests/e2e/**/scenarios.json`을 실제 LLM으로 재생하지 않으며 `PROXY_TOKEN`이 필요하지 않습니다.

결과의 `Ran N tests ... OK`는 발견된 단위 테스트 N개가 모두 통과했다는 뜻입니다. `FAIL` 또는 `ERROR`가 나오면 응용프로그램 로직, test fixture, 러너 검증 로직 중 하나에 문제가 있는 것이며 Make는 0이 아닌 종료 코드를 반환합니다.

### `make e2e-schedule`

```bash
make e2e-schedule
```

내부적으로 Week 3/4 시나리오 러너를 실행합니다.

```bash
uv run python tests/e2e/schedule/run_scenarios.py
```

이 테스트는 실제 Week 3/4 agent와 LLM을 실행해 다음 행동을 검증합니다.

- 일정의 제목·날짜·시간이 충분하면 불필요하게 되묻지 않고 저장 tool까지 호출하는지
- 필수 정보가 부족할 때만 추가 질문을 하고, 답을 받으면 기존 대화의 정보와 합쳐 저장하는지
- 저장한 일정을 대화 기억으로만 답하지 않고 조회 tool을 실제로 호출하는지
- 일정과 무관한 대화에서 저장·조회·수정·삭제 tool을 불필요하게 호출하지 않는지
- 저장 시나리오의 경우 최종 일정 row가 임시 SQLite에 실제로 반영되었는지

각 시나리오에 `PASS`가 나오고 마지막에 `ALL PASS`가 나오면 모든 대화 turn의 tool 호출·답변 조건과 선택적 DB 상태 검사가 통과한 것입니다. `FAIL`은 기대 tool이 호출되지 않았거나, 금지된 tool이 호출됐거나, 답변·DB 상태가 fixture와 다른 회귀를 의미합니다.

### `make e2e-week05`

```bash
make e2e-week05
```

내부적으로 Week 5 MCP 시나리오 러너를 실행합니다.

```bash
uv run python tests/e2e/week05_mcp/run_scenarios.py
```

이 테스트는 최종 자연어 답변뿐 아니라 trace에 남은 MCP tool 호출과 tool result를 검증합니다.

- 외부 멤버 일정 조회가 `search_previous_conversations -> extract_schedules_from_history -> 선택적 load_conversation_messages` 순서를 지키는지
- 각 tool에 멤버 이름과 날짜 범위 등의 인자를 올바르게 전달하는지
- `collect_member_schedules`가 외부 일정을 이미 조회할 때 extract tool을 중복 호출하지 않는지
- 추출 결과가 없을 때 임의의 `conversation_id`나 일정을 만들지 않는지
- 개인 일정과 외부 멤버 일정이 표준 row 형태로 병합되고 외부 row의 `source_conversation_id`가 보존되는지
- 개인 일정, 외부 대화 일정, MCP 공유 일정이 요청 의도에 맞는 각각의 tool 경계를 지키는지

각 시나리오의 `PASS`는 기대한 tool 목록·순서·인자, tool result row, 답변 문구 조건이 모두 일치했다는 뜻입니다. `FAIL`은 출력에 표시된 turn의 실제 tool 호출과 기대값이 다르다는 뜻이며, prompt 또는 Week 5 tool 구현의 회귀 가능성을 의미합니다.

### `make e2e-week05-update`

```bash
make e2e-week05-update
```

Week 5 일정 수집 업데이트의 TC-01/02/04/07/08/09/10/11을 각각 독립된
시나리오로 실행합니다. 각 시나리오는 임시 DB에 개인·그룹·구버전·공유
일정을 사전 조건으로 준비한 뒤, 실제 Week 5 agent가 `collect_member_schedules`를
선택하는지와 tool result의 row 개수·값·members·payload key를 검증합니다.

특정 TC만 실행할 수도 있습니다.

```bash
make e2e-week05-update E2E_ARGS="--only tc04-duplicate-schedule-is-collapsed"
```

### `make e2e`

```bash
make e2e
```

`e2e-schedule`과 `e2e-week05`를 순서대로 모두 실행하는 종합 타깃입니다.

```text
e2e-schedule
    ↓ 성공
e2e-week05
```

기본 `make`를 병렬 옵션 없이 실행하면 Week 3/4가 성공한 뒤 Week 5로 넘어갑니다. 첫 번째 타깃이 실패하면 Make가 즉시 중단되므로 Week 5는 실행되지 않습니다. 최종 종료 코드 0은 두 E2E 러너가 모두 성공했다는 뜻입니다.

### 시나리오 선택과 디버깅 옵션

특정 시나리오나 임시 DB 보존 옵션은 `E2E_ARGS`로 러너에 전달합니다. `--only`는 해당 시나리오가 있는 개별 타깃에만 사용해야 합니다. `make e2e E2E_ARGS="--only ..."`를 실행하면 같은 id가 없는 러너에서 실패할 수 있습니다.

```bash
make e2e-schedule E2E_ARGS="--only save-when-fields-already-known"
make e2e-week05 E2E_ARGS="--only integrate-personal-and-external-schedules"
make e2e-week05 E2E_ARGS="--keep-tmp"
```

Make 타깃이 실행하는 원본 Python 명령은 다음과 같습니다.

```bash
uv run python tests/e2e/schedule/run_scenarios.py
uv run python tests/e2e/week05_mcp/run_scenarios.py
```

## E2E 결과 해석

- `PASS`: 해당 시나리오의 모든 turn과 최종 상태가 fixture의 기대와 일치합니다.
- `ALL PASS`: 선택된 모든 시나리오가 통과했으며 러너가 종료 코드 0을 반환합니다.
- `FAIL` + tool·답변·row·DB 불일치: 실제 agent 행동이 fixture의 기대와 다릅니다. prompt, tool 구현, fixture 기대값을 함께 조사합니다.
- `FAIL` + `agent 실행 자체가 실패함`: tool 선택 회귀로 단정하지 않습니다. `PROXY_TOKEN`, 프록시 연결, model 응답 오류를 먼저 확인합니다.
- `AuthenticationError` 또는 `expired_key`: 테스트 실패가 아니라 인증 키 문제입니다. 키를 갱신한 뒤 동일 명령을 다시 실행합니다.

실제 LLM은 실행마다 행동이 달라질 수 있으므로 단 한 번의 실패만으로 코드 회귀를 확정하지 않습니다. 실패 메시지와 trace를 확인하고, 필요하면 같은 `--only` 시나리오를 다시 실행해 재현성을 확인합니다.

## 구조

- `schedule/`: Week 3/4에서 저장·조회 tool을 실제로 호출하는지 검증합니다.
- `week05_mcp/`: Week 5의 `search_previous_conversations -> extract_schedules_from_history -> load_conversation_messages` 순서, 불필요한 중복 호출, 결과 row 구조를 검증합니다.
- `week05_mcp/schedule_update_scenarios.json`: Week 5 일정 누락·중복 제거 업데이트의 TC별 사전 DB 조건과 기대 tool result를 정의합니다.
- 각 `scenarios.json`은 대화 turn과 기대 tool 호출·답변·DB 상태를 정의하는 test fixture입니다.
- 각 `run_scenarios.py`는 fixture를 재생하고 trace와 DB를 검증하는 CLI 테스트 러너입니다.

## 시나리오 추가

1. 해당 디렉터리의 `scenarios.json`에 고유한 kebab-case `id`와 회귀 조건을 추가합니다.
2. tool 호출 여부는 `expect_tool_called`, `expect_any_tool_called`, `expect_no_tool_called`로 검증합니다.
3. Week 5의 정확한 호출 목록과 순서는 `expect_tool_calls_exact`, `expect_tool_order`, `expect_tool_call_arguments`로 검증합니다.
4. 답변 문구는 `expect_answer_contains_any`, `expect_answer_contains_all`, `expect_answer_not_contains`로 검증합니다.
5. 추가한 시나리오를 `--only <id>`로 먼저 실행해 fixture 스키마와 기대값을 확인합니다.
