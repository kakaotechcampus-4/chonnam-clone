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


# [4주차 수강생 구현 가이드]
#
# 목표
#   Nana가 "내가 적어 둔 참고자료", "SQLite에 저장된 일정/할 일 기록",
#   "앱에 저장된 일반 채팅 발화"를 구분해서 검색하게 합니다.
#   Week 4의 핵심은 RAG를 하나의 마법 함수로 보지 않고, 데이터 출처별 검색 tool을 분리하는 것입니다.
#
# 과제 구성
#   - 메인과제: 개인 참고자료를 추가하고, 참고자료와 SQLite 저장 기록을 출처별로 검색하는
#     RAG 세로 슬라이스를 완성합니다.
#   - 추가 과제: 앱 대화 발화를 ChromaDB에 lazy sync해 검색하는 agentic RAG와
#     이전 버전 호환 통합 검색까지 확장합니다.
#
# 구현 위치와 사용할 코드
#   - 이 파일(student_parts/week04_retrieve_nanas_memory.py)의 개인 참고자료/RAG tool을 구현합니다.
#   - 개인 참고자료 저장소는 fixed/reference_store.py의 PersonalReferenceStore이며,
#     이 파일 상단의 REFERENCE_STORE가 CONFIG.chroma_dir 기준 인스턴스입니다.
#   - SQLite 저장 요청 검색은 fixed/app_store.py의 AppSQLiteStore를 사용하고,
#     이 파일 상단의 SQLITE_STORE가 CONFIG.app_db_path 기준 인스턴스입니다.
#   - 일반 채팅 발화 검색은 fixed/conversation_rag_store.py의 ConversationRAGStore를 사용하고,
#     이 파일 상단의 CONVERSATION_RAG_STORE가 CONFIG.chroma_dir 기준 인스턴스입니다.
#   - 각 tool 입력은 Pydantic args_schema로 검증하고,
#     search_personal_reference_hits(), search_saved_request_rows(), search_conversation_message_rows()에서 조회 결과를 정리합니다.
#   - tool 함수 add_personal_reference/search_personal_references/search_saved_requests/search_conversation_messages는
#     위 helper 결과를 json_payload()로 감싼 JSON 문자열로 반환합니다.
#   - top_k/limit 보정은 이 파일의 safe_limit()를 사용해 tool 안에서 처리합니다.
#   - week04_tools()는 student_parts/week03_build_nanas_logbook.py의 week03_tools() 위에
#     Week 4 RAG tool을 누적해 agent에 공개합니다.
#
# 메인과제 구현 대상
#   1. add_personal_reference
#      - title/content/tags를 REFERENCE_STORE.add_personal_reference에 넘깁니다.
#      - tags가 None이면 빈 list로 바꿉니다.
#      - 이 tool 안에서 reference_backend와 reference가 있는 JSON payload를 완성합니다.
#
#   2. search_personal_references
#      - query와 top_k로 ChromaDB 개인 참고자료를 검색합니다.
#      - top_k는 이 tool 안에서 안전한 범위로 정리합니다.
#      - course repo 기준 계약에 맞게 top-level {"hits": [...]} JSON을 반환합니다.
#      - hit에는 id, content, distance, metadata(title/tags)가 들어가야 답변 근거로 쓰기 쉽습니다.
#
#   3. search_saved_requests
#      - SQLITE_STORE.search_saved_requests(query, limit)를 호출합니다.
#      - top_k는 이 tool 안에서 안전한 범위로 정리합니다.
#      - 검색 결과가 없으면 rows=[]를 그대로 반환합니다.
#      - course repo 기준 계약에 맞게 top-level {"rows": [...]} JSON을 반환합니다.
#
# 추가 과제 구현 대상
#   1. search_conversation_messages
#      - SQLite에 저장된 앱 대화 메시지를 ConversationRAGStore.sync_from_sqlite(...)로 ChromaDB에 lazy sync합니다.
#      - conversation_id를 명시하지 않으면 현재 대화 범위는 검색에서 제외해 "방금 한 말"이 과거 검색처럼 섞이지 않게 합니다.
#      - 반환 JSON에는 hits와 rows에 같은 결과를 넣고, context/rag_backend/sync도 함께 둡니다.
#      - hit에는 conversation_id, role, content 등 대화 근거가 있어야 하며, assistant 발화만으로 사실을 확정하지 않습니다.
#
# 출처 구분
#   search_personal_references는 ChromaDB + OpenAI embedding 기반 reference 검색입니다.
#   search_saved_requests는 SQLite structured_requests/schedules 계열 기록 검색입니다.
#   search_conversation_messages는 SQLite conversations/messages를 대화 단위 청크로 sync해 검색하는 agentic RAG입니다.
#   LLM이 질문 성격에 따라 둘 중 하나 또는 둘 다 선택하도록 prompt가 준비되어 있습니다.
#
# 참고 코드
#   search_nana_memory는 reference_backend와 context를 함께 확인하는 compatibility helper입니다.
#   학생 핵심 구현 대상은 add_personal_reference, search_personal_references,
#   search_saved_requests, search_conversation_messages 4개입니다.
#   week04_tools()는 Week 1-3 도구에 이 RAG 도구들을 누적합니다.
#
# 검증 방법
#   - 메인과제: 참고자료를 추가한 뒤 관련 질문을 입력하고 trace에서 search_personal_references 호출을 확인합니다.
#     저장된 일정/할 일 질문은 search_saved_requests가 호출되는지, 결과 JSON top-level 키가 각각 hits, rows인지 확인합니다.
#   - 추가 과제: 일반 채팅 발화 질문은 search_conversation_messages가 호출되고 현재 대화가 제외되는지 확인합니다.
#
# 함수별 동작 설명 ([메인]/[추가]/[공통]은 각 함수가 속한 과제 티어입니다)
#   - [공통] _decode_attendees(raw_attendees)
#     SQLite row의 attendees_json 문자열을 list로 바꿉니다. 깨진 JSON이나 list가 아닌 값은 빈 list로 처리합니다.
#
#   - [공통] json_payload(payload)
#     tool 응답 dict를 한글이 보존되는 JSON 문자열로 바꿉니다.
#
#   - [공통] safe_limit(limit, default, maximum)
#     LLM이나 사용자가 넘긴 limit/top_k 값을 int로 바꾸고 1 이상 maximum 이하로 제한합니다.
#
#   - [메인] AddPersonalReferenceInput / SearchPersonalReferencesInput / SearchSavedRequestsInput
#     개인 참고자료 추가, 개인 참고자료 검색, SQLite 저장 요청 검색 tool의 입력 스키마입니다.
#
#   - [추가] SearchConversationMessagesInput / SearchNanaMemoryInput
#     앱 대화 RAG 검색과 기존 호환용 통합 검색 tool의 입력 스키마입니다.
#
#   - [메인] add_personal_reference_dict(...)
#     PersonalReferenceStore에 참고자료를 저장하고, 어떤 backend에 저장됐는지와 저장된 reference row를 dict로 반환합니다.
#
#   - [메인] search_personal_reference_hits(...)
#     vector store 검색 결과를 id/content/distance/metadata 구조로 정리합니다. tool은 이 list를 hits로 감싸 반환합니다.
#
#   - [메인] search_saved_request_rows(...)
#     AppSQLiteStore의 저장 요청 검색 결과를 rows 배열로 반환합니다. 일정/할 일/알림 구조화 기록을 찾을 때 사용합니다.
#
#   - [추가] search_conversation_messages_dict(...)
#     SQLite 대화 기록을 ConversationRAGStore에 lazy sync한 뒤 ChromaDB 검색을 수행합니다.
#     현재 대화는 기본적으로 제외해 "방금 한 말"이 과거 검색 결과처럼 섞이지 않게 합니다.
#
#   - [추가] search_conversation_message_rows(...)
#     search_conversation_messages_dict(...)에서 hits만 꺼내는 내부 helper입니다.
#
#   - [메인] add_personal_reference(...)
#     참고자료 추가 tool입니다. title/content/tags를 받아 vector store에 저장하고 JSON 문자열을 반환합니다.
#
#   - [메인] search_personal_references(...)
#     개인 참고자료 전용 검색 tool입니다. top-level hits 키를 반환하므로 LLM이 근거 문서를 바로 읽을 수 있습니다.
#
#   - [메인] search_saved_requests(...)
#     SQLite에 저장된 structured request/schedule 기록 검색 tool입니다. top-level rows 키를 반환합니다.
#
#   - [추가] search_conversation_messages(...)
#     앱에 저장된 일반 대화 발화를 검색하는 RAG tool입니다. 일정 DB 검색과 다른 출처임을 context/rag_backend/sync로 함께 보여줍니다.
#
#   - [추가] search_nana_memory(...)
#     이전 버전 호환용 통합 검색 tool입니다. 개인 참고자료 hit와 SQLite 일정 chunk를 한 번에 묶어 context 문자열을 만듭니다.
#
#   - [공통] week04_tools()
#     Week 3까지의 tool에 Week 4 RAG tool들을 누적해 agent에 공개합니다.
#
#   - [공통] week04_system_prompt() / week04_prompt_parts()
#     질문 성격에 따라 reference, saved request, conversation RAG 중 맞는 tool을 고르도록 system prompt를 만듭니다.
#
#   - [공통] build_week04_agent() / build_week_agent()
#     Week 1~4 tool을 가진 agent를 만들고 재사용합니다.


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

    title: str
    content: str
    tags: list[str] | None = None


