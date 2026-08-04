# Week 5 구현 계획 — Kana의 이전 대화와 팀원 일정 불러오기

> 대상 파일: `student_parts/week05_load_kanas_past_conversations.py`
>
> 이 문서는 Week 5 메인 과제와 후속 추가 과제의 구현 계획서다. 최초 구현에서는 메인 과제만
> 완료했고, 리뷰 대응 단계에서 추가 과제인 `create_shared_schedule`과
> `delete_shared_schedule` wrapper까지 확장한다.
> `student_parts_baseline/week04_retrieve_nanas_memory.py`와 `fixed/`,
> `mcp_server/` 아래의 제공 코드는 참고만 하고 수정하지 않는다.
>
> 구현과 검증을 모두 마친 뒤 변경 사항은 한 번에 커밋한다.

---

## 0. 목표와 핵심 흐름

Week 4까지 Nana는 앱 내부 SQLite와 개인 참고자료에서 사용자의 기록을 찾을 수 있었다.
Week 5에서는 외부 SQLite/MCP 서버에 저장된 Kana의 이전 대화와 팀원 일정을 agent가
사용할 수 있도록 얇은 wrapper tool을 완성한다.

```text
사용자 요청
  ├─ 팀원의 관련 과거 대화 찾기
  │    └─ search_previous_conversations
  │          └─ conversation_id 선택
  │                └─ load_conversation_messages
  │
  ├─ 과거 대화에서 팀원 busy-time 조회
  │    └─ extract_schedules_from_history
  │
  ├─ 외부 공유 일정 저장소 조회
  │    └─ list_shared_schedules
  │
  └─ 나와 팀원의 일정을 한 구조로 수집
       └─ collect_member_schedules
            ├─ AppSQLiteStore의 저장 일정
            ├─ 현재 대화의 미저장 Week 1 임시 일정
            └─ MCP의 외부 팀원 일정
```

핵심 원칙은 다음과 같다.

1. **직접 SQL을 작성하지 않는다.** 외부 데이터는 반드시 제공된 MCP 호출 helper를 통해 조회한다.
2. **정규화 책임을 중복하지 않는다.** 단순 wrapper는 MCP 서버에 인자를 그대로 전달하고,
   일정 통합 helper에서만 제공된 이름·날짜 정규화 helper를 사용한다.
3. **MCP 응답 계약을 보존한다.** 단순 wrapper는 서버의 JSON 문자열을 임의로 재구성하지 않는다.
4. **내 일정의 출처를 구분한다.** SQLite 영속 일정과 현재 대화의 임시 일정만 합치고,
   이미 SQLite에 저장된 임시 일정은 ID 기준으로 중복 제거한다.
5. **모든 일정 row를 같은 모양으로 맞춘다.**
   `member_name/title/date/start_time/end_time/notes` 필드를 유지한다.
6. **구현 단계에 맞는 tool만 agent에 노출한다.** 최초 구현에서는 미완성 추가 과제 wrapper를
   `week05_tools()`에서 제외하고, 후속 구현과 검증을 마친 뒤 두 tool을 노출한다.
7. **Week 6 책임을 앞당기지 않는다.** 이번 주차는 busy-time 수집까지 수행하고,
   여러 사람의 최종 회의 시간 선택이나 공통 빈 시간 계산은 구현하지 않는다.

---

## 1. 구현 범위

### 1.1 메인 과제

- 앱 내부 개인 일정 수집
  - `_personal_schedules_for_current_scope`
- 앱 일정 row를 `StructuredRequest`로 읽는 기존 bridge 활용
  - `_structured_request_from_schedule_row`
- 내 일정과 외부 멤버 일정 통합
  - `_collect_member_schedules`
  - `collect_member_schedules`
- 외부 이전 대화 검색
  - `search_previous_conversations`
- 특정 외부 대화 메시지 로드
  - `load_conversation_messages`
- 외부 대화 기반 일정 조회
  - `extract_schedules_from_history`
- 외부 공유 일정 저장소 조회
  - `list_shared_schedules`
- Week 1~5 누적 tool 목록 구성
  - `week05_tools`
