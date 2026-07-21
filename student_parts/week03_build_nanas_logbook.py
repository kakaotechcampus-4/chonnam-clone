from __future__ import annotations

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
    "## Week 3 영속 기록장\n"
    "- SQLite 기록장에 저장한 일정/할 일/알림은 새 대화를 열거나 앱을 다시 시작해도 그대로 남는다.\n"
    "- Week 1 임시 tool이 만드는 일정은 지금 이 대화에서만 살아 있고 앱을 다시 시작하면 사라진다. "
    "둘은 다른 저장소이므로 섞어서 답하지 않는다.\n"
    "- 과거에 저장했는지 확실하지 않으면 기억에 의존해 추측하지 말고 조회 tool로 먼저 확인한다."
)

WEEK03_TOOL_CALL_PROMPT = (
    "## Week 3 tool 호출 순서\n"
    "- 저장 요청이면 아래 순서를 그대로 따른다.\n"
    "  1) extract_schedule_request(query=사용자 요청 원문)를 호출해 자연어를 구조화한다.\n"
    "  2) 반환된 structured_request의 kind/title/date/start_time/end_time/members/priority/reason/"
    "original_text를 save_structured_request 인자로 그대로 전달한다. 값을 다시 해석하거나 지어내지 않는다.\n"
    "  3) 저장 결과의 request_id를 근거로 저장이 끝났음을 사용자에게 알린다.\n"
    "  4) (조건부) 위 저장(2~3)을 반드시 끝낸 뒤, 저장한 요청의 reason에 알림 의도가 애매하다는 "
    "내용이 있으면 답변에서 알림도 설정할지 물어본다. 저장을 건너뛰고 되묻기만 하지 않는다.\n"
    "- 조회 요청이면 대상에 맞는 tool을 한 번만 호출한다.\n"
    "  - 저장된 일정(개인/그룹) 목록: personal_list_saved_schedules\n"
    '  - 저장된 할 일/알림: list_saved_requests (kind="todo" 또는 kind="reminder")\n'
    "  - 저장된 원본 기록의 목록/단건: list_saved_requests / get_saved_request\n"
    "- personal_list_saved_schedules는 일정만 조회한다. 할 일/알림은 이 tool로 조회되지 않으므로 "
    'kind="todo"/"reminder"로 이 tool을 호출하지 않는다.\n'
    '- "내 일정 보여줘"처럼 종류를 특정하지 않은 조회는 kind를 채우지 않고 비워 둔다. 그래야 개인 일정과 '
    '그룹 일정이 모두 나온다. 사용자가 "그룹 일정만"처럼 종류를 특정할 때만 kind를 넣는다.\n'
    "- 같은 이유로, 사용자가 날짜 범위를 말하지 않았으면 date_from/date_to도 비워 둔다. 범위를 임의로 좁히면 "
    '그 밖의 저장 일정이 조용히 빠진다. "내일 일정"처럼 날짜가 분명할 때만 범위를 넣는다.\n'
    "- 요청 하나당 저장은 한 번만 한다. 같은 tool을 이유 없이 반복 호출하지 않고, "
    "구조화만 하고 저장 없이 끝내지 않는다.\n"
    "- 저장된 일정의 수정 요청이면 아래 순서를 따른다.\n"
    "  1) personal_list_saved_schedules로 대상 일정과 schedule_id를 확인한다.\n"
    "  2) 그 schedule_id로 personal_update_saved_schedule을 호출하되, "
    "사용자가 바꾸라고 한 필드만 채우고 나머지는 비워 둔다. 비워 둔 필드는 그대로 유지된다.\n"
    "  3) updated_schedule을 근거로 무엇이 어떻게 바뀌었는지 답한다.\n"
    "- 삭제 요청이면 personal_list_saved_schedules로 지울 대상을 먼저 특정한다.\n"
    "- delete_all=True는 사용자가 전체 삭제를 명시적으로 재확인한 경우에만 넘긴다.\n"
    "- 조회한 schedule_id를 남김없이 모아 넘기는 것도 결과가 전체 삭제이므로 같은 규칙을 따른다. "
    "재확인 전에는 삭제 tool을 호출하지 말고 무엇을 지울지 먼저 확인받는다.\n"
    "- 사용자가 특정하지 않은 삭제 필터(date/title/start_time/time_unspecified)나 수정 필드는 "
    "채우지 않고 비워 둔다. 임의로 채우면 사용자가 의도하지 않은 일정이 조용히 지워지거나 덮어써진다.\n"
    "\n"
    "### 예시\n"
    '- "내일 10시 개인 코칭 저장해줘" → extract_schedule_request → save_structured_request → '
    '"내일 10시 개인 코칭 일정을 기록장에 저장했어요."\n'
    '- "내 일정 보여줘" → personal_list_saved_schedules → 조회된 일정을 날짜/시각과 함께 목록으로 답한다.\n'
    '- "내일 코칭을 2시로 바꿔줘" → personal_list_saved_schedules → '
    "personal_update_saved_schedule(schedule_id=조회한 ID, start_time=\"14:00\") → "
    '"내일 코칭을 14:00으로 옮겼어요." (title/date/end_time은 바꾸라고 하지 않았으므로 비워 둔다.)\n'
    '- "내일 10시 코칭 지워줘" → personal_list_saved_schedules → '
    'personal_delete_saved_schedules(schedule_ids=["조회한 ID"]) → "내일 10시 코칭 일정을 지웠어요." '
    "(date나 title 필터는 ID로 이미 특정됐으므로 넣지 않는다.)\n"
    "\n"
    "### tool을 쓰지 말아야 할 때\n"
    "- 인사나 일반 대화에는 tool을 호출하지 않는다.\n"
    "\n"
    "### 실패 처리\n"
    "- tool 결과가 ok=false이면 저장/조회가 되지 않은 것이다. error를 근거로 무엇이 잘못됐는지 "
    "설명하고, 성공한 것처럼 답하거나 값을 지어내지 않는다.\n"
    "- 일정을 기록장에 저장하거나 수정하는 tool의 응답에는 공유 저장소 동기화 결과 shared_sync가 "
    "실린다 — 최상위에 있거나(저장·수정 tool), sqlite_save 안에 있다(즉시 생성 tool). "
    "shared_sync.ok가 false면 공유 저장소 동기화가 실패/생략된 것이므로 그 사실을 답변에 알린다.\n"
    "- 저장 응답의 already_exists가 true면(즉시 생성 tool에서는 sqlite_save 안) 새로 저장한 것이 "
    "아니라 이미 저장된 건이라고 답한다.\n"
    "- 저장·수정이 성공한 답변이라도 shared_sync.status가 skipped/failed면 "
    '"공유 저장소에는 등록되지 않았다"는 안내를 답변에 반드시 포함한다.'
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


def _store() -> AppSQLiteStore:
    return AppSQLiteStore(CONFIG.app_db_path)


def _tool_name(item: Any) -> str:
    return getattr(item, "name", getattr(item, "__name__", str(item)))


def json_payload(payload: dict[str, Any]) -> str:
    """도구 반환용 dict를 한글이 깨지지 않는 JSON 문자열로 변환합니다."""

    return json.dumps(payload, ensure_ascii=False)


def tool_result(tool_name: str, *, ok: bool = True, **payload: Any) -> dict[str, Any]:
    """Week 3 tool들이 공통으로 쓰는 JSON payload 껍데기를 만듭니다."""

    return {"ok": ok, "tool_name": tool_name, **payload}


class SaveStructuredRequestInput(StructuredRequest):
    """SQLite 저장 직전에 검증하는 Week 3 입력 스키마입니다."""

    kind: RequestKind = Field(default="unknown", description="분류된 요청 종류")
    source_schedule_id: str | None = Field(default=None, description="Week 1 임시 일정에서 넘어온 원본 일정 ID")

    @model_validator(mode="before")
    @classmethod
    def unwrap_legacy_payload(cls, value: Any) -> Any:
        """예전 trace의 payload wrapper만 짧게 풀고 실제 검증은 필드 스키마에 맡깁니다."""

        if not isinstance(value, dict):
            # dict가 아니면 필드 스키마가 판단하게 둔다.
            return value

        # {"payload": {"structured_request": {...}}}처럼 겹쳐 있을 수 있어 한 겹씩 반복해서 푼다.
        while True:
            for key in ("structured_request", "payload"):
                inner = value.get(key)
                if isinstance(inner, dict):
                    value = inner
                    break
            else:
                break

        # 필드 검사는 반드시 unwrap 뒤에 한다. 먼저 하면 wrapper dict가 오탐으로 거부된다.
        if not any(field in value for field in cls.model_fields):
            # Pydantic 기본값이 extra='ignore'라 여기서 막지 않으면 wrapper의 내용이 조용히 사라지고
            # kind="unknown" 기본값 row만 저장된다.
            raise ValueError(
                "저장할 수 있는 필드가 없습니다. kind/title/date/start_time/end_time/members/"
                "priority/reason/original_text 중 실제 값을 넘기세요."
            )

        # mode="before"는 기본값이 채워지기 전 원본 dict를 보므로, "kind 키 누락"(거부)과
        # "kind='unknown' 명시"(정당한 판정, 통과)를 구분할 수 있다.
        if "kind" not in value:
            raise ValueError(
                "kind가 없습니다. extract_schedule_request가 판정한 kind를 "
                "personal_schedule/group_schedule/todo/reminder/unknown 중 하나로 명시하세요."
            )
        return value


def _save_input_from(value: SaveStructuredRequestInput | StructuredRequest | dict[str, Any] | str) -> SaveStructuredRequestInput:
    """저장 입력을 SaveStructuredRequestInput 하나로 모읍니다."""

    if isinstance(value, SaveStructuredRequestInput):
        return value
    if isinstance(value, StructuredRequest):
        return SaveStructuredRequestInput.model_validate(value.model_dump())
    if isinstance(value, dict):
        return SaveStructuredRequestInput.model_validate(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return SaveStructuredRequestInput.model_validate(parsed)
        # JSON이 아니거나 dict가 아니면 자연어로 보고 Week 2 구조화를 거친다.
        return SaveStructuredRequestInput.model_validate(
            extract_structured_request(value).model_dump()
        )
    raise TypeError(f"저장 입력으로 쓸 수 없는 타입입니다: {type(value).__name__}")


def save_structured_request_payload(
    request: SaveStructuredRequestInput | StructuredRequest | dict[str, Any] | str,
    *,
    store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    """검증된 structured request를 앱 DB에 저장합니다."""

    validated = _save_input_from(request)
    saved = (store or _store()).save_structured_request(validated.model_dump(exclude_none=True))
    return tool_result("save_structured_request", **saved)


class SavedRequestListInput(BaseModel):
    """저장 요청 목록 조회 입력입니다."""

    kind: RequestKind | None = None
    date_from: str | None = None
    date_to: str | None = None


class SavedRequestGetInput(BaseModel):
    """저장 요청 단건 조회 입력입니다."""

    request_id: str


class SavedScheduleListInput(BaseModel):
    """저장 일정 목록 조회 입력입니다."""

    limit: int = Field(default=50, ge=1, le=200)
    kind: RequestKind | None = None
    date_from: str | None = None
    date_to: str | None = None


class SavedScheduleUpdateInput(BaseModel):
    """저장 일정 수정 입력입니다."""

    schedule_id: str
    title: str | None = None
    date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    attendees: list[str] | None = None


class SavedScheduleDeleteInput(BaseModel):
    """저장 일정 삭제 입력입니다."""

    schedule_ids: list[str] | None = None
    date: str | None = None
    title: str | None = None
    start_time: str | None = None
    time_unspecified: bool = False
    delete_all: bool = False


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
    if not delete_all and not any([schedule_ids, date, title, start_time, time_unspecified]):
        # 조건 전무 삭제는 store가 빈 목록으로 조용히 넘기지만, 그러면 "지웠다"와 "못 찾았다"가
        # 같은 응답이 된다. 여기서 코드로 거부해 LLM이 대상을 먼저 특정하게 만든다.
        return {
            "ok": False,
            "error": {
                "code": "missing_filters",
                "message": (
                    "삭제 조건이 없습니다. personal_list_saved_schedules로 대상을 확인한 뒤 "
                    "schedule_ids나 date/title/start_time 필터를 넘기세요. 전체 삭제는 "
                    "사용자가 재확인한 뒤에만 delete_all=True로 요청합니다."
                ),
            },
            "deleted_count": 0,
            "filters": filters,
            "deleted": [],
        }

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
    return {
        "ok": True,
        "deleted_count": len(deleted),
        "filters": filters,
        "deleted": deleted,
    }


def structured_request_from_week01_schedule(schedule: dict[str, Any]) -> SaveStructuredRequestInput:
    """Week 1 임시 일정 dict를 Week 3 저장 입력으로 변환합니다."""

    end_time = schedule.get("end_time")
    return SaveStructuredRequestInput(
        kind="personal_schedule",
        title=schedule.get("title"),
        date=schedule.get("date"),
        start_time=schedule.get("start_time"),
        # Week 1은 종료 시각 미상을 "미정"으로 쓰지만 Week 3 저장 계약은 HH:MM 아니면 None이다.
        # 여기서 정규화하지 않으면 한국어 문자열이 DB의 시각 필드에 그대로 들어간다.
        end_time=None if end_time == "미정" else end_time,
        members=list(schedule.get("attendees") or []),
        original_text=json.dumps(schedule, ensure_ascii=False),
        source_schedule_id=schedule.get("id"),
    )


@tool("personal_create_schedule")
def personal_create_schedule(
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    attendees: list[str] | None = None,
) -> str:
    """Nana의 개인 일정을 생성하고 Week 3+ 앱 SQLite DB에도 저장합니다."""

    created_raw = week01_personal_create_schedule.invoke({
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "attendees": attendees,
    })
    try:
        created = json.loads(created_raw) if isinstance(created_raw, str) else dict(created_raw)
    except (TypeError, ValueError):
        return json_payload(tool_result(
            "personal_create_schedule",
            ok=False,
            error="Week 1 일정 생성 tool 결과를 JSON으로 해석할 수 없습니다.",
            created_raw=created_raw,
        ))

    schedule = created.get("created_schedule")
    if not isinstance(schedule, dict):
        return json_payload(tool_result(
            "personal_create_schedule",
            ok=False,
            created=created,
            error="Week 1 일정 생성 결과에 created_schedule이 없습니다.",
        ))

    structured_request = structured_request_from_week01_schedule(schedule)
    sqlite_save = _store().save_structured_request(structured_request.model_dump(exclude_none=True))
    return json_payload({
        **created,
        "structured_request": structured_request.model_dump(),
        "sqlite_save": sqlite_save,
    })


@tool(args_schema=SaveStructuredRequestInput)
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
        "members": members if members is not None else [],
        "priority": priority,
        "reason": reason,
        "original_text": original_text,
        "source_schedule_id": source_schedule_id,
    }
    saved = _store().save_structured_request({k: v for k, v in payload.items() if v is not None})
    normalized_table = next(
        (row["table"] for row in saved["saved_rows"] if row["table"] != "structured_requests"),
        None,
    )
    return json_payload(
        tool_result("save_structured_request", **saved, normalized_table=normalized_table)
    )


@tool(args_schema=SavedRequestListInput)
def list_saved_requests(
    kind: RequestKind | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """SQLite에 저장된 구조화 요청 목록을 조회합니다."""

    rows = _store().list_saved_requests(kind=kind, date_from=date_from, date_to=date_to)
    return json_payload(tool_result("list_saved_requests", rows=rows))


@tool(args_schema=SavedRequestGetInput)
def get_saved_request(request_id: str) -> str:
    """request_id로 구조화 요청 행 하나를 조회합니다."""

    row = _store().get_saved_request(request_id)
    return json_payload(tool_result("get_saved_request", request_id=request_id, row=row))


@tool(args_schema=SavedScheduleListInput)
def personal_list_saved_schedules(
    limit: int = 50,
    kind: RequestKind | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """앱 DB에 저장된 일정 목록을 날짜/종류 필터로 반환합니다. Nana가 조회/수정/삭제 후보를 볼 때 사용합니다."""

    # kind는 선택적 필터다. None이면 store가 종류 제한 없이 조회하므로 개인/그룹 일정이 모두 나온다.
    rows = _store().list_schedules(limit=limit, kind=kind, date_from=date_from, date_to=date_to)
    return json_payload(tool_result(
        "personal_list_saved_schedules",
        filters={"limit": limit, "kind": kind, "date_from": date_from, "date_to": date_to},
        rows=rows,
    ))


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

    return _delete_saved_schedules(
        store=app_store or _store(),
        schedule_ids=schedule_ids,
        date=date,
        title=title,
        start_time=start_time,
        time_unspecified=time_unspecified,
        delete_all=delete_all,
    )


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

    result = _store().update_schedule(
        schedule_id,
        title=title,
        date=date,
        start_time=start_time,
        end_time=end_time,
        attendees=attendees,
    )
    if result is None:
        return json_payload(tool_result(
            "personal_update_saved_schedule",
            ok=False,
            schedule_id=schedule_id,
            error={
                "code": "not_found",
                "message": (
                    f"저장된 일정에서 schedule_id {schedule_id!r}를 찾지 못했습니다. "
                    "personal_list_saved_schedules로 대상 ID를 다시 확인하세요."
                ),
            },
        ))
    return json_payload(tool_result(
        "personal_update_saved_schedule",
        schedule_id=schedule_id,
        updated_schedule=result["schedule"],
        shared_sync=result["shared_sync"],
    ))


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
    return json_payload(tool_result("personal_delete_saved_schedules", **result))


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


def week03_system_prompt() -> str:
    """3주차 단일 agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt(week03_prompt_parts())


def week03_prompt_parts() -> list[str]:
    """1~3주차 system prompt 조각을 누적합니다."""

    return [
        *week02_prompt_parts(),
        SQLITE_MEMORY_PROMPT,
        WEEK03_TOOL_CALL_PROMPT,
        # 상속되는 Week 1-2 지시 중 Week 3와 충돌하는 것은 "뒤 지시 우선" 규칙에 맡기지 않고 콕 집어 무효화한다.
        "## Week 3 역할과 범위\n"
        "- Week 3의 주 역할은 구조화 결과를 SQLite 기록장에 저장하고 다시 조회하는 것이다. "
        "따라서 '## Week 2 범위 제한'의 'SQLite 저장을 하지 않는다'와 "
        "'## Week 2 역할: 요청 구조화 agent'라는 역할 규정은 Week 3에 적용되지 않는다. "
        "단 RAG와 외부 멤버 일정 조율을 하지 않는다는 제한은 Week 3에도 그대로 유효하다.\n"
        "- '## kind 판정과 tool 사용'의 'tool은 kind가 personal_schedule인 요청에만 호출한다'는 "
        "Week 2 한정 규칙이라 Week 3에는 적용되지 않는다. Week 3에서는 kind가 personal_schedule/"
        "group_schedule/todo/reminder 중 무엇이든 저장 요청이면 save_structured_request로 저장한다. "
        "다만 kind를 어떻게 판정하는지의 기준 자체는 Week 3에서도 그대로 따른다.\n"
        "- Week 1 임시 tool(personal_list_schedules/personal_delete_schedule)은 지금 이 대화에서만 "
        "살아 있는 임시 일정 전용이고, SQLite 기록장의 저장 일정은 다루지 못한다. 사용자가 "
        "'이 대화에서 만든 임시 일정'이라고 분명히 말할 때만 쓴다.\n"
        "- 저장된 일정의 조회/수정/삭제는 반드시 SQLite tool로 한다. 조회는 personal_list_saved_schedules, "
        "수정은 personal_update_saved_schedule, 삭제는 personal_delete_saved_schedules다. "
        "이름이 비슷한 임시 tool로 대신하지 않는다.\n"
        "- 두 저장소는 동기화되지 않는다. personal_delete_schedule로 임시 일정을 지워도 기록장의 저장 "
        "일정은 그대로 남고, 반대도 마찬가지다. 그래서 '일정 지워줘'는 기본적으로 저장 일정 삭제로 보고 "
        "personal_delete_saved_schedules로 처리한다.\n"
        "- 일정 생성/저장 요청은 extract_schedule_request → save_structured_request 경로로 처리한다. "
        "personal_create_schedule은 임시 일정과 기록장에 함께 남기는 이중 기록 tool이라, "
        "사용자가 Week 1처럼 즉시 생성을 요청할 때만 쓴다.",
    ]


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


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week03_agent()
