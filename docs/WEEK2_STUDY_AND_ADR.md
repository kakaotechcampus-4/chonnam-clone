# Week 2 스터디 & ADR — 자연어/Week1 JSON → 구조화(StructuredRequest)

- 작성일: 2026-07-08
- 대상 파일: `student_parts/week02_structure_natural_language_requests.py`
- 브랜치: `junyoung/week2` (base = `junyoung/final`)
- 범위: **메인 과제 + 심화(bridge 3함수) 구현 완료.**

이 문서는 (1) 구현 코드 해설 + (2) 설계 결정 기록(ADR)을 담는다.

---

## 1. 이번 주 한 일 (요약)

Week1은 "이미 분해된 인자"를 받아 임시 일정을 만드는 tool을 만들었다.
Week2는 그 앞단, 즉 **사람이 쓴 자연어나 Week1 tool의 JSON을 앱이 저장할 수 있는
구조(`StructuredRequest`)로 변환**하는 에이전트를 완성했다. 저장·RAG·멤버 조율은
Week3 이후이므로 여기서는 "구조화해서 반환"까지만 한다.

구현한 6개(메인 과제):

1. `StructuredRequest` — 요청 1건의 스키마
2. `StructuredRequestBatch` — 요청 여러 건 + 기준일(base_date)
3. `week02_tools()` — Week1 도구 그대로 노출
4. `week02_prompt_parts()` — Week1 프롬프트 위에 Week2 구조화 지시 누적
5. `week02_system_prompt()` — 최종 답변 규칙까지 합친 system prompt
6. `build_week02_agent()` — `response_format=StructuredRequestBatch` agent 생성

---

## 2. 구현 해설 (코드 워크스루) — 자세히

각 항목은 **① 쉽게 말하면(비유) → ② 코드 → ③ 구현 의도(왜) → ④ 과제 원문 인용(지시받은 부분) / ✳️ 내 판단(범위 밖·독창)** 순서로 정리했다.

전체 큰 그림 비유: **Week2 agent = 민원 창구 직원.** 손님이 말로 아무렇게나 요청("다음 주 화요일 오후 3시에 철수랑 회의 잡아줘")하면, 직원이 그걸 듣고 **정해진 신청서 양식**에 칸칸이 옮겨 적어(=구조화) 접수부서(Week3 이후)로 넘길 수 있게 만든다. Week1은 "이미 다 적힌 신청서"를 받아 처리하는 뒷단이었고, Week2는 "말 → 신청서"로 바꾸는 앞단이다.

---

### 2.1 `StructuredRequest` — 요청 1건을 담는 "신청서 양식"

**① 쉽게 말하면**
택배 송장이다. "내일 저녁에 엄마한테 소포 보내줘"라는 말을, 송장의 정해진 칸(받는 사람 / 날짜 / 물품 종류)에 옮겨 적는 것. 칸 이름이 바로 필드(kind/title/date...)이고, 칸 옆의 "예: YYYY-MM-DD" 안내문이 `description`이다. `kind`는 "택배 종류: 일반 / 등기 / 착불" 드롭다운처럼 **정해진 값 중에서만** 고를 수 있다.

**② 코드**
```python
class StructuredRequest(BaseModel):
    kind: RequestKind = Field(description="요청 종류. personal_schedule/group_schedule/todo/reminder/unknown 중 하나")
    title: str | None = Field(default=None, description="일정/할 일 제목. 모르면 None")
    date: str | None = Field(default=None, description="YYYY-MM-DD. 상대표현은 base_date 기준 환산, 모르면 None")
    start_time: str | None = Field(default=None, description="HH:MM 시작 시각. 모르면 None")
    end_time: str | None = Field(default=None, description="HH:MM 종료 시각. '미정'은 None")
    members: list[str] = Field(default_factory=list, description="참석자/관련 멤버. 모르면 빈 목록")
    priority: str | None = Field(default=None, description="할 일 우선순위. 판단 불가하면 None")
    reason: str | None = Field(default=None, description="판단 근거. 없으면 None")
    original_text: str = Field(default="", description="원문 보존")
```

