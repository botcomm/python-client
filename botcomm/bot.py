"""The official Python SDK for building BotComm bots.

A bot authenticates with its client credentials (client_credentials grant,
re-granted automatically before the access token expires), keeps an SSE
stream from /updates open and receives incoming messages on the ``messages`` and
``commands`` queues. On every (re)connect the SDK back-fills unread messages
via the REST API, so nothing is lost while the bot was offline.
See examples/echo.py for a minimal bot.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlencode

import aiohttp

from .auth import AUTH_HOST, REGRANT_EARLINESS, REGRANT_RETRY, grant, regrant_interval, sub_from_token
from .broadcast import Broadcast
from .collection import CollectionField, CollectionItem, CollectionRequest, CollectionResult
from .command import Command, CommandInput
from .errors import APIError, BotCommError
from .message import Keyboard, KeyboardOption, LinkPreview, Message, PreviewImage, _parse_ts
from .session import Session, SessionSettings, SessionUser, SettingField
from .transport import API_HOST, HTTP_TIMEOUT, READ_TIMEOUT, connect, request

_UNSET = object()

logger = logging.getLogger("botcomm")

QUEUE_BUFFER = 64  # messages/commands queue buffer
RECONNECT_DELAY = 5.0  # pause between reconnect attempts, seconds


class Bot:
    """A BotComm bot: an authenticated client streaming /updates. Incoming messages arrive on ``messages`` (regular) and
    ``commands`` (matching a registered command value); a new chat opened
    with the bot invokes ``on_new_session``."""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.id = ""  # bot ID, resolved from the access token subject on run()

        self.reactions: asyncio.Queue[Message] = asyncio.Queue(QUEUE_BUFFER)
        self.messages: asyncio.Queue[Message] = asyncio.Queue(QUEUE_BUFFER)
        self.commands: asyncio.Queue[Message] = asyncio.Queue(QUEUE_BUFFER)
        # effective settings of a session after either side changed them
        self.collection_requests: asyncio.Queue[CollectionRequest] = asyncio.Queue(QUEUE_BUFFER)
        self.settings: asyncio.Queue[SessionSettings] = asyncio.Queue(QUEUE_BUFFER)
        # called with the Session when a user opens a new chat with the bot;
        # may be a plain function or a coroutine function
        self.on_new_session: Optional[Callable[[Session], Any]] = None

        self.argument_commands = False
        self.startup_commands: Optional[list[Command]] = None
        self.input_mode: Optional[str] = None
        self._commands: dict[str, Command] = {}
        self._backfilled: set[str] = set()  # message IDs delivered by the latest backfill
        self._access_token = ""
        self._http: Optional[aiohttp.ClientSession] = None
        self._stream: Optional[aiohttp.ClientResponse] = None
        self._tasks: list[asyncio.Task] = []
        self._stopped = False

    async def run(self) -> None:
        """Authorize the bot, open the updates stream and start the listen
        loop. Raises if the initial grant or connect fails; after that the SDK
        keeps the token fresh and reconnects on its own until stop()."""
        self._http = aiohttp.ClientSession()
        try:
            expires_in = await self._grant()
            if self.startup_commands is not None:
                await self.register_commands(self.startup_commands)
            if self.input_mode is not None:
                await self.set_input_mode(self.input_mode)
            self._stream = await self._connect()
        except BaseException:
            await self._http.close()
            raise

        self._tasks = [
            asyncio.create_task(self._regrant_loop(expires_in), name="botcomm-regrant"),
            asyncio.create_task(self._listen(), name="botcomm-listen"),
        ]

    async def stop(self) -> None:
        """Close the updates stream and stop the background tasks."""
        self._stopped = True
        for task in self._tasks:
            task.cancel()
        if self._stream is not None:
            self._stream.close()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        if self._http is not None:
            await self._http.close()

    async def send(self, session_id: str, content: str, silent: bool = False, *, subject: str = "", metadata: Optional[dict[str, Any]] = None, stream: bool = False) -> Message:
        """Post a message into a session and return it."""
        body = {
            "content": content,
            "stream": stream,
            "subject": subject,
            "metadata": metadata,
            "silent": silent,
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        return await self.send_message(session_id, body)

    async def broadcast(
        self,
        content: str,
        keyboard: Optional[list[KeyboardOption]] = None,
        silent: bool = False,
        *,
        subject: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> Broadcast:
        """Send one message to every session of the bot as a background job.
        Poll it with ``broadcast_status``."""
        body: dict = {"content": content, "subject": subject, "metadata": metadata, "silent": silent}
        if keyboard:
            body["keyboard"] = {"options": [o.to_json() for o in keyboard]}
        return Broadcast.from_json(await self._do("POST", f"/bot/{self.id}/broadcast", body))

    async def broadcast_status(self, broadcast_id: str) -> Broadcast:
        return Broadcast.from_json(await self._do("GET", f"/bot/{self.id}/broadcast/{broadcast_id}"))

    async def register_settings(self, fields: list[SettingField]) -> None:
        """Publish the per-session settings schema users see in the bot's profile."""
        await self._do("POST", f"/bot/{self.id}", {"settings": [f.to_json() for f in fields]})

    async def _send_message(self, session_id: str, message: dict) -> dict:
        body = {"ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), **message}
        return await self._do("POST", f"/session/{session_id}/message", body)

    async def send_message(self, session_id: str, message: dict) -> Message:
        """Send text, actions, attachments, or an agent card using one payload."""
        return Message.from_json(await self._send_message(session_id, message))

    async def start_stream(self, session_id: str) -> Message:
        return await self.send_message(session_id, {"stream": True})

    async def update_stream(self, session_id: str, message_id: str, content: str, sequence: int, status: str = "active") -> Message:
        """Send accumulated text at ~500ms intervals; finish with completed or failed."""
        body = {"content": content, "sequence": sequence, "status": status}
        return Message.from_json(await self._do("POST", f"/session/{session_id}/message/{message_id}/stream", body))

    async def react(self, session_id: str, message_id: str, emoji: str = "") -> Message:
        """Replace the bot's reaction; an empty emoji removes it."""
        return Message.from_json(await self._do("POST", f"/session/{session_id}/message/{message_id}/reaction", {"emoji": emoji}))

    async def update_message(self, session_id: str, message_id: str, change: dict) -> Message:
        return Message.from_json(await self._do("POST", f"/session/{session_id}/message/{message_id}", change))

    async def get_message(self, session_id: str, message_id: str) -> Message:
        return Message.from_json(await self._do("GET", f"/session/{session_id}/message/{message_id}"))

    async def send_card(self, session_id: str, card: dict) -> dict:
        """Send an agent card; returns the full message including card metadata."""
        return await self._send_message(session_id, {"card": card})

    async def update_card(self, session_id: str, message_id: str, change: dict) -> dict:
        """Update state using the last card revision; stale writes return 409."""
        return await self._do("POST", f"/session/{session_id}/message/{message_id}", {"card": change})

    async def get_card_message(self, session_id: str, message_id: str) -> dict:
        """Fetch card metadata or the structured fields of a form answer."""
        return await self._do("GET", f"/session/{session_id}/message/{message_id}")

    async def register_collections(self, fields: list[CollectionField]) -> None:
        await self._do("POST", f"/bot/{self.id}", {"collections": [f.to_json() for f in fields]})

    async def respond_collection(self, request: CollectionRequest, result: CollectionResult) -> None:
        await self._do(
            "POST",
            f"/session/{request.session_id}/collections/{request.key}/result/{request.id}",
            result.to_json(),
        )

    async def set_settings(self, session_id: str, values: dict[str, str]) -> SessionSettings:
        """Change settings on the user's behalf; returns the effective values."""
        return SessionSettings.from_json(await self._do("POST", f"/session/{session_id}/settings", values))

    async def send_keyboard(
        self, session_id: str, content: str, options: list[KeyboardOption], *, subject: str = "", metadata: Optional[dict[str, Any]] = None
    ) -> Message:
        """Post a message with one-tap answer options. The user's tap arrives
        on the ``messages`` queue as a message whose content is the chosen
        option's label, with ``reply_to`` set to the keyboard message's id and
        ``value`` to the option's value (a value matching a registered command
        lands on the ``commands`` queue instead)."""
        body = {
            "content": content,
            "keyboard": {"options": [opt.to_json() for opt in options]},
            "subject": subject,
            "metadata": metadata,
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        return await self.send_message(session_id, body)

    async def edit(
        self,
        session_id: str,
        message_id: str,
        content: Optional[str] = None,
        keyboard: Optional[list[KeyboardOption]] = None,
        *,
        subject: Optional[str] = None,
        metadata: dict[str, Any] | None | object = _UNSET,
    ) -> Message:
        """Change the content, subject or keyboard of a message the bot authored.
        An empty subject clears it; None leaves it unchanged.
        Metadata is a JSON object (up to 4096 bytes); None clears it, omission preserves it.
        Raises ``APIError`` 409 when the keyboard was already answered."""
        body: dict = {}
        if content is not None:
            body["content"] = content
        if metadata is not _UNSET:
            body["metadata"] = metadata
        if subject is not None:
            body["subject"] = subject
        if keyboard is not None:
            body["keyboard"] = {"options": [opt.to_json() for opt in keyboard]}
        return await self.update_message(session_id, message_id, body)

    async def delete(self, session_id: str, message_id: str) -> None:
        """Delete a message the bot authored."""
        await self._do("DELETE", f"/session/{session_id}/message/{message_id}")

    async def typing(self, session_id: str) -> None:
        """Show a typing indicator to the user for ~5s; re-post while working."""
        await self._do("POST", f"/session/{session_id}/typing")

    async def set_input_mode(self, mode: str) -> None:
        """Configure user input after successfully publishing commands."""
        await self._do("POST", f"/bot/{self.id}", {"inputMode": mode})

    async def set_online_status_visible(self, visible: bool) -> None:
        """Control whether apps show the bot's connection status."""
        await self._do("POST", f"/bot/{self.id}", {"onlineStatusVisible": visible})

    async def register_commands(self, commands: list[Command]) -> None:
        """Publish the bot commands to the API and route incoming messages
        whose content equals a command value to the ``commands`` queue."""
        await self._do("POST", f"/bot/{self.id}", {"commands": [c.to_json() for c in commands]})
        self._commands = {cmd.value: cmd for cmd in commands}

    async def sessions(self) -> list[Session]:
        """Fetch all sessions of the bot."""
        data = await self._do("GET", "/session") or []
        return [Session.from_json(item) for item in data]

    async def _grant(self) -> int:
        tk = await grant(self._http, self.client_id, self.client_secret)
        self._access_token = tk["access_token"]
        self.id = sub_from_token(tk["access_token"])
        return int(tk.get("expires_in", 0))

    async def _regrant_loop(self, expires_in: int) -> None:
        interval = regrant_interval(expires_in)
        while True:
            await asyncio.sleep(interval)
            try:
                expires_in = await self._grant()
            except Exception as e:  # noqa: BLE001 - keep retrying on any failure
                logger.error("failed to refresh access token: %s", e)
                interval = REGRANT_RETRY
                continue
            interval = regrant_interval(expires_in)

    async def _connect(self) -> aiohttp.ClientResponse:
        return await connect(self._http, self._access_token)

    async def _listen(self) -> None:
        while True:
            await self._backfill()

            stream = self._stream
            try:
                async for line in stream.content:
                    if not line.startswith(b"data:"):
                        continue
                    msg = await self._dispatch(line[5:].strip().decode())
                    if msg is not None:
                        asyncio.create_task(self._confirm_read(msg.session_id, msg.id))
            except Exception as e:  # noqa: BLE001
                if not self._stopped:
                    logger.warning("updates stream read failed: %s", e)
            finally:
                stream.close()

            if self._stopped:
                return

            while True:
                try:
                    self._stream = await self._connect()
                except Exception as e:  # noqa: BLE001
                    logger.warning("failed to reconnect: %s", e)
                    await asyncio.sleep(RECONNECT_DELAY)
                    continue
                logger.info("reconnected to the updates stream")
                break

    async def _dispatch(self, frame: str) -> Optional[Message]:
        """Parse one event payload and route it: "message" envelopes go to the
        messages or commands queue (returned for read confirmation),
        "new_session" invokes on_new_session."""
        try:
            env = json.loads(frame)
        except (ValueError, TypeError) as e:
            logger.warning("failed to unmarshal envelope: %s", e)
            return None

        env_type = env.get("type")
        data = env.get("data") or {}

        if env_type == "message":
            msg = Message.from_json(data)
            if msg.id in self._backfilled:
                # already delivered (and confirmed read) by the backfill
                self._backfilled.discard(msg.id)
                return None
            await self._route(msg)
            return msg

        if env_type == "reaction":
            try:
                self.reactions.put_nowait(Message.from_json(data))
            except asyncio.QueueFull:
                pass
            return None

        if env_type == "new_session":
            session = Session.from_json(data)
            if self.on_new_session is not None:
                result = self.on_new_session(session)
                if inspect.isawaitable(result):
                    asyncio.create_task(_await_callback(result))
            return None

        if env_type == "collection_request":
            try:
                self.collection_requests.put_nowait(CollectionRequest.from_json(data))
            except asyncio.QueueFull:
                pass
            return None

        if env_type == "settings":
            try:
                self.settings.put_nowait(SessionSettings.from_json(data))
            except asyncio.QueueFull:
                pass
            return None

        if env_type == "read":
            # the counterpart read one of the bot's messages: nothing to do here
            return None

        logger.warning("unknown envelope type %r", env_type)
        return None

    async def _route(self, msg: Message) -> None:
        """Deliver a message to the ``commands`` queue when its content (or,
        for keyboard answers, its machine value) matches a registered command
        value, to the ``messages`` queue otherwise."""
        key = msg.value or msg.content
        is_command = key in self._commands
        if self.argument_commands and not msg.value and not msg.reply_to:
            if is_command:
                msg.command = key
                msg.argument = ""
            else:
                command = re.split(r"[ \t\r\n]", msg.content, maxsplit=1)[0]
                definition = self._commands.get(command)
                if definition and definition.input is not None:
                    is_command = True
                    msg.command = command
                    msg.argument = msg.content[len(command):].strip(" \t\r\n")
        if is_command:
            await self.commands.put(msg)
        else:
            await self.messages.put(msg)

    async def _backfill(self) -> None:
        """Load the sessions and re-deliver messages that arrived while the
        bot was offline, oldest first, confirming each as read."""
        try:
            sessions = await self.sessions()
        except Exception as e:  # noqa: BLE001
            logger.error("failed to get sessions: %s", e)
            return

        delivered: set[str] = set()
        for session in sessions:
            if session.unread_count == 0:
                continue
            after = None
            while not self._stopped:
                try:
                    unread = await self._load_unread(session.id, after)
                except Exception as e:
                    logger.error("failed to load unread messages: %s", e)
                    break
                for msg in unread:
                    if msg.id in delivered:
                        continue
                    delivered.add(msg.id)
                    await self._route(msg)
                    await self._confirm_read(msg.session_id, msg.id)
                if len(unread) < 100:
                    break
                last = unread[-1]
                if after and after.id == last.id:
                    break
                after = last

        # remember what was just delivered so dispatch can drop a duplicate
        # that arrived over the stream while the backfill was running
        self._backfilled = delivered

    async def _load_unread(self, session_id: str, after: Optional[Message] = None) -> list[Message]:
        query = {"order": "asc"}
        if after:
            query.update(afterID=after.id, afterTS=after.create_ts.isoformat())
        data = await self._do("GET", f"/session/{session_id}/message/unread?{urlencode(query)}") or []
        return [Message.from_json(item) for item in data]

    async def _confirm_read(self, session_id: str, message_id: str) -> None:
        try:
            await self._do("POST", f"/session/{session_id}/message/{message_id}/read")
        except Exception as e:  # noqa: BLE001
            logger.error("failed to confirm message read: %s", e)

    async def _do(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        """Perform an authenticated JSON request against the API."""
        return await request(self._http, self._access_token, method, path, body)


async def _await_callback(result: Any) -> None:
    try:
        await result
    except Exception as e:  # noqa: BLE001
        logger.error("on_new_session callback failed: %s", e)
