"""Week 6 supervisor 위임과 공통 가능 시간 결정 로직 검증 스크립트.

(a)/(b)는 fixed/schedule_decision.py 계약을 직접 호출로 검증하므로 LLM 연결이 필요 없다.
(c)/(d)는 실제 supervisor agent를 실행해 위임이 올바른 하위 agent로 가는지, kana_agent의
find_common_available_slots/decide_final_slot 연쇄 호출 결과가 week06의
extract_langchain_trace를 거쳐 올바른 키(inner_tool_names/final_slot_payload)로 올라오는지
확인하므로 .env의 PROXY_TOKEN이 필요하다.
"""

import json

import student_parts.week06_kanamate_decides_schedule as m
from fixed.app_store import AppSQLiteStore
from fixed.config import CONFIG


def run(query: str) -> dict:
    agent = m.build_week_agent()
    return agent.invoke({"messages": [{"role": "user", "content": query}]})


def tool_result_for(events: list[dict], tool_name: str):
    for event in events:
        if event["event"] == "tool_result" and event["tool_name"] == tool_name:
            return event["content"]
    return None


def iter_all_events(events: list[dict]):
    """supervisor 이벤트뿐 아니라 nana_agent/kana_agent tool_result에 중첩된 하위 trace도 훑는다."""

    for event in events:
        yield event
        content = event.get("content")
        if isinstance(content, dict):
            nested = (content.get("trace") or {}).get("events")
            if isinstance(nested, list):
                yield from iter_all_events(nested)


def created_schedule_ids(events: list[dict]) -> list[str]:
    """중첩 trace에서 save_structured_request가 실제로 만든 schedules row id를 모두 찾는다."""

    ids = []
    for event in iter_all_events(events):
        if event.get("event") != "tool_result" or event.get("tool_name") != "save_structured_request":
            continue
        content = event.get("content")
        if not isinstance(content, dict):
            continue
        for row in content.get("saved_rows") or []:
            if row.get("table") == "schedules":
                ids.append(row["id"])
    return ids


# (a) find_common_available_slots_dict - 겹치는 후보/업무시간 밖 후보가 걸러지는지 확인 (LLM 불필요)
MEMBER = "WEEK6VERIFY_MEMBER"
BUSY_ROWS = [{"member_name": MEMBER, "date": "2026-07-20", "start_time": "10:00", "end_time": "11:00"}]
CANDIDATES = [
    {"date": "2026-07-20", "start_time": "10:30", "end_time": "11:30", "duration_minutes": 60, "reason": "busy와 겹침"},
    {"date": "2026-07-20", "start_time": "14:00", "end_time": "15:00", "duration_minutes": 60, "reason": "가능한 시간"},
    {"date": "2026-07-20", "start_time": "08:00", "end_time": "09:00", "duration_minutes": 60, "reason": "업무시간 밖"},
]
result_a = m.find_common_available_slots_dict(
    member_names=[MEMBER],
    date_from="2026-07-20",
    date_to="2026-07-20",
    busy_rows=BUSY_ROWS,
    candidate_slots=CANDIDATES,
)
assert result_a["ok"] is True, result_a
kept = [(slot["start_time"], slot["end_time"]) for slot in result_a["candidate_slots"]]
assert kept == [("14:00", "15:00")], f"겹침/업무시간 밖 후보가 걸러지지 않음: {result_a['candidate_slots']}"
assert "나" in result_a["members"] and MEMBER in result_a["members"], result_a["members"]
print("(a) find_common_available_slots_dict 검증 통과 - 겹치는 후보/업무시간 밖 후보 제외 확인")


# (a2) find_common_available_slots_dict - busy_rows=None(자동 수집 경로)일 때 collect_member_schedules의
# external_lookup_ok/external_lookup_error가 그대로 반환값에 실리는지 확인 (LLM 불필요, MCP만 사용)
auto_collected = m.find_common_available_slots_dict(
    member_names=["철수"],
    date_from="2026-07-07",
    date_to="2026-07-17",
)
assert "external_lookup_ok" in auto_collected, auto_collected
assert auto_collected["external_lookup_ok"] is True, auto_collected
assert auto_collected["external_lookup_error"] is None, auto_collected
print("(a2) find_common_available_slots_dict busy_rows=None 경로 검증 통과 - external_lookup_ok 전달 확인")


