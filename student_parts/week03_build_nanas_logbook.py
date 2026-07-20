from __future__ import annotations

"""3주차: 구조화된 요청을 대화가 끝나도 휘발되지 않게 SQLite에 저장하는 agent입니다.

Week 2가 자연어를 StructuredRequest/StructuredRequestBatch로 구조화했다면, Week 3은 그
구조화 결과를 SQLite에 영구 저장합니다.

저장은 두 층으로 나뉩니다. 먼저 요청의 원본 payload가 kind와 상관없이 항상
structured_requests 테이블에 raw_json 형태로 그대로 보관됩니다(무엇이 들어왔는지 남기는
기록용 원장 역할 = source of truth). 그다음 kind(personal_schedule/group_schedule/todo/
reminder)에 따라 조회하기 쉽게 일부 필드를 컬럼으로 뽑아낸 row가 schedules/todos/
reminders 테이블 중 한 곳에 하나 더 추가됩니다(조회 편의를 위한 파생 뷰 = derived
projection). 이렇게 나뉜 원본 row와 컬럼화된 row는 request_id로 서로 연결됩니다.

※ 여기서 "컬럼화"는 DB 이론에서 말하는 정규화(normal form)와는 다릅니다.
   정규화는 중복 제거가 목적이지만, 여기서는 title/date 같은 필드가 raw_json과
   컬럼 테이블 양쪽에 의도적으로 중복 저장됩니다. raw_json이 나중에 재처리나
   감사(audit)를 위한 원본 그대로의 기록이라면, 컬럼 테이블은 그걸 kind별로
   조회하기 좋게 미리 펼쳐둔 캐시/프로젝션에 가깝습니다.

그림으로 보면 다음과 같습니다.

            +-----------------------------------+
            |        structured_requests        |
            | request_id(PK) / kind / raw_json  |
            |     (원본 = source of truth)      |
            +-----------------------------------+
                              |
                              |  request_id로 연결
                              |  kind에 따라 아래 세 테이블 중 하나로 분기
                              |
         +--------------------+--------------------+
         v                    v                    v
+-----------------+  +-----------------+  +-----------------+
|    schedules    |  |      todos      |  |    reminders    |
|  (컬럼화 캐시)  |  |  (컬럼화 캐시)  |  |  (컬럼화 캐시)  |
+-----------------+  +-----------------+  +-----------------+

kind -> personal_schedule/group_schedule: schedules, todo: todos, reminder: reminders

컬럼화라고 해서 payload의 모든 필드가 그대로 옮겨지는 것은 아닙니다. kind별로 어느 필드가
그대로 남고, 이름이 바뀌고, 아예 버려지는지는 다음과 같습니다(fixed/app_store.py의
AppSQLiteStore.save_structured_request 기준).

  [schedules]  (kind: personal_schedule / group_schedule)
    title          <- title       그대로 (비어 있으면 "제목 없음"으로 대체)
    date            <- date        그대로
    start_time      <- start_time  그대로
    end_time        <- end_time    그대로
    attendees_json  <- members     이름 변경(members -> attendees) + list를 JSON 문자열로 변환
    priority / reason / original_text -> 컬럼화되지 않음 (raw_json에만 남음)

  [todos]  (kind: todo)
    title    <- title     그대로 (비어 있으면 "제목 없음")
    due_date <- date       이름 변경(date -> due_date)
    priority <- priority   그대로
    start_time / end_time / members / reason / original_text -> 컬럼화되지 않음

  [reminders]  (kind: reminder)
    title      <- title       그대로 (비어 있으면 "제목 없음")
    date       <- date        그대로
    start_time <- start_time  그대로
    reason     <- reason      그대로
    end_time / members / priority / original_text -> 컬럼화되지 않음

  공통: request_id/created_at은 payload에 없던 값으로, 저장 시점에 새로 만들어집니다\.
  kind 컬럼도 컬럼화 테이블에는 없어서, 조회 시 structured_requests와 다시 join해야 합니다.
  original_text는 어떤 컬럼화 테이블에도 없고, structured_requests.raw_json 안에만
  원문 그대로 남습니다.

실제 테이블 스키마와 분기 저장 로직은 이미 fixed/app_store.py의
AppSQLiteStore.save_structured_request에 구현되어 있으므로, 이 파일의 책임은 LLM agent가
그 저장소를 호출하도록 tool과 prompt를 잇는 것입니다.
"""

import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from pydantic import BaseModel, Field, model_validator

from fixed.config import CONFIG
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from fixed.app_store import AppSQLiteStore
from student_parts.week01_wake_up_nana import (
    join_system_prompt,
    personal_create_schedule as week01_personal_create_schedule,
    week01_tools,
)
from student_parts.week02_structure_natural_language_requests import (
    RequestKind,
    StructuredRequest,
    extract_schedule_request,
    extract_structured_request,
    week02_prompt_parts,
)


_WEEK03_AGENT: Any | None = None

SQLITE_MEMORY_PROMPT = (
    "[영속성] Week 1의 개인 일정은 대화가 끝나면 사라지는 임시 메모리이지만, Week 3부터는 구조화된 요청을 "
    "SQLite 앱 DB에 저장하므로 대화가 끝나거나 새 대화를 시작해도 내용이 남는다. 사용자가 이전에 저장한 "
    "일정/할 일/알림을 물으면 메모리가 아니라 아래 조회 tool로 답한다.\n"
    "\n"
    "[조회 tool]\n"
    "  1) personal_list_saved_schedules(limit, kind, date_from, date_to) -> "
    "{ok, tool_name, filters, schedules:[{schedule_id, title, date, start_time, end_time, attendees, request_kind}]}\n"
    "  2) list_saved_requests(kind, date_from, date_to) -> {ok, tool_name, rows:[structured_requests 원본 row, ...]}\n"
    "  3) get_saved_request(request_id) -> {ok, tool_name, row:structured_requests 원본 row | null}\n"
    "     (원본 row 필드: request_id/kind/title/date/start_time/end_time/members_json/priority/reason/raw_json/created_at)\n"
    "  * 주의: 위 세 tool 모두 결과가 없어도 ok는 그대로 true고 schedules=[]/rows=[]/row=null로 돌아온다. "
    "이는 오류가 아니라 정상 상태이므로, 그대로 '저장된 항목이 없다'고 답한다."
)

