from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class KeyboardOption:
    """One tappable choice offered by a keyboard: ``label`` is shown to the
    user, ``value`` is what the bot receives when it is chosen."""

    label: str
    value: str

    def to_json(self) -> dict:
        return {"label": self.label, "value": self.value}

    @classmethod
    def from_json(cls, data: dict) -> "KeyboardOption":
        return cls(label=data.get("label", ""), value=data.get("value", ""))


@dataclass
class Keyboard:
    """A set of one-tap answer options attached to a message. The server
    stamps ``selected`` once the user answers; clients render an answered
    keyboard unclickable."""

    options: list[KeyboardOption]
    selected: Optional[str] = None

    @classmethod
    def from_json(cls, data: dict) -> "Keyboard":
        return cls(
            options=[KeyboardOption.from_json(item) for item in data.get("options") or []],
            selected=data.get("selected"),
        )


@dataclass
class PreviewImage:
    id: str
    width: int
    height: int


@dataclass
class LinkPreview:
    url: str
    site_name: str
    title: str
    description: str = ""
    image: Optional[PreviewImage] = None

    @classmethod
    def from_json(cls, data: dict) -> "LinkPreview":
        image = data.get("image")
        return cls(
            url=data.get("url", ""),
            site_name=data.get("siteName", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            image=PreviewImage(id=image["id"], width=image["width"], height=image["height"]) if image else None,
        )


@dataclass
class Message:
    """A single chat message, as returned by the API."""

    id: str
    session_id: str
    author_id: str
    content: str
    # keyboard is present on bot messages sent with one-tap answer options;
    # reply_to and value are set on a user's answer to a keyboard message:
    # reply_to is the id of the keyboard message, value the machine value of
    # the chosen option (content carries its human-readable label)
    keyboard: Optional[Keyboard] = None
    reply_to: str = ""
    value: str = ""
    silent: bool = False
    read: bool = False
    delivered: bool = False
    author_ts: Optional[datetime] = None
    create_ts: Optional[datetime] = None
    edit_ts: Optional[datetime] = None
    subject: str = ""
    metadata: Optional[dict[str, Any]] = None
    command: str = ""
    argument: str = ""
    link_preview: Optional[LinkPreview] = None
    preview_ts: Optional[datetime] = None
    stream: Optional[dict] = None
    reactions: Optional[dict[str, str]] = None
    reaction_revision: int = 0
    card: Optional[dict] = None
    fields: Optional[dict] = None
    cancel: bool = False

    @classmethod
    def from_json(cls, data: dict) -> "Message":
        keyboard = data.get("keyboard")
        preview = data.get("linkPreview")
        return cls(
            cancel=data.get("cancel", False),
            id=data.get("id", ""),
            session_id=data.get("sessionID", ""),
            author_id=data.get("authorID", ""),
            content=data.get("content", ""),
            keyboard=Keyboard.from_json(keyboard) if keyboard else None,
            stream=data.get("stream"),
            reactions=data.get("reactions"),
            reaction_revision=data.get("reactionRevision", 0),
            card=data.get("card"),
            fields=data.get("fields"),
            reply_to=data.get("replyTo", ""),
            value=data.get("value", ""),
            silent=bool(data.get("silent", False)),
            read=bool(data.get("read", False)),
            delivered=bool(data.get("delivered", False)),
            author_ts=_parse_ts(data.get("authorTS")),
            create_ts=_parse_ts(data.get("createTS")),
            edit_ts=_parse_ts(data.get("editTS")),
            subject=data.get("subject", ""),
            metadata=data.get("metadata"),
            link_preview=LinkPreview.from_json(preview) if preview else None,
            preview_ts=_parse_ts(data.get("previewTS")),
        )


def _parse_ts(raw: Optional[str]) -> Optional[datetime]:
    """Parse an RFC3339 timestamp leniently: Go emits up to nanosecond
    precision, which datetime.fromisoformat rejects before Python 3.11."""
    if not raw:
        return None
    value = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        m = re.match(r"^(.*?)\.(\d+)([+-]\d{2}:\d{2})?$", value)
        if m is None:
            return None
        frac = m.group(2)[:6].ljust(6, "0")
        try:
            return datetime.fromisoformat(f"{m.group(1)}.{frac}{m.group(3) or ''}")
        except ValueError:
            return None
