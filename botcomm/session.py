from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .message import KeyboardOption, Message, _parse_ts


@dataclass
class SettingField:
    """One entry of the bot's per-session settings schema; ``type`` is
    ``toggle`` ("true"/"false"), ``select`` (≤10 ``options``), ``text`` or
    ``time`` ("HH:MM")."""

    key: str
    label: str
    type: str
    description: str = ""
    options: list[KeyboardOption] = field(default_factory=list)
    default: str = ""

    def to_json(self) -> dict:
        data: dict = {"key": self.key, "label": self.label, "type": self.type}
        if self.description:
            data["description"] = self.description
        if self.options:
            data["options"] = [o.to_json() for o in self.options]
        if self.default:
            data["default"] = self.default
        return data


@dataclass
class SessionSettings:
    """Effective settings of a session, as sent in the ``settings`` envelope."""

    session_id: str
    settings: dict[str, str]

    @classmethod
    def from_json(cls, data: dict) -> "SessionSettings":
        return cls(session_id=data.get("sessionID", ""), settings=dict(data.get("settings") or {}))


@dataclass
class SessionUser:
    """The account on the other side of a session."""

    id: str
    name: Optional[str] = None
    timezone: Optional[str] = None
    locale: Optional[str] = None

    @classmethod
    def from_json(cls, data: dict) -> "SessionUser":
        return cls(
            id=data.get("id", ""),
            name=data.get("name"),
            timezone=data.get("timezone"),
            locale=data.get("locale"),
        )


@dataclass
class Session:
    """A conversation between one account and the bot."""

    id: str
    unread_count: int = 0
    last_message: Optional[Message] = None
    user: Optional[SessionUser] = None
    settings: dict[str, str] = field(default_factory=dict)
    muted: bool = False
    create_ts: Optional[datetime] = None

    @classmethod
    def from_json(cls, data: dict) -> "Session":
        last = data.get("lastMessage")
        user = data.get("user")
        return cls(
            id=data.get("id", ""),
            unread_count=int(data.get("unreadCount", 0)),
            last_message=Message.from_json(last) if last else None,
            user=SessionUser.from_json(user) if user else None,
            settings=dict(data.get("settings") or {}),
            muted=bool(data.get("muted", False)),
            create_ts=_parse_ts(data.get("createTS")),
        )