WEEK03_TOOL_CALL_PROMPT = (
    "[저장 절차]\n"
    "  1) 일정/할 일/알림을 저장해야 하는 자연어 요청이 들어오면 extract_schedule_request로 구조화한다.\n"
    "  2) 반환된 structured_request의 kind/title/date/start_time/end_time/members/priority/reason/original_text 값을 "
    "save_structured_request의 같은 이름 인자에 그대로 전달해 호출한다.\n"
    "  3) save_structured_request는 {ok, tool_name, request_id, kind, saved_rows:[{table, id}], shared_sync} 형태의 "
    "JSON을 돌려주므로, request_id와 saved_rows(실제 저장된 테이블 목록)를 사용자에게 자연어로 확인해 준다.\n"
    "  4) shared_sync가 있고 그 안의 ok가 false이면 앱 저장은 성공했지만 외부 공유 일정 동기화는 실패한 것이므로, "
    "이 사실도 함께 알려준다.\n"
    "\n"
    "[조회 절차]\n"
    "  1) 저장된 일정을 보여달라는 요청에는 personal_list_saved_schedules를 limit/kind/date_from/date_to 인자로 호출한다.\n"
    "  2) 이 tool은 {ok, tool_name, filters, schedules:[{schedule_id, title, date, start_time, end_time, attendees, request_kind}]} "
    "형태를 돌려주므로, schedules 목록을 날짜·시간과 함께 정리해 답한다."
)


