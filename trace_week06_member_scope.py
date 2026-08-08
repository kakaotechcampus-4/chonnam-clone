"""Week 6 트레이스 — 리뷰 ①: '전원(다들)' 요청에서 member_names 필수 스키마가 문제인가.

배경
    find_common_available_slots는 member_names가 required입니다(FindCommonAvailableSlotsInput).
    Week 5에서 collect_member_schedules/extract_schedules_from_history는 member_names를
    선택 필드로 두고 "생략 = 등록 멤버 전원 + 나"로 확정했습니다. 리뷰어(GitJIHO)는
    week6의 required 스키마로 "다들 언제 되는지"처럼 전원을 지칭하는 요청을 제대로
    표현할 수 있는지 물었습니다. 실제로 문제가 되는지 트레이스로 확인합니다.

무엇을 보나요
    같은 발화를 여러 번 돌려(라우팅은 LLM 판단이라 흔들림) 매 실행마다:
      · supervisor가 kana_agent로 위임했는가
      · find_common_available_slots가 실제로 호출됐는가, 그때 member_names 인자는 무엇인가
      · 그 member_names가 등록 멤버 전원({민준,서연,영희,지훈,철수,하린})을 덮었는가,
        아니면 일부만/빈 목록/엉뚱한 이름이었는가 (= required 스키마가 전원 표현을 막는가)
      · 도구가 ok=False로 실패했는가

    하드 판정은 두지 않습니다(전원 표현은 모델 판단). '전원 커버율'을 관찰로 모아
    required가 실제 회귀를 만드는지 근거를 남깁니다.

실행:
    KANANA_ACTIVE_WEEK=6 PYTHONNOUSERSITE=1 uv run python trace_week06_member_scope.py
"""

from __future__ import annotations

from fixed.config import CONFIG
from fixed.langchain_trace import extract_agent_events, extract_final_text
from fixed.session_scope import conversation_session_scope
from student_parts.week06_kanamate_decides_schedule import build_week_agent
from trace_week06_common import app_ids, cleanup_new_rows, shared_ids

# collect_member_schedules(member_names=None)이 돌려준 등록 멤버 전원 (나 제외 외부 멤버)
ALL_MEMBERS = {"민준", "서연", "영희", "지훈", "철수", "하린"}

# 발화 세트: 순수 모호형(날짜 없음)과 날짜 포함형. 둘 다 "다들/전원"을 지칭합니다.
UTTERANCES = [
    ("vague", "다들 언제 되는지 회의 시간 찾아줘."),
    ("dated", "다들 2026년 7월에 공통으로 회의 가능한 시간을 찾아줘."),
]
REPEAT = 3


def _supervisor_calls(result: dict) -> list[str]:
    return [
        ev["tool_name"]
        for ev in extract_agent_events(result)
        if ev.get("event") == "tool_call" and ev.get("tool_name") in {"nana_agent", "kana_agent"}
    ]


def _kana_inner_events(result: dict) -> list[dict]:
    """kana_agent tool_result content의 하위 trace(events)를 펼쳐 돌려줍니다."""

    inner: list[dict] = []
    for ev in extract_agent_events(result):
        if ev.get("event") == "tool_result" and ev.get("tool_name") == "kana_agent":
            content = ev.get("content")
            if isinstance(content, dict):
                inner.extend(content.get("trace", []) or [])
    return inner


def _find_slot_calls(inner: list[dict]) -> list[dict]:
    """하위 trace에서 find_common_available_slots tool_call의 arguments를 모읍니다."""

    return [
        ev.get("arguments") or {}
        for ev in inner
        if ev.get("event") == "tool_call" and ev.get("tool_name") == "find_common_available_slots"
    ]


def _find_slot_results(inner: list[dict]) -> list[dict]:
    out: list[dict] = []
    for ev in inner:
        if ev.get("event") == "tool_result" and ev.get("tool_name") == "find_common_available_slots":
            c = ev.get("content")
            if isinstance(c, dict):
                out.append(c)
    return out