**③ 구현 의도**
- `kind`를 `RequestKind`(=`Literal["personal_schedule", ...]`)로 둔 건, LLM이 "회의요청" 같은 **제멋대로 값**을 못 내게 막기 위해서다. 드롭다운 밖의 값이 오면 Pydantic이 `ValidationError`로 걷어낸다.
- 나머지 필드를 `str | None = None`으로 둔 건 "모르면 비워두게" 하려는 것. 억지로 채우면 환각(없는 시간 지어내기)이 생긴다.
- `members`처럼 여러 개가 들어갈 수 있는 값은 기본을 `default_factory=list`로 준다. (`[]`를 기본값에 직접 쓰면 모든 인스턴스가 같은 리스트를 공유하는 파이썬 고전 버그가 나기 때문 — Pydantic이 factory를 요구하는 이유이기도 하다.)
- 각 `description`에 "모르면 None" 같은 규칙을 박은 이유: structured output에서 이 description은 **LLM에게 그대로 전달되는 미니 지시문**이라, 여기서 안전 규칙을 걸어두면 프롬프트를 덜 건드려도 된다.

**④ 과제 원문 (이 부분은 과제가 명시적으로 지시)**
> 메인과제 구현 대상 1. StructuredRequest 스키마
> - kind/title/date/start_time/end_time/members/priority/reason/original_text 필드가 이후 Week 3 저장 payload의 기준이 됩니다.
> - kind는 RequestKind Literal에 들어 있는 값만 허용합니다.
> - 각 필드에는 LLM structured output이 이해할 수 있도록 한국어 description을 붙입니다.

또한 필드 타입/기본값은 파일의 TODO가 그대로 지정해줬다("title/date/start_time/end_time 필드를 str | None ... 기본값 None", "members ... default_factory=list", "original_text ... 기본값 \"\"").
"모르면 None/빈 list" 원칙도 과제 원문에 근거가 있다:
> 모르는 값을 억지로 만들지 않는 것이 중요합니다. 확실하지 않으면 None 또는 빈 list가 안전합니다.

---

### 2.2 `StructuredRequestBatch` — 신청서 여러 장 + "오늘 날짜 도장"

**① 쉽게 말하면**
장바구니다. 손님이 한 번에 여러 건("운동 예약하고, 회의도 잡고, 알림도 걸어줘")을 말하면 신청서(StructuredRequest)가 여러 장 나오는데, 이걸 한 봉투(batch)에 모아 담는다. 한 건만 말해도 봉투에 한 장 넣는 규칙. `base_date`는 봉투에 찍는 **"접수일 도장"** — "다음 주 화요일"이 며칠인지는 오늘이 며칠인지 알아야 계산되니까.

**② 코드**
```python
class StructuredRequestBatch(BaseModel):
    requests: list[StructuredRequest] = Field(default_factory=list, description="구조화된 요청 목록. 하나여도 목록으로")
    base_date: str = Field(default_factory=current_app_date_iso, description="상대 날짜 해석 기준일(YYYY-MM-DD)")
```

**③ 구현 의도**
- `requests`를 항상 list로 둔 건 "요청 1건"과 "여러 건"을 **같은 형태**로 처리하려는 것. 소비하는 쪽(Week3 저장 로직)이 분기 없이 `for req in batch.requests`만 돌리면 된다.
- `base_date`에 `default_factory=current_app_date_iso`를 쓴 이유: batch가 만들어지는 그 순간의 앱 기준일을 자동으로 찍어주기 위함. 상수로 박으면 실행 시점 날짜가 안 맞는다.

**④ 과제 원문**
> 2. StructuredRequestBatch 스키마
> - requests에는 StructuredRequest 목록을 담고, 요청이 하나뿐이어도 list 형태를 유지합니다.
> - base_date에는 상대 날짜 해석 기준일(current_app_date_iso)을 담습니다.

---

### 2.3 `week02_tools()` — 옆 팀 도구함 그대로 빌리기