# [3주차 수강생 구현 가이드]
#
# 목표
#   Week 2에서 만든 StructuredRequest를 Pydantic 입력 스키마로 검증한 뒤 SQLite에 저장하고,
#   저장된 요청/일정을 다시 조회/수정/삭제합니다. 여기서부터 Nana는 Week 1의 임시 메모리 대신
#   앱 DB에 남는 "기록장"을 갖게 됩니다.
#
# 과제 구성
#   - 메인과제: 구조화 결과를 SQLite에 저장하고 다시 조회하는 세로 슬라이스를 완성해
#     "저장 → 조회 → 새 대화에서도 유지"가 동작하는 최소 기록장을 만듭니다.
#   - 추가 과제: 저장된 일정을 수정/삭제하고 외부 공유 저장소와 동기화하며,
#     Week 1 호환 생성과 레거시 payload 정규화까지 다루는 확장 기능을 완성합니다.
#
# 핵심 흐름
#   1. LLM은 extract_schedule_request(query=사용자 요청)를 호출해 자연어를 Week 2 StructuredRequest로 바꿉니다.
#   2. LLM은 structured_request의 kind/title/date/start_time/end_time/members/priority/reason/original_text를
#      save_structured_request 인자로 그대로 전달합니다.
#   3. 각 tool에 붙은 @tool(args_schema=...)가 Pydantic class로 입력을 검증합니다.
#   4. Python tool 본문은 이미 검증된 인자를 AppSQLiteStore에 넘기고, 결과를 JSON 문자열로 반환합니다.
#
# 구현 위치와 사용할 코드
#   - StructuredRequest와 RequestKind는 week02_structure_natural_language_requests.py에서 재사용합니다.
#   - SaveStructuredRequestInput은 Week 2 StructuredRequest를 상속하고, Week 1 호환용 source_schedule_id만 추가합니다.
#   - SavedRequestListInput, SavedRequestGetInput, SavedScheduleListInput,
#     SavedScheduleUpdateInput, SavedScheduleDeleteInput은 조회/수정/삭제 tool 인자 스키마입니다.
#   - 실제 DB 접근은 fixed/app_store.py의 AppSQLiteStore를 사용하고, _store()가 CONFIG.app_db_path 기준
#     store 객체를 만들어 줍니다.
#   - save_structured_request_payload()와 delete_saved_schedules_dict()는 테스트/직접 호출/이전 trace 호환용 helper입니다.
#     agent가 일반적으로 호출하는 경로는 @tool(args_schema=...)가 붙은 tool 함수입니다.
#
# 메인과제 구현 대상
#   1. save_structured_request
#      - @tool(args_schema=SaveStructuredRequestInput)으로 Week 2 구조화 결과를 검증합니다.
#      - tool 본문에서는 Pydantic class를 다시 만들지 말고, 함수 인자로 들어온 값을 바로 저장 dict로 정리합니다.
#      - 자연어 문자열이나 ok/tool_name/base_date wrapper를 직접 저장하지 않습니다.
#
#   2. list_saved_requests / get_saved_request
#      - list는 kind/date_from/date_to 필터를 AppSQLiteStore.list_saved_requests(...)에 그대로 넘깁니다.
#      - get은 request_id 하나로 단건 조회합니다.
#      - 조회 결과가 없어도 예외를 던지지 말고 rows=[] 또는 row=None 형태를 유지합니다.
#
#   3. personal_list_saved_schedules
#      - 저장된 일정 목록을 반환해 "내 일정 보여줘" 같은 조회 질문과 이후 수정/삭제 후보 확인에 씁니다.
#      - 날짜가 명확한 조회는 date_from/date_to로 범위를 좁히고, 너무 많은 row가 들어가지 않게 limit을 사용합니다.
#
# 추가 과제 구현 대상
#   1. personal_update_saved_schedule
#      - AppSQLiteStore.update_schedule(...) 결과를 JSON 응답으로 완성하고, 공유 일정 복사본 동기화 결과(shared_sync)도 함께 반환합니다.
#      - None으로 들어온 필드는 "수정하지 않음"이라는 뜻입니다. ID를 못 찾으면 ok=False로 답합니다.
#
#   2. personal_delete_saved_schedules
#      - schedule_ids, date, title, start_time, time_unspecified, delete_all 조건을 받습니다.
#      - 조건 없이 삭제하지 않도록 _delete_saved_schedules(...)에서 안전 규칙을 확인합니다.
#      - deleted_count, filters, deleted를 유지해야 trace에서 무엇이 지워졌는지 확인할 수 있습니다.
#
#   3. personal_create_schedule (Week 1 호환)
#      - Week 1과 같은 이름을 유지하면서 임시 일정 생성 결과를 SQLite에도 저장하는 이중 기록 tool입니다.
#      - week01_personal_create_schedule 결과를 structured_request_from_week01_schedule()로 변환해 저장합니다.
#
#   4. 레거시 payload 정규화
#      - SaveStructuredRequestInput.unwrap_legacy_payload는 예전 trace/테스트의 payload/structured_request wrapper를 저장 스키마로 풉니다.
#      - _save_input_from / save_structured_request_payload는 tool 없이 dict/JSON/자연어를 직접 저장할 때 쓰는 helper입니다.
#
# 반환 규칙
#   모든 @tool은 JSON 문자열을 반환합니다.
#   ok와 tool_name은 기본으로 넣고, 조회는 rows/row, 삭제는 deleted_count/filters/deleted를 유지하세요.
#
# 참고 코드
#   week03_tools()는 Week 1-2 도구에 SQLite 도구를 누적해 공개합니다.
#   Week 1 호환 personal_create_schedule은 week01_personal_create_schedule 결과를
#   structured_request_from_week01_schedule()로 SaveStructuredRequestInput에 맞춘 뒤 SQLite에 저장합니다.
#   삭제 요청은 먼저 personal_list_saved_schedules로 후보를 확인한 뒤
#   personal_delete_saved_schedules에 schedule_ids 또는 명시 필터를 넘기는 흐름으로 처리합니다.
#
# 검증 방법
#   - 메인과제: ./run.sh --week3에서 "내일 10시 개인 코칭 저장해줘"처럼 입력합니다.
#     trace에서 extract_schedule_request 다음에 save_structured_request가 호출되는지 보고,
#     이어서 "내 일정 보여줘"가 personal_list_saved_schedules로 조회되며, 앱을 다시 시작하거나
#     새 대화를 열어도 저장된 일정이 그대로 보이면 메인과제가 동작하는 것입니다.
#   - 추가 과제: 저장된 일정을 personal_list_saved_schedules로 확인한 뒤 personal_update_saved_schedule로 시간을 바꾸고,
#     personal_delete_saved_schedules에 schedule_ids 또는 명시 필터를 넘겨 삭제한 일정이 목록에서 사라지는지 봅니다.
#
# 함수별 동작 설명 ([메인]/[추가]/[공통]은 각 함수가 속한 과제 티어입니다)
#   - [공통] _store()
#     현재 CONFIG.app_db_path를 기준으로 AppSQLiteStore를 생성합니다. SQL은 store.py가 담당하고,
#     이 파일의 tool들은 store 메서드를 호출하는 얇은 입구 역할만 합니다.
#
#   - [공통] _tool_name(item)
#     LangChain tool 객체와 일반 함수 객체 모두에서 이름을 안전하게 꺼냅니다. week03_tools()에서 Week 1 tool을 교체할 때 사용합니다.
#
#   - [공통] json_payload(payload)
#     tool 결과 dict를 한글이 깨지지 않는 JSON 문자열로 바꿉니다.
#
#   - [공통] tool_result(tool_name, ok, **payload)
#     여러 tool이 공통으로 쓰는 응답 껍데기를 만듭니다. 필수 구조는 아니지만 ok/tool_name 반복을 줄이는 작은 helper입니다.
#
#   - [메인] SaveStructuredRequestInput
#     Week 2 StructuredRequest를 상속한 저장 입력 스키마입니다. LangChain의 @tool(args_schema=...)가 이 class를 보고
#     save_structured_request 인자를 검증합니다.
#
#   - [추가] SaveStructuredRequestInput.unwrap_legacy_payload(value)
#     예전 trace나 테스트에서 들어올 수 있는 payload/structured_request wrapper를 저장 스키마 형태로 풀어 줍니다.
#     일반적인 agent 경로에서는 LLM이 필드를 직접 넘기므로 이 함수가 크게 개입하지 않습니다.
#
#   - [추가] _save_input_from(value)
#     테스트나 직접 호출 helper에서 dict, JSON 문자열, StructuredRequest를 SaveStructuredRequestInput 하나로 맞춥니다.
#     자연어 문자열이 들어오면 Week 2 extract_structured_request(...)로 먼저 구조화합니다.
#
#   - [추가] save_structured_request_payload(...)
#     tool wrapper 없이 직접 저장을 테스트해야 할 때 쓰는 helper입니다. 입력을 검증한 뒤 AppSQLiteStore.save_structured_request(...)에 넘깁니다.
#
#   - [메인/추가] SavedRequestListInput / SavedRequestGetInput / SavedScheduleListInput / SavedScheduleUpdateInput / SavedScheduleDeleteInput
#     조회, 단건 조회, 일정 목록, 일정 수정, 일정 삭제 tool의 입력 스키마입니다. Pydantic이 기본값과 범위를 검증합니다.
#     앞의 셋(list/get/schedule list)은 메인과제, 수정/삭제 스키마는 추가 과제에서 씁니다.
#
#   - [추가] _delete_saved_schedules(...)
#     삭제 조건이 비어 있는지 먼저 확인하고, delete_all인지 필터 삭제인지에 따라 store 삭제 메서드를 호출합니다.
#     실제 SQL 삭제는 AppSQLiteStore가 수행하고, 이 함수는 안전 규칙과 응답 모양을 정리합니다.
#
#   - [추가] structured_request_from_week01_schedule(schedule)
#     Week 1의 임시 schedule dict를 Week 3 저장 입력으로 변환합니다. personal_create_schedule 호환 wrapper에서 사용합니다.
#
#   - [추가] personal_create_schedule(...)
#     Week 1과 같은 이름을 유지하는 호환 tool입니다. 먼저 Week 1 임시 일정을 만들고, 같은 내용을 SQLite에도 저장합니다.
#
#   - [메인] save_structured_request(...)
#     Week 2 structured_request 필드를 직접 받아 SQLite에 저장하는 Week 3 핵심 tool입니다.
#     args_schema가 입력 검증을 끝낸 뒤 들어오므로, 본문은 저장 dict를 만들어 store에 넘기는 일만 합니다.
#
#   - [메인] list_saved_requests(...) / get_saved_request(...)
#     SQLite에 저장된 structured_requests 원본 기록을 목록 또는 단건으로 조회합니다.
#
#   - [메인] personal_list_saved_schedules(...)
#     저장된 일정 row를 조회합니다. 수정/삭제 전 후보 schedule_id를 확인하거나 사용자의 일정 조회 질문에 답할 때 사용합니다.
#
#   - [추가] delete_saved_schedules_dict(...)
#     테스트나 내부 코드에서 tool invoke 없이 삭제 로직을 호출할 수 있게 만든 dict 반환 helper입니다.
#
#   - [추가] personal_update_saved_schedule(...)
#     schedule_id로 저장 일정을 찾아 제목/날짜/시간/참석자를 수정합니다. 공유 일정 동기화 결과도 함께 반환합니다.
#
#   - [추가] personal_delete_saved_schedules(...)
#     schedule_ids나 날짜/제목/시간 필터로 저장 일정을 삭제하는 tool입니다. 조건 없는 삭제는 실패 응답으로 막습니다.
#
#   - [공통] week03_tools()
#     Week 1 tool 목록에 Week 2 구조화 tool과 Week 3 SQLite tool을 누적합니다. Week 1 personal_create_schedule은
#     SQLite 저장까지 수행하는 이 파일의 호환 tool로 교체합니다.
#
#   - [공통] week03_system_prompt() / week03_prompt_parts()
#     Week 3 agent가 "구조화 후 저장" 흐름을 따르도록 system prompt를 조립합니다.
#
#   - [공통] build_week03_agent() / build_week_agent()
#     Week 1~3 tool을 가진 agent를 한 번만 만들고 재사용합니다. build_week_agent()는 실행기가 호출하는 표준 entry point입니다.




