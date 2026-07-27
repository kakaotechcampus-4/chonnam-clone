import json

import student_parts.week04_retrieve_nanas_memory as m
from fixed.langchain_trace import extract_agent_events, extract_final_text
from student_parts.week03_build_nanas_logbook import save_structured_request

agent = m.build_week04_agent()


def run(query: str) -> tuple[list[dict], str]:
    result = agent.invoke({"messages": [{"role": "user", "content": query}]})
    return extract_agent_events(result), extract_final_text(result)


def tool_result_for(events: list[dict], tool_name: str):
    for event in events:
        if event["event"] == "tool_result" and event["tool_name"] == tool_name:
            return event["content"]
    return None


# (A) 개인 참고자료: search_personal_references가 호출되고, hits와 final text에 같은 근거가 있는지 확인
MARKER_REF = "WEEK4VERIFY_REF_9f2a"
add_result = json.loads(
    m.add_personal_reference.invoke(
        {
            "title": "week4 검증용 참고자료",
            "content": f"이것은 검증용 내용입니다. 키워드: {MARKER_REF}",
            "tags": ["verify"],
        }
    )
)
reference_id = add_result["reference"]["reference_id"]

try:
    events, final_text = run(f"{MARKER_REF} 관련해서 내가 저장해둔 참고자료 찾아줘")
    content = tool_result_for(events, "search_personal_references")
    assert content is not None, f"search_personal_references가 호출되지 않음: {events}"
    hits = content["hits"]
    assert any(MARKER_REF in hit["content"] for hit in hits), f"hits에 마커가 없음: {hits}"
    assert MARKER_REF in final_text, f"final text에 마커가 없음: {final_text}"
    print("(A) 개인 참고자료 검증 통과 - hits와 final text 모두 마커 포함")
finally:
    m.REFERENCE_STORE.collection.delete(ids=[reference_id])


# (B) SQLite 저장 요청: search_saved_requests가 호출되고, rows와 final text에 같은 근거가 있는지 확인
MARKER_REQ = "WEEK4VERIFY_TODO_9f2a"
save_result = json.loads(save_structured_request.invoke({"kind": "todo", "title": MARKER_REQ}))
assert save_result["ok"] is True, save_result
request_id = save_result["request_id"]

try:
    events, final_text = run(f"저장해둔 일정이나 할 일 중에 {MARKER_REQ} 라는 단어 들어간 거 있어?")
    content = tool_result_for(events, "search_saved_requests")
    assert content is not None, f"search_saved_requests가 호출되지 않음: {events}"
    rows = content["rows"]
    assert any(MARKER_REQ in json.dumps(row, ensure_ascii=False) for row in rows), f"rows에 마커가 없음: {rows}"
    assert MARKER_REQ in final_text, f"final text에 마커가 없음: {final_text}"
    print("(B) 저장 요청 검증 통과 - rows와 final text 모두 마커 포함")
finally:
    with m.SQLITE_STORE.connect() as conn:
        conn.execute("DELETE FROM structured_requests WHERE request_id = ?", (request_id,))


# (C) 대화 이력 RAG: search_conversation_messages가 호출되고, hits/rows와 final text에 같은 근거가 있는지 확인
MARKER_CONV = "WEEK4VERIFY_CONV_9f2a"
conv = m.SQLITE_STORE.create_conversation(title="week4 검증용 대화")
conversation_id = conv["conversation_id"]
m.SQLITE_STORE.append_message(conversation_id, "user", f"{MARKER_CONV} 관련 이야기입니다.")
m.SQLITE_STORE.append_message(conversation_id, "assistant", f"네, {MARKER_CONV} 확인했습니다.")

try:
    events, final_text = run(f"예전 대화에서 {MARKER_CONV} 관련된 내용 찾아줘")
    content = tool_result_for(events, "search_conversation_messages")
    assert content is not None, f"search_conversation_messages가 호출되지 않음: {events}"
    hits = content["hits"]
    rows = content["rows"]
    assert hits == rows, "hits와 rows가 서로 다름"
    assert any(MARKER_CONV in hit["content"] for hit in hits), f"hits에 마커가 없음: {hits}"
    assert MARKER_CONV in final_text, f"final text에 마커가 없음: {final_text}"
    print("(C) 대화 이력 검증 통과 - hits/rows와 final text 모두 마커 포함")
finally:
    m.SQLITE_STORE.delete_conversation(conversation_id)
    m.CONVERSATION_RAG_STORE.sync_from_sqlite(m.SQLITE_STORE)


# (D) search_nana_memory: 개인 참고자료 + SQLite 일정 통합 검색 (week04_tools()에는 노출되지 않는 호환 tool이라 tool.invoke()로 직접 호출)
MARKER_NANA_REF = "WEEK4VERIFY_NANA_REF_9f2a"
MARKER_NANA_TITLE = "WEEK4VERIFY_NANA_SCHEDULE_9f2a"
MARKER_NANA_ATTENDEE = "WEEK4VERIFY_NANA_ATTENDEE_9f2a"

nana_add_result = json.loads(
    m.add_personal_reference.invoke(
        {
            "title": "week4 nana_memory 검증용 참고자료",
            "content": f"검증용 내용입니다. {MARKER_NANA_REF}",
            "tags": [],
        }
    )
)
nana_reference_id = nana_add_result["reference"]["reference_id"]

nana_save_result = json.loads(
    save_structured_request.invoke(
        {
            "kind": "personal_schedule",
            "title": MARKER_NANA_TITLE,
            "date": "2026-08-01",
            "members": [MARKER_NANA_ATTENDEE],
        }
    )
)
assert nana_save_result["ok"] is True, nana_save_result
nana_schedule_id = next(row["id"] for row in nana_save_result["saved_rows"] if row["table"] == "schedules")

try:
    result = json.loads(
        m.search_nana_memory.invoke(
            {"query": MARKER_NANA_REF, "attendee": MARKER_NANA_ATTENDEE, "limit": 20}
        )
    )
    assert result["ok"] is True, result
    assert "reference_backend" in result and "context" in result, result

    reference_hits = result["reference_hits"]
    assert any(MARKER_NANA_REF in hit["content"] for hit in reference_hits), f"reference_hits에 마커가 없음: {reference_hits}"

    chunks = result["chunks"]
    assert chunks, "attendee 필터 적용 후 chunks가 비어 있음"
    assert all(
        MARKER_NANA_ATTENDEE in chunk["metadata"]["attendees"] for chunk in chunks
    ), f"attendee 필터가 제대로 적용되지 않음: {chunks}"
    assert any(
        chunk["metadata"]["title"] == MARKER_NANA_TITLE for chunk in chunks
    ), f"테스트 일정이 chunks에 없음: {chunks}"

    assert MARKER_NANA_REF in result["context"] and MARKER_NANA_TITLE in result["context"], result["context"]
    print("(D) search_nana_memory 검증 통과 - reference_hits/chunks/context 모두 마커 포함, attendee 필터 적용 확인")
finally:
    m.REFERENCE_STORE.collection.delete(ids=[nana_reference_id])
    m.SQLITE_STORE.delete_schedule(nana_schedule_id)


print("week04 메인/추가과제 검증 통과")