- Week 5 tool 선택 규칙 추가
  - `week05_prompt_parts`

### 1.2 최초 구현에서 제외하고 후속 단계로 이동

- `create_shared_schedule`
- `delete_shared_schedule`
- 공유 일정 row 직접 생성·갱신·삭제
- 여러 사람의 공통 가능 시간 계산
- 최종 회의 시간 선택 및 그룹 일정 확정
- `fixed/` 또는 `mcp_server/` 제공 코드 수정
- `student_parts_baseline/` 정답 파일 수정

최초 구현에서는 추가 과제 함수와 입력 스키마를 starter 코드에 그대로 두고 구현하지 않는다.
미완성 함수가 실행 중 선택되지 않도록 `create_shared_schedule`과
`delete_shared_schedule`은 `week05_tools()`에서 제거하고, Week 5 prompt에도 공유 일정
생성·삭제를 지시하는 문구를 넣지 않는다. 후속 단계에서 두 wrapper를 구현하고 tool 목록과
prompt를 함께 확장하는 계획은 이 문서의 7절에서 다룬다.

---

## 2. 확인한 연동 지점과 API 계약

### 2.1 `call_mcp_tool_sync`

`fixed.mcp_client.call_local_mcp_tool_sync`의 별칭이다.

```text
call_mcp_tool_sync(tool_name: str, args: dict) -> str
```

- 로컬 MCP 서버를 stdio subprocess로 실행한다.
- 이름이 일치하는 MCP tool을 호출한다.
- 결과를 JSON 문자열로 반환한다.
- wrapper에서 직접 SQLite 파일을 열거나 SQL을 작성할 필요가 없다.

### 2.2 `call_external_tool_payload`

```text
call_external_tool_payload(tool_name: str, args: dict) -> dict
```

- MCP 결과 JSON 문자열을 파싱해 dict로 반환한다.
- 이번 과제에서는 `load_conversation_messages`가 이 helper를 사용한다.
- 반환 dict를 임의로 변형하지 않고 `json_payload()`로 다시 직렬화한다.

### 2.3 `AppSQLiteStore.list_schedules`

```text
list_schedules(
    limit=12,
    kind=None,
    date_from=None,
    date_to=None,
) -> list[dict]
```

반환 row의 주요 필드는 다음과 같다.

- `schedule_id`
- `request_id`
- `owner`
- `title`
- `date`
- `start_time`
- `end_time`
- `attendees`
- `source`
- `created_at`
- `request_kind`

`_personal_schedules_for_current_scope()`에서는 저장된 개인 일정 후보를 충분히 읽기 위해
명시적인 limit을 사용한다. 날짜 범위 필터는 이후
`_collect_member_schedules()`에서 요청 범위에 맞게 적용한다.

### 2.4 `PERSONAL_SCHEDULES`와 대화 범위

Week 1 임시 일정의 주요 필드는 다음과 같다.

- `id`
- `title`
- `date`
- `start_time`
- `end_time`
- `attendees`
- `created_at`
- `session_id`

`current_session_scope()`는 현재 agent 실행의 conversation ID를 반환하고,
직접 tool을 호출하는 경우 `DEFAULT_SESSION_SCOPE`를 반환한다.

임시 일정은 아래 조건을 모두 만족할 때만 개인 일정 후보에 포함한다.

1. `_schedule_scope(schedule) == current_session_scope()`
2. 같은 ID의 일정이 앱 SQLite에 아직 저장되지 않음

Week 1 임시 일정이 Week 3 저장 흐름을 거치면 임시 `id`가 SQLite의
`schedule_id`로 사용될 수 있다. 따라서 SQLite row의 `schedule_id`와 임시 row의
`id`를 비교해 동일 일정을 두 번 포함하지 않는다.

### 2.5 외부 MCP tool 응답

| MCP tool | 전달 인자 | 반환 payload 핵심 필드 |
|---|---|---|
| `search_previous_conversations` | `query`, `member_names`, `limit` | `ok`, `tool_name`, `rows` |
| `load_conversation_messages` | `conversation_id` | `ok`, `tool_name`, `rows` |
| `extract_schedules_from_history` | `member_names`, `date_from`, `date_to` | `ok`, `tool_name`, `rows`, `schedule_summary` |
| `list_shared_schedules` | `member_names`, `date_from`, `date_to`, `source_conversation_id`, `limit` | `ok`, `tool_name`, `rows`, `schedule_summary` |

