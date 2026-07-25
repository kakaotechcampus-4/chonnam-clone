from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fixed.app_store import AppSQLiteStore
from fixed.conversation_rag_store import ConversationRAGStore
from fixed.session_scope import conversation_session_scope
from student_parts import week04_retrieve_nanas_memory as week04


class FakeConversationRAGStore:
    def __init__(self, hits: list[dict] | None = None) -> None:
        self.hits = hits or []
        self.search_kwargs: dict | None = None

    def sync_from_sqlite(self, sqlite_store: AppSQLiteStore) -> dict[str, int]:
        return {"upserted": 1, "skipped": 0, "deleted": 0, "total": 1}

    def search(self, **kwargs: object) -> list[dict]:
        self.search_kwargs = dict(kwargs)
        return list(self.hits) if kwargs.get("query") else []

    def context_from_hits(self, hits: list[dict]) -> str:
        return f"context:{len(hits)}"

    def backend_info(self) -> dict[str, str]:
        return {"vector_store": "fake"}


class FakeReferenceStore:
    def search_personal_references(self, query: str, limit: int) -> list[dict]:
        if not query:
            return []
        return [
            {
                "id": "ref_1",
                "title": "회의 선호",
                "content": "오전 회의를 선호한다.",
                "tags": "preference,meeting",
                "distance": 0.1,
            }
        ][:limit]

    def backend_info(self) -> dict[str, str]:
        return {"vector_store": "fake-reference"}


class FakeScheduleStore:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.list_kwargs: dict | None = None

    def list_schedules(self, **kwargs: object) -> list[dict]:
        self.list_kwargs = dict(kwargs)
        return list(self.rows)


class InMemoryCollection:
    def __init__(self) -> None:
        self.documents: dict[str, str] = {}
        self.metadatas: dict[str, dict] = {}

    def get(self, include: list[str] | None = None) -> dict:
        ids = list(self.documents)
        return {"ids": ids, "metadatas": [self.metadatas[item_id] for item_id in ids]}

    def count(self) -> int:
        return len(self.documents)

    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict]) -> None:
        for item_id, document, metadata in zip(ids, documents, metadatas, strict=True):
            self.documents[item_id] = document
            self.metadatas[item_id] = metadata

    def delete(self, ids: list[str]) -> None:
        for item_id in ids:
            self.documents.pop(item_id, None)
            self.metadatas.pop(item_id, None)