**① 쉽게 말하면**
새로 생긴 부서(Week2)가 바퀴를 다시 발명하지 않고, 옆 부서(Week1)가 이미 만들어 둔 공구함(일정 생성/조회/삭제 도구)을 **통째로 빌려 쓰는** 것.

**② 코드**
```python
def week02_tools() -> list[Any]:
    return week01_tools()
```

**③ 구현 의도**
Week2 agent가 "내 일정 추가해줘" 같은 개인 일정 요청을 받으면, Week1의 `personal_create_schedule`을 호출해 나온 `created_schedule` JSON을 **구조화의 근거 재료**로 쓴다. 그래서 Week1 도구를 그대로 노출하는 게 맞다. 굳이 새로 만들 이유가 없다.

**④ 과제 원문**
> week02_tools()는 Week 1 tool 목록을 그대로 반환합니다.

TODO도 동일: "Week 1에서 구현한 tool 목록을 그대로 반환하세요."

---

### 2.4 `week02_prompt_parts()` — 공통 사규 위에 부서 지침 얹기

**① 쉽게 말하면**
신입에게 주는 업무 매뉴얼. 맨 앞에 **회사 공통 수칙(Week1: 오늘 날짜, Nana 페르소나)**을 붙이고, 그 뒤에 **이번 부서 전용 지침(Week2: 말을 신청서로 바꾸는 법)**을 추가한다. 규칙이 겹치면 "뒤에 적힌(=더 최신) 지침을 따른다".

**② 코드**
```python
def week02_prompt_parts() -> list[str]:
    return [
        *week01_prompt_parts(),                                   # 공통 사규 상속
        "[Week2] ... 상대 날짜 기준일은 {오늘} ... 이 값을 최우선으로 삼는다 ...",
        "자연어를 StructuredRequest 필드로 구조화 ... 모르면 None/빈 목록 ...",
        "Week1 tool JSON을 받으면 tool 재호출 없이 payload(created_schedule)를 읽어 ...",
        "Week2에서는 SQLite 저장/RAG/멤버 조율을 하지 않는다.",
    ]
```

**③ 구현 의도 & ④ 과제 원문 (지시받은 부분)**
TODO 4개가 넣을 지침을 직접 지시했고, 그대로 반영했다:
> - Week 2 요청 구조화 agent 역할과 현재 날짜(current_app_date_iso()) 기준을 추가하세요.
> - 자연어를 StructuredRequest 필드(kind/title/date/start_time/end_time/members 등)로 구조화하도록 지시하세요.
> - Week 1 tool JSON을 받은 경우 다시 tool을 호출하지 않고 payload를 읽어 structured_response로 만들도록 지시하세요.
> - Week 2에서는 SQLite 저장, RAG, 외부 멤버 일정 조율을 하지 않는다고 명시하세요.

**✳️ 내 판단 (범위 밖·독창)** — 날짜 기준 "최우선" 문구
과제는 "current_app_date_iso() 기준을 추가"까지만 지시했다. 그런데 상속하는 `week01_prompt_parts()`에는 내가 Week1 때 넣은 `datetime.now()` 기반 "오늘의 날짜" 문구가 이미 있다. 두 날짜 기준이 프롬프트에 공존하면 LLM이 헷갈릴 수 있다.
- **왜 이렇게**: Week1 파일은 이미 merge된 파일이라 **건드리면 충돌 리스크**가 있다(→ ADR-1). 그래서 Week1은 그대로 두고, Week2 지침에 "상대 날짜 계산에는 `current_app_date_iso()` 기준일을 **최우선**으로 삼으라"는 한 줄을 더해 프롬프트 레벨에서 우선순위를 정리했다. 이는 `join_system_prompt`의 공통 헤더 규칙("더 뒤/높은 주차 지시를 우선한다")과도 맞아떨어진다.

---

### 2.5 `week02_system_prompt()` — 매뉴얼 + "제출 양식 규칙"

