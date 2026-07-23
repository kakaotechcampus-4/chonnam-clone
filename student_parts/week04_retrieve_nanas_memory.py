from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from fixed.config import CONFIG
from fixed.conversation_rag_store import ConversationRAGStore
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from fixed.app_store import AppSQLiteStore
from fixed.reference_store import PersonalReferenceStore
from fixed.session_scope import DEFAULT_SESSION_SCOPE, current_session_scope
from student_parts.week01_wake_up_nana import join_system_prompt
from student_parts.week03_build_nanas_logbook import week03_prompt_parts, week03_tools


REFERENCE_STORE = PersonalReferenceStore(CONFIG.chroma_dir)
SQLITE_STORE = AppSQLiteStore(CONFIG.app_db_path)
CONVERSATION_RAG_STORE = ConversationRAGStore(CONFIG.chroma_dir)
_WEEK04_AGENT: Any | None = None


def _decode_attendees(raw_attendees: str | None) -> list[str]:
    try:
        decoded = json.loads(raw_attendees or "[]")
    except Exception:
        return []
    return decoded if isinstance(decoded, list) else []


def json_payload(payload: dict[str, Any]) -> str:
    """도구 반환용 dict를 한글이 깨지지 않는 JSON 문자열로 변환합니다."""

    return json.dumps(payload, ensure_ascii=False)


def safe_limit(limit: int, default: int = 5, maximum: int = 50) -> int:
    """사용자/LLM이 넘긴 limit 값을 안전한 양의 정수 범위로 보정합니다."""

    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


class AddPersonalReferenceInput(BaseModel):
    """개인 참고자료 추가 입력입니다."""

    title: str = Field(description="참고자료 제목. 검색 시 근거 표시에 사용됩니다.")
    content: str = Field(description="참고자료 본문. 벡터 embedding 대상이 됩니다.")
    tags: list[str] | None = Field(default=None, description="참고자료 분류 태그 목록. 생략하면 빈 리스트로 저장됩니다.")


class SearchPersonalReferencesInput(BaseModel):
    """개인 참고자료 검색 입력입니다."""

    query: str = Field(description="검색할 자연어 질의. OpenAI embedding으로 유사도 검색합니다.")
    top_k: int = Field(default=2, ge=1, le=20, description="반환할 최대 결과 수(1~20).")


class SearchSavedRequestsInput(BaseModel):
    """SQLite 저장 요청 검색 입력입니다."""

    query: str = Field(description="검색할 핵심어. 일정/할 일/알림 제목·원문·근거를 LIKE 검색합니다.")
    top_k: int = Field(default=3, ge=1, le=50, description="반환할 최대 결과 수(1~50).")


class SearchConversationMessagesInput(BaseModel):
    """앱 대화 RAG 검색 입력입니다."""

    query: str = Field(description="검색할 짧은 핵심 명사나 구. ChromaDB embedding 검색에 사용됩니다.")
    top_k: int = Field(default=5, ge=1, le=50, description="반환할 최대 결과 수(1~50).")
    conversation_id: str | None = Field(default=None, description="현재 대화 ID. 지정하면 이 대화는 검색에서 제외됩니다.")


class SearchNanaMemoryInput(BaseModel):
    """Week 4 호환 통합 검색 입력입니다."""

    query: str = Field(description="검색할 자연어 질의. 개인 참고자료와 SQLite 일정을 함께 검색합니다.")
    date_from: str | None = None
    date_to: str | None = None
    attendee: str | None = None
    limit: int = Field(default=5, ge=1, le=20)


