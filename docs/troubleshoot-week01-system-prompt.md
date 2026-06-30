# 트러블슈팅: LLM이 오늘 날짜를 모르는 문제

**파일**: `student_parts/week01_wake_up_nana.py`  
**함수**: `week01_prompt_parts()`

---

## 증상

채팅에 "내일 오후 2시에 회의 일정 만들어줘"를 입력하면 LLM이 날짜를 **2023-10-05**, **2024-04-28** 등 과거 날짜로 추론해 tool을 호출한다.

```json
{
  "title": "회의",
  "date": "2023-10-05",
  "start_time": "14:00"
}
```

---

## 원인

### 원인 1: `week01_prompt_parts()`가 빈 리스트 반환

LLM에게 전달되는 시스템 프롬프트에 실질적인 지시가 없다.

```python
def week01_prompt_parts() -> list[str]:
    return [
        # TODO: Week 1 Nana 일정 agent system prompt를 자유롭게 추가하세요.
        # ← 아무것도 없음. LLM은 날짜를 모름.
    ]
```

### 원인 2: `CHAT_MEMORY_PROMPT`에 f-string 없이 함수 호출 작성

`CHAT_MEMORY_PROMPT`는 모듈 로드 시 한 번만 평가되는 상수다.  
일반 `"""..."""` 안에 `{current_app_date_iso()}`를 넣으면 함수가 호출되지 않고 그냥 텍스트로 들어간다.

```python
# ❌ 잘못된 패턴 — 함수 호출 안 됨
CHAT_MEMORY_PROMPT = """너는 Nana...
오늘 날짜: {current_app_date_iso()}   ← f-string 아님, 그냥 텍스트
"""
```

---

## 시스템 프롬프트 흐름

```
week01_prompt_parts()       ← 여기에 내용을 넣어야 함
        ↓
week01_system_prompt()      ← join_system_prompt()로 parts 합침
        ↓
build_week01_agent()        ← create_agent(..., system_prompt=...)로 LLM에 전달
        ↓
LLM (GPT-4.1-mini)          ← 시스템 프롬프트 받아 tool 선택·날짜 추론
```

---

## 해결

> **날짜는 동적으로 넣어야 한다.**  
> `CHAT_MEMORY_PROMPT`는 모듈 로드 시 고정되므로, `current_app_date_iso()`는 반드시 `week01_prompt_parts()` 안에서 f-string으로 호출해야 매 실행마다 오늘 날짜가 들어간다.

```python
# CHAT_MEMORY_PROMPT — 고정 텍스트만
CHAT_MEMORY_PROMPT = """너는 Nana, 개인 일정 관리 assistant다.
일정 생성/조회/삭제 요청에는 반드시 tool을 사용해라.
날짜 언급 없으면 오늘 날짜 기준으로 추론해라."""

# week01_prompt_parts() — 동적 날짜는 f-string으로
def week01_prompt_parts() -> list[str]:
    return [
        CHAT_MEMORY_PROMPT,
        f"오늘 날짜: {current_app_date_iso()}",  # ← 매 실행마다 갱신
    ]
```

---

## 요약

| 항목 | 잘못된 방법 | 올바른 방법 |
|------|------------|------------|
| 날짜 삽입 위치 | `CHAT_MEMORY_PROMPT` 상수 안 | `week01_prompt_parts()` 안 |
| 문자열 형식 | 일반 `"""` — 함수 호출 안 됨 | `f"""` — 함수 실행됨 |
| 날짜 함수 | 생략 또는 하드코딩 | `current_app_date_iso()` |
| `CHAT_MEMORY_PROMPT` 용도 | 동적 내용 포함 | 고정 역할·규칙 텍스트만 |
