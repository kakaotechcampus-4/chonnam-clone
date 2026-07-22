---
name: assignment-stress-test
description: >
  student_parts/ 안의 과제 파일(weekNN_*.py) 경로를 받아, 그 파일이 실제로
  agent에 노출하는 tool 구조(진입점/tool 목록/입력 스키마/설명)를 코드 파싱으로
  다시 계산하고, 그 구조에 맞는 예시 프롬프트 100개를 생성해 실제 agent를
  실행(AgentRuntime)해서 tool 라우팅이 의도대로 되는지 스트레스 테스트합니다.
  이전에 같은 파일로 만든 프롬프트가 stress_test_prompts/ 아래 있으면 tool
  시그니처가 안 바뀐 부분만 재사용하고 바뀐 부분만 새로 만듭니다. 실행은 격리된
  임시 DB/Chroma에서만 이뤄져 실제 앱 데이터(data/kanana_app.sqlite3, data/chroma)는
  건드리지 않습니다. "스트레스 테스트해줘", "100개 프롬프트로 테스트해줘",
  "tool 충돌 있는지 실제로 돌려서 확인해줘" 같은 요청과 student_parts 파일
  경로가 함께 오면 사용하세요.
---

# assignment-stress-test

과제 파일 하나를 코드 구조로 다시 분석해서, 그 구조에 맞는 예시 프롬프트 100개를
만들고, 실제 LangChain agent를 돌려서 tool이 의도대로 호출되는지 확인하는
스킬입니다. 목적은 "TODO 요약"이 아니라 "실제로 돌려서 tool 라우팅이 깨지는
지점을 찾는 것"입니다.

**절대 원칙**: 이 문서 안의 모든 함수명·tool명·필드명·예시 프롬프트는 특정
시점(week04)의 **포맷 참고용 샘플**일 뿐입니다. 실행할 때마다 대상 파일을
처음부터 다시 읽고 아래 절차를 전부 재계산합니다. 이전 실행 결과나 이 문서의
예시를 그대로 베끼지 않습니다. 미래에 구조가 완전히 달라진 과제 파일이 와도
(다른 tool 데코레이터 방식, args_schema 없는 tool, 다른 진입점 이름 등)
아래 fallback을 순서대로 타면서 동작해야 합니다.

## 입력

- 인자로 과제 파일 경로 하나를 받습니다 (예: `student_parts/week04_retrieve_nanas_memory.py`).
- 경로가 없으면 `student_parts/*.py` 목록을 보여주고 어떤 파일을 볼지 되묻습니다.
- 파일이 없거나 못 읽으면 그 사실을 바로 사용자에게 알립니다 (파싱 실패와 구분).
- 실행에는 `.env`의 `PROXY_TOKEN`(실제 LLM 호출)이 필요합니다. 없으면 이 스킬은
  실행 단계로 못 가니 그 사실을 먼저 알립니다.

## 절차

### 1단계 — 구조 탐색 (항상 재계산, 캐시 대상 아님)

가이드 주석이 아니라 **실행 가능한 코드**를 근거로 삼습니다. `Read`/`Grep`으로
직접 확인하거나 필요하면 `ast` 모듈을 쓰는 짧은 python 스니펫으로 확인합니다.

**1.1 진입점 발견**
- 최우선: `build_week_agent()` 함수. `fixed/week_agent_registry.py`가 모든
  주차에 강제하는 안정된 계약이라 가장 신뢰도 높은 앵커입니다.
- fallback: 못 찾으면 파일 안에서 `create_agent(` 호출부를 찾아 `tools=` 인자
  표현식을 역추적합니다.
- 그래도 실패하면: "이 파일에서 agent 진입점을 못 찾음"이라고 명시하고
  사용자에게 진입점을 물어봅니다. 조용히 포기하지 않습니다.

**1.2 실제 노출된 tool 목록 발견**
- `*_tools()` 형태 함수(이름을 하드코딩하지 않고, 진입점이 `tools=`에 넘기는
  함수를 따라감)를 앵커로 삼되, 그 함수가 이전 주차 `*_tools()`를 펼치는
  구조(`*week03_tools()` 같은)면 재귀적으로 따라가 최종 리스트를 만듭니다.