def add_personal_reference_dict(
    reference_store: PersonalReferenceStore,
    *,
    title: str,
    content: str,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """개인 참고자료를 vector store에 추가하고 backend 정보를 반환합니다."""

    result =  reference_store.add_personal_reference(
        title=title,
        content=content,
        tags=tags or [],
    )
    
    return {
        "reference_backend": result["backend"],
        "reference": {
            "reference_id": result["reference_id"],
            "title": result["title"],
            "content": result["content"],
            "tags": result["tags"],
        },
    }


def search_personal_reference_hits(
    reference_store: PersonalReferenceStore,
    *,
    query: str,
    top_k: int = 2,
) -> list[dict[str, Any]]:
    """ChromaDB 검색 결과를 tool이 바로 반환하기 쉬운 hit 구조로 정리합니다."""

    results = reference_store.search_personal_references(
        query=query,
        limit=top_k,
    )

    return [
        {
            "id": hit["id"],
            "content": hit["content"],
            "distance": hit["distance"],
            "metadata": {
                "title": hit["title"],
                "tags": hit["tags"],
            }
        }
        for hit in results
    ]
   

def search_saved_request_rows(
    sqlite_store: AppSQLiteStore,
    *,
    query: str,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """SQLite 저장 요청을 검색하고 실제 검색 결과만 반환합니다."""

    return sqlite_store.search_saved_requests(
        query=query,
        limit=top_k,
    )


def search_conversation_messages_dict(
    sqlite_store: AppSQLiteStore,
    conversation_rag_store: ConversationRAGStore,
    *,
    query: str,
    top_k: int = 5,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """SQLite 대화 목록을 lazy sync한 뒤 ChromaDB conversation RAG 결과를 반환합니다."""

    sync = conversation_rag_store.sync_from_sqlite(sqlite_store)

    hits = conversation_rag_store.search(
        query=query,
        top_k=top_k,
        exclude_conversation_id=conversation_id,
    )

    context = conversation_rag_store.context_from_hits(hits)
    
    return {
        "hits": hits,
        "rows": hits,
        "context": context,
        "rag_backend": conversation_rag_store.backend_info(),
        "sync": sync,
    }


def search_conversation_message_rows(
    sqlite_store: AppSQLiteStore,
    *,
    query: str,
    top_k: int = 5,
    conversation_id: str | None = None,
) -> list[dict[str, Any]]:
    """앱 SQLite에 저장된 일반 채팅 대화 청크를 RAG 검색합니다."""

    return search_conversation_messages_dict(
        sqlite_store,
        CONVERSATION_RAG_STORE,
        query=query,
        top_k=top_k,
        conversation_id=conversation_id,
    )["hits"]


@tool(args_schema=AddPersonalReferenceInput)
def add_personal_reference(title: str, content: str, tags: list[str] | None = None) -> str:
    """개인 참고자료를 ChromaDB에 추가합니다.

    사용자의 선호도, 습관, 배경 지식 등 나중에 검색해 답변 근거로 쓸 정보를 저장할 때 사용합니다.
    저장된 자료는 search_personal_references로 검색할 수 있습니다.
    reference_backend(저장 위치)와 reference(저장된 row)를 담은 JSON 문자열을 반환합니다.
    """

    return json_payload(
        add_personal_reference_dict(
            REFERENCE_STORE,
            title=title,
            content=content,
            tags=tags,
            )
    )


@tool(args_schema=SearchPersonalReferencesInput)
def search_personal_references(query: str, top_k: int = 2) -> str:
    """개인 참고자료를 ChromaDB와 OpenAI embedding 기반으로 검색합니다.

    "나는 오전 회의를 선호해" 같이 add_personal_reference로 저장한 선호/참고 정보를 찾을 때 사용합니다.
    저장된 일정/할 일/알림을 찾을 때는 search_saved_requests를 사용하세요.
    top-level hits 키를 가진 JSON 문자열을 반환합니다. 각 hit에는 id/content/distance/metadata가 포함됩니다.
    """

    return json_payload({
        "hits": search_personal_reference_hits(
            REFERENCE_STORE,
            query=query,
            top_k=safe_limit(top_k),
        )
    })


@tool(args_schema=SearchSavedRequestsInput)
def search_saved_requests(query: str, top_k: int = 3) -> str:
    """SQLite에 저장된 구조화 일정/할 일/알림 row를 검색합니다.

    "다음 주 회의 일정 알려줘"처럼 저장된 structured request 기록을 찾을 때 사용합니다.
    개인 선호/참고자료를 찾을 때는 search_personal_references를 사용하세요.
    query에는 LLM이 고른 일정/할 일/알림 핵심어를 넣습니다.
    top-level rows 키를 가진 JSON 문자열을 반환합니다.
    """

    return json_payload({
        "rows": search_saved_request_rows(
            SQLITE_STORE,
            query=query,
            top_k=safe_limit(top_k),
        )
    })


@tool(args_schema=SearchConversationMessagesInput)
def search_conversation_messages(
    query: str,
    top_k: int = 5,
    conversation_id: str | None = None,
) -> str:
    """앱 SQLite 대화 목록을 대화 단위 ChromaDB RAG로 검색합니다.

    이전 채팅 발화 내용을 찾을 때 사용합니다. 일정/할 일 기록은 search_saved_requests를 사용하세요.
    검색 시점에 SQLite → ChromaDB lazy sync를 수행하며, conversation_id를 넘기면 현재 대화는 제외됩니다.
    query에는 LLM이 고른 짧은 핵심 명사나 구를 넣습니다.
    hits/rows/context/rag_backend/sync를 담은 JSON 문자열을 반환합니다.
    """

    return json_payload(
        search_conversation_messages_dict(
            SQLITE_STORE,
            CONVERSATION_RAG_STORE,
            query=query,
            top_k=safe_limit(top_k),
            conversation_id=conversation_id,
        )
    )


@tool(args_schema=SearchNanaMemoryInput)
def search_nana_memory(
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    attendee: str | None = None,
    limit: int = 5,
) -> str:
    """개인 참고자료와 SQLite 저장 일정을 한 번에 검색하고 통합 context를 반환합니다.

    이전 버전 호환용 통합 검색 tool입니다. 출처를 구분해 검색하려면
    search_personal_references와 search_saved_requests를 각각 사용하세요.
    hits/rows/context/reference_backend를 담은 JSON 문자열을 반환합니다.
    """

    k = safe_limit(limit)
    hits = search_personal_reference_hits(REFERENCE_STORE, query=query, top_k=k)
    rows = search_saved_request_rows(SQLITE_STORE, query=query, top_k=k)
    context_lines = ["[개인 참고자료]"]
    for hit in hits:
        context_lines.append(f"- {hit['metadata']['title']}: {hit['content']}")
    context_lines.append("[저장된 일정/할 일/알림]")
    for row in rows:
        context_lines.append(f"- {row.get('title', '')}: {row.get('raw_json', '')}")
    return json_payload({
        "hits": hits,
        "rows": rows,
        "context": "\n".join(context_lines),
        "reference_backend": REFERENCE_STORE.backend_info(),
    })


def week04_tools() -> list[Any]:
    """3주차까지의 도구에 4주차 RAG 도구를 누적한 목록입니다."""

    return [
        *week03_tools(),
        add_personal_reference,
        search_personal_references,
        search_saved_requests,
        search_conversation_messages,
    ]


def week04_system_prompt() -> str: 
    """4주차 단일 agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt(week04_prompt_parts())


def week04_prompt_parts() -> list[str]:
    """1~4주차 system prompt 조각을 누적합니다."""

    return [
        *week03_prompt_parts(),
        """
## 개인 참고자료 저장·검색 (Week 4 RAG)

[tool 선택 기준]
- 사용자 선호도/습관 저장 → add_personal_reference
  저장 전 search_personal_references로 중복 여부를 먼저 확인합니다.
  중복 시: 사용자에게 이미 저장된 정보를 알리고 저장하지 않습니다.
  중복이 아닐 시: 저장합니다.
  예: "기억해 줘", "알아 둬", "나는 ~을 좋아해", "항상 ~해"
  ※ "저장해 줘"는 일정 저장(save_structured_request)과 혼동되므로 트리거로 쓰지 않습니다.
- 사용자 선호도/습관/참고 정보 검색 → search_personal_references
  예: "내가 좋아하는 회의 시간대", "점심 약속 잡을 때 주의사항"
- 저장된 일정/할 일/알림 조회 → search_saved_requests
  예: "다음 주 회의 일정", "이번 주 할 일 목록"
- 이전 채팅 대화 내용 참조 → search_conversation_messages
  예: "저번에 내가 말한 것", "지난 대화에서 언급한 내용"
- 선호도와 일정이 모두 필요한 경우 두 tool을 순서대로 호출하세요.

[검색 결과 활용 규칙]
- 검색 결과를 답변 근거로 사용하고, 결과 없이 사실을 단정하지 않습니다.
- assistant 발화만으로 사실을 확정하지 않습니다. user 발화와 함께 판단하세요.
- 검색 결과가 없으면 "저장된 기록을 찾지 못했습니다"라고 솔직하게 알립니다.
- hits의 distance가 클수록 유사도가 낮으므로 참고 수준을 조절하세요.
""",
    ]


def build_week04_agent() -> object:
    """Week 1-4 누적 tool 목록을 노출하는 단일 LangChain agent를 만듭니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK04_AGENT
    if _WEEK04_AGENT is None:
        _WEEK04_AGENT = create_agent(
            model=chat_model(),
            tools=week04_tools(),
            system_prompt=week04_system_prompt(),
        )
    return _WEEK04_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week04_agent()