**① 쉽게 말하면**
2.4의 업무 매뉴얼에 **"보고서는 반드시 이 양식(StructuredRequestBatch)으로 제출"**이라는 제출 규칙을 덧붙여 하나로 묶은 최종 사규.

**② 코드**
```python
def week02_system_prompt() -> str:
    return join_system_prompt([
        *week02_prompt_parts(),
        "최종 답변은 반드시 StructuredRequestBatch 형식으로 반환한다.",
        "요청이 하나여도 requests에 하나 담고, 여러 의도면 나눈다.",
        "created_schedule을 읽어 필드를 채운다. attendees→members로 매핑, '미정' end_time→None.",
    ])
```

**③ 구현 의도 & ④ 과제 원문**
TODO가 지시한 대로 (1) prompt_parts + 최종 답변 규칙 합치기, (2) 하나여도 목록 담기, (3) created_schedule 읽어 채우기를 넣었다:
> - join_system_prompt(...)로 week02_prompt_parts()와 Week 2 structured_response 최종 답변 규칙을 합치세요.
> - StructuredRequestBatch에는 요청이 하나뿐이어도 requests 목록에 StructuredRequest 하나를 담도록 지시하세요.
> - personal_create_schedule tool 결과 JSON의 created_schedule을 읽어 필드를 채우도록 지시하세요.

"여러 의도면 나눈다"도 과제 원문 근거가 있다:
> 여러 일정/할 일/알림 의도가 한 문장에 섞이면 Week 2 agent에서는 여러 StructuredRequest로 나눕니다.

**✳️ 내 판단 (glue 코드)** — `attendees→members`, `'미정'→None` 매핑
과제는 "created_schedule을 읽어 채워라"까지만 말한다. 그런데 실제로 Week1의 `created_schedule` JSON은 필드 이름이 **`attendees`**이고 `end_time` 기본값이 **`"미정"`**인데, Week2 스키마는 **`members`**, `end_time`은 `HH:MM|None`이다. 이름·형식이 다르면 LLM이 값을 못 옮기거나 `"미정"`을 시각처럼 넣을 수 있다.
- **왜 이렇게**: 이 불일치를 코드 파서로 처리하는 건 과제 취지(=LLM 구조화)와 안 맞아서, **프롬프트에 매핑 규칙 두 줄**로 흡수했다. "attendees는 members로", "'미정' 같은 비-시각 값은 None으로". (과제 "StructuredRequest 읽는 법"의 members 설명, end_time HH:MM 규칙과 정합적)

---

### 2.6 `build_week02_agent()` — 직원 채용·배치

**① 쉽게 말하면**
민원 창구 직원을 채용해 배치하는 것. (1) 채용 자격(=API 키 `PROXY_TOKEN`) 확인 → 없으면 채용 거절(에러). (2) 이미 뽑아둔 직원이 있으면 다시 안 뽑고 재사용(전역 캐시). (3) 새로 뽑을 땐 공구함(tools)을 쥐어주고 **"보고는 무조건 이 양식으로"(response_format)** 규칙을 달아서 배치.

**② 코드**
```python
def build_week02_agent() -> object:
    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK02_AGENT
    if _WEEK02_AGENT is None:
        _WEEK02_AGENT = create_agent(
            model=chat_model(),
            tools=week02_tools(),
            response_format=StructuredRequestBatch,   # ★ 이번 주 핵심
            system_prompt=week02_system_prompt(),
        )
    return _WEEK02_AGENT
```

**③ 구현 의도**
- `response_format=StructuredRequestBatch`가 Week2의 심장이다. 이걸 걸면 LangChain이 LLM 최종 출력을 이 스키마로 **강제**하고, 결과의 `structured_response`에 batch 객체가 담긴다. 앱 런타임(`fixed/langchain_trace.py`)이 그 `structured_response`를 읽어 화면·trace에 보여준다.
- 키 가드와 전역 캐시(`_WEEK02_AGENT`)는 Week1 `build_week01_agent()`와 **똑같은 패턴**을 따랐다(일관성 + 매 호출마다 agent 재생성하는 낭비 방지).

