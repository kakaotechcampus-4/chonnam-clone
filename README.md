# Kanana Schedule Agent

Kanana 강의용 일정 Agent 실습 프로젝트입니다. 학생들은 `student_parts/week01_wake_up_nana.py`부터 `student_parts/week06_kanamate_decides_schedule.py`까지 순서대로 열고, 각 파일 상단의 `[수강생 구현 가이드]`가 지정한 함수와 tool 본문을 직접 완성합니다.

처음 구조를 볼 때는 [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)를 먼저 읽고, 수업 흐름은 [CURRICULUM.md](CURRICULUM.md)를 기준으로 따라가면 됩니다.

## 실행

기본 Python 패키지 관리는 `uv`를 사용합니다.

```bash
cd kakao_clone_coding_projects_q
./run.sh --install
```

설치 후에는 아래 명령으로 Week 1 앱을 실행합니다.

```bash
./run.sh
```

명시적으로 주차를 선택할 수도 있습니다.

```bash
./run.sh --week1   # ~ --week6
```

`.env`는 repo 루트의 파일을 읽습니다. `.env.example`을 복사해 개인 키를 채워 넣으세요.

```bash
PROXY_TOKEN=여기에 api key 입력
CHAT_PROXY_URL=https://mlapi.run/4bbd0c4d-bf02-4e59-a635-457b1c30c56a/v1
EMBEDDING_PROXY_URL=https://mlapi.run/b54ff33e-6d14-42df-93f9-0f1132160ee8/v1
OPENAI_MODEL=openai/gpt-4.1-mini
OPENAI_EMBEDDING_MODEL=openai/text-embedding-3-small
KANANA_ACTIVE_WEEK=1
KANANA_USE_LLM=1
KANANA_LLM_ASSIST=1
```

`PROXY_TOKEN`이 없으면 프롬프트 기반 agent는 실행되지 않고 안내 메시지가 표시됩니다. 키를 넣으면 Week 1 agent가 prompt와 tool 목록을 보고 직접 tool을 고릅니다.

### Conda fallback

conda 환경이 필요한 경우 `environment.yml` 기반 runner를 사용할 수 있습니다.

```bash
./run.sh --conda --install
./run.sh --conda
```

## 주차별 명세

각 파일 상단의 `[N주차 수강생 구현 가이드]`가 원문 명세입니다. 아래는 그 명세의 요약입니다.

### Week 1 · `week01_wake_up_nana.py` — 개인 일정 CRUD tool

- 목표: Nana가 "내 일정 만들어줘/보여줘/지워줘" 요청을 받았을 때 LLM이 직접 고르는 LangChain tool 3개를 완성. 이 주차의 일정은 앱 DB에 저장하지 않는 현재 대화 전용 임시 메모리(`PERSONAL_SCHEDULES`).
- 구현 대상: `personal_create_schedule`, `personal_list_schedules`, `personal_delete_schedule`.
- 확인 포인트: 상세 trace에서 세 tool 중 어떤 tool이 호출됐는지, `created_schedule`/`schedules`/`deleted` payload가 기대한 모양인지.

### Week 2 · `week02_structure_natural_language_requests.py` — 자연어 → 구조화 요청

- 목표: 사용자의 한국어 자연어 요청이나 Week 1 tool이 만든 JSON payload를 앱이 읽을 수 있는 `StructuredRequest`/`StructuredRequestBatch`로 구조화. 아직 SQLite/RAG/외부 조율 흐름에는 저장하지 않음.
- 과제 구성: (메인) agent가 자연어·Week 1 JSON을 `StructuredRequestBatch`로 최종 반환하는 세로 슬라이스, (추가) 이 스키마를 Week 3 이상 저장/조율 흐름에서 재사용할 bridge 함수(`extract_structured_request`, `extract_schedule_request`).
- 구현 대상: `StructuredRequest` 스키마(kind/title/date/start_time/end_time/members/priority/reason/original_text), `week02_tools`, `week02_prompt_parts`, `week02_system_prompt`, `build_week02_agent`(response_format=StructuredRequestBatch).

### Week 3 · `week03_build_nanas_logbook.py` — SQLite 기록장

- 목표: Week 2의 `StructuredRequest`를 Pydantic 스키마로 검증해 SQLite에 저장하고, 다시 조회/수정/삭제. 여기서부터 Nana는 대화가 끝나도 남는 "기록장"을 가짐.
- 과제 구성: (메인) "저장 → 조회 → 새 대화에서도 유지"가 동작하는 최소 기록장 세로 슬라이스.
- 구현 대상: `save_structured_request`, `list_saved_requests`/`personal_list_saved_schedules`, `get_saved_request`, `personal_update_saved_schedule`, `personal_delete_saved_schedules`(단건/조건/`delete_all`). tool 호출 순서 규칙은 `WEEK03_TOOL_CALL_PROMPT`에 명시(개인 일정 생성 vs 할 일/리마인더 구분, 전체 조회 vs kind 지정 조회 등).

