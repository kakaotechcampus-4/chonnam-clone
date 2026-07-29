# Week 05 MCP 기반 과거 대화·일정 조회 구현 계획

## 1. 목표

Week 05의 핵심 목표는 **Agent 코드와 외부 DB 접근 권한을 분리**하는 것이다.

Agent는 외부 SQLite의 테이블 구조를 알 필요가 없고 SQL도 직접 작성하지 않는다.
대신 MCP server가 공개한 정해진 tool 인터페이스만 MCP client를 통해 호출한다.

```text
사용자 요청
  ↓
LangChain Agent
  ↓ 정해진 tool 인터페이스만 사용
Week 05 wrapper
  ↓ MCP client 호출
MCP server
  ↓ SQL 실행 권한 보유
외부 SQLite
```

실무에서는 MCP server가 별도 프로세스나 서비스에서 DB 접근 권한을 가지고,
Agent는 client로서 tool만 호출한다. 이 프로젝트에서도
`mcp_server/sqlite_mcp_server.py`가 외부 SQLite 접근을 담당하고,
`student_parts/week05_load_kanas_past_conversations.py`는 LangChain `@tool`
wrapper를 제공한다.

이번 주에는 최종 자연어 답변만 확인하지 않는다.
Agent가 system prompt에서 지시한 순서대로 tool을 선택했는지 trace로 확인하고,
해당 호출 순서를 테스트의 `assert`로 강제하는 것까지 구현 범위에 포함한다.

## 2. 구현 범위와 책임 경계

### 수정 대상

- `student_parts/week05_load_kanas_past_conversations.py`
- `student_parts/prompts/week05.py`
- Week 05 동작을 검증할 테스트 파일

### 수정하지 않을 대상

- `mcp_server/sqlite_mcp_server.py`
- `fixed/external_people_store.py`

MCP server와 외부 store는 이미 SQL 실행과 정규화를 담당한다.
Week 05 wrapper에는 SQL, 테이블 지식, 중복 정규화 로직을 추가하지 않는다.

### 메인 과제

- `_personal_schedules_for_current_scope`
- `_collect_member_schedules`
- `search_previous_conversations`
- `load_conversation_messages`
- `extract_schedules_from_history`
- `list_shared_schedules`
- `collect_member_schedules`
- `week05_prompt_parts`
- 직접 tool 계약 테스트
- Agent tool 호출 순서 trace 테스트

### 추가 과제

- `create_shared_schedule`
- `delete_shared_schedule`

추가 과제를 구현하지 않는 경우에는 미구현 tool이 Agent에게 노출되지 않도록
`week05_tools()`에서 두 함수를 제거한다.

## 3. MCP wrapper 구현

### 3.1 `search_previous_conversations`

외부 과거 대화 중 사용자 요청과 관련된 후보만 제한적으로 검색한다.
Agent는 이 결과에서 원문 조회에 사용할 `conversation_id`를 얻는다.

구현 형태:

```python
return call_mcp_tool_sync(
    "search_previous_conversations",
    {
        "query": query,
        "member_names": member_names,
        "limit": limit,
    },
)
```

구현 원칙:

- 직접 SQL을 작성하지 않는다.
- 멤버 이름을 wrapper에서 다시 정규화하지 않는다.
- MCP가 반환한 JSON 문자열을 그대로 반환한다.
- `limit`으로 검색 결과의 범위를 제한한다.

### 3.2 `load_conversation_messages`

검색 결과에서 선택한 `conversation_id` 하나에 속한 전체 메시지를 시간순으로
불러온다. 일정 추출 결과가 애매하거나 사용자가 원문 근거를 요청했을 때만
선택적으로 사용한다.

구현 형태:

```python
payload = call_external_tool_payload(
    "load_conversation_messages",
    {"conversation_id": conversation_id},
)
return json_payload(payload)
```

다음 정보를 가공하거나 순서를 바꾸지 않고 보존한다.

- `sender`
- `content`
- `created_at`
- 메시지의 시간순 배열

### 3.3 검색 tool과 로드 tool의 경계