**④ 과제 원문**
> build_week02_agent()는 langchain.agents.create_agent, fixed/llm.py의 chat_model(), week02_system_prompt(), response_format=StructuredRequestBatch를 사용해 Week 2 agent를 만듭니다.

TODO도 인자 구성까지 못박아 지시했다: "create_agent에는 model=chat_model(), tools=week02_tools(), response_format=StructuredRequestBatch, system_prompt=week02_system_prompt()를 연결", "CONFIG.has_openai_key가 없으면 RuntimeError(\"PROXY_TOKEN이 .env에 필요합니다.\")", "전역 _WEEK02_AGENT를 재사용".

---

## 2-B. 심화(bridge) 구현 해설 — 무인 키오스크 3형제

메인 agent가 "상담원과 대화해 신청서 작성"이라면, 심화 bridge는 **대화 없이 문장 하나로 신청서를 뽑는 지름길**이다. Week3 이상에서 저장/조율 직전에 가볍게 구조화하려고 미리 만들어 둔다.
호출 사슬(위→아래): `extract_schedule_request`(@tool, Week3가 부름) → `extract_structured_request`(LLM 한 번 호출) → `_coerce_structured_request`(결과 정리).

### 2.7 `_coerce_structured_request()` — LLM 답을 표준 양식으로 "접수 정리"

**① 쉽게 말하면**
LLM이 주는 결과가 어떨 땐 완성된 신청서(StructuredRequest 객체), 어떨 땐 손메모(dict)로 온다. 무엇이 오든 **표준 신청서 객체로 맞춰주는 접수 데스크**. 아예 엉뚱한 게(숫자 등) 오면 그 자리에서 **반려(에러)**한다.

**② 코드**
```python
def _coerce_structured_request(value: Any) -> StructuredRequest:
    if isinstance(value, StructuredRequest):
        return value
    if isinstance(value, dict):
        return StructuredRequest.model_validate(value)
    raise RuntimeError(f"예상치 못한 structured output 형식입니다: {type(value)!r}")
```

**③ 구현 의도 & 이렇게 했을 때의 이점**
과제가 이 함수를 따로 두라고 한 이유는, **LLM 층에서 나온 결과를 딱 한 곳에서 "표준 StructuredRequest"로 정리하는 경계(adapter)**를 만들기 위해서다. `with_structured_output`의 반환은 LLM 제공자·langchain 버전·설정에 따라 **완성 객체일 수도, 원시 dict일 수도** 있는데, 이걸 정리하지 않으면 결과를 쓰는 **모든 코드가 매번 "객체인가 dict인가?"를 따져야** 한다.

이점:
- **호출부가 단순해진다**: `extract_structured_request`나 Week3 저장 코드는 형태를 신경 쓸 필요 없이 항상 StructuredRequest를 받는다 → `.kind`, `.date`처럼 속성 접근을 안심하고 쓴다.
- **검증이 보장된다**: dict 경로에서 `model_validate`를 거치므로 `kind`가 허용된 값인지·타입이 맞는지 pydantic이 확인 → 잘못된 구조가 저장 단계까지 못 흘러간다.
- **빠른 실패(fail-fast)**: 예상 밖 타입이면 `raise`로 즉시 멈춘다 → 버그가 조용히 묻히지 않고 "여기서 깨졌다"가 바로 드러난다. (과제 원문의 "조용히 통과시키지 않습니다"가 이 의도)
- **바뀔 때 한 곳만 고친다**: 나중에 LLM 반환 형태가 달라져도 이 함수 하나만 수정하면 된다(단일 책임).

**④ 과제 원문 (그대로 지시)**
> 1. _coerce_structured_request
>  - LangChain structured output 결과가 이미 StructuredRequest이면 그대로 반환합니다.
>  - dict이면 StructuredRequest.model_validate(...)로 검증해 반환합니다.
>  - 예상한 형태가 아니면 RuntimeError를 발생시켜 잘못된 LLM 응답을 조용히 통과시키지 않습니다.