`load_conversation_messages`의 `rows`는 `role/sender/content/created_at` 순서를
보존한 메시지 목록이다. 외부 일정 row는 다음 필드를 유지한다.

```text
member_name
title
date
start_time
end_time
notes
source_conversation_id
```

---

## 3. 함수별 구현 계획

### Step 1 — 현재 범위의 개인 일정 수집

#### `_personal_schedules_for_current_scope`

1. `AppSQLiteStore(CONFIG.app_db_path)`를 만든다.
2. `list_schedules(...)`로 앱 SQLite의 저장 일정을 읽는다.
3. SQLite row의 `schedule_id` 집합을 만든다.
4. `current_session_scope()`를 읽는다.
5. `PERSONAL_SCHEDULES` 중 현재 scope에 속하는 row만 고른다.
6. 임시 row의 `id`가 SQLite `schedule_id` 집합에 있으면 제외한다.
7. SQLite 저장 일정 뒤에 아직 저장되지 않은 현재 대화 임시 일정을 합쳐 반환한다.

보장할 동작:

- 다른 대화의 임시 일정은 섞이지 않는다.
- `session_id`가 없는 기존 직접 호출 row는 기본 scope에서만 보인다.
- SQLite로 승격된 Week 1 임시 일정은 한 번만 반환된다.
- 원본 `PERSONAL_SCHEDULES`를 수정하지 않는다.

### Step 2 — 내 일정과 외부 일정의 공통 row 계약

#### `_structured_request_from_schedule_row`

기존 함수는 SQLite 일정과 Week 1 임시 일정을 공통 `StructuredRequest`로 읽는 bridge로
그대로 사용한다.

- `title/date/start_time/end_time`을 일정 필드로 옮긴다.
- `attendees` 또는 `members`를 `members`로 읽는다.
- 누락된 제목은 이후 공통 row 생성 시 안전한 기본값으로 처리한다.

#### `_collect_member_schedules`

1. `normalize_external_member_names(member_names)`로 외부 멤버 이름을 정리한다.
2. `normalize_external_schedule_date_bounds(...)`로 날짜에서 ISO datetime의 시간 부분을 제거한다.
3. 전달받은 개인 일정들을 `StructuredRequest`로 읽는다.
4. 개인 일정 중 정규화된 `date_from <= date <= date_to` 범위에 포함되는 row만 남긴다.
5. 개인 일정 각각을 아래 공통 형태로 변환한다.

```text
{
  "member_name": "나",
  "title": ...,
  "date": ...,
  "start_time": ...,
  "end_time": ...,
  "notes": "내 일정"
}
```

6. 다음 인자로 `extract_schedules_from_history` MCP tool을 직접 호출한다.

```text
{
  "member_names": 정규화된 외부 멤버 이름,
  "date_from": 정규화된 시작일,
  "date_to": 정규화된 종료일
}
```

7. MCP 결과 문자열을 `json.loads(...)`로 파싱하고 `rows`를 읽는다.
8. 개인 일정 row 뒤에 외부 일정 row를 합친다.
9. 전체 rows를 `external_schedule_summary(rows)`에 전달해 설명용 요약을 만든다.
10. `ok`, `tool_name`, 정규화된 조회 조건, `rows`, `schedule_summary`를 담은 dict를 반환한다.

외부 MCP row의 필드를 다시 만들거나 제거하지 않는다. 이를 통해
`source_conversation_id`와 향후 확장 필드도 보존한다.

### Step 3 — 외부 이전 대화 검색 wrapper

#### `search_previous_conversations`

1. 아래 인자 dict를 만든다.

```text
{
  "query": query,
  "member_names": member_names,
  "limit": limit
}
```

2. `call_mcp_tool_sync("search_previous_conversations", args)`를 호출한다.
3. MCP 결과 문자열을 그대로 반환한다.

