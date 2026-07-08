# 트러블슈팅: Week 2 이전 턴 요청이 배치에 중복 포함되고 priority가 오염됨

**파일**: `student_parts/week02_structure_natural_language_requests.py`
**함수**: `week02_prompt_parts()`

---

## 증상

`./run.sh --week2`로 실행한 뒤 같은 대화에서 메시지를 두 번 입력하면,
두 번째 응답의 `requests`에 **첫 번째 턴에서 이미 구조화한 요청이 다시 포함**된다.

1번째 입력: "이틀 뒤 3시 철수와 미팅 약속 잡아줘"

```python
StructuredRequestBatch(requests=[
    StructuredRequest(kind='personal_schedule', title='미팅', date='2026-07-10',
                      start_time='15:00', members=['철수'], priority=None, ...),
], base_date='2026-07-08')
```

2번째 입력: "급한 일정이야 다음주 월요일 오후 3시에 영희와 3시간동안의 회의가 있어"

```python
StructuredRequestBatch(requests=[
    # ❌ 이전 턴의 철수 미팅이 다시 포함됨. priority까지 None → '높음'으로 바뀜
    StructuredRequest(kind='personal_schedule', title='미팅', date='2026-07-10',
                      start_time='15:00', members=['철수'], priority='높음', ...),
    StructuredRequest(kind='personal_schedule', title='회의', date='2026-07-13',
                      start_time='15:00', end_time='18:00', members=['영희'],
                      priority='높음', ...),
], base_date='2026-07-08')
```

문제는 두 가지다.

1. 이미 구조화가 끝난 과거 요청이 매 턴 배치에 누적된다.
2. 새 메시지의 표현("급한 일정이야")이 **이전 턴의 요청에 소급 적용**되어
   철수 미팅의 `priority`가 `None`에서 `'높음'`으로 오염된다.

Week 2에서는 저장을 하지 않아 화면 표시만 이상하지만, Week 3에서 이 결과를
SQLite에 저장하기 시작하면 **같은 일정이 턴마다 중복 저장**되는 버그로 이어진다.

---

## 원인

### 원인 1: agent에 현재 메시지가 아니라 대화 전체 히스토리가 넘어간다

`fixed/agent_runtime.py`의 `run_agent()`/`stream_agent()`는 agent를 호출할 때
방금 입력한 메시지 하나가 아니라 **현재 대화의 user/assistant 메시지 전체**를 넘긴다.

```python
# fixed/agent_runtime.py
previous_messages = self.app_store.load_conversation(conversation_id)
...
messages = self._agent_messages(previous_messages, user_message)  # 히스토리 + 새 메시지
result = run_active_week_agent(self.active_week, messages)
```

이는 "그 회의 3시로 바꿔줘" 같은 후속 발화를 해석하려면 필요한 구조이므로
`fixed/` 쪽을 고칠 문제가 아니다.

### 원인 2: 시스템 프롬프트에 구조화 범위 지시가 없다

LLM 입장에서는 대화에 등장한 모든 일정 요청이 눈에 보이는데,
시스템 프롬프트에 "무엇을 구조화 대상으로 삼을지"에 대한 지시가 없으면
**대화 전체를 다시 구조화**하는 쪽으로 동작한다. 이 과정에서 새 메시지의
맥락("급한 일정이야")이 과거 요청의 필드에까지 번진다.

---

## 재구조화 흐름

```
1턴: "이틀 뒤 3시 철수와 미팅"      → requests=[철수 미팅(priority=None)]
        ↓ (user/assistant 메시지가 DB에 저장됨)
2턴: "급한 일정이야 ... 영희와 회의"
        ↓
agent 입력 = [1턴 user, 1턴 assistant, 2턴 user]   ← 히스토리 전체가 넘어감
        ↓
LLM이 대화에 보이는 요청을 전부 구조화             ← 범위 지시가 없음
        ↓
requests=[철수 미팅(priority='높음'), 영희 회의(priority='높음')]
         └ 중복 포함 + priority 오염
```

---

## 해결

> **시스템 프롬프트에 구조화 범위를 명시한다.**
> 히스토리가 들어오는 것 자체는 막을 수 없으므로, "받되 구조화 대상은
> 마지막 사용자 메시지 하나"라고 범위를 잘라준다. 단, 히스토리를 완전히
> 무시하라고 하면 후속 발화 해석이 불가능해지므로 "맥락 참고용" 예외를 남긴다.

`week02_prompt_parts()`의 안내 문구에 아래 두 줄을 추가한다.

```python
def week02_prompt_parts() -> list[str]:
    return [
        *week01_prompt_parts(),
        f"""
        [2주차 구조화 agent 안내]
        ...(기존 지시)...
        - 구조화 대상은 가장 마지막 사용자 메시지 하나로 한정하세요. 이전 대화는 대명사 해석 등 맥락 참고용일 뿐,
          이미 구조화한 과거 요청을 requests에 다시 포함하지 마세요.
        - 마지막 메시지의 표현(예: "급한 일정이야")을 이전 턴의 요청에 소급 적용하지 마세요.
        """,
    ]
```

- 첫 줄이 핵심 규칙이다. 중복 포함과 priority 오염 둘 다 이 규칙 하나로 대부분 해결된다.
- 둘째 줄은 오염 방지 보강이다. LLM은 부정 지시만 있을 때보다 실제 사례를
  예시로 들어줄 때 훨씬 잘 따르므로, 실제 겪은 표현을 그대로 예시로 넣었다.

### 확인 방법

`_WEEK02_AGENT`가 전역 캐시이고 시스템 프롬프트는 agent 생성 시점에 문자열로
고정되므로, **앱을 재시작한 뒤** 같은 두 문장을 순서대로 입력한다.

- 두 번째 응답의 `requests`에 영희 회의 **하나만** 있으면 성공
- 철수 미팅이 다시 나타나거나 필드가 바뀌어 있으면 실패

---

## 요약

| 항목 | 수정 전 | 수정 후 |
|------|--------|--------|
| 구조화 범위 지시 | 없음 → 대화 전체를 재구조화 | 마지막 사용자 메시지로 한정 |
| 과거 요청 중복 | 턴마다 requests에 누적 | 새 요청만 포함 |
| priority 오염 | 새 메시지 표현이 과거 요청에 소급 적용 | 마지막 메시지에만 적용 |
| 히스토리 전달 (`fixed/agent_runtime.py`) | 후속 발화 해석에 필요한 구조 | 수정하지 않음 — 프롬프트로 해결 |
| 반영 방법 | — | 앱 재시작 필요 (`_WEEK02_AGENT` 전역 캐시) |
