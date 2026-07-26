"""Week 4 확장 검증 대본 (LLM 없이 결정적).

실행:
    KANANA_ACTIVE_WEEK=4 PYTHONIOENCODING=utf-8 uv run python test_week04_extended.py

trace_week04.py / trace_week04_probe.py가 LLM 라우팅(변동적)을 보는 반면,
이 대본은 Week4 helper/tool을 fake store로 직접 호출해 계약과 가드를
결정적으로 점검합니다. (매번 같은 결과, 프록시/네트워크 불필요, 몇 초)

멘토 리뷰 대응 매핑
  - point 1 (reference_backend shape): D에서 add payload의 reference_backend가
    store.backend_info()와 같은 dict임을 확인.
  - point 2 (빈 query 가드): A/B에서 빈/공백 query가 store 호출 없이 []를 반환함을 확인.

점검 갈래
  A. search_personal_reference_hits — 빈 query 가드, tags 콤마→list 정규화
  B. search_saved_request_rows — 빈 query 가드, 결과 passthrough
  C. safe_limit — 0/음수/초과/비정수 보정
  D. add_personal_reference_dict — payload shape, tags None→[], reference_backend
  E. tool 계약 — search_personal_references={"hits":..}, search_saved_requests={"rows":..}
  F. search_conversation_messages_dict — 현재 대화 제외 로직, payload 키(hits==rows)

fake store를 쓰므로 실제 ChromaDB/SQLite(data/)와 네트워크를 건드리지 않습니다.
"""

from __future__ import annotations

import os

# import 시 PersonalReferenceStore.seed()가 embedding 네트워크를 호출하지 않도록
# has_openai_key를 꺼둔다. load_dotenv(override=False)라 미리 넣은 값이 이긴다.
os.environ["PROXY_TOKEN"] = "여기에 api key 입력"  # config.PROXY_TOKEN_PLACEHOLDER
os.environ.setdefault("KANANA_ACTIVE_WEEK", "4")

import json
from typing import Any

import student_parts.week04_retrieve_nanas_memory as w4
from fixed.session_scope import DEFAULT_SESSION_SCOPE, conversation_session_scope

_passed = 0
_failed: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed
    if cond:
        _passed += 1
        print(f"[OK]   {name}")
    else:
        _failed.append(name)
        print(f"[FAIL] {name}  {detail}")


def call(tool: Any, **kwargs: Any) -> dict[str, Any]:
    """@tool을 호출하고 JSON 문자열 결과를 dict로 돌려줍니다."""

    return json.loads(tool.invoke(kwargs))