- **주의**: `@tool` 데코레이터가 붙어 있다고 전부 포함되는 건 아닙니다
  (예: 어떤 파일은 호환용 tool을 정의는 해두고 노출 리스트에서 빼기도 합니다).
  반드시 진입점이 실제로 넘기는 리스트에 들어간 것만 대상으로 삼습니다.

**1.3 각 tool의 입력 스키마 발견**
- `@tool(args_schema=XxxInput)` 패턴이면 그 Pydantic 클래스의 필드명/타입/
  기본값/`Field(ge=, le=)` 제약까지 읽습니다. 이게 3단계 "경계값 프롬프트"의
  재료입니다.
- `args_schema` 없는 순수 `@tool` 함수면 함수 시그니처(파라미터명/타입/기본값)를
  직접 읽습니다.
- 둘 다 안 되면: "입력 스키마 추론 불가"로 표시하고 docstring만으로 넘어갑니다.

**1.4 tool 설명/역할 수집**
- `@tool` 바로 아래 docstring을 최우선으로 읽습니다 (LLM이 실제로 tool
  선택할 때 보는 텍스트라 가이드 주석보다 신뢰도 높습니다).
- 가이드 블록에 "함수별 동작 설명" 같은 섹션이 있으면 보조로 참고합니다
  (todo-summary 스킬의 파싱 방식과 동일하게, 있으면 쓰고 없으면 생략).