def run() -> int:
    if not CONFIG.has_openai_key:
        print("⚠️ .env의 PROXY_TOKEN이 필요합니다. 키를 넣고 다시 실행하세요.")
        return 1

    print("#" * 78)
    print("# Week 6 트레이스 — 리뷰 ①: '전원(다들)' 요청 vs member_names 필수 스키마")
    print("#" * 78)
    print(f"등록 멤버 전원(나 제외): {sorted(ALL_MEMBERS)}\n")

    app_before, shared_before = app_ids(), shared_ids()
    agent = build_week_agent()

    coverage_notes: list[str] = []
    try:
        for kind, text in UTTERANCES:
            print("=" * 78)
            print(f"[{kind}] \"{text}\"  (x{REPEAT})")
            for i in range(1, REPEAT + 1):
                with conversation_session_scope(f"trace_w6_scope_{kind}_{i}"):
                    result = agent.invoke({"messages": [{"role": "user", "content": text}]})
                calls = _supervisor_calls(result)
                inner = _kana_inner_events(result)
                slot_calls = _find_slot_calls(inner)
                slot_results = _find_slot_results(inner)

                delegated = "kana_agent" in calls
                called = bool(slot_results)
                # 겹침 계산은 busy_rows가 하므로 '전원 고려' 여부는 member_names 인자(라벨)가 아니라
                # find_slots가 실제로 받은 busy_rows가 덮는 멤버 + payload members로 판정합니다.
                # (LLM은 collect로 전원 rows를 모은 뒤 member_names는 []나 None으로 비워 넘기는 일이 잦습니다.)
                considered: set[str] = set()
                for r in slot_results:
                    considered.update(str(m) for m in (r.get("members") or []))
                    considered.update(
                        str(row.get("member_name"))
                        for row in (r.get("busy_rows") or [])
                        if row.get("member_name")
                    )
                covered = ALL_MEMBERS & considered
                missing = ALL_MEMBERS - considered
                arg_members = [str(m) for m in (slot_calls[0].get("member_names") or [])] if slot_calls else None
                ok = all(r.get("ok", True) for r in slot_results) if slot_results else None

                print(f"  run{i}: 위임={' → '.join(calls) or '(없음)'} | find_slots호출={called}")
                if called:
                    print(f"         member_names 인자(라벨)={arg_members}")
                    print(f"         전원고려(busy_rows∪members)={len(covered)}/{len(ALL_MEMBERS)}"
                          f" | 누락={sorted(missing) or '없음'} | tool_ok={ok}")
                    coverage_notes.append(
                        f"[{kind} run{i}] 전원고려 {len(covered)}/{len(ALL_MEMBERS)}, "
                        f"누락={sorted(missing) or '없음'}, 인자라벨={arg_members}")
                else:
                    # find_slots를 아예 안 불렀으면 답변 앞부분으로 왜 그런지 관찰
                    ans = extract_final_text(result)[:160].replace("\n", " ")
                    print(f"         (find_slots 미호출) 위임됨={delegated} | 답변앞부분={ans}")
                    coverage_notes.append(f"[{kind} run{i}] find_slots 미호출 (위임={delegated})")
    finally:
        cleanup_new_rows(app_before, shared_before)

    print("\n" + "=" * 78)
    print("요약 — 전원 커버 관찰")
    print("-" * 78)
    for note in coverage_notes:
        print("  · " + note)
    print("\n판정 기준(사람이 읽고): member_names를 선택화한 뒤에도 매 실행 busy_rows∪members가")
    print("전원 6명을 덮으면, LLM이 인자를 비워 넘겨도(collect로 전원 rows를 모으므로) 전원 조율이 유지됨.")
    print("누락이 반복되면 collect 단계에서 전원 수집이 새는 것이므로 그쪽을 봐야 함.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