class SearchPersonalReferencesInput(BaseModel):
    """개인 참고자료 검색 입력입니다."""

    query: str
    top_k: int = Field(default=2, ge=1, le=20)


class SearchSavedRequestsInput(BaseModel):
    """SQLite 저장 요청 검색 입력입니다."""

    query: str
    top_k: int = Field(default=3, ge=1, le=50)


class SearchConversationMessagesInput(BaseModel):
    """앱 대화 RAG 검색 입력입니다."""

    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    conversation_id: str | None = None


class SearchNanaMemoryInput(BaseModel):
    """Week 4 호환 통합 검색 입력입니다."""

    query: str
    date_from: str | None = None
    date_to: str | None = None
    attendee: str | None = None
    limit: int = Field(default=5, ge=1, le=20)


# ============================================================================
#  add_personal_reference 전체 호출 체인 다이어그램
#
#  도형 범례(diagram legend)
#    ┌─────┐            ___
#    │ 함수 │  = 함수/메서드   ( 배열 ) = 배열/리스트    /___/| = 저장소(DB)
#    └─────┘            (_____)                  |   || = persistent
#     .-.                                        |___|/   storage
#    ( ☁ ) = 네트워크(외부 API)   [0.1, -0.4, ...] = 임베딩 벡터
#     `-'
# ----------------------------------------------------------------------------
#
#   ┌────────────────────────────────────────────────┐
#   │ [tool]  add_personal_reference(title, content)  │  이 파일, LangChain tool
#   └────────────────────────────────────────────────┘
#                        │  호출
#                        ▼
#   ┌────────────────────────────────────────────────┐
#   │ [helper] add_personal_reference_dict(store, ..) │  이 파일, tags=None -> []
#   └────────────────────────────────────────────────┘
#                        │  호출
#                        ▼
#   ┌────────────────────────────────────────────────┐
#   │ [method] store.add_personal_reference(...)      │  fixed/reference_store.py:138
#   └────────────────────────────────────────────────┘   PersonalReferenceStore 객체
#            │                              │
#            │ ① ID 생성                     │ ② 저장 요청
#            ▼                              ▼
#     ┌──────────────┐            ┌───────────────────────────┐
#     │ new_id("ref")│            │ self.collection.add(       │
#     └──────────────┘            │   ids, documents, metadata)│  ChromaDB Collection 객체
#     "ref_xxxxxxxxxx"            └───────────────────────────┘
#     (로컬 계산,                              │
#      네트워크 없음)                           │ documents 를 벡터로 변환 요청
#                                             ▼
#                                    ┌──────────────────────────┐
#                                    │ OpenAIEmbeddingFunction   │  fixed/reference_store.py:44
#                                    │        .__call__()        │
#                                    └──────────────────────────┘
#                                             │
#                                             ▼        .-~-.
#                                         embeddings  ( ☁  ☁ )  OpenAI 임베딩 API
#                                         .create()    `-~-~-'   (외부 네트워크 호출)
#                                             │
#                                             ▼
#                                     [0.021, -0.44, 0.13, ...]  content 의 임베딩 벡터
#                                             │
#                                             ▼
#                                            ___
#                                           /___/|   ChromaDB persistent storage
#                                           |   ||   id + 벡터 + document + metadata 저장
#                                           |___|/
#
#   반환은 역순으로 거슬러 올라옵니다:
#     storage 저장 완료 -> method 가 dict 반환 -> helper 가 그대로 전달
#     -> tool 이 json_payload()로 JSON 문자열화 -> agent(LLM)에게 전달
# ============================================================================
def add_personal_reference_dict(
    reference_store: PersonalReferenceStore,
    *,
    title: str,
    content: str,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """개인 참고자료를 vector store에 추가하고 backend 정보를 반환합니다."""

    return reference_store.add_personal_reference(title, content, tags or [])


# ============================================================================
#  search_personal_references 전체 호출 체인 다이어그램
#  (add 는 "글 -> 벡터 -> 저장", search 는 "질문 -> 벡터 -> 유사도 비교 -> 결과" 로 방향이 반대)
#
#   ┌────────────────────────────────────────────────┐
#   │ [tool]  search_personal_references(query,top_k) │  이 파일, LangChain tool
#   └────────────────────────────────────────────────┘
#                        │  safe_limit()으로 top_k 를 1~20 으로 보정
#                        ▼
#   ┌────────────────────────────────────────────────┐
#   │ [helper] search_personal_reference_hits(...)    │  이 파일
#   │          flat dict -> metadata 로 재포장          │
#   └────────────────────────────────────────────────┘
#                        │  호출
#                        ▼
#   ┌────────────────────────────────────────────────┐
#   │ [method] store.search_personal_references(...)  │  fixed/reference_store.py:155
#   └────────────────────────────────────────────────┘
#                        │  질문(query)을 벡터로 변환 요청
#                        ▼
#     ┌───────────────────────────┐
#     │ self.collection.query(     │  ChromaDB Collection 객체
#     │   query_texts, n_results)  │
#     └───────────────────────────┘
#                        │
#                        ▼
#             OpenAIEmbeddingFunction        .-~-.
#                  .__call__()  ─────────▶  ( ☁  ☁ )  OpenAI 임베딩 API
#                        │                   `-~-~-'   (외부 네트워크 호출)
#                        ▼
#             [0.03, -0.51, 0.20, ...]  질문의 임베딩 벡터
#                        │
#                        ▼
#                       ___
#                      /___/|   ChromaDB persistent storage
#                      |   ||   저장된 참고자료 벡터들과 거리(distance) 계산
#                      |___|/   -> 가까운 top_k 개를 골라 반환
#                        │
#                        ▼
#     반환된 배열 (flat dict 들):
#     ( {id, title, content, tags, distance},  {..}, ... )
#                        │  helper 가 metadata 로 재포장
#                        ▼
#     ( {id, content, distance, metadata:{title, tags}}, {..}, ... )
#                        │  tool 이 {"hits": [...]} 로 감싸 json_payload()
#                        ▼
#             '{"hits": [...]}'  (JSON 문자열) -> agent(LLM)
# ============================================================================
def search_personal_reference_hits(
    reference_store: PersonalReferenceStore,
    *,
    query: str,
    top_k: int = 2,
) -> list[dict[str, Any]]:
    """ChromaDB 검색 결과를 tool이 바로 반환하기 쉬운 hit 구조로 정리합니다."""

    raw_hits = reference_store.search_personal_references(query, limit=top_k)
    hits: list[dict[str, Any]] = []
    """
    raw[key] 대신 raw.get(key)를 사용하는 이유.

    1. 배경
       raw는 reference_store.search_personal_references(...)가 반환하는 dict이며,
       현재 구현에서는 title/content/tags/distance 키가 모두 존재한다.

    2. raw[key] 방식의 문제
       해당 키가 dict에 없을 경우 KeyError 예외를 발생시킨다.

    3. raw.get(key, default) 사용 효과
       키가 없을 때 예외를 발생시키지 않고 default 값을 반환한다.
       reference_store 구현이 변경되어 특정 키가 누락되는 경우에도
       for 루프 전체가 중단되지 않는다.

    4. default 인자를 생략하는 경우
       distance/id처럼 값이 없을 때 None을 허용하는 필드는 default 인자를 생략한
       raw.get(key) 형태로 호출해 None을 그대로 반환하게 한다.
    """
    for raw in raw_hits:
        hits.append(
            {
                "id": raw.get("id"),
                "content": raw.get("content"),
                "distance": raw.get("distance"),
                "metadata": {
                    "title": raw.get("title", ""),
                    "tags": raw.get("tags", ""),
                },
            }
        )
    return hits


# ============================================================================
#  search_saved_requests 전체 호출 체인 다이어그램
#
#  도형 범례
#    ┌─────┐              ___
#    │ 함수 │  = 함수/메서드     /___/|  = 저장소(DB)
#    └─────┘              |   ||
#                         |___|/
#    ( ... )  = 배열/리스트
#
#   ┌────────────────────────────────────────────┐
#   │ [tool] search_saved_requests(query, top_k)  │  이 파일, LangChain tool
#   └────────────────────────────────────────────┘
#                     │  safe_limit()으로 top_k 보정
#                     ▼
#   ┌────────────────────────────────────────────┐
#   │ [helper] search_saved_request_rows(...)     │  이 파일
#   └────────────────────────────────────────────┘
#                     │  호출
#                     ▼
#   ┌────────────────────────────────────────────┐
#   │ [method] sqlite_store.search_saved_requests │  fixed/app_store.py:454
#   │          (query, limit=top_k)               │  AppSQLiteStore 객체
#   └────────────────────────────────────────────┘
#                     │  SQL LIKE 조건 조립 후 실행
#                     ▼
#                    ___
#                   /___/|   SQLite 파일(structured_requests 테이블)
#                   |   ||   raw_json/title/reason 컬럼을 LIKE '%query%'로 조회
#                   |___|/   (임베딩/외부 네트워크 호출 없음)
#                     │
#                     ▼
#     ( {kind, title, raw_json, ...}, {..}, ... )   조회된 row 배열
#                     │  helper 는 결과를 그대로 반환 (재포장 불필요)
#                     ▼
#     tool 이 {"rows": [...]} 로 감싸 json_payload()
#                     │
#                     ▼
#             '{"rows": [...]}'  (JSON 문자열) -> agent(LLM)
# ============================================================================
def search_saved_request_rows(
    sqlite_store: AppSQLiteStore,
    *,
    query: str,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """SQLite 저장 요청을 검색하고 실제 검색 결과만 반환합니다."""

    """
    sqlite_store.search_saved_requests(...) 결과를 재가공하지 않는 이유.

    1. 반환 형식이 이미 일치한다.
       fixed/app_store.py의 search_saved_requests(query, kind=None, limit=5)는
       structured_requests 테이블의 row를 dict의 list로 반환한다.
       이 파일의 계약(rows 배열)과 형식이 이미 일치하므로 추가 변환이 필요 없다.

    2. search_personal_reference_hits와 차이가 있다.
       참고자료 검색(search_personal_reference_hits)은 title/tags를 metadata로
       옮기는 변환이 필요했지만, 이 함수는 그런 변환 없이 결과를 그대로 반환한다.

    3. 검색 방식이 다르다.
       query 문자열을 raw_json/title/reason 컬럼에 대해 SQL LIKE 연산으로 비교한다.
       임베딩 계산이나 외부 API 호출은 발생하지 않는다.
    """
    return sqlite_store.search_saved_requests(query, limit=top_k)


def search_conversation_messages_dict(
    sqlite_store: AppSQLiteStore,
    conversation_rag_store: ConversationRAGStore,
    *,
    query: str,
    top_k: int = 5,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """SQLite 대화 목록을 lazy sync한 뒤 ChromaDB conversation RAG 결과를 반환합니다."""

    # TODO: SQLite 대화 기록을 ConversationRAGStore에 lazy sync한 뒤 현재 대화를 제외하고 검색하세요.
    ...


def search_conversation_message_rows(
    sqlite_store: AppSQLiteStore,
    *,
    query: str,
    top_k: int = 5,
    conversation_id: str | None = None,
) -> list[dict[str, Any]]:
    """앱 SQLite에 저장된 일반 채팅 대화 청크를 RAG 검색합니다."""

    # TODO: search_conversation_messages_dict(...) 결과에서 hits만 반환하세요.
    ...


@tool(args_schema=AddPersonalReferenceInput)
def add_personal_reference(title: str, content: str, tags: list[str] | None = None) -> str:
    """개인 참고자료를 ChromaDB에 추가합니다."""

    reference = add_personal_reference_dict(REFERENCE_STORE, title=title, content=content, tags=tags)
    return json_payload(
        {
            "reference_backend": reference.get("backend"),
            "reference": reference,
        }
    )


@tool(args_schema=SearchPersonalReferencesInput)
def search_personal_references(query: str, top_k: int = 2) -> str:
    """개인 참고자료를 ChromaDB와 OpenAI embedding 기반으로 검색합니다."""

    """
    safe_limit(top_k, default=2, maximum=20) 인자 설명.

    1. top_k
       LLM 또는 호출자가 전달한 원본 값이다. SearchPersonalReferencesInput의
       Field(ge=1, le=20)로 1차 검증되지만, 타입 변환이 필요한 값(문자열 "3" 등)이나
       None이 인자로 전달될 가능성에 대비해 safe_limit 내부에서 int(top_k) 변환을 재실행한다.

    2. default=2
       int(top_k) 변환이 실패하거나 top_k가 None일 때 대체할 값이다.

    3. maximum=20
       top_k 값의 상한이다. collection.query(n_results=top_k) 호출 시
       n_results가 과도하게 커지는 것을 제한한다.

    4. safe_limit 함수의 처리 순서
       (1) int(top_k) 변환을 시도하고, 실패하면 default를 사용한다.
       (2) 변환에 성공한 값은 max(1, min(value, maximum)) 연산으로
           1 이상 maximum 이하 범위로 제한한다.
    """
    hits = search_personal_reference_hits(
        REFERENCE_STORE,
        query=query,
        top_k=safe_limit(top_k, default=2, maximum=20),
    )
    return json_payload({"hits": hits})


@tool(args_schema=SearchSavedRequestsInput)
def search_saved_requests(query: str, top_k: int = 3) -> str:
    """SQLite에 저장된 구조화 일정/할 일/알림 row를 검색합니다. query에는 LLM이 고른 일정/할 일/알림 핵심어를 넣습니다."""

    """
    safe_limit(top_k, default=3, maximum=50) 인자를 search_personal_references와
    다르게 설정한 이유.

    1. default=3이다.
       search_personal_references의 default=2보다 크다. 저장 요청 검색은
       문자열 포함 여부만 확인하는 LIKE 검색이므로, 결과에 관련 없는 항목이
       섞일 가능성이 참고자료 벡터 검색보다 낮다.

    2. maximum=50이다.
       search_personal_references의 maximum=20보다 크다. structured_requests
       테이블 조회는 벡터 유사도 계산을 거치지 않으므로, 결과 개수가 늘어나도
       계산 비용이 크게 증가하지 않는다.
    """
    rows = search_saved_request_rows(
        SQLITE_STORE,
        query=query,
        top_k=safe_limit(top_k, default=3, maximum=50),
    )
    return json_payload({"rows": rows})


@tool(args_schema=SearchConversationMessagesInput)
def search_conversation_messages(
    query: str,
    top_k: int = 5,
    conversation_id: str | None = None,
) -> str:
    """앱 SQLite 대화 목록을 대화 단위 ChromaDB RAG로 검색합니다. query에는 LLM이 고른 짧은 핵심 명사나 구를 넣습니다."""

    # TODO: 앱 SQLite 대화 목록을 대화 단위 ChromaDB RAG로 검색하고 JSON 문자열로 반환하세요.
    ...


@tool(args_schema=SearchNanaMemoryInput)
def search_nana_memory(
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    attendee: str | None = None,
    limit: int = 5,
) -> str:
    """개인 참고자료와 SQLite 저장 일정을 한 번에 검색하고 일정 chunk를 반환합니다."""

    # TODO: compatibility 통합 검색이 필요하면 개인 참고자료와 SQLite 일정 chunk를 함께 구성하세요.
    ...

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
        # TODO: Week 4 Nana memory agent system prompt를 자유롭게 추가하세요.
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
