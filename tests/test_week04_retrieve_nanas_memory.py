from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fixed.config import CONFIG
from fixed.session_scope import conversation_session_scope


_TEST_DATA = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
_ORIGINAL_CONFIG = {
    "proxy_token": CONFIG.proxy_token,
    "app_db_path": CONFIG.app_db_path,
    "chroma_dir": CONFIG.chroma_dir,
}
object.__setattr__(CONFIG, "proxy_token", None)
object.__setattr__(CONFIG, "app_db_path", Path(_TEST_DATA.name) / "app.sqlite3")
object.__setattr__(CONFIG, "chroma_dir", Path(_TEST_DATA.name) / "chroma")
try:
    import student_parts.week04_retrieve_nanas_memory as week04
finally:
    for _name, _value in _ORIGINAL_CONFIG.items():
        object.__setattr__(CONFIG, _name, _value)


class ReferenceStoreFake:
    def __init__(self) -> None:
        self.add_calls: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []

    def backend_info(self) -> dict[str, Any]:
        return {"vector_store": "fake", "collection_name": "references"}

    def add_personal_reference(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        call = {"title": title, "content": content, "tags": tags}
        self.add_calls.append(call)
        return {"reference_id": "ref_1", **call}

    def search_personal_references(self, query: str, limit: int) -> list[dict[str, Any]]:
        self.search_calls.append({"query": query, "limit": limit})
        return [
            {
                "id": "ref_1",
                "title": "집중 시간",
                "content": "오전에는 회의를 잡지 않는다.",
                "tags": "preference,meeting",
                "distance": 0.125,
            }
        ]


class SavedRequestStoreFake:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.search_calls: list[dict[str, Any]] = []

    def search_saved_requests(
        self,
        query: str,
        kind: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        self.search_calls.append({"query": query, "kind": kind, "limit": limit})
        return self.rows[:limit]


class ConversationRAGStoreFake:
    def __init__(self, hits: list[dict[str, Any]] | None = None) -> None:
        self.hits = hits or []
        self.events: list[str] = []
        self.search_calls: list[dict[str, Any]] = []

    def sync_from_sqlite(self, sqlite_store: Any) -> dict[str, int]:
        self.events.append("sync")
        return {"upserted": 1, "skipped": 0, "deleted": 0, "total": 1}

    def search(self, **arguments: Any) -> list[dict[str, Any]]:
        self.events.append("search")
        self.search_calls.append(arguments)
        return self.hits

    def context_from_hits(self, hits: list[dict[str, Any]]) -> str:
        self.events.append("context")
        return "[SQLite 대화 RAG 검색 결과]\n" + str(len(hits))

    def backend_info(self) -> dict[str, Any]:
        return {"vector_store": "fake-rag", "collection_name": "conversations"}


class ScheduleStoreFake:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.list_calls: list[dict[str, Any]] = []

    def list_schedules(self, **arguments: Any) -> list[dict[str, Any]]:
        self.list_calls.append(arguments)
        return self.rows


class PersonalReferenceTests(unittest.TestCase):
    def test_add_normalizes_none_tags_and_returns_backend(self) -> None:
        store = ReferenceStoreFake()

        result = week04.add_personal_reference_dict(
            store,
            title="집중 시간",
            content="오전에는 회의를 잡지 않는다.",
            tags=None,
        )

        self.assertEqual(store.add_calls[0]["tags"], [])
        self.assertEqual(result["reference_backend"]["vector_store"], "fake")
        self.assertEqual(result["reference"]["reference_id"], "ref_1")

    def test_search_restructures_hits_and_preserves_distance(self) -> None:
        store = ReferenceStoreFake()

        hits = week04.search_personal_reference_hits(
            store,
            query="  오전 회의  ",
            top_k=100,
        )

        self.assertEqual(store.search_calls, [{"query": "오전 회의", "limit": 20}])
        self.assertEqual(
            hits,
            [
                {
                    "id": "ref_1",
                    "content": "오전에는 회의를 잡지 않는다.",
                    "distance": 0.125,
                    "metadata": {
                        "title": "집중 시간",
                        "tags": "preference,meeting",
                    },
                }
            ],
        )

    def test_blank_search_does_not_call_vector_backend(self) -> None:
        store = ReferenceStoreFake()

        hits = week04.search_personal_reference_hits(store, query="   ", top_k=2)

        self.assertEqual(hits, [])
        self.assertEqual(store.search_calls, [])

    def test_public_tools_return_source_aware_unescaped_json(self) -> None:
        store = ReferenceStoreFake()
        with patch.object(week04, "REFERENCE_STORE", store):
            added_raw = week04.add_personal_reference.invoke(
                {
                    "title": "집중 시간",
                    "content": "오전에는 회의를 잡지 않는다.",
                    "tags": None,
                }
            )
            searched_raw = week04.search_personal_references.invoke(
                {"query": "  오전 회의  ", "top_k": 2}
            )

        added = json.loads(added_raw)
        searched = json.loads(searched_raw)
        self.assertIn("집중 시간", added_raw)
        self.assertNotIn("\\u", added_raw)
        self.assertEqual(added["tool_name"], "add_personal_reference")
        self.assertEqual(added["reference"]["tags"], [])
        self.assertEqual(searched["query"], "오전 회의")
        self.assertEqual(searched["top_k"], 2)
        self.assertEqual(searched["reference_backend"]["vector_store"], "fake")
        self.assertEqual(searched["hits"][0]["id"], "ref_1")


class SavedRequestSearchTests(unittest.TestCase):
    def test_search_trims_query_and_clamps_limit(self) -> None:
        store = SavedRequestStoreFake([{"request_id": "req_1"}])

        rows = week04.search_saved_request_rows(
            store,
            query="  과제 제출  ",
            top_k=100,
        )

        self.assertEqual(rows, [{"request_id": "req_1"}])
        self.assertEqual(
            store.search_calls,
            [{"query": "과제 제출", "kind": None, "limit": 50}],
        )

    def test_blank_query_does_not_turn_into_full_history_lookup(self) -> None:
        store = SavedRequestStoreFake([{"request_id": "must_not_leak"}])

        rows = week04.search_saved_request_rows(store, query="   ", top_k=3)

        self.assertEqual(rows, [])
        self.assertEqual(store.search_calls, [])

    def test_real_sqlite_searches_title_original_text_and_reason(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            store = week04.AppSQLiteStore(Path(directory) / "saved.sqlite3")
            store.save_structured_request(
                {
                    "kind": "todo",
                    "title": "과제 제출",
                    "reason": "마감 전에 완료해야 함",
                    "original_text": "금요일까지 보고서를 내야 해",
                }
            )
            store.save_structured_request(
                {
                    "kind": "reminder",
                    "title": "운동 알림",
                    "reason": "집중 시간이 끝나면 알려 달라고 요청함",
                    "original_text": "오후 여섯 시에 운동하라고 알려줘",
                }
            )

            title_rows = week04.search_saved_request_rows(store, query="과제")
            original_rows = week04.search_saved_request_rows(store, query="보고서")
            reason_rows = week04.search_saved_request_rows(store, query="집중 시간")
            missing_rows = week04.search_saved_request_rows(store, query="없는 기록")

        self.assertEqual(title_rows[0]["title"], "과제 제출")
        self.assertEqual(original_rows[0]["title"], "과제 제출")
        self.assertEqual(reason_rows[0]["title"], "운동 알림")
        self.assertEqual(missing_rows, [])

    def test_public_tool_returns_effective_query_limit_and_rows(self) -> None:
        store = SavedRequestStoreFake([{"request_id": "req_한글", "title": "과제"}])
        with patch.object(week04, "SQLITE_STORE", store):
            raw = week04.search_saved_requests.invoke(
                {"query": "  과제  ", "top_k": 3}
            )

        result = json.loads(raw)
        self.assertIn("과제", raw)
        self.assertNotIn("\\u", raw)
        self.assertEqual(result["tool_name"], "search_saved_requests")
        self.assertEqual(result["query"], "과제")
        self.assertEqual(result["top_k"], 3)
        self.assertEqual(result["rows"][0]["request_id"], "req_한글")


class ConversationRAGTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hit = {
            "chunk_id": "conv_old:conversation",
            "conversation_id": "conv_old",
            "title": "지난 대화",
            "content": "user: 오전 회의를 피하고 싶어",
            "distance": 0.2,
            "metadata": {"conversation_id": "conv_old"},
        }

    def test_sync_precedes_search_and_current_conversation_is_excluded(self) -> None:
        rag_store = ConversationRAGStoreFake([self.hit])
        sqlite_store = object()

        with conversation_session_scope("conv_current"):
            result = week04.search_conversation_messages_dict(
                sqlite_store,
                rag_store,
                query="  오전 회의  ",
                top_k=100,
            )

        self.assertEqual(rag_store.events[:2], ["sync", "search"])
        self.assertEqual(
            rag_store.search_calls,
            [
                {
                    "query": "오전 회의",
                    "top_k": 50,
                    "exclude_conversation_id": "conv_current",
                    "conversation_id": None,
                }
            ],
        )
        self.assertEqual(result["hits"], [self.hit])
        self.assertEqual(result["rows"], [self.hit])
        self.assertEqual(result["excluded_conversation_id"], "conv_current")
        self.assertIsNone(result["conversation_id"])
        self.assertEqual(result["rag_backend"]["vector_store"], "fake-rag")
        self.assertEqual(result["sync"]["upserted"], 1)
        self.assertIn("SQLite 대화 RAG", result["context"])

    def test_default_direct_scope_is_not_treated_as_a_conversation(self) -> None:
        rag_store = ConversationRAGStoreFake()

        result = week04.search_conversation_messages_dict(
            object(),
            rag_store,
            query="과거 대화",
        )

        self.assertIsNone(result["excluded_conversation_id"])
        self.assertIsNone(rag_store.search_calls[0]["exclude_conversation_id"])

    def test_explicit_conversation_targets_it_instead_of_excluding_current(self) -> None:
        rag_store = ConversationRAGStoreFake([self.hit])

        with conversation_session_scope("conv_current"):
            result = week04.search_conversation_messages_dict(
                object(),
                rag_store,
                query="지난 대화",
                conversation_id="  conv_old  ",
            )

        self.assertEqual(result["conversation_id"], "conv_old")
        self.assertIsNone(result["excluded_conversation_id"])
        self.assertEqual(rag_store.search_calls[0]["conversation_id"], "conv_old")
        self.assertIsNone(rag_store.search_calls[0]["exclude_conversation_id"])

    def test_rows_helper_uses_shared_rag_store(self) -> None:
        rag_store = ConversationRAGStoreFake([self.hit])
        with patch.object(week04, "CONVERSATION_RAG_STORE", rag_store):
            rows = week04.search_conversation_message_rows(
                object(),
                query="오전 회의",
                top_k=5,
            )

        self.assertEqual(rows, [self.hit])

    def test_public_tool_returns_traceable_rag_envelope(self) -> None:
        rag_store = ConversationRAGStoreFake([self.hit])
        with (
            patch.object(week04, "SQLITE_STORE", object()),
            patch.object(week04, "CONVERSATION_RAG_STORE", rag_store),
            conversation_session_scope("conv_current"),
        ):
            raw = week04.search_conversation_messages.invoke(
                {"query": "  오전 회의  ", "top_k": 5}
            )

        result = json.loads(raw)
        self.assertIn("지난 대화", raw)
        self.assertNotIn("\\u", raw)
        self.assertEqual(result["tool_name"], "search_conversation_messages")
        self.assertEqual(result["query"], "오전 회의")
        self.assertEqual(result["top_k"], 5)
        self.assertEqual(result["hits"], result["rows"])
        self.assertEqual(result["excluded_conversation_id"], "conv_current")


class CompatibilityMemorySearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reference_store = ReferenceStoreFake()
        self.schedule_rows = [
            {
                "schedule_id": "sch_1",
                "request_id": "req_1",
                "request_kind": "personal_schedule",
                "title": "철수와 회의",
                "date": "2026-07-23",
                "start_time": "14:00",
                "end_time": "15:00",
                "attendees": ["철수"],
            },
            {
                "schedule_id": "sch_2",
                "request_id": "req_2",
                "request_kind": "group_schedule",
                "title": "영희와 회의",
                "date": "2026-07-24",
                "start_time": "10:00",
                "end_time": None,
                "attendees_json": '["영희"]',
            },
            {
                "schedule_id": "sch_3",
                "request_id": "req_3",
                "request_kind": "personal_schedule",
                "title": "깨진 참석자 데이터",
                "date": "2026-07-25",
                "start_time": None,
                "end_time": None,
                "attendees_json": "not-json",
            },
        ]

    def _invoke(
        self,
        *,
        attendee: str | None = None,
        limit: int = 5,
        rows: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], ScheduleStoreFake]:
        schedule_store = ScheduleStoreFake(self.schedule_rows if rows is None else rows)
        with (
            patch.object(week04, "REFERENCE_STORE", self.reference_store),
            patch.object(week04, "SQLITE_STORE", schedule_store),
        ):
            raw = week04.search_nana_memory.invoke(
                {
                    "query": "  회의 선호  ",
                    "date_from": " 2026-07-23 ",
                    "date_to": " 2026-07-31 ",
                    "attendee": attendee,
                    "limit": limit,
                }
            )
        return json.loads(raw), schedule_store

    def test_combines_sources_with_effective_filters_and_candidate_limit(self) -> None:
        result, schedule_store = self._invoke(limit=2)

        self.assertEqual(
            schedule_store.list_calls,
            [
                {
                    "limit": 50,
                    "date_from": "2026-07-23",
                    "date_to": "2026-07-31",
                }
            ],
        )
        self.assertEqual(result["query"], "회의 선호")
        self.assertEqual(result["limit"], 2)
        self.assertEqual(result["filters"]["attendee"], None)
        self.assertEqual(len(result["reference_hits"]), 1)
        self.assertEqual(len(result["chunks"]), 2)
        self.assertEqual(result["chunks"][0]["metadata"]["source"], "sqlite_schedule")
        self.assertEqual(result["chunks"][0]["metadata"]["attendees"], ["철수"])
        self.assertIn("[개인 참고자료 검색 결과]", result["context"])
        self.assertIn("[SQLite 일정 검색 결과]", result["context"])

    def test_attendee_filter_reads_list_and_json_fallback(self) -> None:
        list_result, _ = self._invoke(attendee=" 철수 ")
        json_result, _ = self._invoke(attendee="영희")

        self.assertEqual(
            [chunk["metadata"]["schedule_id"] for chunk in list_result["chunks"]],
            ["sch_1"],
        )
        self.assertEqual(
            [chunk["metadata"]["schedule_id"] for chunk in json_result["chunks"]],
            ["sch_2"],
        )

    def test_malformed_attendees_json_is_ignored_safely(self) -> None:
        result, _ = self._invoke(attendee="누구", rows=[self.schedule_rows[2]])

        self.assertEqual(result["chunks"], [])
        self.assertIn("조건에 맞는 저장 일정이 없습니다", result["context"])

    def test_schedule_chunk_has_stable_provenance_metadata(self) -> None:
        chunk = week04._schedule_chunk(self.schedule_rows[1])

        self.assertEqual(chunk["metadata"]["schedule_id"], "sch_2")
        self.assertEqual(chunk["metadata"]["request_id"], "req_2")
        self.assertEqual(chunk["metadata"]["request_kind"], "group_schedule")
        self.assertEqual(chunk["metadata"]["attendees"], ["영희"])
        self.assertIn("영희와 회의", chunk["page_content"])
        self.assertIn("10:00", chunk["page_content"])

    def test_empty_sources_are_reported_as_no_evidence(self) -> None:
        reference_store = ReferenceStoreFake()
        reference_store.search_personal_references = lambda query, limit: []
        schedule_store = ScheduleStoreFake([])
        with (
            patch.object(week04, "REFERENCE_STORE", reference_store),
            patch.object(week04, "SQLITE_STORE", schedule_store),
        ):
            result = json.loads(
                week04.search_nana_memory.invoke(
                    {"query": "없음", "limit": 5}
                )
            )

        self.assertEqual(result["reference_hits"], [])
        self.assertEqual(result["chunks"], [])
        self.assertIn("검색된 개인 참고자료가 없습니다", result["context"])
        self.assertIn("조건에 맞는 저장 일정이 없습니다", result["context"])


if __name__ == "__main__":
    unittest.main()
