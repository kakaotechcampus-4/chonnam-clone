# 3주차 「나나의 기록장을 만들다」 학습 내용 정리

## 1. 3주차 전체 목표

3주차의 핵심은 다음 흐름이다.

```
사용자 자연어 요청
→ LLM이 구조화된 tool arguments 생성
→ Pydantic으로 입력 검증
→ Python tool 실행
→ SQLite 저장
→ tool trace와 실제 DB row 확인
```

예를 들어 사용자가:

```
민수 지아랑 다음 주 화요일 3시에 회의 잡아줘.
```

라고 입력하면 LLM은 이를 다음과 비슷한 구조로 만든다.

```json
{
  "source_text": "민수 지아랑 다음 주 화요일 3시에 회의 잡아줘.",
  "kind": "group_schedule",
  "title": "회의",
  "date": "2026-05-19",
  "start_time": "15:00",
  "members": ["민수", "지아"]
}
```

이 데이터가 `save_structured_request` tool로 전달되고 SQLite에 저장된다.

---

# 2. `SaveStructuredRequestInput`

```python
class SaveStructuredRequestInput(BaseModel):
    source_text: str
    kind: Literal[
        "personal_schedule",
        "group_schedule",
        "todo",
        "reminder",
        "unknown",
    ]
    title: str | None = None
    date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    members: list[str] = []
    priority: str | None = None
    reason: str | None = None
```

이 클래스는 LLM이 tool을 호출할 때 따라야 하는 **입력 데이터 계약**이다.

| 필드 | 역할 |
| --- | --- |
| `source_text` | 사용자가 입력한 원문 |
| `kind` | 요청 종류 |
| `title` | 일정·할 일·알림 제목 |
| `date` | 날짜 |
| `start_time` | 시작 시각 |
| `end_time` | 종료 시각 |
| `members` | 참석자 목록 |
| `priority` | 우선순위 |
| `reason` | 분류 또는 추출 근거 |

`kind`는 `Literal`로 제한되어 있기 때문에 지정된 다섯 값 중 하나만 사용할 수 있다.

```
personal_schedule
group_schedule
todo
reminder
unknown
```

---

# 3. `args_schema`

```python
@tool(
    "save_structured_request",
    args_schema=SaveStructuredRequestInput,
)
```

`args_schema`는 데코레이터 함수에 넘기는 키워드 인자다.

```python
args_schema=SaveStructuredRequestInput
```

의 의미는:

> `save_structured_request` tool의 입력은 `SaveStructuredRequestInput` 구조를 따라야 한다.
> 

는 뜻이다.

역할을 구분하면 다음과 같다.

```
SaveStructuredRequestInput
= 입력 데이터 계약서

args_schema
= 해당 tool이 어떤 계약서를 사용할지 지정하는 설정

tool_call.arguments
= LLM이 계약서에 맞춰 생성한 실제 입력값
```

LLM은 이 스키마를 보고 필드 이름, 데이터 타입, 필수 여부, 허용값을 판단해 arguments를 만든다.

---

# 4. 데코레이터

데코레이터는 **함수를 다른 함수의 인자로 넘겨서 기능이나 정보를 추가하는 방식**이다.

예:

```python
@decorate
def hello():
    print("안녕")
```

위 코드는 사실상 다음과 같다.

```python
def hello():
    print("안녕")

hello = decorate(hello)
```

즉 `hello` 함수 자체가 `decorate` 함수의 인자로 들어간다.

현재 코드에서는:

```python
@tool(...)
def save_structured_request(...):
```

일반 Python 함수인 `save_structured_request`를 LangChain이 사용할 수 있는 tool 객체로 변환한다.

```
일반 Python 함수
→ @tool 데코레이터
→ LLM agent가 호출할 수 있는 tool
```

`@tool(...)` 괄호 안은 데코레이터에 넘기는 설정값이다.

---

# 5. SQLite

SQLite는 **별도의 DB 서버 없이 파일 하나로 동작하는 관계형 데이터베이스**다.

MySQL과 비교하면 다음과 같다.

| 항목 | MySQL | SQLite |
| --- | --- | --- |
| 실행 방식 | 별도 DB 서버 | 프로그램 내부에서 직접 실행 |
| 저장 | 서버가 관리 | `.db`, `.sqlite3` 파일 |
| 접속 | 계정·비밀번호·포트 | 파일 경로 |
| 주요 용도 | 웹서비스, 다중 사용자 | 로컬 앱, 실습, 테스트 |
| Python 설치 | 별도 드라이버 필요 가능 | `sqlite3` 기본 포함 |

