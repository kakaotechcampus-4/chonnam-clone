from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fixed.config import CONFIG


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


if __name__ == "__main__":
    unittest.main()