# (b) decide_final_slot - selected_index로 최종 확정 vs 미선택 시 needs_agent_selection 유지 확인 (LLM 불필요)
decided = json.loads(
    m.decide_final_slot.invoke(
        {
            "candidate_slots": result_a["candidate_slots"],
            "selected_index": 0,
            "member_names": ["나", MEMBER],
        }
    )
)
assert decided["final_slot"] == "2026-07-20 14:00-15:00", decided
assert decided["needs_agent_selection"] is False, decided

pending = json.loads(m.decide_final_slot.invoke({"candidate_slots": result_a["candidate_slots"]}))
assert pending["final_slot"] is None, pending
assert pending["needs_agent_selection"] is True, pending
print("(b) decide_final_slot 검증 통과 - 선택 시 확정, 미선택 시 needs_agent_selection 유지 확인")


if not CONFIG.has_openai_key:
    print("PROXY_TOKEN이 없어 (c)/(d) LLM 위임 검증은 건너뜁니다.")
    print("week06 결정론적 검증(a, b) 통과")
else:
    # (c) supervisor 위임 - 개인 일정 조회 요청은 nana_agent로 (실제 LLM 필요)
    result_c = run("내가 저장해둔 일정 목록 좀 보여줘")
    trace_c = m.extract_langchain_trace(result_c)
    assert trace_c["supervisor_selected_agent"] == "nana_agent", trace_c
    nana_content = tool_result_for(trace_c["events"], "nana_agent")
    assert nana_content is not None, trace_c["events"]
    assert "personal_list_saved_schedules" in nana_content["inner_tool_names"], nana_content
    print("(c) supervisor 개인 일정 위임 검증 통과 - nana_agent 선택 및 inner_tool_names 확인")

    # (d) supervisor 위임 - 그룹 조율 요청은 kana_agent로, find_common_available_slots/decide_final_slot까지
    # 이어지는지 확인 (실제 LLM 필요). fixed/external_people_store.py의 JULY_PRACTICE 시드 범위를 명시한다.
    # 확정 후 supervisor가 저장까지 nana_agent에 이어서 위임할 수도 있으므로(Kana가 정하고 Nana가 저장하는
    # 역할 분담), extract_langchain_trace()의 supervisor_selected_agent(마지막 호출자만 남김)로 단정하지
    # 않고 kana_agent 호출 자체가 있었는지로 확인한다. 실제로 저장까지 이어지면 앱 DB에 남으므로 finally에서 정리한다.
    result_d = run("철수랑 2026년 7월 7일부터 7월 17일 사이에 1시간짜리 회의 가능한 시간 하나 찾아서 확정해줘")
    trace_d = m.extract_langchain_trace(result_d)
    schedule_ids_to_clean = created_schedule_ids(trace_d["events"])
    try:
        kana_agent_called = any(
            event["event"] == "tool_call" and event["tool_name"] == "kana_agent" for event in trace_d["events"]
        )
        assert kana_agent_called, trace_d["events"]
        assert "find_common_available_slots" in trace_d["inner_tool_names"], trace_d
        assert "decide_final_slot" in trace_d["inner_tool_names"], trace_d
        assert trace_d["final_slot_payload"] is not None and "final_slot" in trace_d["final_slot_payload"], trace_d
        print(
            "(d) supervisor 그룹 조율 위임 검증 통과 - kana_agent 호출, "
            "find_common_available_slots/decide_final_slot 연쇄 호출, final_slot_payload 확인"
        )
    finally:
        if schedule_ids_to_clean:
            store = AppSQLiteStore(CONFIG.app_db_path)
            for schedule_id in schedule_ids_to_clean:
                store.delete_schedule(schedule_id)
            print(f"(d) 정리: 테스트 중 nana_agent가 저장한 일정 {len(schedule_ids_to_clean)}건 삭제")

    print("week06 메인/추가과제 검증 통과")
