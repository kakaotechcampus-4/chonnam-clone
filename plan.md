# Week 3 "Nana의 기록장" 

## Context

`student_parts/week03_build_nanas_logbook.py`는 Week 2의 `StructuredRequest`를 SQLite에 저장하고 다시 조회하는 과제다. 파일 안 주석(§메인과제/§추가과제)이 과제를 두 tier로 나누는데, 이번 작업은 **메인과제만** 구현한다: "구조화 → 저장 → 조회 → 새 대화에서도 유지"가 되는 최소 세로 슬라이스.

`personal_update_saved_schedule`, `personal_delete_saved_schedules`, Week1 호환 `personal_create_schedule`, 레거시 payload 정규화(`unwrap_legacy_payload` 내부, `_save_input_from`, `save_structured_request_payload`) 등 **추가과제로 표시된 항목은 그대로 TODO로 남긴다.**

**발견한 의존성 문제**: week03의 핵심 흐름 1번("LLM은 `extract_schedule_request`를 호출해 자연어를 구조화")은 `week02_structure_natural_language_requests.py`의 `extract_schedule_request` / `extract_structured_request` / `_coerce_structured_request`에 의존하는데, 이 셋은 week02 파일 자체 기준으로는 "추가 과제"라서 아직 TODO(빈 `...`)다. 이 세 함수가 없으면 week03 메인과제 검증 시나리오("내일 10시 개인 코칭 저장해줘" → 저장 → 조회)가 아예 실행되지 않는다. **사용자 확인 결과, 이 세 함수도 이번 계획에 포함**하기로 했다.

## 구현 대상

### 1. `student_parts/week02_structure_natural_language_requests.py` — bridge 함수 3개 + 검증 함수 활성화

이미 완성된 `StructuredRequest`/`StructuredRequestBatch` 스키마(212~247행 상당)는 건드리지 않는다.

- **`missing_required_fields(req)`** (250~260행, 현재 주석 처리됨): "Week 3+ 저장 전 검증에서 재사용할 예약 함수"라는 주석대로, 이번에 실제로 활성화해서 쓴다. 주석을 풀어 일반 함수로 만든다 (내용은 그대로):
  ```python
  def missing_required_fields(req: StructuredRequest) -> list[str]:
      """kind별 필수 필드 중 값이 없는 것을 반환한다. 빈 list면 완전한 요청."""
      required = KIND_REQUIRED_FIELDS.get(req.kind, [])
      return [
          f for f in required
          if not getattr(req, f, None)
          or (isinstance(getattr(req, f), list) and not getattr(req, f))
      ]
  ```
  기존 `KIND_REQUIRED_FIELDS`(19행)를 그대로 사용 — 새로 정의할 것 없음.

- **`_coerce_structured_request(value)`** (263행)
  ```python
  if isinstance(value, StructuredRequest):
      return value
  if isinstance(value, dict):
      return StructuredRequest.model_validate(value)
  raise RuntimeError(f"예상치 못한 structured output 형식: {type(value)!r}")
  ```

- **`extract_structured_request(text)`** (272행)
  ```python
  structured_llm = chat_model().with_structured_output(StructuredRequest, method="function_calling")
  result = structured_llm.invoke([
      {"role": "system", "content": join_system_prompt(week02_prompt_parts())},
      {"role": "user", "content": text},
  ])
  return _coerce_structured_request(result)
  ```

- **`extract_schedule_request(query)`** (`@tool`, 281행)
  ```python
  structured = extract_structured_request(query)
  payload = {
      "ok": True,
      "tool_name": "extract_schedule_request",
      "base_date": current_app_date_iso(),
      "structured_request": structured.model_dump(),
  }
  return json.dumps(payload, ensure_ascii=False)
  ```

### 2. `student_parts/week03_build_nanas_logbook.py` — 메인과제 함수

먼저 19~25행의 week02 import 목록에 `missing_required_fields`를 추가한다.

- **`SQLITE_MEMORY_PROMPT`** (31행): Week 1의 `CHAT_MEMORY_PROMPT`(대화 한정 임시 메모리)와 대비되는, "Week 3부터는 SQLite 앱 DB에 저장되어 대화가 끊기거나 앱을 재시작해도 유지된다"는 취지의 prompt 문자열.

- **`WEEK03_TOOL_CALL_PROMPT`** (34행): "자연어 저장 요청 → 먼저 `extract_schedule_request` 호출 → 결과의 `structured_request` 필드를 그대로 `save_structured_request` 인자로 전달" 순서, "일정 조회는 `personal_list_saved_schedules`, 원본 구조화 요청 조회는 `list_saved_requests`/`get_saved_request`"라는 tool 선택 규칙을 담은 문자열.

- **`save_structured_request`** (330행, `@tool(args_schema=SaveStructuredRequestInput)`) — 저장 전에 `missing_required_fields`로 kind별 필수 필드를 검증하는 단계를 추가한다. 검증 결과(`missing_fields`)가 응답에 그대로 남도록 해서, 실패했을 때 무엇이 빠졌는지 결과물로 확인할 수 있게 한다.
  ```python
  req_for_validation = StructuredRequest(
      kind=kind, title=title, date=date, start_time=start_time, end_time=end_time,
      members=members or [], priority=priority, reason=reason, original_text=original_text,
  )
  missing = missing_required_fields(req_for_validation)
  if missing:
      return json_payload(tool_result(
          "save_structured_request", ok=False,
          missing_fields=missing,
          reason=f"필수 필드 누락: {missing}",
      ))

  payload = {
      "kind": kind, "title": title, "date": date,
      "start_time": start_time, "end_time": end_time,
      "members": members or [], "priority": priority,
      "reason": reason, "original_text": original_text,
      "source_schedule_id": source_schedule_id,
  }
  payload = {k: v for k, v in payload.items() if v is not None}
  result = _store().save_structured_request(payload)
  return json_payload(tool_result("save_structured_request", missing_fields=[], **result))
  ```
  (`AppSQLiteStore.save_structured_request(payload: dict)`는 `{"request_id", "kind", "saved_rows", "shared_sync", ...}`를 반환 — `fixed/app_store.py:281`)

