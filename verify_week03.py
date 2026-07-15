import json

from student_parts.week02_structure_natural_language_requests import missing_required_fields, StructuredRequest
from student_parts.week03_build_nanas_logbook import (
    extract_schedule_request,
    save_structured_request,
    personal_list_saved_schedules,
)

# (a) missing_required_fields 자체 검증 - personal_schedule
complete = StructuredRequest(kind="personal_schedule", title="코칭", date="2026-07-16", members=[], original_text="x")
assert missing_required_fields(complete) == []
incomplete = StructuredRequest(kind="personal_schedule", title=None, date=None, members=[], original_text="x")
assert set(missing_required_fields(incomplete)) == {"title", "date"}
print("(a) missing_required_fields 검증 통과 (personal_schedule)")

# (a-2) missing_required_fields 자체 검증 - group_schedule (title/date/members 모두 필수)
group_complete = StructuredRequest(
    kind="group_schedule", title="회의", date="2026-07-20", members=["철수"], original_text="x"
)
assert missing_required_fields(group_complete) == []
group_missing_members = StructuredRequest(
    kind="group_schedule", title="회의", date="2026-07-20", members=[], original_text="x"
)
assert missing_required_fields(group_missing_members) == ["members"]
group_missing_all = StructuredRequest(kind="group_schedule", title=None, date=None, members=[], original_text="x")
assert set(missing_required_fields(group_missing_all)) == {"title", "date", "members"}
print("(a-2) missing_required_fields 검증 통과 (group_schedule)")

# (b) 저장 -> 조회 세로 슬라이스
extracted = json.loads(extract_schedule_request.invoke({"query": "내일 10시 개인 코칭 저장해줘"}))
assert extracted["ok"] is True, extracted
sr = extracted["structured_request"]
print("(b) extract_schedule_request 결과:", sr)

saved = json.loads(save_structured_request.invoke(sr))
assert saved["ok"] is True, saved
assert saved["missing_fields"] == []
print("(b) save_structured_request 결과:", saved)

listed = json.loads(personal_list_saved_schedules.invoke({}))
assert any(s["request_id"] == saved["request_id"] for s in listed["schedules"]), "방금 저장한 일정이 조회 결과에 없음"
print("(b) personal_list_saved_schedules 결과:", listed)

print("week03 메인과제 검증 통과")
