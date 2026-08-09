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
6. **검색 품질형** (검색 tool이 있는 파일만): "올바른 tool을 골랐나"가 아니라
   "그 tool이 **관련 있는 결과를 반환했나**"를 재는 별도 축입니다. fixture로
   미리 심어둔 문서(아래 3.5단계)를 근거로, 라벨에 `expected_hits`(반드시
   검색돼야 할 fixture_id 목록)와 `forbidden_hits`(나오면 안 되는 것)를 답니다.
   구성: 직접 매칭, 패러프레이즈(동의어로 임베딩 의미 매칭 확인), 유사쌍 순위
   (비슷한 문서 2개 중 하나만 정답 — 어느 쪽이 상위인지), 빈 결과가 정답
   (`expected_hits: []` — 관련 fixture가 없는 질문), 통합 검색 recall.
   ⚠️ **top_k 함정**: 1단계에서 파싱한 tool의 top_k 기본값보다 `expected_hits`
   개수가 크면 recall 1.0이 원천 불가능합니다. 라벨 설계 시 반드시 반영하세요.
   ⚠️ **배경 데이터 경쟁**: 격리 DB여도 앱 초기화 코드가 심는 기본/데모 데이터가
   존재할 수 있습니다 (week04에서 실제 겪음 — 격리 DB에 데모 참고자료가 있어
   fixture가 top_k 슬롯을 그 문서들과 경쟁했고, 그만큼 recall이 구조적으로
   깎였습니다). 배경 데이터는 지우지 말고 현실적 배경 코퍼스로 간주하되,
   그 존재를 manifest.md에 명시하고 expected_hits를 배경 경쟁을 감안해
   보수적으로 잡으세요.
   ⚠️ **호환/통합 tool 라벨 함정**: docstring에 "호환"이라 적혔거나 개별 tool들을
   합쳐놓은 통합 tool은 `expected_tool`로 강제하지 마세요 — agent가 개별 tool
   조합으로 같은 결과를 내면 그것도 정답입니다 (week04의 search_nana_memory에서
   실제 겪음). 이런 프롬프트는 `expected_tool: null`로 두고 `expected_hits`만
   평가하세요.

### 3.5단계 — fixture 정의 (검색 품질형을 만들 때만)

캐시 폴더에 `fixtures.jsonl`을 만듭니다 (git 커밋 대상). 한 줄 형식:

```json
{"fixture_id": "f001", "seed_module": "student_parts.week04_retrieve_nanas_memory", "seed_via": "add_personal_reference", "payload": {"title": "...", "content": "...", "tags": ["..."]}, "id_fields": ["reference_id"], "note": "무슨 검증용인지"}
```

- `seed_via`는 **대상 파일(또는 이전 주차 파일)에 실재하는** 저장 tool/함수 이름.
  1단계 구조 탐색에서 발견한 것만 씁니다. harness가 이름으로 import·호출하므로
  (LangChain tool이면 `.invoke(payload)`, 일반 함수면 `fn(**payload)`) harness는
  과제 구조를 계속 몰라도 됩니다.
- **id 값 스캔 규약**: fixture 판정은 payload에 인공 마커를 심는 게 아니라,
  seed 호출의 **반환값에서 저장 id를 수집**하는 방식입니다. `id_fields`에
  "반환값 어느 키의 값이 id인지"를 선언하면(예: 참고자료는 `["reference_id"]`,
  SQLite 저장은 `["request_id", "id"]` — saved_rows[].id까지 재귀 수집됨)
  harness가 seed 시 그 값들을 `fixture_map_*.json`에 기록하고, 집계기가
  tool_result 직렬화 문자열에서 그 id 값의 등장을 스캔합니다. 테스트 데이터가
  오염되지 않고, 반환 구조 지식은 코드가 아니라 fixtures 데이터에만 들어갑니다.
  id_fields는 1단계에서 파싱한 저장 함수의 반환 구조를 근거로 정하세요.
  id를 하나도 못 뽑으면 seed가 즉시 실패합니다.
- **사각지대 주의**: 이 방식은 검색 tool이 결과에 id를 포함해 반환할 때만
  동작합니다. id 없이 content만 반환하는 tool이 있으면 그 경로는 못 잡습니다 —
  1단계에서 반환 구조를 확인하고, 그런 tool이 있으면 리포트에 명시하세요.
- 유사쌍(비슷한 문서 2~3개)을 일부러 포함해야 순위 평가가 의미를 가집니다.
- fixture는 agent를 거치지 않고 store 함수 직접 호출로 심습니다(결정론 보장).

### 4단계 — 프롬프트 생성 (재사용 안 된 부분만)