#####테스트 파일 : ../test/test_week03_build_nanas_logbook.py에 존재한다.

# [테스트] 이 함수 자체는 테스트 스위트에서 한 번도 실제로 실행되지 않는다. 모든 테스트가
# _store를 mocker.patch("student_parts.week03_build_nanas_logbook._store", ...)로 store fixture나
# MagicMock으로 바꾼 뒤 실행되기 때문에, 진짜 CONFIG.app_db_path를 읽는 이 코드 경로는
# tests/test_week03_build_nanas_logbook.py의 어떤 함수 시그니처와도 직접 연결되지 않는다.
def _store() -> AppSQLiteStore:
    return AppSQLiteStore(CONFIG.app_db_path)


# [테스트] 직접 호출하는 테스트는 없다. week03_tools() 내부의 tool 교체 분기에서 호출되므로
# TestWeek03ToolsAssembly.test_replaces_week01_personal_create_schedule_with_week03_version이
# 간접적으로 이 함수를 실행한다.
def _tool_name(item: Any) -> str:
    return getattr(item, "name", getattr(item, "__name__", str(item)))


# [테스트] 직접 호출하는 테스트는 없다. 거의 모든 @tool 함수가 반환 직전에 이 함수를 거치므로,
# .invoke(...)를 쓰는 테스트는 모두 간접적으로 이 함수를 실행한다. 대표적으로:
#   1) TestScheduleLifecycleIntegration
#   2) TestPersonalListSavedSchedules
#   3) TestErrorGuessing
#   (이 외에도 .invoke를 쓰는 테스트는 전부 해당된다)
def json_payload(payload: dict[str, Any]) -> str:
    """도구 반환용 dict를 한글이 깨지지 않는 JSON 문자열로 변환합니다."""

    return json.dumps(payload, ensure_ascii=False)


# [테스트] 직접 호출하는 테스트는 없다. save_structured_request_payload와 대부분의 @tool 본문이
# 이 함수로 응답을 감싸므로 json_payload와 마찬가지로 광범위하게 간접 실행된다.
def tool_result(tool_name: str, *, ok: bool = True, **payload: Any) -> dict[str, Any]:
    """Week 3 tool들이 공통으로 쓰는 JSON payload 껍데기를 만듭니다."""

    return {"ok": ok, "tool_name": tool_name, **payload}


# [테스트]
#   1) TestUnwrapLegacyPayloadBranches - structured_request wrapper / payload wrapper / 일반 dict
#      3개 분기
#   2) TestErrorGuessing.test_invalid_kind_is_rejected_by_pydantic - kind Literal 위반 거부
class SaveStructuredRequestInput(StructuredRequest):
    """SQLite 저장 직전에 검증하는 Week 3 입력 스키마입니다."""

    kind: RequestKind = Field(default="unknown", description="분류된 요청 종류")
    source_schedule_id: str | None = Field(default=None, description="Week 1 임시 일정에서 넘어온 원본 일정 ID")

    @model_validator(mode="before")
    @classmethod
    def unwrap_legacy_payload(cls, value: Any) -> Any:
        """예전 trace의 payload wrapper만 짧게 풀고 실제 검증은 필드 스키마에 맡깁니다."""

        # extract_schedule_request는 {ok, tool_name, base_date, structured_request:{...}} 형태로,
        # 예전 저장 helper는 {"payload": {...}} 형태로 감싸서 넘겼다. 이런 wrapper만 한 겹 벗겨
        # 실제 필드 dict를 돌려주고, 필드 검증은 아래 Pydantic 스키마에 맡긴다.
        if isinstance(value, dict):
            for wrapper_key in ("structured_request", "payload"):
                inner = value.get(wrapper_key)
                if isinstance(inner, dict):
                    return inner
        return value


