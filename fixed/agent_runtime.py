"""Gradio 앱과 주차별 LangChain agent 사이의 실행 런타임입니다."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fixed.app_store import AppSQLiteStore
from fixed.config import CONFIG, DATA_DIR
from fixed.local_trace_log import LocalTraceLogStore
from fixed.session_scope import conversation_session_scope
from fixed.week_agent_registry import run_active_week_agent, stream_active_week_agent


LOGGER = logging.getLogger(__name__)
DEFAULT_TRACE_LOG_PATH = DATA_DIR / "logs" / "agent_traces.jsonl"


@dataclass
class RuntimeResult:
    """agent 실행이 끝난 뒤 UI와 DB에 저장할 최종 결과입니다."""

    answer: str
    trace: dict[str, Any]
    conversation_id: str


@dataclass
class RuntimeStreamEvent:
    """stream 실행 중 UI로 전달하는 진행 상태 또는 최종 결과입니다."""

    status_text: str | None = None
    result: RuntimeResult | None = None


class AgentRuntime:
    """UI와 student_parts agent 사이를 잇는 얇은 런타임 어댑터입니다.

    이 클래스는 채팅 메시지를 저장하고, 선택된 주차의 student agent에
    현재 대화의 전체 메시지를 전달한 뒤, 반환된 답변과 trace를 다시 저장합니다.
    주차별 prompt, tool 목록, agent 선택, trace 해석은 student_parts가 맡습니다.
    """

    def __init__(
        self,
        active_week: int | None = None,
        trace_log_store: LocalTraceLogStore | None = None,
    ) -> None:
        """앱 DB 저장소를 열고 실행할 주차를 설정합니다."""

        self.app_store = AppSQLiteStore(CONFIG.app_db_path)
        self.active_week = (
            active_week if active_week is not None else CONFIG.active_week
        )
        self.trace_log_store = trace_log_store or LocalTraceLogStore(
            DEFAULT_TRACE_LOG_PATH
        )

    def ensure_conversation(
        self, conversation_id: str | None, first_message: str
    ) -> str:
        """기존 대화 ID가 없으면 첫 사용자 메시지를 제목으로 새 대화를 만듭니다."""

        if conversation_id:
            return conversation_id
        created = self.app_store.create_conversation(first_message[:40] or "새 대화")
        return created["conversation_id"]

    def load_messages_for_chatbot(self, conversation_id: str) -> list[dict[str, str]]:
        """UI 챗봇 컴포넌트가 표시할 user/assistant 메시지만 불러옵니다."""

        rows = self.app_store.load_conversation(conversation_id)
        return [
            {"role": row["role"], "content": row["content"]}
            for row in rows
            if row["role"] in {"user", "assistant"}
        ]

    def archive_conversation(self, conversation_id: str | None) -> None:
        """대화를 삭제하지 않고 목록에서 숨깁니다."""

        if conversation_id:
            self.app_store.archive_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str | None) -> None:
        """대화와 메시지를 DB에서 삭제합니다."""

        self.app_store.delete_conversation(conversation_id)

    def run_agent(
        self, user_message: str, conversation_id: str | None
    ) -> RuntimeResult:
        """사용자 메시지를 저장하고 선택된 주차 agent를 한 번 실행합니다.

        agent에는 현재 대화의 user/assistant 메시지를 넘깁니다. 실행 결과는
        assistant 메시지로 다시 저장하고, trace에는 현재 conversation_id를 붙입니다.
        """

        conversation_id = self.ensure_conversation(conversation_id, user_message)
        previous_messages = self.app_store.load_conversation(conversation_id)
        self.app_store.append_message(conversation_id, "user", user_message)

        messages = self._agent_messages(previous_messages, user_message)
        with conversation_session_scope(conversation_id):
            result = run_active_week_agent(self.active_week, messages)
        trace = dict(result.trace)
        trace["conversation_id"] = conversation_id

        self.app_store.append_message(conversation_id, "assistant", result.answer)
        runtime_result = RuntimeResult(
            answer=result.answer, trace=trace, conversation_id=conversation_id
        )
        self._log_final_result(user_message, runtime_result)
        return runtime_result

    def stream_agent(
        self, user_message: str, conversation_id: str | None
    ) -> Iterator[RuntimeStreamEvent]:
        """stream 모드로 agent를 실행하며 tool 진행 상태와 최종 답변을 순서대로 yield합니다."""

        conversation_id = self.ensure_conversation(conversation_id, user_message)
        previous_messages = self.app_store.load_conversation(conversation_id)
        self.app_store.append_message(conversation_id, "user", user_message)

        messages = self._agent_messages(previous_messages, user_message)
        stream = stream_active_week_agent(self.active_week, messages)
        while True:
            with conversation_session_scope(conversation_id):
                try:
                    event = next(stream)
                except StopIteration:
                    break
            if event.status_text:
                yield RuntimeStreamEvent(status_text=event.status_text)
            if event.result:
                trace = dict(event.result.trace)
                trace["conversation_id"] = conversation_id
                result = RuntimeResult(
                    answer=event.result.answer,
                    trace=trace,
                    conversation_id=conversation_id,
                )
                self.app_store.append_message(
                    conversation_id, "assistant", result.answer
                )
                self._log_final_result(user_message, result)
                yield RuntimeStreamEvent(result=result)
                return

        trace = {
            "mode": "active_week_agent",
            "active_week": self.active_week,
            "conversation_id": conversation_id,
            "events": [],
            "error": "stream_completed_without_result",
        }
        result = RuntimeResult(
            answer="응답을 생성하지 못했습니다.",
            trace=trace,
            conversation_id=conversation_id,
        )
        self.app_store.append_message(conversation_id, "assistant", result.answer)
        self._log_final_result(user_message, result)
        yield RuntimeStreamEvent(result=result)

    def _log_final_result(self, user_message: str, result: RuntimeResult) -> None:
        """UI에 전달할 최종 실행 결과를 best-effort 로컬 로그로 남깁니다."""

        try:
            self.trace_log_store.append(
                active_week=self.active_week,
                conversation_id=result.conversation_id,
                user_message=user_message,
                assistant_answer=result.answer,
                trace=result.trace,
            )
        except Exception as exc:
            LOGGER.warning(
                "최종 agent trace를 로컬 로그에 기록하지 못했습니다: %s", exc
            )

    def _agent_messages(
        self, previous_messages: list[dict[str, Any]], user_message: str
    ) -> list[dict[str, str]]:
        """agent 입력용 현재 대화 history를 만들고 현재 사용자 메시지를 마지막에 붙입니다."""

        messages = [
            {"role": row["role"], "content": row["content"]}
            for row in previous_messages
            if row["role"] in {"user", "assistant"}
        ]
        messages.append({"role": "user", "content": user_message})
        return messages