각 프롬프트를 아래 스키마로 만들어 `prompts.jsonl`에 한 줄씩 씁니다:
```json
{"id": "p001", "text": "...", "expected_tool": "search_saved_requests", "category": "ambiguous", "reason": "날짜 조건 없이 키워드만 있어서 이 tool이 맞음", "conversation_group": null, "tool_signature_hash": "sha256:..."}
```
- `expected_tool`은 tool 안 부르는 게 맞으면 `null`.
- **검색 품질형만** 필드 추가: `expected_hits`(fixture_id 배열; `[]`이면
  "아무 fixture도 반환되면 안 됨"), `forbidden_hits`(반환되면 안 되는 fixture_id
  배열), `allow_rank`(선택, 기본 1 — 정답이 이 순위 안이면 통과. 유사쌍에서
  임베딩이 구분 못하는 미세 차이(예: "3월/4월" 한 글자)를 측정으로 확인한 뒤
  1순위 요구를 완화할 때만 쓰고, 근거를 reason에 남기세요). 이 필드가 아예 없는 프롬프트는 기존처럼 라우팅만 평가되므로 하위호환
  걱정 없습니다. 검색 품질형은 별도 파일 `retrieval_prompts.jsonl`로 관리해도
  되고(기존 100줄 자산을 안 건드리는 장점), prompts.jsonl에 합쳐도 됩니다 —
  harness의 `--prompts`에 어느 파일을 주는지만 다릅니다.
- **내용 정합성(하위 tool 인자 값)을 검증하고 싶으면** `expected_inner_args`를 씁니다:
  `[{"tool_name": "...", "args_equal": {"인자명": 기대값}}]` 형식. 라우팅
  (`expected_tool`)이 맞아도 그 안에서 호출한 하위 tool의 인자가 틀리면(예: 날짜
  미지정 조회인데 date_from/date_to에 임의 값이 들어감) 라우팅 체크만으로는 못
  잡습니다 — `expected_inner_args`는 top-level events뿐 아니라 nana_agent/
  kana_agent처럼 중첩된 tool_result 안의 trace까지 재귀적으로 훑어 해당
  tool_name 호출 중 하나라도 `args_equal`과 일치하면 통과시킵니다. 이 필드가
  없는 프롬프트는 기존처럼 라우팅만 평가되므로 하위호환 걱정 없습니다.
- **라벨을 나중에 고칠 때는 이력을 남깁니다**: 실행 결과를 보고 라벨이 틀렸다고
  판단해 수정하면(라벨 오류 기각), 그 프롬프트의 `reason` 필드에 "원래 라벨 →
  바뀐 라벨 + 근거 + 재검토 조건"을 적고 manifest.md에도 한 줄 기록하세요.
  이력이 없으면 다음 실행자가 완화된 라벨을 원래 기준인 줄 알게 됩니다.
- **manifest 등록은 retrieval 세트도 포함합니다**: manifest.json의
  `tool_signatures`에 검색 tool들의 해시를, `fixtures_hash`에 fixtures.jsonl
  전체 sha256을 넣고, `prompt_files`에 라우팅/검색 파일 경로를 둘 다 나열하세요.
  manifest에 없는 프롬프트 파일은 다음 스킬 실행 때 캐시 판단이 불가능해
  재생성으로 덮일 수 있습니다.
- `conversation_group`은 독립 프롬프트면 `null`, 멀티턴 시나리오면 같은
  그룹 문자열(예: `"scenario_a"`)로 묶고, 그룹 안에서는 실행 순서가 곧
  `id` 오름차순이 되게 합니다.
- 재사용된 줄도 같은 파일에 합쳐 최종 100줄을 만듭니다.
- **manifest.md는 덮어쓰지 않고 누적합니다**: "알려진 이력", "알려진 검증 공백"처럼
  이전 실행이나 사람이 남긴 고정 제목 섹션은 지우지 말고, 이번 실행에서 확인된
  내용을 그 섹션 안에 이어붙입니다. week05_load_kanas_past_conversations/manifest.md의
  "알려진 이력"이 여러 번의 재실행에 걸쳐 누적된 사례를 참고하세요. 스킬이 표준으로
  만드는 섹션(대상 구조/카테고리별 개수/캐시 상태 등)이 아닌, 사람이 직접 추가한
  섹션도 이번 세트와 무관해 보여도 임의로 지우지 않습니다.

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

검색 품질형(expected_hits 라벨)을 돌릴 때는 `--fixtures`를 추가합니다:

```bash
uv run python .claude/skills/assignment-stress-test/run_harness.py \
  --prompts stress_test_prompts/<stem>/retrieval_prompts.jsonl \
  --active-week <N> \
  --fixtures stress_test_prompts/<stem>/fixtures.jsonl \
  --out stress_test_prompts/<stem>/results_history/<타임스탬프>_retrieval.jsonl
```