# [테스트] TestSaveInputFromBranches가 아래 3개 분기를 각각 직접 실행한다.
#   1) StructuredRequest 인스턴스 분기
#   2) 유효 JSON 문자열 분기
#   3) 자연어 문자열 -> extract_structured_request로 넘어가는 분기(mock 처리)
# 남은 한 분기(SaveStructuredRequestInput 인스턴스를 그대로 통과시키는 첫 분기)는 별도 테스트 없이
# TestScheduleLifecycleIntegration.test_duplicate_source_schedule_id_is_not_saved_twice가
# structured_request_from_week01_schedule의 반환값을 그대로 넘길 때 간접 실행한다.
def _save_input_from(value: SaveStructuredRequestInput | StructuredRequest | dict[str, Any] | str) -> SaveStructuredRequestInput:
    """저장 입력을 SaveStructuredRequestInput 하나로 모읍니다."""

    if isinstance(value, SaveStructuredRequestInput):
        return value
    if isinstance(value, StructuredRequest):
        return SaveStructuredRequestInput.model_validate(value.model_dump())
    if isinstance(value, dict):
        return SaveStructuredRequestInput.model_validate(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            # JSON 문자열이면 그대로 검증한다(wrapper는 unwrap_legacy_payload가 벗긴다).
            return SaveStructuredRequestInput.model_validate(parsed)
        # 자연어 문자열이면 Week 2 bridge로 먼저 구조화한 뒤 저장 입력으로 맞춘다.
        structured = extract_structured_request(text)
        return SaveStructuredRequestInput.model_validate(structured.model_dump())
    raise RuntimeError(f"저장 입력으로 변환할 수 없는 형태입니다: {type(value)!r}")


# [테스트]
#   1) TestSaveStructuredRequestKindRouting - 직접 호출, kind별 테이블 라우팅 검증
#   2) TestSaveStructuredRequestBoundaries - 직접 호출, title 기본값 등 경계 상황 검증
#   3) TestDeleteGuardBranches - 데이터 준비 단계에서 호출(간접 검증)
#   4) TestPersonalListSavedSchedules - 데이터 준비 단계에서 호출(간접 검증)
#   5) TestListAndGetSavedRequestFiltering - 데이터 준비 단계에서 호출(간접 검증)
#   6) TestScheduleLifecycleIntegration - 데이터 준비 단계에서 호출(간접 검증)
# 3~6번은 결국 이 함수가 정확히 저장한다는 전제 위에서 성립하는 흐름이라 간접 검증이기도 하다.
def save_structured_request_payload(
    request: SaveStructuredRequestInput | StructuredRequest | dict[str, Any] | str,
    *,
    store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    """검증된 structured request를 앱 DB에 저장합니다."""

    save_input = _save_input_from(request)
    payload = save_input.model_dump(exclude_none=True)
    active_store = store or _store()
    result = active_store.save_structured_request(payload)
    return tool_result("save_structured_request", **result)


# [테스트] 이 클래스만 겨냥한 단위 테스트는 없다. list_saved_requests.invoke(...)를 통해 아래에서 간접 검증된다.
#   1) TestListAndGetSavedRequestFiltering
#   2) TestScheduleLifecycleIntegration
class SavedRequestListInput(BaseModel):
    """저장 요청 목록 조회 입력입니다."""

    kind: RequestKind | None = None
    date_from: str | None = None
    date_to: str | None = None


# [테스트] 이 클래스만 겨냥한 단위 테스트는 없다. get_saved_request.invoke(...)를 통해 아래에서 간접 검증된다.
#   1) TestListAndGetSavedRequestFiltering
#   2) TestErrorGuessing
class SavedRequestGetInput(BaseModel):
    """저장 요청 단건 조회 입력입니다."""

    request_id: str


# [테스트]
#   1) limit(ge=1/le=200) - TestSavedScheduleListInputBoundaries가 이 클래스를 직접 생성해 검증
#   2) kind/date_from/date_to - personal_list_saved_schedules.invoke(...)를 통해
#      TestPersonalListSavedSchedules에서 간접 검증
class SavedScheduleListInput(BaseModel):
    """저장 일정 목록 조회 입력입니다."""

    limit: int = Field(default=50, ge=1, le=200)
    kind: RequestKind | None = None
    date_from: str | None = None
    date_to: str | None = None


# [테스트] 이 클래스만 겨냥한 단위 테스트는 없다. personal_update_saved_schedule.invoke(...)를 통해 아래에서 간접 검증된다.
#   1) TestErrorGuessing - 실패 경로
#   2) TestScheduleLifecycleIntegration - 성공 경로
class SavedScheduleUpdateInput(BaseModel):
    """저장 일정 수정 입력입니다."""

    schedule_id: str
    title: str | None = None
    date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    attendees: list[str] | None = None


# [테스트] 이 클래스만 겨냥한 단위 테스트는 없다. personal_delete_saved_schedules.invoke(...)를 통해 아래에서 간접 검증된다.
#   1) TestErrorGuessing - 실패 경로
#   2) TestScheduleLifecycleIntegration - 성공 경로
class SavedScheduleDeleteInput(BaseModel):
    """저장 일정 삭제 입력입니다."""

    schedule_ids: list[str] | None = None
    date: str | None = None
    title: str | None = None
    start_time: str | None = None
    time_unspecified: bool = False
    delete_all: bool = False


# [테스트] TestDeleteGuardBranches가 아래 4개 분기를 각각 직접 실행한다.
#   1) 조건 없음(거부)
#   2) delete_all=True
#   3) title 필터
#   4) time_unspecified 단독 필터
# TestScheduleLifecycleIntegration.test_full_personal_schedule_lifecycle에서 schedule_ids
# 필터 경로도 함께 실행된다.
def _delete_saved_schedules(
    *,
    store: AppSQLiteStore,
    schedule_ids: list[str] | None = None,
    date: str | None = None,
    title: str | None = None,
    start_time: str | None = None,
    time_unspecified: bool = False,
    delete_all: bool = False,
) -> dict[str, Any]:
    """삭제 guard와 DB 호출을 한 곳에 둡니다."""

    filters = {
        "schedule_ids": schedule_ids,
        "date": date,
        "title": title,
        "start_time": start_time,
        "time_unspecified": time_unspecified,
        "delete_all": delete_all,
    }
    has_filter = bool(schedule_ids) or bool(date) or bool(title) or bool(start_time) or time_unspecified
    if not delete_all and not has_filter:
        # 조건이 하나도 없으면 전체 일정을 통째로 지울 위험이 있으므로 막는다.
        return tool_result(
            "personal_delete_saved_schedules",
            ok=False,
            error="삭제 조건이 없습니다. schedule_ids나 날짜/제목/시간 필터, 또는 delete_all=true가 필요합니다.",
            deleted_count=0,
            filters=filters,
            deleted=[],
        )

    if delete_all:
        deleted = store.delete_all_schedules()
    else:
        deleted = store.delete_schedules_by_filter(
            schedule_ids=schedule_ids,
            date=date,
            title=title,
            start_time=start_time,
            time_unspecified=time_unspecified,
        )
    return tool_result(
        "personal_delete_saved_schedules",
        deleted_count=len(deleted),
        filters=filters,
        deleted=deleted,
    )


# [테스트] TestWeek01ScheduleConversionBranches가 아래 2개 분기를 각각 직접 실행한다.
#   1) end_time이 None/""/"미정"이면 None으로 정규화되는 분기
#   2) 실제 값이 있으면 그대로 보존되는 분기
# 아래에서도 간접적으로 실행된다.
#   3) personal_create_schedule
#   4) TestScheduleLifecycleIntegration.test_duplicate_source_schedule_id_is_not_saved_twice
def structured_request_from_week01_schedule(schedule: dict[str, Any]) -> SaveStructuredRequestInput:
    """Week 1 임시 일정 dict를 Week 3 저장 입력으로 변환합니다."""

    end_time = schedule.get("end_time")
    if end_time in (None, "", "미정"):
        # Week 1은 종료 시간이 없으면 "미정"을 넣지만, DB에는 값 없음(None)으로 남기는 편이 깔끔하다.
        end_time = None
    return SaveStructuredRequestInput(
        kind="personal_schedule",
        title=schedule.get("title"),
        date=schedule.get("date"),
        start_time=schedule.get("start_time"),
        end_time=end_time,
        members=schedule.get("attendees") or [],
        original_text=schedule.get("title") or "",
        source_schedule_id=schedule.get("id"),
    )


# [테스트] TestSaveStructuredRequestCallsStoreCorrectly.test_personal_create_schedule_wires_week01_result_into_sqlite_save
# (Mock 검증 - _store를 MagicMock으로 바꿔 "Week1 결과가 SQLite 저장 인자로 정확히 넘어가는가"만
# 확인한다). 실제 SQLite에 값이 남는지 끝까지 확인하는 통합 테스트는 아직 없다(커버리지 공백).
@tool("personal_create_schedule")
def personal_create_schedule(
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    attendees: list[str] | None = None,
) -> str:
    """Nana의 개인 일정을 생성하고 Week 3+ 앱 SQLite DB에도 저장합니다."""

    created = json.loads(
        week01_personal_create_schedule.invoke(
            {
                "title": title,
                "date": date,
                "start_time": start_time,
                "end_time": end_time,
                "attendees": attendees or [],
            }
        )
    )
    schedule = created.get("created_schedule", {})
    save_input = structured_request_from_week01_schedule(schedule)
    sqlite_save = save_structured_request_payload(save_input)
    return json_payload(
        tool_result(
            "personal_create_schedule",
            created_schedule=schedule,
            structured_request=save_input.model_dump(),
            sqlite_save=sqlite_save,
        )
    )


# fixed/app_store.py의 AppSQLiteStore.save_structured_request가 kind별로 어느 테이블에
# 저장하는지를 그대로 옮겨 적은 매핑입니다. 아래 tool 설명 문구(_save_structured_request_description)를
# 이 dict 하나로 만들어서, kind나 저장 테이블이 바뀌어도 문구를 손으로 따로 고칠 필요가 없게 합니다.
#
# [테스트] 이 dict 자체는 저장 로직에 쓰이지 않고(tool 설명 문구 조립 전용) 실제 kind -> 테이블
# 라우팅은 fixed/app_store.py의 AppSQLiteStore.save_structured_request가 수행합니다.
# TestSaveStructuredRequestKindRouting은 이 dict가 아니라 그 실제 동작을 검증하며, 두 값이
# 우연이 아니라 항상 일치해야 한다는 사실 자체가 이 dict가 존재하는 이유입니다.
_KIND_TABLE_MAP: dict[str, str] = {
    "personal_schedule": "schedules",
    "group_schedule": "schedules",
    "todo": "todos",
    "reminder": "reminders",
}


# [테스트] 없음 - tool의 description 문자열 내용은 어떤 테스트에서도 assert 대상이 아니다.
def _save_structured_request_description() -> str:
    """_KIND_TABLE_MAP에서 kind별 저장 테이블 문구를 코드로 조립합니다."""

    routing = ", ".join(f"{kind} -> {table}" for kind, table in _KIND_TABLE_MAP.items())
    return (
        "extract_schedule_request로 구조화한 structured_request를 SQLite에 영구 저장하는 tool이다. "
        "personal_create_schedule 같은 Week 1 tool의 결과는 메모리에만 남아 대화가 끝나면 사라지므로, "
        "대화 종료 후에도 보관해야 할 내용은 반드시 이 tool로 저장한다.\n"
        "\n"
        "[입력] structured_request의 필드를 같은 이름 인자로 그대로 전달한다: "
        "kind, title, date, start_time, end_time, members, priority, reason, original_text "
        "(source_schedule_id는 Week 1 임시 일정을 이관 저장할 때만 채운다).\n"
        "\n"
        "[저장 절차]\n"
        "  1) kind와 상관없이 요청 원본을 structured_requests 테이블에 항상 기록한다.\n"
        f"  2) kind에 따라 정규화 테이블({routing})에 같은 요청을 한 줄 더 저장한다. "
        "personal_schedule/group_schedule은 외부 공유 일정 저장소에도 busy-time으로 동기화한다.\n"
        "  3) 위 매핑에 없는 kind(unknown 등)는 structured_requests에만 남고 정규화 테이블에는 저장하지 않는다.\n"
        "\n"
        "[동기화(shared_sync)] personal_schedule/group_schedule만 외부 공유 일정 저장소에 "
        "'나'(그룹은 참석자별) 이름의 busy-time 복사본으로 올린다. Week 1 personal_create_schedule은 "
        "'나' 혼자 보는 임시 메모리 일정이었지만, Week 5/6에서 여러 사람과 시간을 맞추려면 각자의 바쁜 시간을 "
        "이 공유 저장소에서 모아야 한다. 그래서 내 일정도 여기 올려둬야 남이 나와 약속을 잡을 때 겹치는 시간이 "
        "보인다. todo/reminder/unknown은 남과 겹칠 시간이 아니므로 동기화하지 않아 shared_sync가 None이 된다.\n"
        "\n"
        "[출력] 다음 형태의 JSON 문자열을 반환한다: "
        "{ok, tool_name, request_id, kind, saved_rows:[{table, id}], shared_sync}. "
        "(source_schedule_id로 이미 저장된 일정을 다시 가리키면 already_exists:true가 덧붙는다.)\n"
        "\n"
        "[후처리] request_id와 saved_rows(실제 저장된 테이블 목록)를 사용자에게 자연어로 확인해 준다. "
        "shared_sync가 있고 그 안의 ok가 false이면 앱 저장 자체는 성공했더라도 외부 공유 일정 동기화가 "
        "실패한 것이므로, 이 실패 사실을 함께 알려준다."
    )


# [테스트]
#   1) TestSaveStructuredRequestCallsStoreCorrectly.test_save_structured_request_forwards_exact_payload_to_store
#      - Mock 검증: 어떤 인자로 store를 호출했는가
#   2) TestScheduleLifecycleIntegration.test_tool_layer_end_to_end_via_agent_style_invoke
#      - 통합: 실제 SQLite에 저장되고 이후 조회/수정/삭제와 맞물리는지
#   3) TestScheduleLifecycleIntegration.test_full_lifecycle_via_tool_invoke_including_update_and_delete
#      - 통합: 위와 같은 관점, update/delete 성공 경로까지 포함
@tool(args_schema=SaveStructuredRequestInput, description=_save_structured_request_description())
def save_structured_request(
    kind: RequestKind = "unknown",
    title: str | None = None,
    date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    members: list[str] | None = None,
    priority: str | None = None,
    reason: str | None = None,
    original_text: str = "",
    source_schedule_id: str | None = None,
) -> str:
    """Week 2 structured_request 필드를 검증한 뒤 SQLite에 저장합니다."""

    payload = {
        "kind": kind,
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "members": members or [],
        "priority": priority,
        "reason": reason,
        "original_text": original_text,
        "source_schedule_id": source_schedule_id,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    """
    [반환 구조] _store().save_structured_request()의 실제 반환 dict
      (fixed/app_store.py AppSQLiteStore.save_structured_request 기준):
        {"request_id": str, "kind": str,
         "saved_rows": [{"table": str, "id": str}, ...], "shared_sync": dict | None}
      - source_schedule_id로 넘어온 일정이 이미 schedules에 있으면 새로 저장하지 않고,
        "already_exists": True와 saved_rows 각 항목의 "existing": True가 덧붙는다.
      - 아래 **result로 이 dict를 펼치므로, 최종 반환 JSON에는 request_id/kind/saved_rows/
        shared_sync가 ok/tool_name과 같은 층(top-level)에 나란히 들어간다.

    [shared_sync란] "앱 DB(내부 기록) -> 외부 공유 일정 저장소(남에게 보이는 나의 busy-time)"
      동기화 결과다.

    [왜 동기화하나 / Week 1과의 관계]
      1) Week 1 personal_create_schedule은 일정을 인메모리 리스트에, 그것도 현재 세션
         범위로만 만들어 "나" 혼자 보고 대화가 끝나면 사라졌다.
      2) Week 3에서 같은 개인 일정을 personal_schedule로 저장하면 앱 DB에 영속되고,
         여기서 외부 공유 저장소의 member_name="나"(fixed/external_mcp.py
         PERSONAL_SHARED_MEMBER_NAME) 복사본으로도 올라간다.
      3) Week 5/6에서 여러 사람과 시간을 맞출 때 각자의 busy-time을 이 공유 저장소에서
         모으기 때문에, 내 일정도 올려둬야 남이 나와 약속을 잡을 때 겹치는 시간이 보인다.
      => Week 1의 "나만 보는 임시 일정"이 Week 3부터 "영속 + 남에게 busy-time으로 보이는
         일정"으로 변환되는 지점이 바로 이곳이다.

    [shared_sync가 채워지는 조건]
      - kind가 personal_schedule/group_schedule일 때만 sync_personal_schedule_to_shared /
        sync_group_schedule_to_shared 호출 결과({"ok": bool, "status": ...})가 채워진다.
      - todo/reminder/unknown은 남과 겹칠 시간이 아니라 동기화하지 않으므로 None이다.
      - 개인 일정이라도 date가 없으면 status="skipped"로 건너뛴다.

    [실패 처리] 외부 호출이 실패해도 예외를 던지지 않고 {"ok": False, "status": "failed", ...}
      형태로 shared_sync에 담기므로, 앱 DB 저장(request_id/saved_rows)은 성공했는데 외부
      동기화만 실패한 경우를 shared_sync만 보고 구분할 수 있다.
    """
    result = _store().save_structured_request(payload)
    return json_payload(tool_result("save_structured_request", **result))


# [테스트]
#   1) TestListAndGetSavedRequestFiltering.test_list_saved_requests_date_range_filters_rows - date_from/date_to 범위
#   2) TestScheduleLifecycleIntegration.test_tool_layer_end_to_end_via_agent_style_invoke
@tool(args_schema=SavedRequestListInput)
def list_saved_requests(
    kind: RequestKind | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """SQLite에 저장된 구조화 요청 목록을 조회합니다."""

    rows = _store().list_saved_requests(kind=kind, date_from=date_from, date_to=date_to)
    return json_payload(tool_result("list_saved_requests", rows=rows))


# [테스트]
#   1) TestListAndGetSavedRequestFiltering.test_get_saved_request_returns_full_row_by_id - 성공 경로
#   2) TestErrorGuessing.test_get_unknown_request_id_returns_none_not_error - 없는 id -> row=None
#   3) TestScheduleLifecycleIntegration.test_tool_layer_end_to_end_via_agent_style_invoke
@tool(args_schema=SavedRequestGetInput)
def get_saved_request(request_id: str) -> str:
    """request_id로 구조화 요청 행 하나를 조회합니다."""

    row = _store().get_saved_request(request_id)
    return json_payload(tool_result("get_saved_request", row=row))


# [테스트]
#   1) TestPersonalListSavedSchedules - kind 기본값/명시 필터, date_from/date_to 범위, limit 상한
#   2) TestSaveStructuredRequestCallsStoreCorrectly.test_personal_list_saved_schedules_forwards_filters_to_store
#      - Mock 검증: store.list_schedules에 넘어가는 인자
#   3) TestScheduleLifecycleIntegration.test_full_lifecycle_via_tool_invoke_including_update_and_delete
@tool(args_schema=SavedScheduleListInput)
def personal_list_saved_schedules(
    limit: int = 50,
    kind: RequestKind | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """앱 DB에 저장된 일정 목록을 날짜/종류 필터로 반환합니다. Nana가 조회/수정/삭제 후보를 볼 때 사용합니다."""

    effective_kind = kind or "personal_schedule"
    schedules = _store().list_schedules(limit=limit, kind=effective_kind, date_from=date_from, date_to=date_to)
    filters = {"limit": limit, "kind": effective_kind, "date_from": date_from, "date_to": date_to}
    return json_payload(tool_result("personal_list_saved_schedules", filters=filters, schedules=schedules))


# [테스트] 없음 - 테스트 스위트에서 이 함수를 직접 호출하는 곳이 없다(커버리지 공백).
def delete_saved_schedules_dict(
    schedule_ids: list[str] | None = None,
    date: str | None = None,
    title: str | None = None,
    start_time: str | None = None,
    time_unspecified: bool = False,
    delete_all: bool = False,
    app_store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    """tool invoke 없이 저장 일정 삭제 로직을 직접 호출합니다."""

    store = app_store or _store()
    return _delete_saved_schedules(
        store=store,
        schedule_ids=schedule_ids,
        date=date,
        title=title,
        start_time=start_time,
        time_unspecified=time_unspecified,
        delete_all=delete_all,
    )


# [테스트]
#   1) TestErrorGuessing.test_update_unknown_schedule_id_fails_gracefully - 실패 경로: ok=False
#   2) TestScheduleLifecycleIntegration.test_full_lifecycle_via_tool_invoke_including_update_and_delete
#      - 성공 경로: updated_schedule/shared_sync 확인
@tool(args_schema=SavedScheduleUpdateInput)
def personal_update_saved_schedule(
    schedule_id: str,
    title: str | None = None,
    date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    attendees: list[str] | None = None,
) -> str:
    """앱 DB에 저장된 내 일정 원본을 수정하고 공유 일정 복사본을 같은 값으로 갱신합니다."""

    # None으로 들어온 필드는 "수정하지 않음"이라는 뜻이며, store.update_schedule이 기존 값을 유지한다.
    result = _store().update_schedule(
        schedule_id,
        title=title,
        date=date,
        start_time=start_time,
        end_time=end_time,
        attendees=attendees,
    )
    if result is None:
        return json_payload(
            tool_result(
                "personal_update_saved_schedule",
                ok=False,
                error=f"schedule_id {schedule_id}에 해당하는 일정을 찾을 수 없습니다.",
                schedule_id=schedule_id,
            )
        )
    return json_payload(
        tool_result(
            "personal_update_saved_schedule",
            schedule_id=schedule_id,
            updated_schedule=result["schedule"],
            shared_sync=result["shared_sync"],
        )
    )


# [테스트]
#   1) TestErrorGuessing.test_delete_without_any_condition_is_rejected - 실패 경로: 조건 없음 거부
#   2) TestScheduleLifecycleIntegration.test_full_lifecycle_via_tool_invoke_including_update_and_delete
#      - 성공 경로: schedule_ids로 실제 삭제
@tool(args_schema=SavedScheduleDeleteInput)
def personal_delete_saved_schedules(
    schedule_ids: list[str] | None = None,
    date: str | None = None,
    title: str | None = None,
    start_time: str | None = None,
    time_unspecified: bool = False,
    delete_all: bool = False,
) -> str:
    """Nana가 고른 일정 ID나 날짜/제목/시간 필터로 저장 일정을 삭제합니다."""

    result = _delete_saved_schedules(
        store=_store(),
        schedule_ids=schedule_ids,
        date=date,
        title=title,
        start_time=start_time,
        time_unspecified=time_unspecified,
        delete_all=delete_all,
    )
    return json_payload(result)


# [테스트] TestWeek03ToolsAssembly가 아래 2가지를 확인한다.
#   1) week01 personal_create_schedule이 이 파일의 버전으로 교체되는지(identity 비교)
#   2) 예상하는 SQLite tool 전체 집합이 포함되는지
def week03_tools() -> list[Any]:
    """Week 1 도구, Week 2 구조화 helper, SQLite 저장/조회/삭제 도구를 조립합니다."""

    base_tools = [
        personal_create_schedule if _tool_name(item) == "personal_create_schedule" else item for item in week01_tools()
    ]
    return [
        *base_tools,
        extract_schedule_request,
        save_structured_request,
        list_saved_requests,
        get_saved_request,
        personal_list_saved_schedules,
        personal_update_saved_schedule,
        personal_delete_saved_schedules,
    ]


# [테스트] 없음 - 시스템 프롬프트 문자열 조립 자체는 assert 대상이 아니다.
def week03_system_prompt() -> str:
    """3주차 단일 agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt(week03_prompt_parts())


# [테스트] 없음 - week03_system_prompt()와 마찬가지로 프롬프트 문자열 내용은 검증하지 않는다.
def week03_prompt_parts() -> list[str]:
    """1~3주차 system prompt 조각을 누적합니다."""

    return [
        *week02_prompt_parts(),
        SQLITE_MEMORY_PROMPT,
        WEEK03_TOOL_CALL_PROMPT,
        (
            f"오늘 날짜는 {current_app_date_iso()}이다. 이번 주(Week 3)의 범위는 구조화 저장·조회와 "
            "저장된 일정의 수정·삭제다. 일정을 새로 만들거나 저장할 때는 항상 extract_schedule_request로 "
            "구조화한 뒤 save_structured_request를 호출한다(personal_create_schedule은 Week 1 임시 일정과 "
            "SQLite 저장을 함께 수행하는 호환 tool이다). 저장된 일정을 수정·삭제할 때는 먼저 "
            "personal_list_saved_schedules로 대상 schedule_id를 확인한 뒤 personal_update_saved_schedule 또는 "
            "personal_delete_saved_schedules를 호출한다. 조건 없이 전체를 지우는 delete_all=true는 "
            "사용자가 명시적으로 전체 삭제를 요청할 때만 사용한다."
        ),
    ]


# [테스트] 없음 - 실제 OpenAI 키(CONFIG.has_openai_key)가 있어야 create_agent가 동작하므로
# 단위 테스트로 다루지 않는다(수동 검증: ./run.sh --week3).
def build_week03_agent() -> object:
    """Week 1-3 누적 tool 목록을 노출하는 단일 LangChain agent를 만듭니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK03_AGENT
    if _WEEK03_AGENT is None:
        _WEEK03_AGENT = create_agent(
            model=chat_model(),
            tools=week03_tools(),
            system_prompt=week03_system_prompt(),
        )
    return _WEEK03_AGENT


# [테스트] 없음 - build_week03_agent()와 동일한 이유로 단위 테스트 대상이 아니다.
def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week03_agent()
