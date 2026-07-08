# Week 02 구현 플랜: `week02_structure_natural_language_requests.py`

## Context

Week 2 목표는 자연어 요청을 `StructuredRequest` / `StructuredRequestBatch` Pydantic 모델로 구조화하는 LangChain 에이전트를 완성하는 것이다. Week 1 tool이 임시 일정을 만드는 데 그쳤다면, Week 2는 사용자 입력이나 tool 결과 JSON을 "앱이 이해하는 구조"로 변환하는 단계다.

수정 파일: `student_parts/week02_structure_natural_language_requests.py` 단독

---

## 구현 순서

### 1. `KIND_REQUIRED_FIELDS` 모듈 상수 추가 (line 17 이후)

kind별 필수 필드 목록을 모델 정의 바깥에 상수로 선언한다. 시스템 프롬프트 텍스트와 검증 함수 양쪽에서 참조한다.

```python
KIND_REQUIRED_FIELDS: dict[str, list[str]] = {
    "personal_schedule": ["title", "date"],
    "group_schedule":    ["title", "date", "members"],
    "todo":              ["title"],
    "reminder":          ["title", "date"],
    "unknown":           [],
}
```

---

### 2. `StructuredRequest` 클래스 (line 99)

9개 필드 선언. `reason` 필드 description에 **모호할 때 여기에 이유를 남긴다**는 안내를 포함해 LLM이 ambiguity를 처리하는 창구로 쓰도록 유도한다.

```python
class StructuredRequest(BaseModel):
    kind: RequestKind = Field(
        description="요청 종류. personal_schedule·group_schedule·todo·reminder·unknown 중 하나."
    )
    title: str | None = Field(default=None, description="일정·할 일·리마인더 제목. 모르면 None.")
    date: str | None = Field(default=None, description="날짜 (YYYY-MM-DD). 불확실하면 None.")
    start_time: str | None = Field(default=None, description="시작 시간 (HH:MM). 불확실하면 None.")
    end_time: str | None = Field(default=None, description="종료 시간 (HH:MM). 불확실하면 None.")
    members: list[str] = Field(default_factory=list, description="참석자·관련 멤버 이름 목록. 없으면 빈 list.")
    priority: str | None = Field(default=None, description="우선순위 (todo일 때 사용). 없으면 None.")
    reason: str | None = Field(
        default=None,
        description="판단 근거. 날짜·시간·kind가 불확실할 때 이유를 한 문장으로 남긴다."
    )
    original_text: str = Field(default="", description="사용자 원문. 감사 추적·디버깅용으로 반드시 보존한다.")
```

---

### 3. `StructuredRequestBatch` 클래스 (line 111)

```python
class StructuredRequestBatch(BaseModel):
    requests: list[StructuredRequest] = Field(
        default_factory=list,
        description="구조화된 요청 목록. 요청이 1개뿐이어도 반드시 list에 담는다."
    )
    base_date: str = Field(
        default_factory=current_app_date_iso,
        description="상대 날짜(내일·다음 주 등) 해석 기준일 (YYYY-MM-DD)."
    )
```

---

### 4. `missing_required_fields()` 공개 헬퍼 함수

`StructuredRequestBatch` 정의 바로 아래에 추가. Week 3+ 저장 전 검증에서 재사용할 수 있도록 모듈 공개 함수로 둔다.

```python
def missing_required_fields(req: StructuredRequest) -> list[str]:
    """kind별 필수 필드 중 값이 없는 것을 반환한다. 빈 list면 완전한 요청."""
    required = KIND_REQUIRED_FIELDS.get(req.kind, [])
    return [
        f for f in required
        if not getattr(req, f, None)
        or (isinstance(getattr(req, f), list) and not getattr(req, f))
    ]
```

이 함수는 `_coerce_structured_request` / `extract_structured_request` 예약 함수에서 이후 회차에 호출될 진입점이다.

---

### 5. `week02_tools()` (line 139)

```python
def week02_tools() -> list[Any]:
    return week01_tools()
```

---

### 6. `week02_prompt_parts()` (line 155) — 핵심

`week01_prompt_parts()` 위에 4개 조각을 추가한다.

**조각 1 — 역할·날짜 기준**
```
너는 Week 2 구조화 에이전트야.
오늘 날짜(기준일)는 {current_app_date_iso()}이야.
사용자의 자연어 요청을 StructuredRequestBatch(requests, base_date) 형태로 구조화하는 게 네 역할이야.
```

