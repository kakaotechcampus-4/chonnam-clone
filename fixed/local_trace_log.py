"""UI에 표시된 최종 agent trace를 로컬 JSONL 파일에 저장합니다."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from fixed.store_base import now_iso


LOGGER = logging.getLogger(__name__)


class LocalTraceLogStore:
    """질문별 최종 답변과 trace를 UTF-8 JSONL로 append합니다."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        """로그 파일 경로를 보관하고 프로세스 내부 append lock을 준비합니다."""

        self.path = path
        self._append_lock = threading.Lock()

    def append(
        self,
        *,
        active_week: int,
        conversation_id: str,
        user_message: str,
        assistant_answer: str,
        trace: dict[str, Any],
    ) -> bool:
        """최종 실행 한 건을 기록하고 성공 여부를 반환합니다.

        로그 저장은 채팅의 부가 기능입니다. 경로 생성이나 파일 쓰기에 실패해도
        agent 응답이 실패하지 않도록 예외를 경고로 바꾸고 False를 반환합니다.
        """

        record = {
            "schema_version": self.SCHEMA_VERSION,
            "logged_at": now_iso(),
            "active_week": active_week,
            "conversation_id": conversation_id,
            "user_message": user_message,
            "assistant_answer": assistant_answer,
            "trace": trace,
        }
        try:
            encoded = json.dumps(record, ensure_ascii=False, default=str)
            with self._append_lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as log_file:
                    log_file.write(encoded + "\n")
        except Exception as exc:
            LOGGER.warning(
                "로컬 trace 로그 저장에 실패했습니다 (%s): %s", self.path, exc
            )
            return False
        return True