### Week 4 · `week04_retrieve_nanas_memory.py` — 출처별 RAG 검색

- 목표: "내가 적어 둔 참고자료", "SQLite 저장 기록", "앱에 저장된 채팅 발화"를 하나의 마법 검색 함수로 뭉치지 않고 데이터 출처별 tool로 분리해서 검색.
- 과제 구성: (메인) 개인 참고자료 추가 + 참고자료/SQLite 기록을 출처별로 검색하는 RAG 세로 슬라이스, (추가) 앱 대화 발화를 ChromaDB에 lazy sync해 검색하는 agentic RAG와 하위 호환 통합 검색.
- 구현 대상: `add_personal_reference`, `search_personal_references`(`PersonalReferenceStore`), `search_saved_requests`(`AppSQLiteStore`), `search_conversation_messages`(`ConversationRAGStore`). 각 tool 입력은 Pydantic `args_schema`로 검증, top_k/limit 보정은 `safe_limit()`.

### Week 5 · `week05_load_kanas_past_conversations.py` — 외부 MCP 대화/일정 wrapper

- 목표: 외부 SQLite/MCP 서버에 있는 Kana의 이전 대화와 공유 일정을 LangChain agent가 쓸 수 있게 감쌈. 학생이 직접 SQL을 쓰는 주차가 아니라, MCP tool을 호출하고 결과를 agent용 JSON으로 전달하는 wrapper를 만드는 주차.
- 과제 구성: (메인) 이전 대화 검색·로드 및 일정 추출 MCP wrapper + 공유 일정 조회(`list_shared_schedules`) + 내 일정·외부 멤버 busy-time을 합치는 `collect_member_schedules`(Week 6 하위 agent가 그대로 재사용). (추가) 공유 일정 등록/삭제(`create_shared_schedule`/`delete_shared_schedule`).
- 구현 대상: `search_previous_conversations`, `load_conversation_messages`, `extract_schedules_from_history`, `list_shared_schedules`, `collect_member_schedules`. MCP 호출은 `call_mcp_tool_sync`(=`call_local_mcp_tool_sync` 별칭) 사용, 실제 MCP tool 구현(`mcp_server/sqlite_mcp_server.py`)은 수정 대상 아님.

### Week 6 · `week06_kanamate_decides_schedule.py` — supervisor + Nana/Kana 위임

- 목표: "모든 기능을 한 agent가 처리"하지 않고 supervisor가 Nana(개인 일정/저장/RAG 담당)와 Kana(외부 대화/멤버 일정/그룹 시간 결정 담당) 하위 agent로 위임. supervisor가 직접 보는 tool은 `nana_agent`/`kana_agent` 두 개뿐.
- 과제 구성: (메인) 단일 agent 구조를 supervisor + Nana/Kana 하위 agent 구조로 나누는 뼈대 — 세 agent의 system prompt와 위임 wrapper tool 2개. (추가) 공통 가능 시간 후보 검증(`find_common_available_slots`)과 최종 시간 결정(`decide_final_slot`)까지 붙여 그룹 일정 조율 완성.
- 구현 대상: `NANA_AGENT_NAME`/`KANA_AGENT_NAME`/`SUPERVISOR_AGENT_NAME` 세 agent의 prompt, 위임 tool, `find_common_available_slots_payload`/`decide_final_slot_payload`(`fixed/schedule_decision.py`) 연동.

## 구현 확인

이 학생용 repo에는 자동 테스트 하네스가 포함되어 있지 않습니다. `./run.sh --weekN`으로 원하는 주차 앱을 실행한 뒤 채팅을 입력하고, 화면의 상세 trace에서 어떤 tool이 호출됐는지와 tool 결과 JSON에 어떤 값이 들어왔는지 확인하세요.

초기 배포 상태의 구현 대상 함수 본문에는 `# TODO`와 빈칸이 들어 있습니다. 함수를 완성하면 상세 trace에서 실제 결과 JSON을 확인할 수 있어야 합니다. 문제를 만났을 때의 원인 분석과 해결 과정은 `docs/troubleshooting/weekN.md`, 실제 대화로 검증한 eval 결과는 `docs/evals/weekN-tasks.md`에 주차별로 정리돼 있습니다.

## 패키지 관리

새 의존성의 기준 파일은 `pyproject.toml`과 `uv.lock`입니다. `requirements.txt`와 `environment.yml`은 기존 수강생 환경을 위한 fallback 파일입니다.

```bash
uv add "package-name>=1.0"
uv remove package-name
uv lock
```
