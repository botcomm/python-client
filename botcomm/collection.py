from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .message import _parse_ts


@dataclass
class CollectionField:
    key: str
    label: str
    max_items: int
    description: str = ""
    placeholder: str = ""

    def to_json(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "maxItems": self.max_items,
            "description": self.description,
            "placeholder": self.placeholder,
        }


@dataclass
class CollectionRequest:
    """Compare/increment revision atomically on mutation; reject expired requests."""

    id: str
    session_id: str
    key: str
    action: str
    expires_ts: Optional[datetime]
    value: str = ""
    item_id: str = ""
    revision: Optional[int] = None

    @classmethod
    def from_json(cls, data: dict) -> "CollectionRequest":
        return cls(
            id=data["id"],
            session_id=data["sessionID"],
            key=data["key"],
            action=data["action"],
            expires_ts=_parse_ts(data["expiresTS"]),
            value=data.get("value", ""),
            item_id=data.get("itemID", ""),
            revision=data.get("revision"),
        )


@dataclass
class CollectionItem:
    id: str
    label: str
    description: str = ""

    def to_json(self) -> dict:
        return {"id": self.id, "label": self.label, "description": self.description}


@dataclass
class CollectionResult:
    items: list[CollectionItem] = field(default_factory=list)
    revision: int = 0
    error: str = ""
    changed: bool = False

    def to_json(self) -> dict:
        return {
            "items": [item.to_json() for item in self.items],
            "revision": self.revision,
            "error": self.error,
            "changed": self.changed,
        }