이 wrapper에서는 멤버 이름을 별도로 정규화하지 않는다. 이름 정규화는 외부
store/MCP 경계에서 이미 수행되므로 중복 변환하지 않는다.

### Step 4 — 특정 외부 대화 메시지 로드 wrapper

#### `load_conversation_messages`

1. `call_external_tool_payload(
   "load_conversation_messages",
   {"conversation_id": conversation_id},
   )`를 호출한다.
2. payload의 `rows`를 정렬하거나 메시지를 합치지 않는다.
3. dict 전체를 `json_payload()`로 직렬화해 반환한다.

이 과정에서 `sender/content/created_at`과 MCP 서버가 보장한 메시지 순서를 보존한다.

### Step 5 — 외부 멤버 busy-time wrapper

#### `extract_schedules_from_history`

1. `member_names`, `date_from`, `date_to`를 인자 dict에 넣는다.
2. `call_mcp_tool_sync("extract_schedules_from_history", args)`를 호출한다.
3. MCP 결과 문자열을 그대로 반환한다.

이 wrapper에서도 이름과 날짜를 다시 정규화하지 않는다. MCP 서버가 반환하는
`rows`와 `schedule_summary`를 그대로 agent에 전달한다.

### Step 6 — 공유 일정 조회 wrapper

#### `list_shared_schedules`

1. 입력 스키마의 모든 필드를 빠짐없이 인자 dict에 넣는다.
   - `member_names`
   - `date_from`
   - `date_to`
   - `source_conversation_id`
   - `limit`
2. `call_mcp_tool_sync("list_shared_schedules", args)`를 호출한다.
3. MCP 결과 문자열을 그대로 반환한다.

필터가 모두 비어 있으면 MCP 서버가 제공하는 기본 실습용 공유 일정을 반환하도록
`None` 값을 임의로 제거하거나 다른 기본 필터를 추가하지 않는다.

### Step 7 — 통합 일정 수집 tool

#### `collect_member_schedules`

1. `_personal_schedules_for_current_scope()`로 내 일정 후보를 가져온다.
2. 요청받은 `member_names/date_from/date_to`와 개인 일정 목록을
   `_collect_member_schedules(...)`에 전달한다.
3. helper가 반환한 dict를 `json_payload()`로 직렬화한다.
4. 한글 이름과 요약이 `\uXXXX`로 이스케이프되지 않은 JSON 문자열인지 확인한다.

이 tool은 조회 전용이다. 공유 일정 저장소를 생성·수정·삭제하지 않는다.

### Step 8 — Week 5 tool 목록

#### `week05_tools`

최초 구현에서는 `week04_tools()` 위에 아래 메인 과제 tool만 누적한다.

```text
search_previous_conversations
load_conversation_messages
extract_schedules_from_history
list_shared_schedules
collect_member_schedules
```

최초 구현에서는 다음 추가 과제 tool을 제외한다. 후속 단계에서는 구현과 검증을 마친 뒤 다시
포함한다.

```text
create_shared_schedule
delete_shared_schedule
```

중복 이름이 없고 Week 1~4 tool이 그대로 유지되는지도 확인한다.

### Step 9 — Week 5 system prompt

#### `week05_prompt_parts`

`*week04_prompt_parts()` 뒤에 Week 5 규칙을 추가한다.

- 외부 팀원의 과거 대화가 필요한 질문:
  1. `search_previous_conversations`로 관련 대화를 찾는다.
  2. 검색 row의 `conversation_id`를 사용해 `load_conversation_messages`를 호출한다.
- 특정 팀원들의 과거 일정만 필요하면
  `extract_schedules_from_history`를 사용한다.
- 나와 팀원들의 busy-time을 함께 비교해야 하면
  `collect_member_schedules`를 사용한다.
- 공유 저장소에 이미 등록된 일정을 직접 확인해야 하면
  `list_shared_schedules`를 사용한다.