class FakeReferenceStore:
    """PersonalReferenceStore를 흉내 내는 fake (네트워크 없음)."""

    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []

    def backend_info(self) -> dict[str, Any]:
        return {
            "vector_store": "chromadb",
            "embedding_provider": "openai",
            "embedding_model": "fake-model",
            "collection_name": "fake_collection",
            "chroma_dir": "/fake/chroma",
        }

    def add_personal_reference(self, title: str, content: str, tags: list[str] | None = None) -> dict[str, Any]:
        self.added.append({"title": title, "content": content, "tags": tags or []})
        return {
            "reference_id": "ref_fake1",
            "title": title,
            "content": content,
            "tags": tags or [],
            "backend": self.backend_info(),
        }

    def search_personal_references(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        # 실제 store와 동일하게 tags를 콤마 문자열로 돌려준다.
        rows = [
            {"id": "ref1", "title": "집중 선호", "content": "오전 집중", "tags": "preference,meeting", "distance": 0.10},
            {"id": "ref2", "title": "빈 태그", "content": "태그 없음", "tags": "", "distance": 0.20},
            {"id": "ref3", "title": "list 태그", "content": "이미 list", "tags": ["already", "list"], "distance": 0.30},
        ]
        return rows[:limit]


class FakeSQLiteStore:
    """AppSQLiteStore.search_saved_requests만 흉내 내는 fake."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search_saved_requests(self, query: str, kind: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        self.calls.append((query, limit))
        return [{"request_id": "req1", "kind": "group_schedule", "title": "디자인 리뷰", "date": "2026-07-27"}][:limit]


class FakeConversationRAGStore:
    """ConversationRAGStore를 흉내 내며 search 인자를 기록하는 fake."""

    def __init__(self) -> None:
        self.search_kwargs: dict[str, Any] | None = None

    def sync_from_sqlite(self, sqlite_store: Any) -> dict[str, int]:
        return {"upserted": 0, "skipped": 0, "deleted": 0, "total": 0}

    def search(self, *, query: str, top_k: int = 5, conversation_id: str | None = None, exclude_conversation_id: str | None = None) -> list[dict[str, Any]]:
        self.search_kwargs = {
            "query": query,
            "top_k": top_k,
            "conversation_id": conversation_id,
            "exclude_conversation_id": exclude_conversation_id,
        }
        return [{"chunk_id": "conversation:c1", "conversation_id": "c1", "content": "지난 대화"}]

    def context_from_hits(self, hits: list[dict[str, Any]]) -> str:
        return f"ctx({len(hits)})"

    def backend_info(self) -> dict[str, Any]:
        return {"vector_store": "chromadb", "collection_name": "fake_conv"}


def run() -> int:
    ref = FakeReferenceStore()
    sql = FakeSQLiteStore()

    # A. search_personal_reference_hits: 빈 query 가드 + tags 정규화
    check("A. 빈 query → 검색 없이 []", w4.search_personal_reference_hits(ref, query="", top_k=3) == [])
    check("A. 공백 query → []", w4.search_personal_reference_hits(ref, query="   ", top_k=3) == [])
    hits = w4.search_personal_reference_hits(ref, query="집중", top_k=3)
    check("A. hit 구조 id/content/distance/metadata", all({"id", "content", "distance", "metadata"} <= set(h) for h in hits))
    check("A. tags 콤마문자열→list", hits[0]["metadata"]["tags"] == ["preference", "meeting"], str(hits[0]["metadata"]["tags"]))
    check("A. 빈 tags 문자열→[]", hits[1]["metadata"]["tags"] == [], str(hits[1]["metadata"]["tags"]))
    check("A. 이미 list인 tags 보존", hits[2]["metadata"]["tags"] == ["already", "list"], str(hits[2]["metadata"]["tags"]))

    # B. search_saved_request_rows: 빈 query 가드 + passthrough
    check("B. 빈 query → store 호출 없이 []", w4.search_saved_request_rows(sql, query="", top_k=3) == [])
    check("B. 빈 query일 때 store 미호출", sql.calls == [])
    rows = w4.search_saved_request_rows(sql, query="디자인", top_k=3)
    check("B. 비어있지 않은 query → rows passthrough", rows and rows[0]["title"] == "디자인 리뷰", str(rows))
    check("B. store에 (query, limit) 전달", sql.calls[-1] == ("디자인", 3), str(sql.calls))

    # C. safe_limit 보정
    check("C. 0 → 1", w4.safe_limit(0) == 1)
    check("C. 음수 → 1", w4.safe_limit(-5) == 1)
    check("C. 초과 → maximum", w4.safe_limit(999, maximum=50) == 50)
    check("C. 비정수 → default", w4.safe_limit("abc", default=7) == 7)
    check("C. 정상값 유지", w4.safe_limit(3) == 3)

    # D. add_personal_reference_dict: shape + tags None + reference_backend
    payload = w4.add_personal_reference_dict(ref, title="T", content="C", tags=None)
    check("D. reference_backend == store.backend_info()", payload["reference_backend"] == ref.backend_info(), str(payload["reference_backend"]))
    check("D. reference 하위 키", {"reference_id", "title", "content", "tags"} <= set(payload["reference"]))
    check("D. tags None → []", payload["reference"]["tags"] == [], str(payload["reference"]["tags"]))
    check("D. title/content 반영", payload["reference"]["title"] == "T" and payload["reference"]["content"] == "C")

    # E. tool 계약: 모듈 전역을 fake로 교체하고 top-level 키 확인
    w4.REFERENCE_STORE = ref
    w4.SQLITE_STORE = sql
    r_hits = call(w4.search_personal_references, query="집중", top_k=2)
    check("E. search_personal_references top-level == {hits}", list(r_hits.keys()) == ["hits"], str(list(r_hits.keys())))
    r_rows = call(w4.search_saved_requests, query="디자인", top_k=3)
    check("E. search_saved_requests top-level == {rows}", list(r_rows.keys()) == ["rows"], str(list(r_rows.keys())))
    r_empty = call(w4.search_saved_requests, query="   ", top_k=3)
    check("E. search_saved_requests 빈 query → rows=[]", r_empty["rows"] == [], str(r_empty))
    r_add = call(w4.add_personal_reference, title="새메모", content="본문", tags=["a", "b"])
    check("E. add_personal_reference reference_backend/reference 포함", {"reference_backend", "reference"} <= set(r_add))
    check("E. add tags 반영", r_add["reference"]["tags"] == ["a", "b"], str(r_add["reference"]["tags"]))

    # F. search_conversation_messages_dict: 현재 대화 제외 로직 + payload 키
    conv = FakeConversationRAGStore()
    with conversation_session_scope("current_conv"):
        out = w4.search_conversation_messages_dict(sql, conv, query="회식", top_k=5, conversation_id=None)
    check("F. 현재 세션이면 exclude_conversation_id=현재 conv", conv.search_kwargs["exclude_conversation_id"] == "current_conv", str(conv.search_kwargs))
    check("F. payload 키 hits/rows/context/rag_backend/sync", {"hits", "rows", "context", "rag_backend", "sync"} <= set(out))
    check("F. hits == rows (같은 결과 반영)", out["hits"] == out["rows"])

    conv2 = FakeConversationRAGStore()
    with conversation_session_scope("current_conv"):
        w4.search_conversation_messages_dict(sql, conv2, query="회식", top_k=5, conversation_id="c1")
    check("F. conversation_id 명시 시 exclude 안 함", conv2.search_kwargs["exclude_conversation_id"] is None and conv2.search_kwargs["conversation_id"] == "c1", str(conv2.search_kwargs))

    conv3 = FakeConversationRAGStore()
    # 세션 범위 밖(DEFAULT) → 제외할 현재 대화가 없음
    check("F. 사전조건: 기본 세션 범위", w4  is not None)
    w4.search_conversation_messages_dict(sql, conv3, query="회식", top_k=5, conversation_id=None)
    check("F. DEFAULT 세션이면 exclude 없음", conv3.search_kwargs["exclude_conversation_id"] is None, str(conv3.search_kwargs))

    print(f"\n결과: {_passed}개 통과" + (f", 실패 {len(_failed)}개: {_failed}" if _failed else ", 실패 0개"))
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