| Tool | 목적 | 조회 범위 |
| --- | --- | --- |
| `search_previous_conversations` | 관련 대화 후보 검색 | 여러 대화의 제한된 검색 결과 |
| `load_conversation_messages` | 선택한 대화의 원문 확인 | 하나의 `conversation_id`에 속한 전체 메시지 |

검색 tool은 필요한 후보만 좁히는 최소 권한 인터페이스다.
로드 tool은 외부 DB 전체를 읽는 기능이 아니라, 검색 결과에서 선택한 특정 대화
하나의 메시지를 모두 읽는 기능이다.

Agent가 처음부터 load tool을 호출하거나 관련 없는 대화를 읽지 않도록
system prompt와 trace 테스트에서 이 경계를 검증한다.

### 3.4 `extract_schedules_from_history`

외부 멤버와 날짜 범위에 맞는 busy-time을 추출한다. 현재 수업 fixture에서는
실시간 자연어 추출 대신 MCP server가 seed된 `external_schedules` 테이블을
조회한다.

구현 형태:

```python
return call_mcp_tool_sync(
    "extract_schedules_from_history",
    {
        "member_names": member_names,
        "date_from": date_from,
        "date_to": date_to,
    },
)
```

구현 원칙:

- 이름과 날짜 정규화는 MCP/store 경계에 맡긴다.
- wrapper에서 동일한 정규화를 반복하지 않는다.
- 일정 `rows`와 `schedule_summary`를 보존한다.

### 3.5 `list_shared_schedules`

과거 대화에서 일정을 추출하는 것과 별개로, 공유 일정 저장소에 이미 등록된
row를 조회한다.

구현 형태:

```python
return call_mcp_tool_sync(
    "list_shared_schedules",
    {
        "member_names": member_names,
        "date_from": date_from,
        "date_to": date_to,
        "source_conversation_id": source_conversation_id,
        "limit": limit,
    },
)
```

다음 값을 유지한다.

- `rows`
- `schedule_summary`
- `schedule_id`
- `source_conversation_id`

이 tool은 Week 06 Kana 하위 Agent에서도 재사용한다.

### 3.6 추가 과제: 공유 일정 생성과 삭제

`create_shared_schedule`은 다음 MCP tool에 모든 입력을 전달한다.

```python
call_mcp_tool_sync("create_shared_schedule", args)
```

`delete_shared_schedule`은 다음 MCP tool에 삭제 식별자를 전달한다.

```python
call_mcp_tool_sync("delete_shared_schedule", args)
```

동기화와 이후 삭제를 위해 다음 식별자를 보존한다.

- `schedule_id`
- `source_conversation_id`

## 4. 일정 근거 추적성

학습 개념상 일정 추출 결과에는 다음 정보가 남아야 한다.

- `conversation_id`
- `member`
- `date_hint`
- `start_time`
- `source`: 사람이 다시 확인할 수 있는 원문 근거

현재 프로젝트의 MCP 계약은 다음 필드명을 사용한다.

| 학습 개념 | 현재 MCP 필드 | 처리 방침 |
| --- | --- | --- |
| `conversation_id` | `source_conversation_id` | 원본 대화 참조로 보존 |
| `member` | `member_name` | 현재 표준 필드명 유지 |
| `date_hint` | `date` | store가 정규화한 ISO 날짜 유지 |
| `start_time` | `start_time` | 그대로 유지 |
| `source` | 일정 row에 직접 포함되지 않음 | 필요할 때 원본 메시지를 load |

현재 MCP server는 일정 row에 원문 전체를 복사하지 않고
`source_conversation_id`를 제공한다. 따라서 다음 연결로 원문 근거를 추적한다.

```text
일정 row.source_conversation_id
  ↓
load_conversation_messages(conversation_id)
  ↓
sender/content/created_at 원문 확인
```

이 방식을 사용하면 일정 row마다 원문을 중복 저장하지 않으면서도 사람이 원본을
확인할 수 있다. 원문 출력이 필요한 요청에서는 load 결과의 `content`를
`source` 근거로 사용한다.

검증 항목:

