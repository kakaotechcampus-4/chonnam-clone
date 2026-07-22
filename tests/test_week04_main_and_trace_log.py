from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from fixed import agent_runtime as agent_runtime_module
from fixed.agent_runtime import AgentRuntime
from fixed.local_trace_log import LocalTraceLogStore


with (
    patch("fixed.reference_store.PersonalReferenceStore", autospec=True),
    patch("fixed.conversation_rag_store.ConversationRAGStore", autospec=True),
    patch("fixed.app_store.AppSQLiteStore", autospec=True),
):
    week04 = importlib.import_module("student_parts.week04_retrieve_nanas_memory")


class FakeReferenceStore:
    def __init__(self) -> None:
        self.add_calls: list[dict[str, object]] = []
        self.search_calls: list[dict[str, object]] = []

    def backend_info(self) -> dict[str, str]:
        return {"vector_store": "fake"}

    def add_personal_reference(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
    ) -> dict[str, object]:
        self.add_calls.append({"title": title, "content": content, "tags": tags})
        return {
            "reference_id": "ref_test",
            "title": title,
            "content": content,
            "tags": tags or [],
        }

    def search_personal_references(
        self, query: str, limit: int = 3
    ) -> list[dict[str, object]]:
        self.search_calls.append({"query": query, "limit": limit})
        return [
            {
                "id": "ref_test",
                "title": "집중 시간",
                "content": "중요한 회의는 오전을 선호한다.",
                "tags": "preference,meeting",
                "distance": 0.12,
            }
        ]


class FakeSQLiteStore:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, object]] = []

    def search_saved_requests(
        self,
        query: str,
        kind: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, object]]:
        self.search_calls.append({"query": query, "kind": kind, "limit": limit})
        return [{"request_id": "req_test", "title": "코칭 일정"}]


class MissingReferenceIdStore(FakeReferenceStore):
    def add_personal_reference(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
    ) -> dict[str, object]:
        return {"title": title, "content": content, "tags": tags or []}


class MalformedReferenceSearchStore(FakeReferenceStore):
    def search_personal_references(
        self, query: str, limit: int = 3
    ) -> list[dict[str, object]]:
        return [{}]


class MalformedSavedRequestStore(FakeSQLiteStore):
    def search_saved_requests(
        self,
        query: str,
        kind: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, object]]:
        return [{"title": "식별자 없는 일정"}]


class FakeAppStore:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []

    def create_conversation(self, title: str) -> dict[str, str]:
        return {"conversation_id": "conv_test", "title": title}

    def load_conversation(self, conversation_id: str) -> list[dict[str, str]]:
        return []

    def append_message(
        self, conversation_id: str, role: str, content: str
    ) -> dict[str, str]:
        self.messages.append((conversation_id, role, content))
        return {"conversation_id": conversation_id}


class CaptureTraceLog:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def append(self, **record: object) -> bool:
        self.records.append(record)
        return True


class RaisingTraceLog:
    def append(self, **record: object) -> bool:
        raise OSError("쓰기 실패")