- 검색 query는 사용자의 문장 전체가 아니라 관련 대화를 찾을 수 있는 짧은 핵심 명사나 구로 만든다.
- 날짜 범위는 `current_app_date_iso()`를 기준으로 구체적인 ISO 날짜로 계산한다.
- tool 결과가 비어 있으면 대화나 일정이 있다고 추측하지 않는다.
- `rows`와 `schedule_summary`를 근거로 답하고, 조회되지 않은 시간은 임의로 만들지 않는다.
- Week 5에서는 최종 회의 시간이나 공통 빈 시간을 계산·확정하지 않는다.
- 최초 구현에서는 공유 일정 직접 생성·삭제 tool을 사용하지 않는다.

---

## 4. 오류·경계 조건

### 빈 입력과 빈 결과

- `member_names=None`
  - 대화 검색과 공유 일정 조회 wrapper에서는 MCP 의미를 보존해 그대로 전달한다.
- `member_names=[]`
  - 외부 store가 “명시된 멤버 없음”으로 해석해 빈 rows를 반환하도록 그대로 둔다.
- 검색 결과 없음
  - `{"rows": []}` 계약을 오류로 바꾸지 않는다.
- 개인 일정 없음
  - 외부 일정만 정상적으로 반환한다.
- 외부 일정 없음
  - 개인 일정만 반환하고 요약도 해당 rows를 기준으로 만든다.
- 양쪽 일정 모두 없음
  - `rows=[]`와 빈 결과를 설명하는 `schedule_summary`를 반환한다.

### 날짜 처리

- `2026-07-07T10:00:00` 같은 값은 제공된 날짜 정규화 helper를 통해
  `2026-07-07`로 만든다.
- wrapper 단계에서는 날짜 형식을 중복 변환하지 않는다.
- 개인 일정의 날짜가 없거나 조회 범위 밖이면 통합 rows에서 제외한다.

### MCP 실패

- MCP tool 이름 오류, subprocess 실패, 잘못된 JSON은 조용히 빈 결과로 바꾸지 않는다.
- 예외를 숨기지 않아 trace에서 실제 실패 원인을 확인할 수 있게 한다.
- 이번 과제 범위에서 별도의 재시도, fallback SQL, 외부 DB 직접 접근은 추가하지 않는다.

---

## 5. 검증 계획

### 5.1 정적 검증

- 대상 파일이 import/compile 되는지 확인한다.
- 구현 대상에 `...` 또는 관련 TODO가 남지 않았는지 확인한다.
- `week05_tools()`에 메인 tool 5개가 포함되는지 확인한다.
- `create_shared_schedule`과 `delete_shared_schedule`이 tool 목록에서 제외되는지 확인한다.
- `fixed/`, `mcp_server/`, `student_parts_baseline/`에 변경이 없는지 확인한다.

### 5.2 wrapper 계약 검증

MCP 호출 함수를 대체 가능한 fake로 바꿔 각 wrapper가 다음을 지키는지 확인한다.

- 정확한 MCP tool 이름
- 누락 없는 인자 dict
- `None`과 빈 list를 임의로 변환하지 않음
- 단순 wrapper가 결과 문자열을 그대로 반환함
- `load_conversation_messages`만 dict payload를 `json_payload()`로 직렬화함

### 5.3 개인 일정 수집 검증

격리된 임시 앱 DB와 `PERSONAL_SCHEDULES` fixture로 다음 경우를 확인한다.

1. SQLite 저장 일정이 포함된다.
2. 현재 scope의 미저장 임시 일정이 포함된다.
3. 다른 scope의 임시 일정은 제외된다.
4. 임시 `id`와 SQLite `schedule_id`가 같으면 한 번만 포함된다.
5. 원본 `PERSONAL_SCHEDULES`가 변경되지 않는다.

### 5.4 통합 rows 검증

- 개인 일정 row의 `member_name`이 `"나"`인지 확인한다.
- 개인/외부 row 모두 핵심 6개 필드를 갖는지 확인한다.
  - `member_name`
  - `title`
  - `date`
  - `start_time`
  - `end_time`
  - `notes`
- 외부 row의 `source_conversation_id`가 보존되는지 확인한다.
- 개인 일정에 날짜 범위 필터가 적용되는지 확인한다.
- 정규화된 멤버 이름과 날짜가 외부 MCP 호출에 전달되는지 확인한다.
- 합쳐진 전체 rows를 기준으로 `schedule_summary`가 생성되는지 확인한다.

