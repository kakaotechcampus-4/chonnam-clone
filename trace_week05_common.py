"""Week 5 트레이스 대본들이 공유하는 실행 harness.

왜 공용 모듈인가
    대본을 목적별로 쪼개면 턴 인쇄·판정·뒷정리 코드가 그대로 복제됩니다.
    그 부분만 여기 모아 두고, 각 대본은 "무엇을 물어볼지"에만 집중합니다.

왜 대본을 쪼개는가
    한 대본에 케이스를 몰아넣으면 대화가 길어지고, 뒤쪽 턴은 도구를 부르지 않고
    앞 대화 기억으로 답해 버립니다(30턴 실행에서 실제로 관찰됨). 그러면 그 케이스는
    검증력을 잃습니다. 대본마다 대화를 새로 시작하면 모든 케이스가 도구를 다시 거칩니다.

각 대본의 구조
    def run() -> int:            # 0 = 통과, 1 = 실패 있음
        t = TraceRun("제목", "세션id")
        turn = t.turn("분류", "입력", 기대tool집합)
        t.check("판정 이름", 조건)
        t.cleanup(("이 대본이 만든 일정 제목",))
        return t.summary()
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from fixed.app_store import AppSQLiteStore
from fixed.config import CONFIG
from fixed.external_people_store import ExternalPeopleSQLiteStore, external_db_path_from_env
from fixed.langchain_trace import extract_agent_events, extract_final_text
from fixed.session_scope import conversation_session_scope
from student_parts.week01_wake_up_nana import PERSONAL_SCHEDULES
from student_parts.week03_build_nanas_logbook import personal_delete_saved_schedules
from student_parts.week05_load_kanas_past_conversations import build_week05_agent


# ── 기대 tool 묶음 (대본들이 함께 씁니다) ──────────────────────────────────
SEARCH_TOOLS = {"search_previous_conversations"}
LOAD_TOOLS = {"load_conversation_messages"}
EXTRACT_TOOLS = {"extract_schedules_from_history"}
COLLECT_TOOLS = {"collect_member_schedules"}
SHARED_LIST_TOOLS = {"list_shared_schedules"}
SHARED_WRITE_TOOLS = {"create_shared_schedule"}
SHARED_DELETE_TOOLS = {"delete_shared_schedule"}
# 외부 멤버 busy-time은 두 경로 모두 근거가 됩니다(collect는 extract의 상위집합).
BUSY_TOOLS = COLLECT_TOOLS | EXTRACT_TOOLS
WEEK1234_TOOLS = {
    "personal_create_schedule",
    "personal_list_schedules",
    "personal_list_saved_schedules",
    "personal_update_saved_schedule",
    "personal_delete_saved_schedules",
    "save_structured_request",
    "extract_schedule_request",
    "search_personal_references",
    "search_saved_requests",
    "search_conversation_messages",
    "add_personal_reference",
    "list_saved_requests",
    "get_saved_request",
}

# 외부 실습 데이터는 이 구간에 seed되어 있습니다 — 날짜를 물을 때 이 구간을 씁니다.
PRACTICE_DATE_FROM = "2026-07-07"
PRACTICE_DATE_TO = "2026-07-17"


def shared_rows() -> list[dict[str, Any]]:
    """공유 저장소 row 전체를 봅니다.

    필터 없이 부르면 store가 7월 실습 기본 row만 돌려주므로, 넓은 날짜 범위를 명시해
    앱에서 동기화된 row까지 함께 봅니다.
    """

    store = ExternalPeopleSQLiteStore(external_db_path_from_env())
    return store.list_shared_schedules(date_from="2000-01-01", date_to="2100-01-01", limit=500)


def shared_ids() -> set[str]:
    """공유 저장소 row id 집합 — 실행 중 새로 생긴 row를 구분하는 기준선입니다."""

    return {str(row.get("schedule_id")) for row in shared_rows()}


def tool_payloads(events: list[dict], tool_name: str) -> list[dict[str, Any]]:
    """이번 턴에서 특정 tool이 돌려준 payload들을 dict로 모읍니다.

    extract_agent_events가 tool 결과를 이미 json.loads 해서 dict로 넣어주므로
    dict를 우선 받고, 파싱에 실패해 문자열로 남은 경우만 여기서 파싱합니다.
    """

    payloads: list[dict[str, Any]] = []
    for ev in events:
        if ev.get("event") == "tool_call" or ev.get("tool_name") != tool_name:
            continue
        content = ev.get("content")
        if isinstance(content, dict):
            payloads.append(content)
        elif isinstance(content, str):
            try:
                parsed = json.loads(content)
            except Exception:
                continue
            if isinstance(parsed, dict):
                payloads.append(parsed)
    return payloads


def rows_titled(payloads: list[dict[str, Any]], title: str) -> list[dict[str, Any]]:
    """payload들의 rows에서 제목이 일치하는 row만 고릅니다.

    agent가 제목에 말을 덧붙여 저장할 수 있어(예: '집중작업' → '집중작업 정리')
    정확히 일치가 아니라 접두어로 찾습니다.
    """

    return [
        row
        for payload in payloads
        for row in payload.get("rows", [])
        if str(row.get("title") or "").startswith(title)
    ]


@dataclass
class Turn:
    """한 턴의 결과 — 판정에 필요한 것만 담습니다."""

    called: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    answer: str = ""

    def payloads(self, tool_name: str) -> list[dict[str, Any]]:
        return tool_payloads(self.events, tool_name)

    def rows(self, tool_name: str) -> list[dict[str, Any]]:
        return [row for p in self.payloads(tool_name) for row in p.get("rows", [])]

    def rows_titled(self, tool_name: str, title: str) -> list[dict[str, Any]]:
        return rows_titled(self.payloads(tool_name), title)

    def args_of(self, tool_name: str) -> list[dict[str, Any]]:
        """이번 턴에 그 tool을 어떤 인자로 불렀는지 (호출 순서대로)."""

        return [
            ev.get("arguments") or {}
            for ev in self.events
            if ev.get("event") == "tool_call" and ev.get("tool_name") == tool_name
        ]

    def used(self, *tool_names: str) -> bool:
        return bool(set(tool_names) & set(self.called))


class TraceRun:
    """대본 하나의 실행 상태(대화 누적·판정·집계·뒷정리)를 담습니다."""

    def __init__(self, title: str, session_id: str):
        self.title = title
        self.session_id = session_id
        self.agent = build_week05_agent()
        self.history: list = []
        self.index = 0
        self.passed = 0
        self.failed: list[str] = []
        self.tally: Counter[str] = Counter()
        self.no_tool_turns = 0
        self.routed_ok = 0
        self.routed_total = 0
        # 실행 중 새로 생긴 공유 row를 뒷정리에서 구분하기 위한 기준선입니다.
        self.shared_ids_before = shared_ids()
        print(f"\n{'#' * 78}")
        print(f"# {title}")
        print(f"{'#' * 78}\n")

    def turn(self, category: str, text: str, expect: set[str] | None = None) -> Turn:
        """이어지는 대화의 한 턴을 실행합니다.

        직전까지의 history에 이번 질문을 붙여 통째로 넘기므로 agent가 앞 대화를 기억합니다.
        """

        self.index += 1
        print("=" * 78)
        print(f"[{self.index:02d}] ({category}) {text}")
        if expect:
            print(f"     기대 tool 후보: {', '.join(sorted(expect))}")

        prev_len = len(self.history)
        next_history = self.history + [{"role": "user", "content": text}]
        try:
            with conversation_session_scope(self.session_id):
                res = self.agent.invoke({"messages": next_history})
        except Exception as exc:  # 한 턴이 실패해도 대화는 계속 이어갑니다.
            print(f"     ❌ 실행 오류: {type(exc).__name__}: {exc}")
            self.failed.append(f"[{self.index:02d}] 실행 오류: {type(exc).__name__}")
            return Turn()

        self.history = res["messages"]
        try:
            events = extract_agent_events({"messages": self.history[prev_len:]})
        except Exception:
            events = []
        called = [ev["tool_name"] for ev in events if ev.get("event") == "tool_call"]

        if not called:
            print("     tool 호출 없음 (앞 대화/메모리로 답변)")
            self.no_tool_turns += 1
        for i, ev in enumerate(events, 1):
            if ev.get("event") == "tool_call":
                args = json.dumps(ev.get("arguments", {}), ensure_ascii=False)
                print(f"       {i}. call   {ev['tool_name']}  args={args[:150]}")
            else:
                content = ev.get("content")
                preview = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                print(f"       {i}. result {ev['tool_name']}  -> {preview[:170]}")

        self.tally.update(called)
        if expect:
            self.routed_total += 1
            hit = expect.intersection(called)
            if hit:
                self.routed_ok += 1
                print(f"     ✅ 기대대로 라우팅: {', '.join(sorted(hit))}")
            elif called:
                print(f"     ⚠️ 다른 tool로 라우팅: {', '.join(called)}")
            else:
                print("     · tool 없이 답변 (앞 대화 기억으로 처리했을 수 있음)")

        answer = extract_final_text(res)
        print(f"     [답변] {answer[:220].strip()}")
        return Turn(called=called, events=events, answer=answer)

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        """대본이 직접 판정하는 항목입니다(라우팅과 달리 결과 내용을 봅니다)."""

        if ok:
            self.passed += 1
            print(f"     ✅ {label}")
        else:
            self.failed.append(label)
            print(f"     ❌ {label}" + (f"  ({detail})" if detail else ""))

    def cleanup(self, title_prefixes: tuple[str, ...] = ()) -> None:
        """이 대본이 만든 일정을 정리합니다.

        앱 일정을 지우면 공유 사본은 프레임워크가 함께 지웁니다. 그래도 남는 row는
        실행 중에 새로 생긴 것(예: agent가 스스로 등록한 회의)이므로 직접 지웁니다.
        """

        print("=" * 78)
        print("뒷정리")
        print("-" * 78)

        if title_prefixes:
            # agent가 제목을 바꿔 저장할 수 있으므로 정확히 일치가 아니라 접두어로 찾습니다.
            app_store = AppSQLiteStore(CONFIG.app_db_path)
            targets = [
                row
                for row in app_store.list_schedules(limit=500)
                if str(row.get("title") or "").startswith(title_prefixes)
            ]
            if targets:
                result = json.loads(personal_delete_saved_schedules.invoke(
                    {"schedule_ids": [str(row["schedule_id"]) for row in targets]}
                ))
                titles = ", ".join(str(row.get("title")) for row in targets)
                print(f"  앱 DB: {result.get('deleted_count', 0)}건 삭제 ({titles})")
            else:
                print("  앱 DB: 지울 일정 없음")
            PERSONAL_SCHEDULES[:] = [
                s for s in PERSONAL_SCHEDULES
                if not str(s.get("title") or "").startswith(title_prefixes)
            ]

        store = ExternalPeopleSQLiteStore(external_db_path_from_env())
        new_rows = [
            row for row in shared_rows()
            if str(row.get("schedule_id")) not in self.shared_ids_before
        ]
        if new_rows:
            print(f"  공유 저장소: 실행 중 생긴 {len(new_rows)}건 정리")
            for row in new_rows:
                store.delete_shared_schedules(schedule_id=str(row.get("schedule_id")))
                print(f"     삭제 {row.get('schedule_id')} | {row.get('member_name')} | "
                      f"{row.get('title')} | {row.get('date')}")
        else:
            print("  공유 저장소: 잔여물 없음")

    def summary(self) -> int:
        """요약을 인쇄하고 종료 코드를 돌려줍니다(0 = 실패 없음)."""

        print("=" * 78)
        print(f"요약 — {self.title}")
        print("-" * 78)
        print(f"누적 대화 메시지 수: {len(self.history)}")
        if self.tally:
            print("tool 호출 횟수:")
            for name, count in self.tally.most_common():
                print(f"  {count:>3}  {name}")
        if self.routed_total:
            print(f"기대 tool 후보가 있던 {self.routed_total}개 중 {self.routed_ok}개가 기대대로 라우팅됨.")
        print(f"tool 없이 답한 턴: {self.no_tool_turns}개")
        if self.passed or self.failed:
            print(f"내용 판정: {self.passed}개 통과" +
                  (f", 실패 {len(self.failed)}개" if self.failed else ", 실패 0개"))
            for label in self.failed:
                print(f"  ❌ {label}")
        print("(⚠️ 는 오답이 아니라 라우팅이 갈린 경우일 수 있으니 tool_call args와 답변을 함께 보세요.)")
        return 1 if self.failed else 0