### 2.8 `extract_structured_request()` — 대화 없이 한 방에 구조화하는 "무인 키오스크"

**① 쉽게 말하면**
메인 agent가 상담원과 대화라면, 이건 **문장을 넣으면 신청서 한 장이 바로 나오는 무인 키오스크**. 대화 루프(agent) 없이 LLM을 딱 한 번만 부른다.

**② 코드**
```python
def extract_structured_request(text: str) -> StructuredRequest:
    structured_llm = chat_model().with_structured_output(
        StructuredRequest, method="function_calling"
    )
    result = structured_llm.invoke([
        {"role": "system", "content": join_system_prompt(week02_prompt_parts())},
        {"role": "user", "content": text},
    ])
    return _coerce_structured_request(result)
```

**③ 구현 의도**
Week3에서 저장 직전에 구조화하려고 매번 agent를 새로 띄우면 무겁다 → `with_structured_output`으로 **단발 호출**. system 프롬프트로 메인과 **같은 `week02_prompt_parts()`를 재사용**해 매핑·날짜 규칙을 그대로 적용한다(중복 작성 방지). 결과는 `_coerce`로 정규화해 **항상 StructuredRequest 하나**를 돌려준다.

**④ 과제 원문 (그대로 지시)**
> 2. extract_structured_request
>  - chat_model().with_structured_output(StructuredRequest, method="function_calling")를 사용합니다.
>  - system 메시지에는 join_system_prompt(week02_prompt_parts())를 넣고, user 메시지에는 text를 넣어 structured LLM을 호출합니다.
>  - 자연어 또는 JSON 문자열을 StructuredRequest 하나로 검증/구조화합니다.

**✳️ 헷갈리기 쉬운 점**
메인 agent는 batch(여러 개)를 반환하지만, 이 bridge는 **단 하나**만 반환한다. 과제가 "extract_structured_request()는 StructuredRequest 하나만 반환한다"고 명시했기 때문.

### 2.9 `extract_schedule_request()` — Week3가 부를 "포장기"(@tool)

**① 쉽게 말하면**
위에서 만든 신청서(StructuredRequest)를 Week3 저장 담당이 바로 받을 수 있게 **봉투(JSON)에 담고 "접수 완료" 스티커(ok/tool_name/base_date)를 붙이는 포장기**.

**② 코드**
```python
@tool
def extract_schedule_request(query: str) -> str:
    structured_request = extract_structured_request(query)
    payload = {
        "ok": True,
        "tool_name": "extract_schedule_request",
        "base_date": current_app_date_iso(),
        "structured_request": structured_request.model_dump(),
    }
    return json.dumps(payload, ensure_ascii=False)
```

**③ 구현 의도**
Week3 저장 tool이 이 문자열 JSON을 받아 `structured_request` 필드만 꺼내 쓰면 되도록 **표준 봉투**로 포장했다. `ensure_ascii=False`로 한글이 안 깨지게 했고(Week1 `_json` 관례와 동일), `@tool`이지만 `week02_tools()`에는 넣지 않아 **Week2 agent에는 노출하지 않는다**.

**④ 과제 원문 (그대로 지시)**
> 3. extract_schedule_request
>  - extract_structured_request(query) 결과에 ok/tool_name/base_date를 붙입니다.
>  - structured_request에는 model_dump() 결과를 넣고, json.dumps(..., ensure_ascii=False)로 반환합니다.
>  - Week 3 이상 저장 tool이 structured_request 필드를 그대로 받을 수 있게 만듭니다.

또한 "Week 2 agent에 공개되는 tool은 아닙니다"라는 가이드에 따라 `week02_tools()`에서 제외했다.

## 3. 액티브 검증 방법 (직접 확인)

### 3.1 실제 실행 (권장, 메인 과제 정식 검증)

```bash
# .env 에 PROXY_TOKEN 설정 후
./run.sh --week2
```

브라우저 채팅에 아래 입력하고, 우측 trace와 최종 답변을 확인한다.