### 5.5 실제 MCP fixture 검증

제공된 외부 DB를 사용해 다음 흐름을 확인한다.

1. `search_previous_conversations`
   - 멤버와 핵심어로 관련 `conversation_id`를 찾는다.
2. `load_conversation_messages`
   - 선택한 대화의 메시지가 시간순으로 반환된다.
3. `extract_schedules_from_history`
   - 지정한 멤버·날짜 범위의 일정만 반환된다.
4. `list_shared_schedules`
   - `rows`와 `schedule_summary`가 함께 유지된다.
5. `collect_member_schedules`
   - `"나"`와 외부 멤버 일정이 하나의 rows 배열에 들어간다.

### 5.6 agent/UI 검증

`./run.sh --week5` 또는 Windows 환경의 동등한 실행 경로로 Week 5 agent를 실행한다.

확인할 대표 요청:

- “철수의 API 연동 관련 예전 대화를 찾아서 알려줘.”
- “철수와 영희의 7월 7일부터 10일까지 바쁜 시간을 알려줘.”
- “나와 철수, 영희의 같은 기간 일정을 함께 모아줘.”
- “공유 일정 저장소에 등록된 철수 일정을 보여줘.”

trace에서 확인할 내용:

- 과거 대화 질문은 검색 후 필요한 경우 메시지 로드 순서로 호출되는가?
- 일정 질문에 대화 검색 tool을 불필요하게 호출하지 않는가?
- 개인+외부 일정 질문은 `collect_member_schedules`를 사용하는가?
- 추가 과제 tool이 노출되거나 호출되지 않는가?
- 조회 결과가 없을 때 일정을 추측하지 않는가?

LLM이 필요한 실행 검증은 `PROXY_TOKEN`이 설정된 경우에 수행한다. 토큰이 없더라도
helper, wrapper, MCP fixture 수준의 결정론적 검증은 완료한다.

---

## 6. 완료 기준

- Week 5 메인 wrapper 4개가 지정된 MCP/helper 경계를 정확히 사용한다.
- `collect_member_schedules`가 앱 SQLite, 현재 scope의 미저장 임시 일정,
  외부 멤버 일정을 하나의 rows 계약으로 합친다.
- 중복 저장된 Week 1 일정이 두 번 나타나지 않는다.
- 모든 통합 row에 `member_name/title/date/start_time/end_time/notes`가 있다.
- 외부 MCP의 `rows`, `schedule_summary`, 메시지 순서가 불필요하게 변형되지 않는다.
- Week 1~4 tool과 prompt가 유지된 상태로 Week 5 기능이 누적된다.
- 최초 구현에서는 추가 과제인 `create_shared_schedule`과 `delete_shared_schedule`을
  구현하지 않고 agent tool 목록에서도 제외한다.
- `fixed/`, `mcp_server/`, `student_parts_baseline/` 제공 파일을 수정하지 않는다.
- 정적 검증, 결정론적 helper/wrapper 검증, 실제 MCP fixture 검증이 통과한다.
- 가능한 환경에서는 Week 5 agent trace까지 확인한다.

---

## 7. 후속 추가 과제 구현 계획

### 7.1 변경 범위

추가 과제는 리뷰 대응 단계에서 현재 `junyoung/week5` 작업에 이어서 구현한다.

1. 제품 구현 코드는 `student_parts/week05_load_kanas_past_conversations.py`에 한정한다.
2. 리뷰 대응 수정과 추가 과제 구현이 기존 메인 과제 동작을 깨지 않는지 함께 검증한다.
3. 구현 계획 문서에는 후속 범위와 검증 기준을 기록한다.
4. 리뷰 답변 초안은 로컬 전용 문서로 유지해 커밋 대상에서 제외한다.

제공 코드인 `fixed/`, `mcp_server/`, `student_parts_baseline/`은 계약 확인에만 사용하고
수정하지 않는다.

### 7.2 구현 대상

- `create_shared_schedule`
- `delete_shared_schedule`
- `week05_tools()`에 두 tool 추가
- `week05_prompt_parts()`에 공유 일정 직접 생성·갱신·삭제 규칙 추가
- 생성·삭제 입력 schema의 `Field(description=...)` 보강