Python에서는 보통 별도 설치 없이 사용할 수 있다.

```python
import sqlite3
```

따라서 일반적으로 다음 명령은 필요 없다.

```bash
pip install sqlite3
```

DB 연결은 다음과 같이 한다.

```python
conn = sqlite3.connect("example.sqlite3")
```

파일이 없으면 새로 생성하고, 있으면 기존 DB를 연다.

---

# 6. `structured_requests` 테이블

```sql
CREATE TABLE structured_requests (
    request_id TEXT PRIMARY KEY,
    source_text TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
)
```

각 컬럼의 역할은 다음과 같다.

| 컬럼 | 역할 |
| --- | --- |
| `request_id` | 요청 고유 식별자 |
| `source_text` | 사용자 원문 |
| `kind` | 요청 종류 |
| `payload_json` | LLM이 만든 전체 구조화 결과 |
| `created_at` | 저장 시각 |

`PRIMARY KEY`는 중복될 수 없는 대표 식별자다.

`NOT NULL`은 반드시 값이 있어야 한다는 뜻이다.

---

# 7. `source_text`가 중복 저장되는 이유

`source_text`는 별도 컬럼에도 있고 `payload_json` 안에도 들어간다.

```
source_text 컬럼
payload_json 내부 source_text
```

현재 구조에서는 중복 저장이 맞다.

이유는 역할이 다르기 때문이다.

```
source_text 컬럼
= 자주 조회하고 검색하는 대표 필드

payload_json
= LLM이 당시 생성한 전체 구조화 결과를 보존하는 원본 스냅샷
```

별도 컬럼이면 다음처럼 조회가 쉽다.

```sql
SELECT *
FROM structured_requests
WHERE source_text LIKE '%회의%';
```

JSON 안에만 있다면 `json_extract()` 등의 처리가 필요하다.

다만 필수적인 설계는 아니며, 중복을 피하려면 `payload_json`에서 `source_text`를 제외할 수도 있다.

---

# 8. 공통 JSON과 개별 테이블의 연결

LLM은 모든 요청을 공통 스키마로 만든다.

예:

```json
{
  "kind": "todo",
  "title": "보고서 제출",
  "date": "2026-05-22",
  "priority": "high"
}
```

그런데 `todos` 테이블은 다음 컬럼을 사용한다.

```
title
due_date
priority
reason
```

공통 JSON의 `date`와 DB의 `due_date`가 이름이 다르다.

이 매핑은 LLM이 자동으로 하는 것이 아니라 저장 함수에 개발자가 직접 작성해 둔 것이다.

```python
elif kind == "todo":
    conn.execute(
        """
        INSERT INTO todos
        (request_id, title, due_date, priority, reason)
        VALUES (?, ?, ?, ?, ?)
        """,
        (request_id, title, date, priority, reason),
    )
```

대응 관계는 다음과 같다.

| 공통 payload | `todos` 테이블 |
| --- | --- |
| `title` | `title` |
| `date` | `due_date` |
| `priority` | `priority` |
| `reason` | `reason` |

전체 역할 분리는 다음과 같다.

```
LLM
= 자연어를 공통 JSON으로 변환
= kind 판단

Python tool
= kind에 따라 저장 테이블 선택
= 공통 필드를 DB 컬럼에 매핑
= SQL 실행

SQLite
= 전달받은 데이터를 실제 파일에 저장
```

---

# 9. 테이블별 저장 분기

```python
if kind in {"personal_schedule", "group_schedule"}:
    # schedules 저장

elif kind == "todo":
    # todos 저장

elif kind == "reminder":
    # reminders 저장
```

저장 위치는 다음과 같다.

| `kind` | 저장 위치 |
| --- | --- |
| `personal_schedule` | `structured_requests`, `schedules` |
| `group_schedule` | `structured_requests`, `schedules` |
| `todo` | `structured_requests`, `todos` |
| `reminder` | `structured_requests`, `reminders` |
| `unknown` | `structured_requests`만 저장 |

`structured_requests`에는 모든 요청이 공통으로 기록된다.

