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

  공통: request_id/created_at은 payload에 없던 값으로, 저장 시점에 새로 만들어집니다.
  kind 컬럼도 컬럼화 테이블에는 없어서, 조회 시 structured_requests와 다시 join해야 합니다.
  original_text는 어떤 컬럼화 테이블에도 없고, structured_requests.raw_json 안에만
  원문 그대로 남습니다.

실제 테이블 스키마와 분기 저장 로직은 이미 fixed/app_store.py의
AppSQLiteStore.save_structured_request에 구현되어 있으므로, 이 파일의 책임은 LLM agent가
그 저장소를 호출하도록 tool과 prompt를 잇는 것입니다.
"""

import json
from typing import Annotated, Any

from langchain.agents import create_agent
from langchain.tools import tool
from pydantic import Field

from fixed.app_store import AppSQLiteStore
from fixed.config import CONFIG
from fixed.llm import chat_model
from student_parts.week01_wake_up_nana import join_system_prompt
from student_parts.week02_structure_natural_language_requests import (
    RequestKind,
    StructuredRequest,
    extract_schedule_request,
    week02_prompt_parts,
    week02_tools,
)

_WEEK03_AGENT: Any | None = None
_APP_STORE: AppSQLiteStore | None = None

# fixed/app_store.py의 AppSQLiteStore.save_structured_request가 kind별로 어느 테이블에
# 저장하는지를 그대로 옮겨 적은 매핑입니다. 아래 tool 설명 문구(_save_structured_request_description)를
# 이 dict 하나로 만들어서, kind나 저장 테이블이 바뀌어도 문구를 손으로 따로 고칠 필요가 없게 합니다.
_KIND_TABLE_MAP: dict[str, str] = {
    "personal_schedule": "schedules",
    "group_schedule": "schedules",
    "todo": "todos",
    "reminder": "reminders",
}


def _app_store() -> AppSQLiteStore:
    """앱 DB와 같은 SQLite 파일(CONFIG.app_db_path)을 가리키는 저장소를 필요한 시점에 한 번만 만듭니다."""

    global _APP_STORE
    if _APP_STORE is None:
        _APP_STORE = AppSQLiteStore(CONFIG.app_db_path)
    return _APP_STORE


def _save_structured_request_description() -> str:
    """_KIND_TABLE_MAP에서 kind별 저장 테이블 문구를 코드로 조립합니다."""

    routing = ", ".join(f"{kind} -> {table}" for kind, table in _KIND_TABLE_MAP.items())
    return (
        "extract_schedule_request의 structured_request 필드 값을 그대로 받아 SQLite에 영구 저장한다. "
        "personal_create_schedule 같은 Week 1 tool이 만든 결과는 메모리에만 남아 대화가 끝나면 사라지므로, "
        "대화 종료 후에도 보관해야 할 내용은 항상 이 tool을 호출하여 저장한다.\n"
        "저장은 두 단계로 이뤄진다. 먼저 kind와 상관없이 요청 원본이 structured_requests 테이블에 "
        f"항상 기록된다. 이어서 kind에 따라 정규화 테이블({routing})에도 같은 요청이 한 줄 더 저장된다"
        "(personal_schedule/group_schedule은 외부 공유 일정 저장소에도 busy-time으로 동기화된다). "
        "위 매핑에 없는 kind(unknown 등)는 structured_requests에만 남고 정규화 테이블에는 저장되지 않는다.\n"
        "반환 JSON의 request_id와 saved_rows(실제 저장된 테이블 목록)를 사용자에게 자연어로 확인해 준다. "
        "shared_sync가 있고 그 안의 ok가 false이면 외부 공유 일정 동기화가 실패한 것이므로, "
        "앱 저장 자체는 성공했더라도 이 실패 사실을 함께 알려준다."
    )


def _week02_field_description(name: str) -> str:
    """StructuredRequest 필드 설명을 그대로 재사용."""

    return StructuredRequest.model_fields[name].description or ""


@tool(description=_save_structured_request_description())
def save_structured_request(
    kind: Annotated[RequestKind, Field(description=_week02_field_description("kind"))],
    title: Annotated[str | None, Field(description=_week02_field_description("title"))] = None,
    date: Annotated[str | None, Field(description=_week02_field_description("date"))] = None,
    start_time: Annotated[str | None, Field(description=_week02_field_description("start_time"))] = None,
    end_time: Annotated[str | None, Field(description=_week02_field_description("end_time"))] = None,
    members: Annotated[list[str] | None, Field(description=_week02_field_description("members"))] = None,
    priority: Annotated[str | None, Field(description=_week02_field_description("priority"))] = None,
    reason: Annotated[str | None, Field(description=_week02_field_description("reason"))] = None,
    original_text: Annotated[str, Field(description=_week02_field_description("original_text"))] = "",
) -> str:

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
    }
    # _app_store().save_structured_request()가 반환하는 dict의 실제 모양은 다음과 같다
    # (fixed/app_store.py의 AppSQLiteStore.save_structured_request 반환값 기준):
    #   {"request_id": str, "kind": str,
    #    "saved_rows": [{"table": str, "id": str}, ...], "shared_sync": dict | None}
    # 아래 **result로 이 dict를 펼치므로, 최종 반환 JSON에는 request_id/kind/saved_rows/
    # shared_sync가 ok/tool_name과 같은 층(top-level)에 나란히 들어간다.
    #
    # shared_sync는 위 tool 설명의 "personal_schedule/group_schedule은 외부 공유 일정
    # 저장소에도 busy-time으로 동기화된다"를 실제로 수행한 결과다. kind가 personal_schedule/
    # group_schedule일 때만 fixed/external_mcp.py의 sync_personal_schedule_to_shared /
    # sync_group_schedule_to_shared 호출 결과가 채워지고, todo/reminder/unknown이면 그냥
    # None이다. 이 호출이 실패해도 예외를 던지지 않고 {"ok": False, "status": "failed", ...}
    # 형태로 shared_sync에 담기므로, 앱 DB 저장(request_id/saved_rows)은 성공했는데
    # 외부 동기화만 실패한 경우를 shared_sync만 보고 구분할 수 있다.
    result = _app_store().save_structured_request(payload)
    return json.dumps(
        {"ok": True, "tool_name": "save_structured_request", **result},
        ensure_ascii=False,
    )


def week03_tools() -> list[Any]:
    """Week 2 tool에 구조화 bridge tool(extract_schedule_request)과 저장 tool(save_structured_request)을 더한 목록입니다."""

    return [*week02_tools(), extract_schedule_request, save_structured_request]


def week03_prompt_parts() -> list[str]:
    """3주차 agent가 따르는 system prompt 조각입니다."""

    structured_fields = "/".join(StructuredRequest.model_fields)
    return [
        *week02_prompt_parts(),
        (
            "이번 주 목표는 구조화한 요청을 대화가 끝나도 휘발시키지 않고 SQLite에 저장하는 것이다. "
            "일정/할 일/알림 관련 자연어 요청이 들어오면 먼저 extract_schedule_request로 구조화한 뒤, "
            f"반환된 JSON의 structured_request 필드에 담긴 {structured_fields} "
            "값을 꺼내 save_structured_request tool의 같은 이름 인자에 그대로 전달해 호출한다."
        ),
        (
            "personal_create_schedule로 만든 일정은 메모리에만 잠깐 남아 있다가 대화가 끝나면 사라지므로, "
            "대화가 끝난 뒤에도 남겨야 하는 정보는 반드시 save_structured_request tool을 "
            "호출해 저장한다. save_structured_request 결과에 담긴 request_id와 저장된 "
            "테이블(saved_rows)을 사용자에게 자연어로 확인해 준다. 결과에 shared_sync가 있고 "
            "그 ok가 false이면 앱 저장은 성공했지만 외부 공유 일정 동기화는 실패한 것이므로, "
            "이 사실도 함께 알려준다."
        ),
    ]


def week03_system_prompt() -> str:
    """3주차 agent가 따르는 system prompt입니다."""

    return join_system_prompt(week03_prompt_parts())


def build_week03_agent() -> object:
    """구조화 bridge와 SQLite 저장 tool을 가진 Week 3 LangChain agent를 만듭니다."""

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