- 외부 일정 row의 `source_conversation_id`가 유지되는가?
- 원문 확인이 필요한 경우 해당 ID로 load tool을 호출하는가?
- load 결과의 `content`와 `created_at`이 보존되는가?
- 근거가 없는 일정을 Agent가 임의로 생성하지 않는가?

## 5. 개인 일정 수집

### 5.1 `_personal_schedules_for_current_scope`

다음 두 출처에서 내 일정을 가져온다.

1. Week 03 이후 `AppSQLiteStore`에 저장된 일정
2. `PERSONAL_SCHEDULES`에 남아 있는 현재 대화의 임시 일정

구현 순서:

1. `current_session_scope()`로 현재 대화 범위를 구한다.
2. `AppSQLiteStore(CONFIG.app_db_path).list_schedules(...)`로 저장 일정을 조회한다.
3. `PERSONAL_SCHEDULES`에서 현재 scope와 같은 일정만 선택한다.
4. SQLite에 이미 저장된 임시 일정은 제외한다.
5. DB 일정과 남은 임시 일정을 합쳐 반환한다.

중복은 `schedule_id` 또는 `id`를 기준으로 제거한다.

검증 항목:

- 다른 대화 scope의 임시 일정이 섞이지 않는다.
- SQLite에 저장된 일정과 임시 일정이 중복되지 않는다.
- 일정이 없을 때 빈 배열을 반환한다.

## 6. 내 일정과 외부 busy-time 통합

### 6.1 `_collect_member_schedules`

Week 05의 핵심 병합 함수다.

처리 순서:

1. 외부 멤버 이름을 정규화한다.
2. 조회 날짜 범위를 정규화한다.
3. `extract_schedules_from_history` MCP tool을 호출한다.
4. 반환된 JSON 문자열을 `json.loads()`로 파싱한다.
5. 내 일정을 `_structured_request_from_schedule_row()`로 읽는다.
6. 내 일정과 외부 일정을 같은 row 구조로 맞춘다.
7. 모든 row를 하나의 배열로 합친다.
8. `external_schedule_summary()`로 전체 요약을 만든다.

표준 row 구조:

```python
{
    "member_name": "나 또는 외부 멤버",
    "title": "일정 제목",
    "date": "YYYY-MM-DD",
    "start_time": "HH:MM",
    "end_time": "HH:MM 또는 미정",
    "notes": "...",
}
```

Week 06 소비 코드가 사용하는 위 여섯 개 필드는 항상 유지한다.
외부 일정에 존재하는 `source_conversation_id`도 근거 추적을 위해 추가로 보존한다.

### 6.2 `collect_member_schedules`

Agent가 호출하는 공개 wrapper다.

```python
personal_schedules = _personal_schedules_for_current_scope()

payload = _collect_member_schedules(
    member_names=member_names,
    date_from=date_from,
    date_to=date_to,
    personal_schedules=personal_schedules,
)

return json_payload(payload)
```

반환 형태:

```python
{
    "rows": [...],
    "schedule_summary": "...",
}
```

Week 05는 회의 시간 판단에 필요한 busy-time을 수집하는 데까지 담당한다.
여러 사람의 최종 공통 가능 시간을 계산하는 것은 Week 06의 책임이다.

## 7. Week 05 프롬프트 분리와 누적

### 7.1 기존 프롬프트 구조 유지

Week 01~04와 마찬가지로 Week 05 전용 prompt 문장을 Agent 구현 파일 안에
직접 길게 작성하지 않는다. 새 파일인 `student_parts/prompts/week05.py`에
Week 05 정책 조각을 상수로 분리하고,
`week05_load_kanas_past_conversations.py`에서는 필요한 상수만 import한다.

```text
student_parts/
├── prompts/
│   ├── common.py
│   ├── week01.py
│   ├── week02.py
│   ├── week03.py
│   ├── week04.py
│   └── week05.py
└── week05_load_kanas_past_conversations.py
```

`prompts/week05.py`에는 Week 05에서 새로 추가되는 책임만 둔다.

- Agent와 외부 DB의 MCP 권한 경계
- 외부 대화 검색과 일정 추출의 호출 순서
- 선택적인 원문 load 조건
- 일정의 원본 대화 추적 규칙
- 개인 일정과 외부 busy-time 수집 규칙
- Week 05의 현재 기능 범위