harness가 격리 직후·실행 전에 fixture를 심고, fixture_id ↔ 발급된 id 매핑을
`--out` 옆 `fixture_map_<stem>.json`에 남깁니다. fixture 없이 검색 품질형을
돌리면 격리 DB가 비어 있어 전부 "빈 결과"가 나오니 의미가 없습니다 — 반드시
함께 줄 것.

집계할 때는 그 fixture_map을 `--fixture-map`으로 넘깁니다 (id는 실행마다 새로
발급되므로 **반드시 같은 실행의 map**을 써야 하고, `--previous` 회귀 비교 시엔
이전 실행의 map을 `--previous-fixture-map`으로 따로 줍니다):

```bash
uv run python .claude/skills/assignment-stress-test/aggregate_results.py \
  --prompts stress_test_prompts/<stem>/retrieval_prompts.jsonl \
  --results stress_test_prompts/<stem>/results_history/<이번>.jsonl \
  --fixture-map stress_test_prompts/<stem>/results_history/fixture_map_<이번>.json \
  --previous stress_test_prompts/<stem>/results_history/<이전>.jsonl \
  --previous-fixture-map stress_test_prompts/<stem>/results_history/fixture_map_<이전>.json
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
- **검색 품질 리포트 해석** (expected_hits 라벨이 있을 때 자동으로 붙는 섹션):
  - recall/precision/MRR/위반 카운트는 전부 id 값 스캔 기반 **결정론 계산**입니다
    (fixture_map의 id ↔ tool_result 문자열 대조; 과거 마커 방식 결과도 하위호환).
    여기까지는 AI 판단이 개입하지 않습니다.
  - recall 실패를 버그로 단정하기 전에 확인할 것: ① tool의 top_k 기본값이
    기대 개수보다 작지 않은지(라벨 설계 오류), ② agent가 검색 query를 어떻게
    바꿔 넣었는지(events의 tool_call arguments 확인 — 검색 자체는 정상인데
    query 재작성이 문제인 경우가 흔함), ③ 임베딩 vs LIKE 검색 특성(SQLite
    LIKE는 동의어를 못 잡는 게 정상).
  - "빈 결과가 정답" 위반은 임베딩 검색이 관련도 컷 없이 top_k를 무조건
    채우는 특성 때문에 자주 납니다 — tool 버그가 아니라 관련도 임계값 설계
    이슈로 분류하세요.
  - **AI(LLM-judge) 판단은 마지막 층만**: 최종 answer가 검색 결과를 실제
    근거로 썼는지(faithfulness), 검색에 없는 내용을 지어냈는지. 이 판단으로
    케이스를 기각할 때는 근거를 라벨 오류 / 의도된 동작 / 진짜 버그 중
    하나로 분류해 명시합니다.

### 6.5단계 — 1차 실행 후 라벨 재검토 (신규 프롬프트 세트는 필수)

새로 만든 프롬프트 세트의 첫 실행 결과는 "코드 검증"이 아니라 **"라벨 검증"**
으로 먼저 읽습니다. 라벨도 생성물이라 첫 샷에 틀릴 수 있기 때문입니다
(week04 실전에서 10개 중 1개가 라벨 오류였습니다).

1. 모든 불일치/실패를 라벨 오류 / 의도된 동작 / 진짜 버그로 분류합니다.
2. 라벨 오류로 판정한 건은 4단계 규칙대로 `reason`에 이력을 남기고 고친 뒤,
   **고친 라벨로 기존 결과를 재집계**해서(재실행 불필요 — 집계는 결정론)
   깨끗한 기준선을 만듭니다.
3. 기각률이 비정상적으로 높으면(예: 불일치의 절반 이상을 라벨 오류로 기각)
   자기채점 편향을 의심하고, 기각 근거를 사용자에게 보여주고 확인받습니다.
4. 이 과정에서 발견한 새 함정 패턴은 이 문서의 해당 절에 추가합니다 —
   함정이 문서에 쌓여야 다음 cold run의 첫 샷 품질이 올라갑니다.

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
- 검색 품질형 프롬프트의 캐시 판단에는 tool 시그니처 해시에 **fixture 세트
  해시**(fixtures.jsonl 전체의 sha256)를 결합합니다 — fixture가 바뀌면 검색
  품질형만 무효화되고 라우팅형 캐시는 유지됩니다. manifest에 `fixtures_hash`와
  임베딩 backend 정보(모델명)를 함께 기록하세요. 임베딩 모델이 바뀌면 검색
  점수 변화가 회귀가 아니라 환경 변화일 수 있어 구분이 필요합니다.
- `stress_test_prompts/<stem>/prompts.jsonl`, `retrieval_prompts.jsonl`,
  `fixtures.jsonl`, `manifest.json`, `manifest.md`는
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