**조각 2 — 필드 채우기 규칙 (모호 처리 + kind별 필수 필드)**
```
자연어를 StructuredRequest 필드로 구조화할 때 아래 규칙을 따라.

[필드 규칙]
- kind : personal_schedule·group_schedule·todo·reminder·unknown 중 하나. 분류 불가 → unknown.
- date : "내일"·"다음 주 화요일" 같은 상대 날짜는 base_date 기준으로 YYYY-MM-DD로 변환.
         변환이 불가능하거나 언급이 없으면 None.
- start_time/end_time : "오후 3시"→15:00, "점심"→12:00 등 합리적 추론 가능하면 HH:MM.
                        불확실하면 None.
- members : 이름이 언급되면 list에 담아. 없으면 빈 list.
- reason  : kind·날짜·시간이 불확실하거나 추정이 필요할 때 한 문장으로 이유를 남겨.
- original_text : 사용자 원문 그대로 보존.

[kind별 필수 필드]
- personal_schedule : title, date
- group_schedule    : title, date, members (최소 1명)
- todo              : title
- reminder          : title, date
- unknown           : 없음 (original_text만 보존)

필수 필드가 불확실할 때는 억지로 만들지 않고 None으로 두되 reason에 이유를 남겨.
```

**조각 3 — tool JSON 처리**
```
personal_create_schedule tool을 호출한 뒤 결과 JSON이 있으면
같은 tool을 다시 호출하지 말고, 결과의 created_schedule 필드를 읽어 StructuredRequest를 채워.
```

**조각 4 — 범위 제한**
```
Week 2는 구조화만 담당해. SQLite 저장, RAG, 외부 멤버 일정 조율은 이번 주차에 없어.
```

---

### 7. `week02_system_prompt()` (line 146)

```python
def week02_system_prompt() -> str:
    return join_system_prompt([
        *week02_prompt_parts(),
        """
        최종 답변은 반드시 structured_response(StructuredRequestBatch)로만 반환한다.
        요청이 1개뿐이어도 requests 목록에 StructuredRequest 1개를 담아라.
        personal_create_schedule tool 결과가 있으면 created_schedule JSON을 읽어 필드를 채워라.
        """,
    ])
```

---

### 8. `build_week02_agent()` (line 167)

week01 패턴과 동일하게 구현한다.

```python
def build_week02_agent() -> object:
    global _WEEK02_AGENT
    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    if _WEEK02_AGENT is None:
        _WEEK02_AGENT = create_agent(
            model=chat_model(),
            tools=week02_tools(),
            response_format=StructuredRequestBatch,
            system_prompt=week02_system_prompt(),
        )
    return _WEEK02_AGENT
```

---

## 재사용 함수 참조

| 함수 | 파일 | 용도 |
|------|------|------|
| `join_system_prompt` | `week01_wake_up_nana.py:37` | prompt 조각 누적 합산 |
| `week01_prompt_parts` | `week01_wake_up_nana.py:229` | Week 1 역할·tool 지시 상속 |
| `week01_tools` | `week01_wake_up_nana.py:217` | Week 1 3개 tool 목록 |
| `current_app_date_iso` | `fixed/runtime_clock.py` | 오늘 날짜 ISO 문자열 |
| `CONFIG.has_openai_key` | `fixed/config.py:44` | API 키 유효성 확인 |

---

## 검증

```bash
./run.sh --week2
```

테스트 입력 및 기대 결과:

| 입력 | 기대 kind | 주요 확인 |
|------|-----------|---------|
| "다음 주 화요일 오후 3시에 철수랑 회의 잡아줘" | group_schedule | date=YYYY-MM-DD, members=["철수"], start_time="15:00" |
| "내일 점심 약속 만들어줘" | personal_schedule | date=내일 날짜, start_time="12:00" or None+reason |
| "운동하기 todo 추가해줘" | todo | title="운동하기", date=None |
| "그냥 메모해줘" | unknown | original_text 보존, reason에 분류 불가 이유 |

`structured_response` 키가 있고 타입이 `StructuredRequestBatch`인지 확인.  
`missing_required_fields()` 수동 호출로 kind별 필수 필드 누락 여부도 체크 가능.