- `*_prompt_parts()` 함수도 읽어서, 이미 박혀 있는 라우팅 규칙(예: "날짜
  조건 있으면 A tool, 없으면 B tool")이 있는지 확인합니다. 있으면 3단계에서
  그 규칙을 지키는/어기는 경계 케이스를 의도적으로 만듭니다.

**결과물**: tool마다 `{name, args_schema_fields, constraints, docstring}` 묶음.
이 묶음 전체를 문자열로 직렬화해 tool별 해시(`hashlib.sha256`)를 계산해둡니다.
이 해시가 2단계 캐시 판단의 유일한 근거입니다 (mtime 아님 — 주석만 고친 건
캐시를 안 깨야 하고, 필드/제약/역할이 바뀐 건 캐시를 깨야 하기 때문).

### 2단계 — 캐시 확인 (프롬프트만 재사용, 구조 판단은 재사용 안 함)

캐시 폴더: `stress_test_prompts/<과제파일_stem>/` (예:
`stress_test_prompts/week04_retrieve_nanas_memory/`). 파일명에서 자동
생성하고 하드코딩하지 않습니다.

1. 이 폴더가 없으면 → 4단계(전량 신규 생성)로 바로 갑니다.
2. 있으면 `manifest.json`을 읽습니다:
   ```json
   {
     "source_file": "student_parts/week04_retrieve_nanas_memory.py",
     "generated_at": "...",
     "tool_signatures": {"search_saved_requests": "sha256:...", "...": "..."}
   }
   ```
3. 방금 1단계에서 계산한 tool별 해시와 **tool 하나씩** 비교합니다.
   - 해시 동일 → 그 tool과 관련된 `prompts.jsonl`의 줄들을 그대로 재사용
     대상에 넣습니다.
   - 해시 다름 또는 새 tool → 그 tool 관련 프롬프트만 4단계에서 새로 만듭니다.
   - 캐시엔 있는데 지금 tool 목록엔 없음(삭제/이름변경) → 버리고, 최종
     리포트에 "제거된 tool: X (캐시에서 폐기)"라고 명시합니다.

### 3단계 — 카테고리 설계 (100개 배분 기준)

tool 개수를 N이라 할 때, 아래 5개 카테고리로 100개를 나눕니다. tool이
1~2개뿐인 아주 작은 과제 파일이면 카테고리 3(모호성형)의 절대량이 작아지는
게 정상이니 억지로 채우지 않습니다.

1. **직접 매칭형**: tool마다 여러 개, docstring 핵심어를 써서 그 tool 하나만
   명확히 가리키는 프롬프트.
2. **경계값/이상값형**: tool마다 몇 개, args_schema 제약을 건드리는 프롬프트
   (예: top_k에 0/음수/과도하게 큰 값, 빈 query, 필수 필드 누락 뉘앙스).
3. **tool 간 모호성형** (비중 크게): 역할이 겹치는 tool 2개 이상이 있으면
   그 경계에 걸치는 질문을 의도적으로 만듭니다. 각 프롬프트에 `expected_tool`
   라벨을 답니다. 이게 자동 tool-충돌 탐지의 핵심 재료입니다.
4. **멀티턴 시나리오형**: 저장→조회, 저장→수정→삭제, "같은 대화 안에서는
   제외되고 다른 대화에서는 검색되는지" 같은 상태 의존 흐름. `conversation_group`
   필드로 묶어 순서 보장을 표시합니다.
5. **주제 이탈형** (소수): 이 파일의 tool 어디에도 안 걸리는 일반 잡담.
   tool을 안 부르는 게 맞는 경우도 검증 대상입니다.

### 4단계 — 프롬프트 생성 (재사용 안 된 부분만)

각 프롬프트를 아래 스키마로 만들어 `prompts.jsonl`에 한 줄씩 씁니다:
```json
{"id": "p001", "text": "...", "expected_tool": "search_saved_requests", "category": "ambiguous", "reason": "날짜 조건 없이 키워드만 있어서 이 tool이 맞음", "conversation_group": null, "tool_signature_hash": "sha256:..."}
```
- `expected_tool`은 tool 안 부르는 게 맞으면 `null`.
- `conversation_group`은 독립 프롬프트면 `null`, 멀티턴 시나리오면 같은
  그룹 문자열(예: `"scenario_a"`)로 묶고, 그룹 안에서는 실행 순서가 곧
  `id` 오름차순이 되게 합니다.
- 재사용된 줄도 같은 파일에 합쳐 최종 100줄을 만듭니다.

`manifest.json`/`manifest.md`를 갱신합니다. `manifest.md`는 사람이 읽는
설명: 이번 세트가 어떤 tool 충돌/경계값에 초점을 뒀는지, 카테고리별 개수,
이전 대비 뭐가 바뀌었는지(재사용 N개, 신규 M개, 폐기 K개).

### 5단계 — 실행

`run_harness.py`(이 스킬 폴더에 이미 있음, assignment 구조를 전혀 모르는
순수 실행 배선이라 재작성 불필요)를 씁니다:

```bash
uv run python .claude/skills/assignment-stress-test/run_harness.py \
  --prompts stress_test_prompts/<stem>/prompts.jsonl \
  --active-week <weekNN에서 뽑은 정수> \
  --out stress_test_prompts/<stem>/results_history/<타임스탬프>.jsonl
```

- `active-week`은 파일명 `weekNN_...`에서 정규식으로 뽑습니다. 하드코딩 금지.
- 100개 전부 실제 LLM 호출이라 시간·비용이 듭니다. 실행 전에 사용자에게
  대략적인 예상(개수, 순차 실행 기준 소요 시간)을 알리고 진행합니다.
- `conversation_group`이 있는 줄들은 하나의 대화 안에서 순서대로 실행되어야
  하므로 harness가 순차 처리합니다(이미 구현됨). 독립 프롬프트끼리는
  병렬화 여지가 있지만 기본은 순차 — 필요하면 사용자와 병렬화를 상의합니다.
- **격리는 harness가 자동으로 함**: 실행 전에 `fixed.config.CONFIG`의
  `app_db_path`/`chroma_dir`을 `--out` 옆 `isolated_data_<out stem>/`으로
  돌려놓고 시작합니다. 실제 앱이 쓰는 `data/kanana_app.sqlite3`/`data/chroma`는
  절대 안 건드립니다 — 별도 조치 필요 없습니다. 위치를 바꾸고 싶으면
  `--isolate-dir`로 지정할 수 있습니다.
- **백그라운드 실행 시 주의**: Bash 도구의 `run_in_background:true` 위에
  직접 `nohup ... &`를 또 얹지 않습니다. 이중으로 백그라운드 처리하면 Bash
  도구가 실제 프로세스 종료 전에 "완료"로 잘못 보고합니다(래퍼 셸만 먼저
  끝남). `run_in_background:true` 하나만 쓰고, 진짜 완료는 `ps`로 PID 살아있는지
  확인하거나 `until [ ! -d /proc/<pid> ]; do sleep 5; done` 같은 blocking
  polling 커맨드를 별도로(역시 `run_in_background:true`로) 돌려서 확인합니다.

### 6단계 — 집계 및 리포트

`aggregate_results.py`(이 스킬 폴더에 이미 있음, run_harness.py와 마찬가지로
assignment 구조를 모르는 순수 집계 로직)를 씁니다:

```bash
uv run python .claude/skills/assignment-stress-test/aggregate_results.py \
  --prompts stress_test_prompts/<stem>/prompts.jsonl \
  --results stress_test_prompts/<stem>/results_history/<이번 타임스탬프>.jsonl \
  --previous stress_test_prompts/<stem>/results_history/<직전 타임스탬프>.jsonl   # 있으면
```

- `--previous`를 주면 회귀(저번엔 A tool, 이번엔 B tool) 자동 비교까지 나옵니다. 없으면 생략.
- 불일치가 나와도 바로 "코드 버그"로 단정하지 않습니다. 오늘 실제로 겪은 함정:
  - **schedule_id/request_id를 언급하는 단발성 프롬프트**는, 그 ID로 실제
    뭔가를 미리 만들어두지 않았으면 "조회부터 하는" 게 정상(week03류 안전규칙이
    의도한 동작)입니다 — 불일치로 잡혀도 버그 아닙니다. 이런 건 4단계에서
    애초에 멀티턴(`conversation_group`)으로 설계해야 정확히 테스트됩니다.
  - **경계값 카테고리에서 `tool_calls`가 아예 빈 배열**로 나오는 경우가 흔합니다
    — LLM이 이상값(top_k=0, 음수 등)을 눈치채고 tool 호출 자체를 안 하는
    경우가 많아서입니다. 이건 "validator가 막았다"는 증거가 아니라 "LLM이
    tool을 안 불렀다"는 뜻이라 **validator 자체의 방어력은 검증 못한 것**입니다.
    validator를 진짜 확인하려면 agent 경유 말고 tool 객체를 코드에서 직접
    `.invoke({...이상값...})`해서 `ValidationError`가 나는지 별도로 확인해야
    합니다.

## 출력 포맷

```
[불일치] p037 "회의 관련 저장된 거 찾아줘" (기대: personal_list_saved_schedules) → 실제: search_saved_requests
[회귀] p012 이전 실행 대비 tool 선택 바뀜 (search_personal_references → 없음)
[예외] p058 "top_k=-5로 검색해줘" → ValidationError: ...
[정상] 72/100 기대대로 동작
[캐시] 재사용 84개, 신규 생성 16개 (변경/신규 tool: search_saved_requests), 폐기 0개
```

## 주의사항

- 1단계(구조 탐색)는 캐시가 있어도 항상 새로 합니다. 캐시는 오직 "이미 검증된
  동일 tool 시그니처에 대한 프롬프트 문구"만 재사용 대상입니다.
- tool 이름·week 번호·파일명 패턴을 이 문서의 지시문 자체에 하드코딩하지
  않습니다 — 전부 "현재 파일에서 발견"으로 동작해야 합니다.
- 구조가 완전히 다른 미래 파일도 최소한 "함수명 + docstring만으로 프롬프트
  생성"까지는 내려갈 수 있어야 합니다(1.3/1.4의 fallback).
- `stress_test_prompts/<stem>/prompts.jsonl`, `manifest.json`, `manifest.md`는
  재사용 자산이므로 git 커밋 대상입니다. `results_history/`는 실행마다
  쌓이는 로그라 `.gitignore` 대상입니다(레포 최상위 `.gitignore`에 이미
  `stress_test_prompts/*/results_history/` 패턴을 추가해둘 것).
- 이 문서의 카테고리 이름·예시 문구·tool 이름은 모두 포맷 참고용 샘플입니다.
  실제 실행 시 1~4단계를 다시 계산해서 채웁니다.
- `run_harness.py`는 항상 격리된 임시 DB/Chroma에서 실행되므로 실제 앱 데이터를
  걱정할 필요 없습니다. 과거에(이 격리 로직 추가 전) 돌린 적이 있다면 그때
  생긴 테스트용 대화/일정/참고자료가 실제 `data/`에 남아있을 수 있으니, 이
  스킬을 오래 안 쓰다가 다시 쓸 때 `data/` 안에 낯선 테스트성 대화가 있는지
  한 번 확인하는 게 안전합니다.
- 2단계(캐시 재사용)와 6단계의 회귀 비교는 **같은 파일로 두 번 이상 실행해야만
  실제로 타는 경로**입니다. 첫 실행에서는 이 두 경로가 전혀 검증되지 않으니,
  캐시/회귀 기능이 중요한 상황이면 일부러 한 번 더 돌려서 재사용·회귀 탐지가
  의도대로 되는지 확인하는 걸 권장합니다.