1. **단일 일정**: `다음 주 화요일 오후 3시에 철수랑 회의 잡아줘`
   - 기대: `requests` 1개, `kind=group_schedule`, `members=["철수"]`,
     `date`가 기준일 기준 다음 주 화요일, `start_time="15:00"`.
2. **복수 의도**: `내일 오전 운동하고, 금요일까지 보고서 마감 알림 걸어줘`
   - 기대: `requests` 2개(예: todo + reminder)로 분리.
3. **Week1 경유**: `내 일정에 오늘 저녁 8시 저녁약속 추가해줘`
   - 기대: trace에서 `personal_create_schedule` 호출 → 그 `created_schedule`을 읽어
     최종 `StructuredRequestBatch`로 변환.

확인 항목: 최종 답변이 `StructuredRequestBatch` 형태 `structured_response`로 나오는가.

### 3.2 오프라인 스모크 테스트 (LLM 없이, 이미 통과)

LLM/네트워크 없이 스키마·프롬프트·와이어링을 검증했고 전부 통과했다.

- 스키마: 기본값(None/빈 list/""), `kind` Literal 검증, `base_date` factory 채움.
- `week02_tools()` == Week1 도구 3개.
- `week02_prompt_parts()`가 Week1 조각을 앞에 두고 기준일/구조화/SQLite 언급 포함.
- `week02_system_prompt()`에 `StructuredRequestBatch`, `created_schedule`, `attendees→members`, `미정` 규칙 포함.
- `build_week02_agent()`가 `response_format=StructuredRequestBatch` + tools 3개로 조립.
- 키 없으면 `RuntimeError("PROXY_TOKEN...")`.
- 심화 bridge 3함수도 오프라인 통과: `_coerce`(객체/ dict/ 이상값 RuntimeError), `extract_structured_request`(단일 반환), `extract_schedule_request`(ok/tool_name/base_date/structured_request JSON + 한글 보존).

### 3.3 심화 bridge 확인 (액티브)

**오프라인 (LLM 불필요, 이미 통과)** — `_coerce_structured_request`: ①StructuredRequest 입력→그대로 ②dict 입력→검증 통과 ③이상값(`123` 등)→`RuntimeError`.

**라이브 (PROXY_TOKEN 필요)** — 프로젝트 루트(PowerShell)에서:
```powershell
$env:KANANA_ACTIVE_WEEK="2"; $env:PYTHONNOUSERSITE="1"
uv run python -c "import student_parts.week02_structure_natural_language_requests as w; print(w.extract_schedule_request.invoke({'query':'다음 주 화요일 오후 3시에 철수랑 회의 잡아줘'}))"
```
반환 JSON에 `ok=true`, `tool_name="extract_schedule_request"`, `base_date`, `structured_request`(kind/date/members 등 채워짐)가 있으면 정상.

---

## 4. ADR — 설계 결정 기록

> 형식: 배경 → 결정 → 결과.

### ADR-1. 날짜 기준을 프롬프트에서 일원화
- **배경**: Week1 `week01_prompt_parts()`엔 `datetime.now()` 기반 "오늘 날짜" 문구가 있고, Week2는 `current_app_date_iso()`(앱 기준일)을 쓴다. Week1 파일은 이미 merge된 파일이라 수정하면 충돌 위험이 있다.
- **결정**: **Week1 파일은 수정하지 않음.** 대신 `week02_prompt_parts()`에서 "상대 날짜 계산에는 `current_app_date_iso()` 기준일을 최우선으로 삼으라"고 명시해 프롬프트로 덮어씀.
- **결과**: Week1 변경 없이 날짜 기준을 프롬프트 우선순위 규칙으로 일원화.

### ADR-2. 실행 스크립트
- **배경**: 표준 실행은 `./run.sh --week2`지만, `run.sh`는 bash 스크립트라 Windows(PowerShell)에서는 바로 실행되지 않는다.
- **결정**: 동작 자체는 표준(`KANANA_ACTIVE_WEEK=2` + `uv run python app.py`)을 따르되, Windows에서는 동일 동작을 명령/`run.ps1`로 실행한다.
- **결과**: 실행 환경과 무관하게 같은 결과.