### 7.3 제공 MCP 계약

#### `create_shared_schedule`

입력:

- `member_name: str`
- `title: str`
- `date: str`
- `start_time: str`
- `end_time: str = "미정"`
- `notes: str | None`
- `source_conversation_id: str | None`
- `schedule_id: str | None`

동작과 반환:

- `schedule_id`가 없으면 새 공유 일정 row를 만든다.
- 기존 `schedule_id`를 전달하면 같은 row를 갱신한다.
- 반환 JSON의 핵심 필드는 `ok`, `tool_name`, `shared_schedule`이다.
- `shared_schedule.sync_status`는 `created` 또는 `updated`다.

#### `delete_shared_schedule`

입력:

- `schedule_id: str | None`
- `source_conversation_id: str | None`

동작과 반환:

- 전달된 식별자와 일치하는 공유 일정 row를 삭제한다.
- 식별자가 모두 없으면 전체 삭제하지 않고 빈 삭제 결과를 반환한다.
- 반환 JSON의 핵심 필드는 `ok`, `tool_name`, `deleted_count`, `deleted`다.

### 7.4 생성 wrapper 구현

학생 wrapper는 직접 SQL이나 정규화를 추가하지 않고 MCP 결과 문자열을 그대로 반환한다.

```python
return call_mcp_tool_sync(
    "create_shared_schedule",
    {
        "member_name": member_name,
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "notes": notes,
        "source_conversation_id": source_conversation_id,
        "schedule_id": schedule_id,
    },
)
```

wrapper에서 `None` 필드를 임의로 제거하거나 새로운 기본값을 만들지 않는다. 입력 schema와
MCP 서버의 기본 계약을 유지한다.

### 7.5 삭제 wrapper 구현

두 선택 식별자를 그대로 MCP에 전달한다.

```python
return call_mcp_tool_sync(
    "delete_shared_schedule",
    {
        "schedule_id": schedule_id,
        "source_conversation_id": source_conversation_id,
    },
)
```

식별자가 모두 없을 때 wrapper가 전체 삭제나 임의 추론을 수행하지 않는다. MCP의
`deleted_count=0`, `deleted=[]` 계약을 따른다.

### 7.6 agent tool 목록 확장

구현과 직접 호출 검증을 마친 뒤 `week05_tools()`에 두 tool을 포함한다.

```text
create_shared_schedule
delete_shared_schedule
```

각 tool은 한 번만 포함하고 Week 1~4 및 Week 5 메인 tool의 기존 노출을 유지한다.

### 7.7 prompt와 schema 규칙

agent가 앱 개인 일정과 외부 공유 저장소를 혼동하지 않도록 다음 규칙을 추가한다.

- 외부 공유 일정 저장소에 직접 등록해 달라는 요청에만 `create_shared_schedule`을 사용한다.
- 앱의 내 일정 저장 요청에는 이전 주차의 개인 일정 저장 tool을 사용한다.
- 기존 공유 일정을 갱신할 때는 먼저 `list_shared_schedules`로 후보와 `schedule_id`를 확인한다.
- 후보가 하나로 확정되면 같은 `schedule_id`로 `create_shared_schedule`을 호출한다.
- 삭제도 먼저 `list_shared_schedules`로 대상을 확인한다.
- 후보가 여러 개면 사용자의 선택을 받고, 하나로 확정된 뒤 삭제한다.
- 식별자가 없거나 삭제 결과가 비어 있으면 성공했다고 추측하지 않는다.
- 생성·갱신은 `shared_schedule`, 삭제는 `deleted_count`와 `deleted`를 근거로 답한다.

`CreateSharedScheduleInput`에는 직접 공유 저장소용 입력임을 설명하고,
`DeleteSharedScheduleInput`에는 두 식별자의 의미와 둘 다 없을 때 삭제 대상이 확정되지
않는다는 사실을 설명한다.

### 7.8 wrapper 계약 검증

`call_mcp_tool_sync`를 fake로 교체해 다음을 확인한다.