다음과 같은 이전 주차 정책은 Week 05 파일에서 반복하지 않는다.

- Nana의 정체성과 답변 언어
- 상대 날짜 해석과 날짜·시간 형식
- 사용자가 말하지 않은 값의 추측 금지
- Week 01 개인 일정 CRUD 규칙
- Week 02 구조화 출력 규칙
- Week 03 SQLite 저장·수정·삭제 규칙
- Week 04 개인 참고자료와 대화 RAG 규칙

이 정책들은 `week04_prompt_parts()`를 통해 이미 누적된다. 같은 내용을
Week 05 상수에 복사하면 prompt가 길어지고, 나중에 이전 정책을 수정했을 때
서로 다른 문장이 남을 수 있으므로 중복 작성하지 않는다.

### 7.2 `prompts/week05.py` 구성

Week 05 전용 prompt는 책임별로 나눠 다음과 같이 구성한다.

```python
WEEK05_MCP_BOUNDARY_PROMPT = """
외부 멤버의 과거 대화와 공유 일정은 MCP tool을 통해서만 조회한다.
직접 SQL을 작성하거나 외부 SQLite의 테이블 구조와 조회 결과를 추측하지 않는다.
개인 참고자료와 앱 내부 기록에는 이전 주차 tool을 사용하고,
외부 멤버 데이터에만 Week 05 MCP tool을 사용한다.
"""

WEEK05_HISTORY_WORKFLOW_PROMPT = """
외부 멤버의 과거 일정이나 busy-time을 조회할 때는
search_previous_conversations를 먼저 호출하고,
extract_schedules_from_history를 두 번째로 호출한다.
load_conversation_messages는 사용자가 원문을 요구하거나
추출된 일정의 근거를 확인해야 할 때만 선택적으로 호출한다.
load_conversation_messages를 검색보다 먼저 호출하지 않는다.
"""

WEEK05_TRACEABILITY_PROMPT = """
외부 일정의 source_conversation_id를 원본 대화 식별자로 보존한다.
원문 확인이 필요하면 그 ID로 load_conversation_messages를 호출하고,
반환된 sender, content, created_at을 근거로 사용한다.
근거가 없으면 일정이나 원문을 지어내지 않는다.
"""

WEEK05_SCHEDULE_COLLECTION_PROMPT = """
내 일정과 외부 멤버의 busy-time을 함께 확인하는 요청에는
collect_member_schedules를 사용한다.
tool이 반환한 rows와 schedule_summary를 근거로 답하고,
Week 05에서는 여러 사람의 최종 공통 가능 시간을 임의로 확정하지 않는다.
"""

WEEK05_SCOPE_PROMPT = """
현재 실행 주차는 Week 05다.
이전 주차의 개인 일정, SQLite 저장, RAG 정책은 계속 적용하며,
Week 05에서는 외부 멤버의 과거 대화와 공유 일정 조회가 새로 허용된다.
여러 사람의 최종 회의 시간 선택은 Week 06 범위다.
"""
```

상수의 실제 문장은 구현 과정에서 tool 계약과 테스트 시나리오에 맞춰 다듬되,
각 상수의 책임은 섞지 않는다.

### 7.3 이전 scope prompt와의 우선순위

`week04_prompt_parts()`에는 다음과 같은 Week 04 범위 제한이 이미 포함되어 있다.

```text
외부 멤버 일정 조율은 아직 Week 4 범위가 아니다.
```

이 문장은 Week 04 시점의 설명이므로 Week 05에서 그대로 누적되면 새 기능과
충돌할 수 있다. `WEEK05_SCOPE_PROMPT`는 목록의 마지막에 배치하고 다음을
명시해 현재 주차 정책이 이전 주차의 과거 범위 설명보다 우선하도록 한다.

- 현재 실행 주차가 Week 05라는 점
- 외부 멤버 대화와 일정 조회가 Week 05에서 허용된다는 점
- 최종 공통 시간 선택만 Week 06 범위라는 점

이전 주차의 기능 정책 자체는 유지하고, 이미 지난 주차의 scope 제한만
Week 05 scope가 확장한다.