---

## 5. 미구현 / 다음 할 일

- (완료) 심화 bridge 3함수 구현 — agent 없이 `with_structured_output`으로 구조화 → JSON tool payload.
- Week3 연계 시 실제 저장 tool이 `structured_request`를 받아 저장하는 흐름은 Week3에서 확인 예정.

---

## 6. 용어 정리 (파이썬 · pydantic · langchain)

> 코드에 나온 낯선 문법/용어를 초심자 눈높이로 모아둔 것. 복습용.

### 파이썬 기본
- **매개변수 / `value`**: 함수가 받는 입력을 담는 이름. `def f(value):`의 `value`가 그것. 내가 붙인 이름일 뿐이고, key-value의 value와는 무관. → "이 함수에 들어온 입력".
- **`return`**: 함수가 값을 돌려주고 끝내는 것("뱉는다"). `return value` = value를 반환.
- **`raise`**: 에러를 **일부러** 일으켜 실행을 멈춤. 예: `raise RuntimeError("메시지")`.
- **`isinstance(a, b)`**: `a`가 타입 `b`인지 True/False로 알려주는 내장 함수. 예: `isinstance(3, int)` → True.
- **`dict`(딕셔너리)**: `{"키": 값}` 쌍의 모음. `list`(목록): `[1, 2, 3]`.
- **`None`**: "값이 없음"을 뜻하는 특수값. **`str | None`**: 문자열 또는 None 둘 다 허용.
- **상속(inheritance)**: `class 자식(부모):` — 부모가 가진 기능을 물려받음.
- **`global`**: 함수 안에서 바깥(전역) 변수를 바꾸겠다고 선언(예: `_WEEK02_AGENT` 캐시).
- **f-string**: `f"...{변수}..."` 문자열 안에 값 끼워넣기. `{x!r}`는 디버깅용 표현(따옴표 포함)으로 출력.
- **데코레이터 `@tool`**: 함수 위에 붙여 기능을 덧씌우는 표시. `@tool`은 그 함수를 LangChain 도구로 등록.

### pydantic (데이터 검증 라이브러리)
- **`BaseModel`**: pydantic이 주는 부모 클래스. 상속하면 "필드 타입 검사" 기능이 생김.
- **`Field(...)`**: 필드에 기본값·설명 등 부가정보를 붙이는 함수. **`description`**은 그 필드 설명(structured output에선 LLM에게 힌트로 전달됨).
- **`default` / `default_factory`**: 기본값. 리스트처럼 매번 새로 만들어야 하는 건 `default_factory=list`.
- **`Literal[...]`**: 정해진 값들 중에서만 허용. 예: `Literal["a", "b"]`.
- **`model_validate(dict)`**: dict를 검증해 모델 **객체**로 변환(틀리면 `ValidationError`).
- **`model_dump()`**: 모델 객체를 다시 **dict**로 변환(저장/JSON용).
- **`ValidationError`**: pydantic 검증 실패 시 나는 에러.

### langchain / 이 프로젝트
- **agent**: LLM이 도구를 골라 쓰며 대화하는 실행 단위. **tool(도구)**: agent가 호출할 수 있는 함수.
- **`with_structured_output(스키마)`**: LLM 출력을 그 스키마 형태로 강제해 받는 방법(도구·대화 루프 없이 한 번 호출).
- **`response_format=스키마`**: agent 최종 답을 그 스키마로 강제 → 결과의 `structured_response`에 담김.
- **structured output / structured_response**: LLM이 자유 텍스트가 아니라 정해진 구조로 낸 결과.
- **system / user 메시지**: LLM에 주는 지시(system=규칙, user=사용자 입력).
- **`json.dumps(..., ensure_ascii=False)`**: 데이터를 JSON 문자열로 변환. `ensure_ascii=False`면 한글이 `\uXXXX`로 안 깨지고 그대로 보임.