- 생성 wrapper가 정확히 `create_shared_schedule`을 호출한다.
- 생성 인자 8개가 누락되거나 이름이 바뀌지 않는다.
- 삭제 wrapper가 정확히 `delete_shared_schedule`을 호출한다.
- 삭제 식별자 2개가 그대로 전달된다.
- 두 wrapper 모두 MCP JSON 문자열을 그대로 반환한다.
- `week05_tools()`에 생성·삭제 tool이 각각 한 번만 포함된다.

### 7.9 실제 MCP 생성·갱신·삭제 검증

fixture와 충돌하지 않는 고유 식별자를 사용한다.

```text
schedule_id: shared_week5_extra_review
source_conversation_id: extra:week5:review
member_name: 철수
title: 추가 과제 검증 일정
date: 2026-07-12
start_time: 18:00
end_time: 19:00
```

검증 순서:

1. 생성 후 `sync_status=created`인지 확인한다.
2. `source_conversation_id`로 조회해 row가 하나인지 확인한다.
3. 같은 `schedule_id`로 시간을 바꿔 다시 생성한다.
4. `sync_status=updated`이고 row가 두 개로 늘지 않았는지 확인한다.
5. `schedule_id`로 삭제하고 `deleted_count=1`인지 확인한다.
6. 다시 조회해 row가 없는지 확인한다.
7. 식별자 없이 삭제해도 다른 row가 삭제되지 않는지 확인한다.
8. 실제 기본 DB를 사용했다면 검증 마지막에 고유 row를 반드시 정리한다.

### 7.10 UI 검증 시나리오

#### 생성

```text
외부 MCP 공유 일정 저장소에 철수의 "추가 과제 UI 검증" 일정을
2026-07-12 18:00부터 19:00까지 직접 등록해줘.
source_conversation_id는 extra:week5:ui-check로 사용해줘.
```

통과 기준:

- `create_shared_schedule` 한 번 호출
- 개인 일정 저장 tool 호출 없음
- `shared_schedule.sync_status="created"`
- 반환된 `schedule_id`를 확인할 수 있음

#### 조회와 갱신

```text
공유 일정 저장소에서 source_conversation_id가 extra:week5:ui-check인 일정을 조회해줘.
```

조회된 실제 `schedule_id`를 다음 갱신 요청에 명시한다.

```text
공유 일정 schedule_id가 "조회된_ID"인 일정을 같은 제목과 날짜로 유지하고
시간을 18:30부터 20:00까지로 갱신해줘.
```

통과 기준:

- 조회 row가 정확히 하나임
- 같은 `schedule_id`로 `create_shared_schedule` 호출
- `sync_status="updated"`
- 갱신 후에도 row가 하나만 존재함

#### 삭제와 삭제 확인

```text
공유 일정 schedule_id가 "조회된_ID"인 일정을 삭제해줘.
```

통과 기준:

- `delete_shared_schedule` 호출
- `deleted_count=1`
- 삭제 후 `source_conversation_id` 조회 결과가 `rows=[]`

#### 안전 경계

```text
어떤 일정인지 지정하지 않을 테니 공유 일정을 삭제해줘.
```

통과 기준:

- 가장 좋은 동작은 tool을 호출하지 않고 삭제 대상을 질문하는 것임
- tool을 호출하더라도 식별자 없는 요청은 `deleted_count=0`이어야 함
- 전체 일정이 삭제되지 않고 삭제 성공을 거짓으로 답하지 않음

### 7.11 추가 과제 완료 기준

- 두 wrapper의 TODO와 `...`가 제거된다.
- 생성·삭제 wrapper가 MCP tool 이름과 인자 계약을 그대로 따른다.
- `week05_tools()`에 두 추가 과제 tool이 노출된다.
- 개인 일정 저장과 외부 공유 일정 직접 생성 routing이 구분된다.
- 생성, 같은 ID 갱신, 조회, 삭제가 순서대로 동작한다.
- 식별자 없는 삭제가 전체 삭제로 이어지지 않는다.
- 기존 메인 과제의 대화 검색, 일정 추출, 통합 rows 동작이 회귀하지 않는다.
- 제공 코드는 수정되지 않는다.
- 실제 검증에서 만든 공유 row는 마지막에 정리된다.