class Week04MainToolTests(unittest.TestCase):
    def test_add_personal_reference_normalizes_text_and_tags(self) -> None:
        store = FakeReferenceStore()

        payload = week04.add_personal_reference_dict(
            store,
            title="  집중 시간  ",
            content="  오전 회의를 선호한다.  ",
            tags=[" preference ", "", "preference", " meeting "],
        )

        self.assertEqual(store.add_calls[0]["title"], "집중 시간")
        self.assertEqual(store.add_calls[0]["content"], "오전 회의를 선호한다.")
        self.assertEqual(store.add_calls[0]["tags"], ["preference", "meeting"])
        self.assertEqual(payload["reference_backend"], {"vector_store": "fake"})
        self.assertEqual(payload["reference"]["reference_id"], "ref_test")

    def test_tool_input_schemas_reject_blank_required_text(self) -> None:
        invalid_payloads = [
            (week04.AddPersonalReferenceInput, {"title": " ", "content": "내용"}),
            (week04.AddPersonalReferenceInput, {"title": "제목", "content": "\t"}),
            (week04.SearchPersonalReferencesInput, {"query": "  "}),
            (week04.SearchSavedRequestsInput, {"query": "\n"}),
        ]

        for schema, payload in invalid_payloads:
            with self.subTest(schema=schema.__name__, payload=payload):
                with self.assertRaises(ValidationError):
                    schema.model_validate(payload)

    def test_helpers_reject_results_that_could_look_successful(self) -> None:
        with self.assertRaisesRegex(ValueError, r"reference_id.*value="):
            week04.add_personal_reference_dict(
                MissingReferenceIdStore(),
                title="제목",
                content="내용",
            )

        with self.assertRaisesRegex(ValueError, r"missing id.*value="):
            week04.search_personal_reference_hits(
                MalformedReferenceSearchStore(),
                query="회의",
            )

        with self.assertRaisesRegex(ValueError, r"request_id.*value="):
            week04.search_saved_request_rows(
                MalformedSavedRequestStore(),
                query="일정",
            )

    def test_search_personal_references_builds_nested_metadata(self) -> None:
        store = FakeReferenceStore()

        hits = week04.search_personal_reference_hits(store, query="  회의  ", top_k=2)

        self.assertEqual(store.search_calls, [{"query": "회의", "limit": 2}])
        self.assertEqual(
            hits[0],
            {
                "id": "ref_test",
                "content": "중요한 회의는 오전을 선호한다.",
                "distance": 0.12,
                "metadata": {"title": "집중 시간", "tags": "preference,meeting"},
            },
        )

    def test_search_saved_requests_passes_limit_by_keyword(self) -> None:
        store = FakeSQLiteStore()

        rows = week04.search_saved_request_rows(store, query="  코칭  ", top_k=7)

        self.assertEqual(rows[0]["request_id"], "req_test")
        self.assertEqual(
            store.search_calls, [{"query": "코칭", "kind": None, "limit": 7}]
        )

    def test_main_tools_return_korean_json_contracts(self) -> None:
        reference_store = FakeReferenceStore()
        sqlite_store = FakeSQLiteStore()
        with (
            patch.object(week04, "REFERENCE_STORE", reference_store),
            patch.object(week04, "SQLITE_STORE", sqlite_store),
        ):
            added_raw = week04.add_personal_reference.invoke(
                {"title": "집중 시간", "content": "오전 회의를 선호한다.", "tags": None}
            )
            hits_raw = week04.search_personal_references.invoke(
                {"query": "회의", "top_k": 2}
            )
            rows_raw = week04.search_saved_requests.invoke(
                {"query": "코칭", "top_k": 3}
            )

        self.assertIn("집중 시간", added_raw)
        self.assertIn("오전", hits_raw)
        self.assertEqual(reference_store.add_calls[0]["tags"], [])
        self.assertEqual(json.loads(rows_raw)["rows"][0]["request_id"], "req_test")

    def test_only_implemented_week04_tools_are_exposed(self) -> None:
        tool_names = [tool.name for tool in week04.week04_tools()]
        prompt = week04.week04_system_prompt()

        self.assertIn("add_personal_reference", tool_names)
        self.assertIn("search_personal_references", tool_names)
        self.assertIn("search_saved_requests", tool_names)
        self.assertNotIn("search_conversation_messages", tool_names)
        self.assertIn("Week 3의 구조화 및 SQLite 저장 도구", prompt)
        self.assertIn("출처를 확정할 수 없으면", prompt)
        self.assertIn("두 검색 도구를 반드시 모두 호출", prompt)
        self.assertIn("다른 출처까지 검색하기 전에", prompt)
        self.assertIn("이전 assistant의 검색 실패 답변", prompt)
        self.assertNotIn("search_conversation_messages", prompt)

    def test_safe_limit_clamps_and_uses_default(self) -> None:
        self.assertEqual(week04.safe_limit(-1, default=3, maximum=50), 1)
        self.assertEqual(week04.safe_limit(100, default=3, maximum=50), 50)
        self.assertEqual(week04.safe_limit("invalid", default=3, maximum=50), 3)
        self.assertEqual(week04.safe_limit(None, default=100, maximum=50), 50)
        with self.assertRaisesRegex(ValueError, "maximum"):
            week04.safe_limit(3, default=3, maximum=0)