### 7.4 `week05_prompt_parts()` 누적 방식

Agent 파일에서 Week 05 prompt 상수를 import한다.

```python
from student_parts.prompts.week05 import (
    WEEK05_HISTORY_WORKFLOW_PROMPT,
    WEEK05_MCP_BOUNDARY_PROMPT,
    WEEK05_SCHEDULE_COLLECTION_PROMPT,
    WEEK05_SCOPE_PROMPT,
    WEEK05_TRACEABILITY_PROMPT,
)
```

그다음 `week05_prompt_parts()`는 이전 주차 prompt를 그대로 누적하고,
Week 05의 새 정책만 뒤에 추가한다.

```python
def week05_prompt_parts() -> list[str]:
    """1~5주차 system prompt 조각을 누적합니다."""

    return [
        *week04_prompt_parts(),
        WEEK05_MCP_BOUNDARY_PROMPT,
        WEEK05_HISTORY_WORKFLOW_PROMPT,
        WEEK05_TRACEABILITY_PROMPT,
        WEEK05_SCHEDULE_COLLECTION_PROMPT,
        WEEK05_SCOPE_PROMPT,
    ]
```

최종 prompt의 구성은 다음과 같다.

```text
Week 01~03 공통·개인 일정·SQLite 정책
  ↓
Week 04 RAG와 출처 선택 정책
  ↓
Week 05 MCP 권한 경계
  ↓
Week 05 외부 대화 workflow
  ↓
Week 05 근거 추적과 일정 수집
  ↓
Week 05 현재 scope
```

`week05_system_prompt()`는 지금처럼 `join_system_prompt()`를 호출하며,
프롬프트 조각의 공백 정리와 결합만 담당한다.

### 7.5 프롬프트 구성 테스트

Agent 실행 테스트와 별도로 prompt 자체의 조합을 검증한다.

- `week05_prompt_parts()` 앞부분이 `week04_prompt_parts()`와 같은 순서인가?
- Week 05 전용 상수가 각각 한 번만 포함되는가?
- `WEEK05_SCOPE_PROMPT`가 마지막 조각인가?
- 최종 prompt에 `search_previous_conversations`가 `extract_schedules_from_history`
  보다 먼저 언급되는가?
- load가 선택 사항이며 검색 이후에만 호출된다고 명시되는가?
- SQL 직접 작성 금지가 포함되는가?
- Week 04 전용 상수를 Week 05 파일에 복사하지 않았는가?

예시:

```python
parts = week05_prompt_parts()
week04_parts = week04_prompt_parts()

assert parts[:len(week04_parts)] == week04_parts
assert parts[-1] == WEEK05_SCOPE_PROMPT
assert parts.count(WEEK05_HISTORY_WORKFLOW_PROMPT) == 1

prompt = week05_system_prompt()
assert prompt.index("search_previous_conversations") < prompt.index(
    "extract_schedules_from_history"
)
```

## 8. System prompt로 tool 호출 순서 강제

Week 04까지는 Agent가 상황에 맞게 tool을 비교적 자유롭게 선택했다.
Week 05에서는 외부 대화와 일정 조회에 대해 정해진 workflow를 따르도록
`prompts/week05.py`의 `WEEK05_HISTORY_WORKFLOW_PROMPT`에 호출 순서를 명시한다.

추가할 핵심 지침:

```python
(
    "외부 멤버의 과거 일정이나 busy-time을 조회할 때는 "
    "search_previous_conversations를 먼저 호출한다. "
    "그다음 extract_schedules_from_history를 두 번째로 호출한다. "
    "load_conversation_messages는 일정 근거가 불분명하거나 "
    "사용자가 원문 확인을 요청한 경우에만 선택적으로 호출한다. "
    "load_conversation_messages를 search_previous_conversations보다 먼저 호출하지 않는다. "
    "직접 SQL을 작성하거나 외부 DB 구조를 추측하지 않는다."
)
```

기본 workflow:

```text
1. search_previous_conversations
2. extract_schedules_from_history
3. load_conversation_messages — 원문 확인이 필요할 때만
4. 최종 답변
```