나머지 테이블은 서비스에서 조회하기 쉬운 정규화 데이터다.

---

# 10. `save_structured_request` tool

```python
@tool(
    "save_structured_request",
    description="구조화된 사용자 요청을 SQLite에 저장한다.",
    args_schema=SaveStructuredRequestInput,
)
def save_structured_request(**kwargs) -> str:
```

## `*kwargs`

`kwargs`는 `keyword arguments`의 줄임말이다.

- `*kwargs`는 이름이 붙은 여러 인자를 한꺼번에 받아 딕셔너리로 모은다.

예:

```python
def introduce(**kwargs):
    print(kwargs)

introduce(
    name="준영",
    age=26,
    city="광주",
)
```

함수 내부의 `kwargs`:

```python
{
    "name": "준영",
    "age": 26,
    "city": "광주"
}
```

현재 tool에서도 LLM이 만든 tool arguments가 거의 그대로 `kwargs`에 담긴다.

LLM이 만든 arguments:

```json
{
  "source_text": "민수랑 회의 잡아줘",
  "kind": "group_schedule",
  "title": "회의",
  "date": "2026-05-19"
}
```

함수 내부:

```python
kwargs = {
    "source_text": "민수랑 회의 잡아줘",
    "kind": "group_schedule",
    "title": "회의",
    "date": "2026-05-19",
}
```

---

# 11. `model_validate()`와 `model_dump()`

```python
payload = (
    SaveStructuredRequestInput
    .model_validate(kwargs)
    .model_dump()
)
```

이 코드는 두 단계다.

## `model_validate(kwargs)`

```python
validated = SaveStructuredRequestInput.model_validate(kwargs)
```

`kwargs`가 데이터 계약에 맞는지 검사한다.

검사 대상:

- 필수 필드가 존재하는가?
- `source_text`가 문자열인가?
- `kind`가 허용된 값인가?
- `members`가 문자열 리스트인가?
- 선택 필드가 생략되었다면 기본값을 넣을 수 있는가?

검증이 끝나면 일반 딕셔너리가 아니라 Pydantic 객체가 된다.

```python
validated.kind
validated.title
validated.date
```

처럼 접근한다.

## `model_dump()`

```python
payload = validated.model_dump()
```

검증된 Pydantic 객체를 다시 일반 Python 딕셔너리로 바꾼다.

결과:

```python
{
    "source_text": "...",
    "kind": "group_schedule",
    "title": "회의",
    "date": "2026-05-19",
    "start_time": None,
    "end_time": None,
    "members": [],
    "priority": None,
    "reason": None,
}
```

딕셔너리로 바꾸는 이유는 뒤의 코드가 다음과 같이 작성되어 있기 때문이다.

```python
payload["kind"]
payload.get("title")
payload["title"] = title
json.dumps(payload)
```

반드시 `model_dump()`을 해야 하는 것은 아니다.

Pydantic 객체를 그대로 사용할 수도 있다.

```python
validated.kind
validated.title
```

하지만 현재 코드는 DB 저장과 JSON 변환을 편하게 하기 위해 `dict`로 바꾼다.

전체 흐름은 다음과 같다.

```
LLM tool arguments
→ kwargs 딕셔너리
→ model_validate()
→ 검증된 Pydantic 객체
→ model_dump()
→ 일반 payload 딕셔너리
→ SQLite 저장
```

---

# 12. Agent 생성 코드

```python
structured_save_agent = create_agent(
    model=make_model(700),
    tools=[save_structured_request],
    system_prompt=(...),
)
```

이 코드는 LLM, tool, 행동 규칙을 조립해 하나의 agent를 만든다.

| 부분 | 역할 |
| --- | --- |
| `model` | 판단하고 tool arguments를 만드는 LLM |
| `tools` | agent가 실행할 수 있는 도구 |
| `system_prompt` | 역할과 행동 규칙 |
| `structured_save_agent` | 완성된 agent 객체 |

쉽게 표현하면:

```
model
= 두뇌

tools
= 행동 수단

system_prompt
= 규칙과 역할
```

`tools=[save_structured_request]`이므로 현재 agent가 사용할 수 있는 tool은 하나뿐이다.

시스템 프롬프트는 대략 다음을 지시한다.