class LocalTraceLogTests(unittest.TestCase):
    def test_jsonl_append_preserves_korean_and_existing_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "logs" / "agent_traces.jsonl"
            store = LocalTraceLogStore(path)

            for index in range(2):
                saved = store.append(
                    active_week=4,
                    conversation_id="conv_test",
                    user_message=f"질문 {index}",
                    assistant_answer=f"답변 {index}",
                    trace={"events": [{"event": "tool_call", "tool_name": "검색"}]},
                )
                self.assertTrue(saved)

            raw = path.read_text(encoding="utf-8")
            records = [json.loads(line) for line in raw.splitlines()]

        self.assertIn("질문", raw)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["schema_version"], 1)
        self.assertEqual(records[1]["assistant_answer"], "답변 1")

    def test_append_failure_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parent_file = Path(temp_dir) / "not_a_directory"
            parent_file.write_text("block", encoding="utf-8")
            store = LocalTraceLogStore(parent_file / "agent_traces.jsonl")

            with self.assertLogs("fixed.local_trace_log", level="WARNING"):
                saved = store.append(
                    active_week=4,
                    conversation_id="conv_test",
                    user_message="질문",
                    assistant_answer="답변",
                    trace={"events": []},
                )

        self.assertFalse(saved)


class AgentRuntimeTraceLogTests(unittest.TestCase):
    def test_run_agent_logs_one_final_result(self) -> None:
        app_store = FakeAppStore()
        trace_log = CaptureTraceLog()
        agent_result = SimpleNamespace(
            answer="최종 답변", trace={"events": [{"event": "tool_call"}]}
        )

        with (
            patch.object(
                agent_runtime_module, "AppSQLiteStore", return_value=app_store
            ),
            patch.object(
                agent_runtime_module, "run_active_week_agent", return_value=agent_result
            ),
        ):
            runtime = AgentRuntime(active_week=4, trace_log_store=trace_log)
            result = runtime.run_agent("사용자 질문", None)

        self.assertEqual(result.answer, "최종 답변")
        self.assertEqual(len(trace_log.records), 1)
        self.assertEqual(trace_log.records[0]["user_message"], "사용자 질문")
        self.assertEqual(trace_log.records[0]["trace"]["conversation_id"], "conv_test")

    def test_stream_agent_logs_only_the_final_result(self) -> None:
        app_store = FakeAppStore()
        trace_log = CaptureTraceLog()
        stream_events = iter(
            [
                SimpleNamespace(status_text="답변을 진행중입니다", result=None),
                SimpleNamespace(
                    status_text=None,
                    result=SimpleNamespace(answer="스트림 답변", trace={"events": []}),
                ),
            ]
        )

        with (
            patch.object(
                agent_runtime_module, "AppSQLiteStore", return_value=app_store
            ),
            patch.object(
                agent_runtime_module,
                "stream_active_week_agent",
                return_value=stream_events,
            ),
        ):
            runtime = AgentRuntime(active_week=4, trace_log_store=trace_log)
            events = list(runtime.stream_agent("스트림 질문", None))

        self.assertEqual(len(events), 2)
        self.assertEqual(len(trace_log.records), 1)
        self.assertEqual(trace_log.records[0]["assistant_answer"], "스트림 답변")

    def test_stream_without_result_logs_fallback_error(self) -> None:
        app_store = FakeAppStore()
        trace_log = CaptureTraceLog()
        stream_events = iter(
            [SimpleNamespace(status_text="답변을 진행중입니다", result=None)]
        )

        with (
            patch.object(
                agent_runtime_module, "AppSQLiteStore", return_value=app_store
            ),
            patch.object(
                agent_runtime_module,
                "stream_active_week_agent",
                return_value=stream_events,
            ),
        ):
            runtime = AgentRuntime(active_week=4, trace_log_store=trace_log)
            events = list(runtime.stream_agent("결과 없는 질문", None))

        self.assertEqual(len(events), 2)
        self.assertEqual(len(trace_log.records), 1)
        self.assertEqual(
            trace_log.records[0]["trace"]["error"],
            "stream_completed_without_result",
        )

    def test_log_failure_does_not_break_agent_result(self) -> None:
        app_store = FakeAppStore()
        agent_result = SimpleNamespace(answer="정상 답변", trace={"events": []})

        with (
            patch.object(
                agent_runtime_module, "AppSQLiteStore", return_value=app_store
            ),
            patch.object(
                agent_runtime_module, "run_active_week_agent", return_value=agent_result
            ),
        ):
            runtime = AgentRuntime(active_week=4, trace_log_store=RaisingTraceLog())
            with self.assertLogs("fixed.agent_runtime", level="WARNING"):
                result = runtime.run_agent("질문", None)

        self.assertEqual(result.answer, "정상 답변")


if __name__ == "__main__":
    unittest.main()