일정 수집 경로는 다음 두 가지로 구분한다.

```text
외부 대화 근거 탐색:
search → extract → optional load

내 일정과 외부 busy-time 통합:
collect_member_schedules
```

`collect_member_schedules` 내부에서 이미 외부 일정 MCP 호출을 수행하므로,
Agent가 동일한 수집 작업을 불필요하게 중복 호출하지 않도록 prompt에 역할을
명확히 설명한다.

## 9. 직접 Tool 테스트

LLM Agent 테스트 전에 각 함수의 입력·출력 계약을 단위 테스트한다.

### 9.1 Wrapper 위임 테스트

`call_mcp_tool_sync`를 mock하여 확인한다.

- 정확한 MCP tool 이름을 호출한다.
- 인자 이름과 값이 정확하다.
- MCP 결과 문자열을 그대로 반환한다.
- wrapper가 SQL이나 중복 정규화를 수행하지 않는다.

대상:

- `search_previous_conversations`
- `extract_schedules_from_history`
- `list_shared_schedules`
- 추가 과제를 구현할 경우 생성·삭제 wrapper

### 9.2 메시지 load 테스트

`call_external_tool_payload`를 mock하여 확인한다.

- `conversation_id`를 정확히 전달한다.
- 결과를 한글이 보존되는 JSON 문자열로 반환한다.
- `sender`, `content`, `created_at`과 메시지 순서를 유지한다.

### 9.3 개인 일정 scope·중복 제거 테스트

다음 fixture를 준비한다.

- SQLite에 저장된 내 일정 1개
- 같은 ID를 가진 현재 scope의 임시 일정 1개
- 현재 scope의 아직 저장되지 않은 임시 일정 1개
- 다른 scope의 임시 일정 1개

기대 결과:

- SQLite 일정이 포함된다.
- 같은 ID의 임시 일정은 중복으로 포함되지 않는다.
- 현재 scope의 새 임시 일정은 포함된다.
- 다른 scope의 임시 일정은 제외된다.

### 9.4 전체 일정 병합 테스트

외부 MCP 응답을 mock하여 확인한다.

- `"나"`와 외부 멤버 일정이 같은 `rows` 배열에 들어간다.
- 모든 row에 표준 여섯 개 필드가 존재한다.
- 외부 row의 `source_conversation_id`가 보존된다.
- 날짜 범위 밖의 일정이 섞이지 않는다.
- `schedule_summary`가 생성된다.

## 10. Agent trace 호출 순서 테스트

이번 주 핵심 테스트는 최종 답변의 문구가 아니라 **tool 호출 순서**다.

공통 trace의 `events`에서 `tool_call`만 선택한다.

```python
tool_names = [
    event["tool_name"]
    for event in trace["events"]
    if event["event"] == "tool_call"
]
```

검색과 추출의 필수 순서를 검증한다.

```python
assert "search_previous_conversations" in tool_names
assert "extract_schedules_from_history" in tool_names

search_index = tool_names.index("search_previous_conversations")
extract_index = tool_names.index("extract_schedules_from_history")

assert search_index < extract_index
```

load tool이 호출된 경우에는 검색 이후인지 조건부로 검증한다.

```python
if "load_conversation_messages" in tool_names:
    load_index = tool_names.index("load_conversation_messages")
    assert search_index < load_index
```

정확한 workflow가 필요한 시나리오에서는 앞의 호출을 더 엄격하게 검증한다.

```python
assert tool_names[:2] == [
    "search_previous_conversations",
    "extract_schedules_from_history",
]
```

LLM은 실행마다 선택이 달라질 수 있으므로 단위 테스트에서는 fake 또는 stub
model로 tool-call 순서를 결정적으로 만들고, 실제 model 실행은 별도의 통합
검증으로 둔다.

### Trace 테스트 시나리오

#### 일반 외부 일정 조회

기대 순서:

```text
search_previous_conversations
→ extract_schedules_from_history
```

원문 요청이 없으므로 load는 필수가 아니다.

#### 원문 근거를 포함한 일정 조회

기대 순서:

```text
search_previous_conversations
→ extract_schedules_from_history
→ load_conversation_messages
```

