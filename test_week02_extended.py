"""Week 2 확장 검증 대본 (추가 탐색용, 제출용 test_week02.py와 별개).

실행:
    KANANA_ACTIVE_WEEK=2 uv run python test_week02_extended.py

test_week02.py의 ①~⑭를 통과한 뒤, 아래 네 갈래를 추가로 찔러봅니다.
  A. kind 엣지케이스 (역할 기반 참석자, 명시적 '혼자' 등)
  B. 날짜/시간 파싱 (상대 날짜, 오전/오후, 시간 미지정)
  C. 배치 분리 (한 문장에 3개 요청, kind가 섞인 배치)
  D. 추가 과제 bridge 함수(extract_schedule_request) 직접 호출
     - 이 경로는 tool을 전혀 노출하지 않으므로, personal_create_schedule
       tool-이름 편향 가설이 진짜 원인이었는지 교차 검증하는 용도입니다.

LLM 출력은 매번 다를 수 있어 [MISS]는 편차일 수 있습니다. JSON을 같이 출력하니
눈으로도 확인하세요.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Callable

from fixed.runtime_clock import current_app_date_iso
from student_parts.week02_structure_natural_language_requests import (
    StructuredRequest,
    StructuredRequestBatch,
    build_week02_agent,
    extract_schedule_request,
)

TODAY = current_app_date_iso()
_TODAY_D = date.fromisoformat(TODAY)
_MONDAY = _TODAY_D - timedelta(days=_TODAY_D.weekday())


def rel_days(n: int) -> str:
    return (_TODAY_D + timedelta(days=n)).isoformat()


def this_week(weekday: int) -> str:
    return (_MONDAY + timedelta(days=weekday)).isoformat()


def next_week(weekday: int) -> str:
    return (_MONDAY + timedelta(days=7 + weekday)).isoformat()


Check = Callable[[StructuredRequestBatch], "tuple[bool, str]"]


def has_n_requests(n: int) -> Check:
    return lambda b: (len(b.requests) == n, f"requests {len(b.requests)}개 (기대 {n})")


def first_kind_is(kind: str) -> Check:
    def _c(b: StructuredRequestBatch) -> tuple[bool, str]:
        got = b.requests[0].kind if b.requests else "(없음)"
        return got == kind, f"첫 요청 kind={got} (기대 {kind})"
    return _c


def any_kind_is(kind: str) -> Check:
    def _c(b: StructuredRequestBatch) -> tuple[bool, str]:
        kinds = [r.kind for r in b.requests]
        return kind in kinds, f"kind 목록={kinds} (포함 기대 {kind})"
    return _c


def kinds_are(kinds_expected: list[str]) -> Check:
    def _c(b: StructuredRequestBatch) -> tuple[bool, str]:
        kinds = [r.kind for r in b.requests]
        ok = sorted(kinds) == sorted(kinds_expected)
        return ok, f"kind 목록={kinds} (기대 {kinds_expected}, 순서 무관)"
    return _c


def first_date_is(expected: str) -> Check:
    def _c(b: StructuredRequestBatch) -> tuple[bool, str]:
        got = b.requests[0].date if b.requests else None
        return got == expected, f"첫 요청 date={got} (기대 {expected})"
    return _c


def first_start_is(t: str) -> Check:
    def _c(b: StructuredRequestBatch) -> tuple[bool, str]:
        got = b.requests[0].start_time if b.requests else None
        return got == t, f"첫 요청 start_time={got} (기대 {t})"
    return _c


def first_start_is_none() -> Check:
    def _c(b: StructuredRequestBatch) -> tuple[bool, str]:
        got = b.requests[0].start_time if b.requests else "?"
        return got is None, f"첫 요청 start_time={got} (기대 None, 억지로 안 만들기)"
    return _c


def first_member_contains(name: str) -> Check:
    def _c(b: StructuredRequestBatch) -> tuple[bool, str]:
        members = b.requests[0].members if b.requests else []
        return name in members, f"첫 요청 members={members} (포함 기대 {name})"
    return _c


def first_members_empty() -> Check:
    def _c(b: StructuredRequestBatch) -> tuple[bool, str]:
        members = b.requests[0].members if b.requests else ["?"]
        return members == [], f"첫 요청 members={members} (기대 빈 리스트)"
    return _c


# ── A. kind 엣지케이스 ────────────────────────────────────────────────
# ── B. 날짜/시간 파싱 ────────────────────────────────────────────────
# ── C. 배치 분리 ────────────────────────────────────────────────────
SCENARIOS: list[dict[str, Any]] = [
    {
        "desc": "A1) 역할 기반 참석자(이름 아님) → group_schedule",
        "input": "고객이랑 미팅 잡아줘",
        "checks": [first_kind_is("group_schedule")],
    },
    {
        "desc": "A2) 참석자 없는 마감 작업 → todo",
        "input": "나 혼자 이 프로젝트 끝내야 해, 마감 다음 주 금요일",
        "checks": [first_kind_is("todo"), first_members_empty()],
    },
    {
        "desc": "A3) '아무도 안 데려간다' 명시 → personal_schedule",
        "input": "다음 주 목요일에 상담 예약 있어, 아무도 안 데려가",
        "checks": [first_kind_is("personal_schedule"), first_date_is(next_week(3))],
    },
    {
        "desc": "A4) 역할 기반 참석자 + 알림 동사 → 동작 동사 우선 reminder",
        "input": "교수님이랑 면담 있는 거 잊지 않게 알려줘",
        "checks": [first_kind_is("reminder")],
    },
    {
        "desc": "B1) 모레 + '오전'(비정밀 시간) → start_time None 유지",
        "input": "모레 오전에 미용실 예약해줘",
        "checks": [
            first_kind_is("personal_schedule"),
            first_date_is(rel_days(2)),
            first_start_is_none(),
        ],
    },
    {
        "desc": "B2) 오늘 + '저녁'(비정밀 시간) → date는 오늘, 시간은 None",
        "input": "오늘 저녁에 운동하기로 했어",
        "checks": [
            first_kind_is("personal_schedule"),
            first_date_is(TODAY),
            first_start_is_none(),
        ],
    },
    {
        "desc": "C1) 세 요청(personal/group/reminder) 배치 분리",
        "input": "내일 아침에 운동하고, 점심엔 철수랑 밥 먹고, 저녁엔 보고서 마감 알림 걸어줘",
        "checks": [
            has_n_requests(3),
            kinds_are(["personal_schedule", "group_schedule", "reminder"]),
        ],
    },
    {
        "desc": "C2) 같은 kind가 두 번(화요일/목요일 팀 회의) 배치 분리",
        "input": "다음 주에 팀 회의 두 번 있어, 화요일이랑 목요일",
        "checks": [
            has_n_requests(2),
            kinds_are(["group_schedule", "group_schedule"]),
        ],
    },
]


# ── D. 추가 과제 bridge 함수(extract_schedule_request) 직접 호출 ─────────
# agent 경로와 달리 tool을 전혀 노출하지 않으므로, personal_create_schedule
# 이름 편향과 무관하게 kind가 잘 나오는지 교차 검증합니다.
BRIDGE_SCENARIOS: list[dict[str, Any]] = [
    {
        "desc": "D1) [agent에서 깨졌던 문장] 참석자 있는 명시적 요청 → group_schedule",
        "input": "다음 주 화요일 오후 3시에 철수랑 회의 잡아줘",
        "expect_kind": "group_schedule",
    },
    {
        "desc": "D2) [예시2] 참석자 + 알람 동사 → reminder",
        "input": "철수랑 회의 있는 거 알람해줘",
        "expect_kind": "reminder",
    },
    {
        "desc": "D3) [예시3] 참석자 있는 진술형 → group_schedule",
        "input": "영희랑 저녁 약속 있어",
        "expect_kind": "group_schedule",
    },
    {
        "desc": "D4) [예시1] todo/reminder 겹침 → reminder",
        "input": "내일 3시까지 보고서 작성해야하는 거 알람해줘",
        "expect_kind": "reminder",
    },
]


MAX_ATTEMPTS = 3


def invoke_with_retry(agent: Any, text: str, max_attempts: int = MAX_ATTEMPTS):
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            res = agent.invoke({"messages": [{"role": "user", "content": text}]})
            return res, attempt, None
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"  [retry] 시도 {attempt}/{max_attempts} 파싱 실패: {type(exc).__name__}")
    return None, max_attempts, last_err


def run_agent_scenarios() -> tuple[int, int, list[str]]:
    print(f"오늘(current_app_date_iso) = {TODAY}\n")
    agent = build_week02_agent()

    total_checks = 0
    passed_checks = 0
    failed_scenarios: list[str] = []

    for sc in SCENARIOS:
        print("=" * 72)
        print(f"{sc['desc']}")
        print(f"  입력: {sc['input']}")

        res, attempts, err = invoke_with_retry(agent, sc["input"])
        if res is None:
            print(f"  [FAIL] {attempts}회 재시도 후에도 실패: {err!r}")
            failed_scenarios.append(f"{sc['desc']} — 파싱 실패")
            continue
        if attempts > 1:
            print(f"  [OK] {attempts}번째 시도에서 성공")

        sr = res.get("structured_response")
        if not isinstance(sr, StructuredRequestBatch):
            print(f"  [FAIL] structured_response 타입: {type(sr).__name__}")
            failed_scenarios.append(f"{sc['desc']} — 배치 아님")
            continue

        print("  결과:")
        print("    " + json.dumps(sr.model_dump(), ensure_ascii=False, indent=2).replace("\n", "\n    "))

        for check in sc["checks"]:
            ok, detail = check(sr)
            total_checks += 1
            passed_checks += 1 if ok else 0
            print(f"    {'[OK]  ' if ok else '[MISS]'} {detail}")

    return passed_checks, total_checks, failed_scenarios


def run_bridge_scenarios() -> tuple[int, int]:
    print("\n" + "#" * 72)
    print("# D. bridge 함수(extract_schedule_request) 직접 호출 — tool 미노출 경로")
    print("#" * 72)

    passed = 0
    total = 0
    for sc in BRIDGE_SCENARIOS:
        print("=" * 72)
        print(f"{sc['desc']}")
        print(f"  입력: {sc['input']}")
        try:
            raw = extract_schedule_request.invoke({"query": sc["input"]})
            payload = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] 호출 실패: {type(exc).__name__}: {exc}")
            continue

        print("  결과:")
        print("    " + json.dumps(payload, ensure_ascii=False, indent=2).replace("\n", "\n    "))

        got_kind = payload.get("structured_request", {}).get("kind")
        ok = got_kind == sc["expect_kind"]
        total += 1
        passed += 1 if ok else 0
        print(f"    {'[OK]  ' if ok else '[MISS]'} kind={got_kind} (기대 {sc['expect_kind']})")

    return passed, total


def run() -> None:
    passed_a, total_a, failed = run_agent_scenarios()
    passed_d, total_d = run_bridge_scenarios()

    print("\n" + "=" * 72)
    print(f"[A/B/C] agent 경로 자동 점검: {passed_a}/{total_a} 통과")
    if failed:
        print(f"[FAIL] 재시도 후에도 실패한 시나리오 {len(failed)}개:")
        for name in failed:
            print(f"   - {name}")
    print(f"[D] bridge 경로 자동 점검: {passed_d}/{total_d} 통과")
    print("* [MISS]는 LLM 출력 편차일 수 있으니 위 JSON을 눈으로 같이 확인하세요.")


if __name__ == "__main__":
    run()
