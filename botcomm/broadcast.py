from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from .message import _parse_ts


@dataclass
class Broadcast:
    """A fan-out job created by ``Bot.broadcast``."""

    id: str
    content: str
    silent: bool = False
    total: int = 0
    sent: int = 0
    failed: int = 0
    done: bool = False
    create_ts: Optional[datetime] = None
    done_ts: Optional[datetime] = None
    subject: str = ""
    metadata: Optional[dict[str, Any]] = None

    @classmethod
    def from_json(cls, data: dict) -> "Broadcast":
        return cls(
            id=data.get("id", ""),
            content=data.get("content", ""),
            silent=bool(data.get("silent", False)),
            total=int(data.get("total", 0)),
            sent=int(data.get("sent", 0)),
            failed=int(data.get("failed", 0)),
            done=bool(data.get("done", False)),
            create_ts=_parse_ts(data.get("createTS")),
            done_ts=_parse_ts(data.get("doneTS")),
            subject=data.get("subject", ""),
            metadata=data.get("metadata"),
        )
