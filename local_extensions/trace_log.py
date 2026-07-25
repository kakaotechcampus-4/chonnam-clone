"""UI에 표시된 최종 agent trace를 로컬 JSONL 파일에 저장합니다."""

from __future__ import annotations

import json
import threading
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from fixed.store_base import now_iso


class LocalTraceLogError(RuntimeError):
    """로컬 trace를 직렬화하거나 파일에 기록하지 못했을 때 발생합니다."""


class LocalTraceLogStore:
    """질문별 최종 답변과 trace를 UTF-8 JSONL로 append합니다."""

    SCHEMA_VERSION = 2

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
    ) -> None:
        """최종 실행 한 건을 기록하고 실패하면 구체적인 예외를 발생시킵니다."""

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
            encoded = json.dumps(
                record,
                ensure_ascii=False,
                default=_json_default,
            )
            with self._append_lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as log_file:
                    log_file.write(encoded + "\n")
        except Exception as exc:
            raise LocalTraceLogError(
                f"로컬 trace 로그를 기록하지 못했습니다 ({self.path}): {exc}"
            ) from exc


def _json_default(value: Any) -> Any:
    """JSON 기본 타입이 아닌 trace 값을 분석 가능한 구조로 변환합니다."""

    if isinstance(value, Exception):
        return {
            "type": type(value).__name__,
            "message": str(value),
        }
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"지원하지 않는 trace 값입니다: {type(value).__name__}")