class Week04ConversationRAGTests(unittest.TestCase):
    def test_current_conversation_is_excluded_by_default(self) -> None:
        rag_store = FakeConversationRAGStore([{"conversation_id": "conv_old", "content": "과거 대화"}])

        with conversation_session_scope("conv_current"):
            result = week04.search_conversation_messages_dict(
                object(),
                rag_store,
                query="  프로젝트  ",
                top_k=999,
            )

        self.assertEqual(result["hits"], result["rows"])
        self.assertEqual(result["excluded_conversation_id"], "conv_current")
        self.assertEqual(result["rag_backend"], {"vector_store": "fake"})
        self.assertIn("sync", result)
        self.assertEqual(rag_store.search_kwargs["query"], "프로젝트")
        self.assertEqual(rag_store.search_kwargs["top_k"], 50)
        self.assertEqual(rag_store.search_kwargs["exclude_conversation_id"], "conv_current")

    def test_explicit_conversation_id_disables_current_exclusion(self) -> None:
        rag_store = FakeConversationRAGStore()

        with conversation_session_scope("conv_current"):
            result = week04.search_conversation_messages_dict(
                object(),
                rag_store,
                query="기획",
                conversation_id="  conv_target  ",
            )

        self.assertEqual(result["conversation_id"], "conv_target")
        self.assertIsNone(result["excluded_conversation_id"])
        self.assertEqual(rag_store.search_kwargs["conversation_id"], "conv_target")
        self.assertIsNone(rag_store.search_kwargs["exclude_conversation_id"])

    def test_blank_query_returns_empty_hits(self) -> None:
        result = week04.search_conversation_messages_dict(
            object(),
            FakeConversationRAGStore(),
            query="   ",
        )

        self.assertEqual(result["hits"], [])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["context"], "context:0")

    def test_conversation_tool_returns_public_json_contract(self) -> None:
        rag_store = FakeConversationRAGStore([{"conversation_id": "conv_old", "content": "사용자 기록"}])
        with patch.object(week04, "CONVERSATION_RAG_STORE", rag_store):
            payload = json.loads(
                week04.search_conversation_messages.invoke(
                    {"query": "사용자 기록", "top_k": 5}
                )
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tool_name"], "search_conversation_messages")
        self.assertEqual(payload["hits"], payload["rows"])
        self.assertIn("context", payload)
        self.assertIn("rag_backend", payload)
        self.assertIn("sync", payload)

    def test_sqlite_sync_upserts_skips_updates_and_deletes(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            sqlite_store = AppSQLiteStore(Path(temp_dir) / "app.db")
            conversation = sqlite_store.create_conversation("프로젝트")
            conversation_id = conversation["conversation_id"]
            sqlite_store.append_message(conversation_id, "user", "첫 메시지")

            rag_store = ConversationRAGStore.__new__(ConversationRAGStore)
            rag_store.collection = InMemoryCollection()

            first = rag_store.sync_from_sqlite(sqlite_store)
            unchanged = rag_store.sync_from_sqlite(sqlite_store)
            sqlite_store.append_message(conversation_id, "assistant", "두 번째 메시지")
            updated = rag_store.sync_from_sqlite(sqlite_store)
            sqlite_store.delete_conversation(conversation_id)
            deleted = rag_store.sync_from_sqlite(sqlite_store)

        self.assertEqual(first, {"upserted": 1, "skipped": 0, "deleted": 0, "total": 1})
        self.assertEqual(unchanged, {"upserted": 0, "skipped": 1, "deleted": 0, "total": 1})
        self.assertEqual(updated, {"upserted": 1, "skipped": 0, "deleted": 0, "total": 1})
        self.assertEqual(deleted, {"upserted": 0, "skipped": 0, "deleted": 1, "total": 0})


class Week04CompatibilityTests(unittest.TestCase):
    def test_memory_search_filters_attendee_and_handles_invalid_json(self) -> None:
        schedule_store = FakeScheduleStore(
            [
                {
                    "schedule_id": "sch_match",
                    "request_id": "req_1",
                    "title": "민지와 회의",
                    "date": "2026-07-28",
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "attendees_json": '["민지"]',
                    "source": "structured_output",
                    "request_kind": "group_schedule",
                },
                {
                    "schedule_id": "sch_invalid",
                    "title": "깨진 참석자",
                    "attendees_json": "{invalid",
                },
            ]
        )

        with (
            patch.object(week04, "REFERENCE_STORE", FakeReferenceStore()),
            patch.object(week04, "SQLITE_STORE", schedule_store),
        ):
            payload = json.loads(
                week04.search_nana_memory.invoke(
                    {
                        "query": "회의",
                        "date_from": "2026-07-01",
                        "date_to": "2026-07-31",
                        "attendee": "민지",
                        "limit": 5,
                    }
                )
            )

        self.assertEqual([chunk["id"] for chunk in payload["chunks"]], ["sch_match"])
        self.assertEqual(payload["chunks"][0]["metadata"]["attendees"], ["민지"])
        self.assertEqual(payload["filters"]["attendee"], "민지")
        self.assertEqual(schedule_store.list_kwargs["date_from"], "2026-07-01")
        self.assertEqual(schedule_store.list_kwargs["date_to"], "2026-07-31")
        self.assertIn("[개인 참고자료 검색 결과]", payload["context"])
        self.assertIn("[SQLite 일정 검색 결과]", payload["context"])

    def test_conversation_tool_is_registered_once(self) -> None:
        tool_names = [tool.name for tool in week04.week04_tools()]

        self.assertEqual(tool_names.count("search_conversation_messages"), 1)
        self.assertNotIn("search_nana_memory", tool_names)


if __name__ == "__main__":
    unittest.main()