- **`list_saved_requests`** (350행)
  ```python
  rows = _store().list_saved_requests(kind=kind, date_from=date_from, date_to=date_to)
  return json_payload(tool_result("list_saved_requests", rows=rows))
  ```

- **`get_saved_request`** (362행)
  ```python
  row = _store().get_saved_request(request_id)
  return json_payload(tool_result("get_saved_request", row=row))
  ```

- **`personal_list_saved_schedules`** (370행)
  ```python
  effective_kind = kind or "personal_schedule"
  schedules = _store().list_schedules(limit=limit, kind=effective_kind, date_from=date_from, date_to=date_to)
  filters = {"limit": limit, "kind": effective_kind, "date_from": date_from, "date_to": date_to}
  return json_payload(tool_result("personal_list_saved_schedules", filters=filters, schedules=schedules))
  ```
  (`AppSQLiteStore.list_schedules(...)`는 `attendees`/`request_kind`가 포함된 decoded row list 반환 — `fixed/app_store.py` 480행대)

- **`week03_prompt_parts()`** (453행): TODO 두 곳을 실제 지시문으로 채운다 — 현재 날짜(`current_app_date_iso()`), "구조화 후 저장 흐름을 따르라"는 지시, `SQLITE_MEMORY_PROMPT`/`WEEK03_TOOL_CALL_PROMPT` 삽입 위치는 이미 리스트에 있으므로 그 앞뒤 지시 문자열만 추가.

- **`build_week03_agent()`** (465행): week01/02와 동일 패턴으로 채움
  ```python
  _WEEK03_AGENT = create_agent(
      model=chat_model(),
      tools=week03_tools(),
      system_prompt=week03_system_prompt(),
  )
  ```

### 손대지 않는 부분 (추가과제, 그대로 TODO)

`SaveStructuredRequestInput.unwrap_legacy_payload` 내부(이미 no-op passthrough라 무해함), `_save_input_from`, `save_structured_request_payload`, `_delete_saved_schedules`, `structured_request_from_week01_schedule`, `personal_create_schedule`(Week1 호환), `delete_saved_schedules_dict`, `personal_update_saved_schedule`, `personal_delete_saved_schedules`.

**알려진 한계**: `week03_tools()`(이미 구현됨, 수정 안 함)가 week01의 동작하는 `personal_create_schedule`을 이 파일의 미구현 버전으로 교체해 노출한다. 메인과제 검증 시나리오는 이 tool을 거치지 않지만, LLM이 "일정 만들어줘"류 요청에서 이 tool을 직접 고르면 `...`(None 반환)로 인해 tool 호출이 깨질 수 있다. 이는 추가과제 범위라 이번 계획에서 고치지 않는다.

## 검증 방법

1. **정적 확인**: 두 파일 `python -m py_compile`로 문법 오류 없는지 확인.

2. **assert 기반 스크립트** (스크래치패드에 `verify_week03.py` 등으로 작성해 실행, 실제 결과물을 눈으로 확인): agent 전체를 띄우지 않고 tool을 직접 호출해 assert로 결과를 고정 확인한다.
   ```python
   import json
   from student_parts.week02_structure_natural_language_requests import missing_required_fields, StructuredRequest
   from student_parts.week03_build_nanas_logbook import extract_schedule_request, save_structured_request, personal_list_saved_schedules

   # (a) missing_required_fields 자체 검증
   complete = StructuredRequest(kind="personal_schedule", title="코칭", date="2026-07-16", members=[], original_text="x")
   assert missing_required_fields(complete) == []
   incomplete = StructuredRequest(kind="personal_schedule", title=None, date=None, members=[], original_text="x")
   assert set(missing_required_fields(incomplete)) == {"title", "date"}

   # (b) 저장 → 조회 세로 슬라이스
   extracted = json.loads(extract_schedule_request.invoke({"query": "내일 10시 개인 코칭 저장해줘"}))
   assert extracted["ok"] is True
   sr = extracted["structured_request"]
   saved = json.loads(save_structured_request.invoke(sr))
   assert saved["ok"] is True, saved
   assert saved["missing_fields"] == []

   listed = json.loads(personal_list_saved_schedules.invoke({}))
   assert any(s["request_id"] == saved["request_id"] for s in listed["schedules"]), "방금 저장한 일정이 조회 결과에 없음"
   print("week03 메인과제 검증 통과")
   ```
   (`.env`에 `PROXY_TOKEN` 필요 — `extract_schedule_request`가 실제 LLM 호출을 하기 때문)

3. **공식 검증 경로**: `./run.sh --week3` 실행 후 "내일 10시 개인 코칭 저장해줘" → trace에서 `extract_schedule_request` 다음 `save_structured_request` 호출 확인 → "내 일정 보여줘" → `personal_list_saved_schedules`로 조회되는지 확인 → 앱 재시작(또는 새 대화)해도 일정이 남아있는지 확인 (SQLite 파일 기반이라 프로세스 재시작에도 유지되어야 함).