load 결과에 `content`와 `created_at`이 있어야 한다.

#### 검색 결과가 없는 요청

- search tool은 호출한다.
- 임의의 `conversation_id`를 만들어 load하지 않는다.
- 근거가 없는 일정을 생성하지 않는다.

#### 내 일정과 외부 일정 통합

- `collect_member_schedules`를 호출한다.
- 결과에 `"나"`와 요청한 외부 멤버가 함께 존재한다.
- 모든 일정이 같은 row 구조를 사용한다.

## 11. 수동 통합 검증

실행:

```bash
./run.sh --week5
```

일반 일정 조회 예시:

```text
철수와 영희의 2026년 7월 7일부터 17일까지 바쁜 일정을 알려줘.
```

확인 항목:

- `search_previous_conversations`가 먼저 호출된다.
- `extract_schedules_from_history`가 그다음 호출된다.
- 원문 요청이 없다면 load를 불필요하게 호출하지 않는다.
- 일정에 멤버, 날짜, 시작·종료 시간이 있다.
- `source_conversation_id`가 유지된다.

원문 근거 조회 예시:

```text
철수의 7월 9일 일정과 그 일정이 언급된 원문도 보여줘.
```

기대 trace:

```text
search_previous_conversations
→ extract_schedules_from_history
→ load_conversation_messages
```

공유 일정 조회·수정 추가 과제를 구현한 경우에는 다음도 확인한다.

1. `create_shared_schedule`로 일정을 등록한다.
2. `list_shared_schedules` 결과에 해당 row가 나타나는지 확인한다.
3. `delete_shared_schedule`로 삭제한다.
4. 다시 조회했을 때 삭제된 row가 나타나지 않는지 확인한다.

## 12. 권장 구현 순서

1. `search_previous_conversations`
2. `load_conversation_messages`
3. `extract_schedules_from_history`
4. `list_shared_schedules`
5. `_personal_schedules_for_current_scope`
6. `_collect_member_schedules`
7. `collect_member_schedules`
8. `student_parts/prompts/week05.py`에 Week 05 전용 prompt 상수 작성
9. `week05_prompt_parts`에서 Week 04 prompt와 Week 05 상수 누적
10. prompt 구성·중복 방지 테스트
11. wrapper와 병합 로직 단위 테스트
12. Agent trace 순서 테스트
13. 추가 과제인 공유 일정 생성·삭제
14. `./run.sh --week5` 수동 통합 검증

## 13. 완료 기준

- [ ] Agent 코드에 SQL이 없다.
- [ ] 외부 DB 접근은 MCP tool을 통해서만 수행한다.
- [ ] Week 05 전용 정책은 `student_parts/prompts/week05.py`에 분리되어 있다.
- [ ] Week 01~04 정책을 Week 05 prompt 파일에 중복 작성하지 않는다.
- [ ] `week05_prompt_parts()`는 `week04_prompt_parts()` 뒤에 Week 05 정책만 추가한다.
- [ ] 현재 범위를 설명하는 `WEEK05_SCOPE_PROMPT`가 마지막에 배치된다.
- [ ] 검색과 전체 메시지 load의 역할이 분리되어 있다.
- [ ] `search → extract → optional load` 순서가 system prompt에 명시되어 있다.
- [ ] trace 테스트가 tool 호출 순서를 `assert`한다.
- [ ] 최종 자연어 답변만으로 성공 여부를 판단하지 않는다.
- [ ] 일정 row에 멤버, 날짜, 시작·종료 시간이 유지된다.
- [ ] `source_conversation_id`로 원문 대화를 추적할 수 있다.
- [ ] 원문 확인 시 메시지 `content`를 근거로 제공할 수 있다.
- [ ] SQLite 일정과 현재 scope의 임시 일정만 합쳐진다.
- [ ] SQLite 일정과 임시 일정의 중복이 제거된다.
- [ ] 내 일정과 외부 busy-time이 동일한 `rows` 구조로 반환된다.
- [ ] `schedule_summary`가 유지된다.
- [ ] 추가 과제를 생략하면 생성·삭제 tool도 목록에서 제거된다.
