"""Week 2 과제 검증 대본.

실행:
    KANANA_ACTIVE_WEEK=2 PYTHONNOUSERSITE=1 .venv/Scripts/python.exe test_week02.py

week02 agent(build_week02_agent)를 여러 시나리오로 호출해
structured_response가 StructuredRequestBatch로 잘 나오는지,
각 필드가 요구사항대로 채워지는지 자동 점검합니다.
LLM 출력은 매번 조금씩 다를 수 있으므로, 확정적인 부분만 검사하고
나머지는 눈으로 확인하도록 전체 결과를 출력합니다.
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
)

TODAY = current_app_date_iso()  # 앱 클럭 기준 오늘 (예: 2026-07-10)
_TODAY_D = date.fromisoformat(TODAY)
_MONDAY = _TODAY_D - timedelta(days=_TODAY_D.weekday())  # 이번 주 월요일


def rel_days(n: int) -> str:
    """오늘 기준 n일 뒤 날짜(YYYY-MM-DD)."""
    return (_TODAY_D + timedelta(days=n)).isoformat()


def this_week(weekday: int) -> str:
    """이번 주 특정 요일 날짜. weekday는 0=월 ... 6=일."""
    return (_MONDAY + timedelta(days=weekday)).isoformat()


def next_week(weekday: int) -> str:
    """다음 주 특정 요일 날짜. weekday는 0=월 ... 6=일."""
    return (_MONDAY + timedelta(days=7 + weekday)).isoformat()


# 각 시나리오: 입력 문장 + 기대 설명 + 자동 점검 함수 목록
# 점검 함수는 (batch) -> (통과여부: bool, 설명: str)
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


def first_member_contains(name: str) -> Check:
    def _c(b: StructuredRequestBatch) -> tuple[bool, str]:
        members = b.requests[0].members if b.requests else []
        return name in members, f"첫 요청 members={members} (포함 기대 {name})"
    return _c


def first_start_is_none() -> Check:
    def _c(b: StructuredRequestBatch) -> tuple[bool, str]:
        got = b.requests[0].start_time if b.requests else "?"
        return got is None, f"첫 요청 start_time={got} (기대 None, 억지로 안 만들기)"
    return _c


def first_priority_set() -> Check:
    def _c(b: StructuredRequestBatch) -> tuple[bool, str]:
        got = b.requests[0].priority if b.requests else None
        return bool(got), f"첫 요청 priority={got} (기대 값 있음)"
    return _c


def base_date_is_today() -> Check:
    return lambda b: (b.base_date == TODAY, f"base_date={b.base_date} (기대 {TODAY})")


SCENARIOS: list[dict[str, Any]] = [
    {
        "desc": "① 그룹 일정 · 식별 가능한 타인(철수) → group_schedule",
        "input": "다음 주 화요일 오후 3시에 철수랑 회의 잡아줘",
        "checks": [
            has_n_requests(1),
            first_kind_is("group_schedule"),  # 본인 외 참석자(철수)가 있으므로 group
            first_date_is(next_week(1)),  # 다음 주 화요일
            first_start_is("15:00"),
            first_member_contains("철수"),
            base_date_is_today(),
        ],
    },
    {
        "desc": "② 여러 요청 한 문장 → 배치 분리",
        "input": "내일 오전 10시에 팀 회의 잡고, 모레는 병원 예약 알림 걸어줘",
        "checks": [
            has_n_requests(2),
        ],
    },
    {
        "desc": "③ 할 일(todo) + 우선순위",
        "input": "내일까지 기말 보고서 작성하는 거 급한 일로 등록해줘",
        "checks": [
            first_kind_is("todo"),
            first_priority_set(),
        ],
    },
    {
        "desc": "④ 리마인더(reminder)",
        "input": "오후 5시에 약 먹으라고 알려줘",
        "checks": [
            first_kind_is("reminder"),
            first_start_is("17:00"),
        ],
    },
    {
        "desc": "④-2 todo vs reminder 겹침 → 동작 동사 우선(알람) → reminder",
        "input": "내일 3시까지 보고서 작성해야하는 거 알람해줘",
        "checks": [
            first_kind_is("reminder"),  # 내용은 todo지만 '알람해줘' 동작이 이김
            first_date_is(rel_days(1)),  # 마감(내일)은 date에 보존
        ],
    },
    {
        "desc": "⑤ 그룹 일정(group_schedule) · 멤버 다수",
        "input": "이번 주 금요일 저녁 7시에 팀원들이랑 회식하자. 영희랑 민수 부를게",
        "checks": [
            any_kind_is("group_schedule"),
            first_date_is(this_week(4)),  # 이번 주 금요일
        ],
    },
    {
        "desc": "⑥ 시간 미지정 → start_time None 유지 (추측 금지)",
        "input": "다음 주 월요일에 치과 예약 잡아줘",
        "checks": [
            first_kind_is("personal_schedule"),
            first_date_is(next_week(0)),  # 다음 주 월요일
            first_start_is_none(),
        ],
    },
    {
        "desc": "⑦ 모호한 요청 → unknown",
        "input": "음, 그냥 뭐 좀 정리 좀 해줘",
        "checks": [
            any_kind_is("unknown"),
        ],
    },
    {
        "desc": "⑧ week01 tool 연동 흐름 (create 결과 JSON을 구조화)",
        "input": "내일 오전 9시에 개인 코딩 공부 일정 만들어줘",
        "checks": [
            first_kind_is("personal_schedule"),
            first_date_is(rel_days(1)),  # 내일
            first_start_is("09:00"),
        ],
    },
]


MAX_ATTEMPTS = 3  # 파싱 실패 시 제한된 재시도 횟수


def invoke_with_retry(agent: Any, text: str, max_attempts: int = MAX_ATTEMPTS):
    """agent.invoke를 호출하되 파싱 실패 시 제한된 횟수만큼 재시도합니다.

    native response_format 경로는 드물게 두 번째 JSON을 덧붙여 'Extra data' 파싱
    오류를 냅니다. 운영 코드의 정석대로 예외를 잡고 제한 재시도한 뒤, 끝내 실패하면
    그 사실을 그대로 기록합니다.
    반환: (결과 또는 None, 사용한 시도 횟수, 마지막 예외 또는 None)
    """
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            res = agent.invoke({"messages": [{"role": "user", "content": text}]})
            return res, attempt, None
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"  [retry] 시도 {attempt}/{max_attempts} 파싱 실패: {type(exc).__name__}")
    return None, max_attempts, last_err


def run() -> None:
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
        is_batch = isinstance(sr, StructuredRequestBatch)
        if not is_batch:
            print(f"  [FAIL] structured_response 타입: {type(sr).__name__}")
            print(f"     RAW: {sr}")
            failed_scenarios.append(f"{sc['desc']} — 배치 아님")
            continue
        print(f"  [OK] structured_response 타입: {type(sr).__name__}")

        print("  결과:")
        print(
            "    "
            + json.dumps(sr.model_dump(), ensure_ascii=False, indent=2).replace("\n", "\n    ")
        )

        for check in sc["checks"]:
            ok, detail = check(sr)
            total_checks += 1
            passed_checks += 1 if ok else 0
            print(f"    {'[OK]  ' if ok else '[MISS]'} {detail}")

    print("=" * 72)
    print(f"자동 점검: {passed_checks}/{total_checks} 통과")
    if failed_scenarios:
        print(f"[FAIL] 재시도 후에도 실패한 시나리오 {len(failed_scenarios)}개:")
        for name in failed_scenarios:
            print(f"   - {name}")
    else:
        print("[OK] 모든 시나리오가 배치 구조화에 성공했습니다.")
    print("* [MISS] 표시는 LLM 출력 편차일 수 있으니 위 결과(JSON)를 눈으로 확인하세요.")


if __name__ == "__main__":
    run()
