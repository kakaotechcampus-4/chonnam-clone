"""Week 3 과제 검증 대본.

실행:
    KANANA_ACTIVE_WEEK=3 KANANA_USE_LLM=1 PYTHONNOUSERSITE=1 .venv/Scripts/python.exe test_week03.py

week03 agent(build_week03_agent)를 여러 시나리오로 호출해
"구조화 → SQLite 저장 → 조회/수정/삭제" 흐름이 동작하는지 자동 점검합니다.

검증 포인트
  - 저장: extract_schedule_request → save_structured_request 순서, 일정 중복 저장 없음
  - kind 라우팅: personal/group은 schedules, todo/reminder는 각 테이블
  - 조회/수정/삭제: week1 임시 도구가 아니라 _saved_ SQLite 도구를 사용
  - 영속성: 대화 메모리 없이 새 호출에서도 저장 일정을 DB에서 찾음

각 시나리오는 격리된 임시 DB에서 실행하므로 실제 앱 DB를 건드리지 않습니다.
LLM 출력은 매번 조금씩 다를 수 있으니, [MISS]가 보이면 아래 출력(도구 호출·DB 상태)을 눈으로 확인하세요.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

os.environ.setdefault("KANANA_ACTIVE_WEEK", "3")
os.environ.setdefault("KANANA_USE_LLM", "1")

import student_parts.week03_build_nanas_logbook as w3
from fixed.app_store import AppSQLiteStore

# ---- 격리된 임시 DB로 _store를 교체 (실제 앱 DB 보호) ----
_STORE: AppSQLiteStore | None = None


def _fresh_store() -> AppSQLiteStore:
    """시나리오마다 새 임시 DB를 만들어 _STORE에 걸어 둡니다."""
    global _STORE
    path = Path(tempfile.mkdtemp()) / "week03_test.sqlite3"
    _STORE = AppSQLiteStore(path)
    return _STORE


w3._store = lambda: _STORE  # week03 tool들이 이 store를 사용


# ---- 점검 컨텍스트: 한 turn 실행 결과 ----
class Ctx:
    def __init__(self, tools: list[str], answer: str, store: AppSQLiteStore):
        self.tools = tools
        self.answer = answer
        self.store = store

    def schedules(self) -> list[dict[str, Any]]:
        return self.store.list_schedules(limit=200)

    def requests(self, kind: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_saved_requests(kind=kind, limit=200)


Check = Callable[[Ctx], "tuple[bool, str]"]


def called(name: str) -> Check:
    return lambda c: (name in c.tools, f"{name} 호출됨 (호출: {c.tools})")


def not_called(name: str) -> Check:
    return lambda c: (name not in c.tools, f"{name} 미호출 (호출: {c.tools})")


def schedule_count(n: int) -> Check:
    return lambda c: (len(c.schedules()) == n, f"DB 일정 {len(c.schedules())}건 (기대 {n})")


def request_kind_count(kind: str, n: int) -> Check:
    def _c(c: Ctx) -> tuple[bool, str]:
        got = len(c.requests(kind=kind))
        return got == n, f"structured_requests[{kind}] {got}건 (기대 {n})"
    return _c


def first_schedule_field(field: str, expected: Any) -> Check:
    def _c(c: Ctx) -> tuple[bool, str]:
        rows = c.schedules()
        got = rows[0].get(field) if rows else "(일정없음)"
        return got == expected, f"첫 일정 {field}={got} (기대 {expected})"
    return _c


# ---- 시나리오: 격리 DB에서 turn을 순서대로 실행 ----
SCENARIOS: list[dict[str, Any]] = [
    {
        "desc": "① 개인 일정 저장 — 구조화→저장, 중복 없음",
        "turns": [
            {
                "input": "내일 10시에 개인 코칭 일정 저장해줘",
                "checks": [
                    called("extract_schedule_request"),
                    called("save_structured_request"),
                    not_called("personal_create_schedule"),  # 중복 저장 방지
                    schedule_count(1),
                    first_schedule_field("start_time", "10:00"),
                ],
            },
        ],
    },
    {
        "desc": "② 그룹 일정 저장 — schedules 테이블로 라우팅",
        "turns": [
            {
                "input": "다음 주 화요일 오후 3시에 철수랑 회의 저장해줘",
                "checks": [
                    called("save_structured_request"),
                    schedule_count(1),
                    request_kind_count("group_schedule", 1),
                ],
            },
        ],
    },
    {
        "desc": "③ todo 저장 — schedules 아닌 todos로 라우팅",
        "turns": [
            {
                "input": "내일까지 기말 보고서 작성하는 거 급한 일로 저장해줘",
                "checks": [
                    called("save_structured_request"),
                    schedule_count(0),  # todo는 schedules 테이블에 안 들어감
                    request_kind_count("todo", 1),
                ],
            },
        ],
    },
    {
        "desc": "④ reminder 저장 — reminders로 라우팅",
        "turns": [
            {
                "input": "오후 5시에 약 먹으라고 알림 저장해줘",
                "checks": [
                    called("save_structured_request"),
                    schedule_count(0),
                    request_kind_count("reminder", 1),
                ],
            },
        ],
    },
    {
        "desc": "⑤ 저장 후 조회 — _saved_ 조회 도구 사용",
        "turns": [
            {"input": "내일 9시에 개인 스터디 저장해줘", "checks": [schedule_count(1)]},
            {
                "input": "내 저장된 일정 보여줘",
                "checks": [
                    called("personal_list_saved_schedules"),
                    not_called("personal_list_schedules"),  # week1 임시 도구 아님
                ],
            },
        ],
    },
    {
        "desc": "⑥ 수정 — 목록 확인 후 _saved_ 수정 도구",
        "turns": [
            {"input": "내일 10시에 개인 코칭 저장해줘", "checks": [first_schedule_field("start_time", "10:00")]},
            {
                "input": "내 일정 목록 보여주고 개인 코칭을 11시로 바꿔줘",
                "checks": [
                    called("personal_update_saved_schedule"),
                    first_schedule_field("start_time", "11:00"),
                ],
            },
        ],
    },
    {
        "desc": "⑦ 삭제 — week1 임시 도구가 아닌 _saved_ 삭제 도구",
        "turns": [
            {"input": "내일 14시에 개인 미팅 저장해줘", "checks": [schedule_count(1)]},
            {
                "input": "개인 미팅 일정 삭제해줘",
                "checks": [
                    called("personal_delete_saved_schedules"),
                    not_called("personal_delete_schedule"),  # week1 임시 삭제 아님
                    schedule_count(0),
                ],
            },
        ],
    },
    {
        "desc": "⑧ 영속성 — 새 호출(대화 메모리 없음)에서도 DB에서 조회",
        "turns": [
            {"input": "내일 8시에 아침 운동 저장해줘", "checks": [schedule_count(1)]},
            {
                "input": "내 일정 보여줘",
                "checks": [
                    called("personal_list_saved_schedules"),
                ],
            },
        ],
    },
    {
        "desc": "⑨ 그룹 일정 수정 — 기본 personal 필터에 가리지 않고 group도 찾아 수정",
        "turns": [
            {
                "input": "내일 오후 3시에 철수랑 회의 저장해줘",
                "checks": [schedule_count(1), request_kind_count("group_schedule", 1)],
            },
            {
                "input": "철수랑 하는 회의를 오후 4시로 바꿔줘",
                "checks": [
                    called("personal_update_saved_schedule"),
                    first_schedule_field("start_time", "16:00"),
                ],
            },
        ],
    },
    {
        "desc": "⑩ 그룹 일정 삭제 — group도 후보에 포함해 삭제",
        "turns": [
            {
                "input": "내일 오후 3시에 영희랑 점심 약속 저장해줘",
                "checks": [schedule_count(1), request_kind_count("group_schedule", 1)],
            },
            {
                "input": "영희랑 점심 약속 삭제해줘",
                "checks": [
                    called("personal_delete_saved_schedules"),
                    schedule_count(0),
                ],
            },
        ],
    },
]


MAX_ATTEMPTS = 3


def invoke_with_retry(agent: Any, text: str, max_attempts: int = MAX_ATTEMPTS):
    """agent.invoke를 호출하되 일시적 오류 시 제한 횟수만큼 재시도합니다."""
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return agent.invoke({"messages": [{"role": "user", "content": text}]}), attempt, None
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"  [retry] 시도 {attempt}/{max_attempts} 실패: {type(exc).__name__}")
    return None, max_attempts, last_err


def tool_names(result: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for msg in result.get("messages", []):
        for call in getattr(msg, "tool_calls", []) or []:
            out.append(call.get("name"))
    return out


def run() -> int:
    from fixed.runtime_clock import current_app_date_iso

    print(f"오늘(current_app_date_iso) = {current_app_date_iso()}\n")
    agent = w3.build_week03_agent()

    total = 0
    passed = 0
    hard_failures: list[str] = []

    for sc in SCENARIOS:
        print("=" * 72)
        print(sc["desc"])
        store = _fresh_store()  # 시나리오마다 격리된 새 DB

        for i, turn in enumerate(sc["turns"], start=1):
            print(f"  turn {i} 입력: {turn['input']}")
            res, attempts, err = invoke_with_retry(agent, turn["input"])
            if res is None:
                print(f"    [FAIL] {attempts}회 재시도 후에도 실패: {err!r}")
                hard_failures.append(f"{sc['desc']} turn{i} — 호출 실패")
                continue

            tools = tool_names(res)
            answer = res["messages"][-1].content
            ctx = Ctx(tools, answer, store)
            print(f"    호출 도구: {tools}")
            print(f"    답변: {answer}")
            print(f"    DB 일정: {[(s['title'], s['start_time']) for s in ctx.schedules()]}")

            for check in turn["checks"]:
                ok, detail = check(ctx)
                total += 1
                passed += 1 if ok else 0
                print(f"    {'[OK]  ' if ok else '[MISS]'} {detail}")

    print("=" * 72)
    print(f"자동 점검: {passed}/{total} 통과")
    if hard_failures:
        print(f"[FAIL] 호출 자체가 실패한 turn {len(hard_failures)}개:")
        for name in hard_failures:
            print(f"   - {name}")
    if passed == total and not hard_failures:
        print("[OK] 모든 점검을 통과했습니다.")
        return 0
    print("* [MISS]는 LLM 출력 편차일 수 있으니 위 도구 호출·DB 상태를 확인하고, 필요하면 다시 실행하세요.")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