- 요청을 일정·할 일·알림 등으로 분류
- 사용자 원문을 `source_text`에 넣기
- 상대 날짜를 절대 날짜로 변환
- `save_structured_request`를 한 번 호출
- 호출 후 짧게 답변

---

# 13. `fetch_all()`

```python
def fetch_all(table: str) -> list[dict[str, Any]]:
    with connect_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM {table} ORDER BY rowid"
        ).fetchall()

    return [dict(row) for row in rows]
```

노트북에서 직접 만든 함수다.

역할은:

> 전달받은 테이블의 모든 row를 조회해 딕셔너리 리스트로 반환한다.
> 

예:

```python
fetch_all("schedules")
```

실행 SQL:

```sql
SELECT * FROM schedules ORDER BY rowid;
```

데이터가 한 건 있으면:

```python
[
    {
        "id": 1,
        "title": "회의",
        "date": "2026-05-19"
    }
]
```

데이터가 없으면:

```python
[]
```

---

# 14. `saved_rows`와 `len()`

```python
saved_rows = {
    "structured_requests": fetch_all("structured_requests"),
    "schedules": fetch_all("schedules"),
    "todos": fetch_all("todos"),
    "reminders": fetch_all("reminders"),
}
```

각 테이블의 전체 데이터를 한 딕셔너리에 모은다.

예:

```python
saved_rows = {
    "structured_requests": [{"request_id": "req-1"}],
    "schedules": [{"id": 1, "title": "회의"}],
    "todos": [],
    "reminders": [],
}
```

`len()`은 리스트 안의 원소 개수를 센다.

```python
len([{"id": 1}])  # 1
len([])           # 0
```

그룹 일정 요청 하나를 저장했다면:

```
structured_requests: 1
schedules: 1
todos: 0
reminders: 0
```

가 된다.

모든 요청은 `structured_requests`에 저장되고, 그룹 일정이므로 `schedules`에도 저장되기 때문이다.

---

# 15. `assert`

`assert`는 조건이 반드시 참인지 확인하는 Python 문법이다.

```python
assert 1 + 1 == 2
```

참이면 아무 일 없이 넘어간다.

```python
assert 1 + 1 == 3
```

거짓이면 `AssertionError`가 발생한다.

노트북에서는 다음을 검사한다.

```python
assert len(save_calls) == 1
```

저장 tool이 한 번만 호출됐는지 확인한다.

```python
assert save_calls[0]["arguments"]["kind"] == "group_schedule"
```

LLM이 요청을 그룹 일정으로 분류했는지 확인한다.

```python
assert len(saved_rows["structured_requests"]) == 1
assert len(saved_rows["schedules"]) == 1
assert len(saved_rows["todos"]) == 0
assert len(saved_rows["reminders"]) == 0
```

DB 저장 상태가 예상과 일치하는지 확인한다.

---

# 16. 별도 테스트 함수인가?

현재 노트북에서는 별도의 테스트 함수가 정의된 것이 아니다.

하나의 셀 안에 다음 과정이 함께 들어 있다.

```
1. agent 실행
2. tool trace 추출
3. SQLite row 조회
4. 결과 출력
5. assert 검증
```

즉 해당 셀을 직접 실행하면 실행과 검증이 같이 이루어진다.

조건이 맞으면 셀이 정상 종료되고, 틀리면 `AssertionError`가 발생한다.

현재 구조는:

```
실습 실행 코드
+
즉석 검증용 assert
```

에 가깝다.

정식 테스트 코드라면 보통 다음처럼 별도 함수로 만든다.

```python
def test_group_schedule_saved():
    ...
    assert len(saved_rows["schedules"]) == 1
```

그리고 `pytest` 같은 테스트 도구로 실행한다.

---

# 핵심만 압축

```
SaveStructuredRequestInput
= tool 입력 데이터 계약

args_schema
= 해당 tool이 계약을 사용하도록 지정

LLM
= 자연어를 tool arguments로 구조화

**kwargs
= LLM arguments를 dict 형태로 한꺼번에 받음

model_validate()
= kwargs가 스키마에 맞는지 검사

model_dump()
= 검증된 Pydantic 객체를 일반 dict로 변환

save_structured_request()
= kind에 따라 적절한 DB 테이블에 저장

fetch_all()
= 테이블의 모든 row 조회

len()
= 조회된 row 개수 확인

assert
= 결과가 예상 조건과 맞는지 자동 검증
```