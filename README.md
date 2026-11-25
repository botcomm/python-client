# BotComm Python SDK

The official Python SDK for building [BotComm](https://botcomm.app) bots: client-credentials auth with automatic re-grant, a resilient SSE stream from `/updates`, back-fill of unread messages on every (re)connect, and command routing.

Requires Python 3.10+. The only dependency is `aiohttp`.

## Quickstart

Create a bot in the [BotComm console](https://web.botcomm.app/console/bots) and save its credentials. In the same terminal where you'll run the bot, set:

```sh
export CLIENT_ID='your-client-id'
export CLIENT_SECRET='your-client-secret'
```

Create a virtual environment and install the SDK:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install botcomm
```

Save this as `echo.py`:

```python
import asyncio
import os

from botcomm import Bot


async def main():
    bot = Bot(os.environ["CLIENT_ID"], os.environ["CLIENT_SECRET"])
    bot.input_mode = "messages"
    try:
        await bot.run()
        while True:
            msg = await bot.messages.get()
            await bot.send(msg.session_id, msg.content)
    finally:
        await bot.stop()


asyncio.run(main())
```

Run `python echo.py`, open your bot’s chat in BotComm, and send `hello`. The bot should reply with `hello`.

The [full echo example](https://github.com/botcomm/python-client/blob/HEAD/examples/echo.py) also handles commands and settings.

## Source layout

`botcomm/bot.py` contains the bot lifecycle, API methods, event routing and unread recovery.
Models and their JSON serialization live in `message.py`, `command.py`, `session.py`,
`collection.py` and `broadcast.py`. `auth.py`, `transport.py` and `errors.py` handle
authentication, HTTP connections and errors. Existing imports from `botcomm` and
`botcomm.bot` remain supported.

## Subjects

```python
await bot.send(session_id, "Your deployment finished!", subject="Deployment")
await bot.edit(session_id, message_id, subject="")  # clear the subject
```

Subjects are optional single-line plain text, up to 256 Unicode characters. Omit `subject` during an edit to preserve it. `send_keyboard` and `broadcast` also accept the `subject` keyword.

## API

Writes are rate limited per session and per bot; a `429` is retried once after the server's `Retry-After`, then raised as `APIError`.

- `Bot(client_id, client_secret)` — construct.
- `await bot.run()` — grant + connect + listen; the SDK re-grants ~1 min before token expiry and reconnects every 5s after a drop.
- `await bot.stop()` — close the stream and stop background tasks.
- `await bot.send(session_id, content, silent=False, subject="")` — post a message into a session; returns the created `Message`.
- `await bot.broadcast(content, keyboard=None, silent=False, subject="")` — one message to each connected account’s oldest chat as a background job; returns a `Broadcast` with `total`/`sent`/`failed`/`done`, poll it with `await bot.broadcast_status(id)`.
- `await bot.register_settings([SettingField(key, label, type, description, options, default)])` — publish a per-session settings form (`toggle`, `select`, `text`, `time`); users edit it in chat settings. Values arrive on every `Session.settings` (defaults filled) and, on change, as `SessionSettings` on `bot.settings`; `await bot.set_settings(session_id, {key: value})` changes them for the user.
- `await bot.send_keyboard(session_id, content, options)` — post a message with one-tap answer options, see [Keyboards](#keyboards); returns the created `Message`.
- `await bot.edit(session_id, message_id, content=None, keyboard=None)` — change a message the bot sent (progressive replies, status updates); returns the updated `Message` with `edit_ts`. An already answered keyboard cannot be replaced (`APIError` 409).
- `await bot.delete(session_id, message_id)` — delete a message the bot sent.
- `await bot.typing(session_id)` — show a typing indicator for ~5s; call it every 3-4s while working on a reply.
- `await bot.register_commands([Command(name, value, description)])` — publish commands; incoming messages whose content equals a command value land on `bot.commands` instead of `bot.messages`.
- `await bot.sessions()` — all sessions of the bot, each with `user` (`id`, `name`, `timezone`, `locale`), `settings` and `muted`.
- `bot.messages` / `bot.commands` — `asyncio.Queue[Message]` of incoming traffic; every delivered message is confirmed read automatically.
- `bot.settings` — `asyncio.Queue[SessionSettings]` of settings changes.
- `bot.on_new_session` — callback (sync or async) invoked when a user opens a chat with the bot.
- `bot.id` — the bot ID, resolved from the access token after `run()`.

## Keyboards

Offer one-tap answers by attaching a keyboard to a message:

```python
from botcomm import KeyboardOption

await bot.send_keyboard(msg.session_id, "Deploy to production?", [
    KeyboardOption(label="Yes", value="deploy"),
    KeyboardOption(label="No", value="cancel"),
])

answer = await bot.messages.get()
if answer.reply_to:
    print("user chose", answer.value)  # answer.content carries the label
```

The tap arrives as a regular message whose `content` is the chosen option's `label`, with `reply_to` set to the keyboard message's id and `value` to the option's machine value; a `value` matching a registered command lands on `bot.commands` instead. The server stamps `keyboard.selected` on the original message once answered.


## Commands-only input

```python
from botcomm import Bot, Command, CommandInput

bot = Bot(client_id, client_secret)
bot.argument_commands = True
bot.startup_commands = [Command("Set city", "/city", input=CommandInput(
    label="City", placeholder="Warsaw", required=True,
))]
bot.input_mode = "commands"
await bot.run()
msg = await bot.commands.get()
# msg.command == "/city", msg.argument == "New York"
# msg.content remains "/city New York".
```

`await bot.set_input_mode("messages")` enables ordinary messages. Publish startup
commands before running so recovery and live traffic route identically.


## Online status visibility

After `await bot.run()`, use `await bot.set_online_status_visible(True)` to show the bot's online/offline indicator in the web and iOS apps, or `False` to hide it. The setting defaults to hidden and persists between restarts. API failures raise an exception.

## Receive-only mode and collections

Use input mode `none` for a receive-only chat. The composer is hidden. Users can still answer buttons, respond to cards, react to messages, and change session settings. Publish native session collections with `register_collections`, the `collection_requests` queue, and `respond_collection`. Register the schema before enabling `none`. Persist and atomically compare/increment list revisions on mutations, reject expired requests, and return results outside chat history.

## Streaming replies and reactions

```python
message = await bot.start_stream(session_id)
await bot.update_stream(session_id, message.id, "Hello", 1)
await bot.update_stream(session_id, message.id, "Hello world", 2, "completed")
await bot.react(session_id, message.id, "❤️")
reaction = await bot.reactions.get()
```

Batch accumulated text about every 500ms with increasing sequence numbers; identical retries are safe. Finish with `completed` or `failed`, retaining partial text on failure. Send unchanged heartbeats while waiting for a provider: idle streams expire after two minutes. `send(..., stream=True)` and `send_message(..., {"stream": True})` also create live messages. An empty emoji removes the bot's reaction. The bounded reactions queue contains live message snapshots; fetch messages after reconnect to reconcile older reactions.


## Agent cards

Use `await bot.send_message(session_id, {"card": card})` and
`await bot.update_message(session_id, message_id, {"card": change})`. Cards
are dictionaries using the camelCase JSON field names below.

| Kind | Initial status | Other statuses |
|---|---|---|
| `plan` | `queued` | `running`, `waiting`, `completed`, `failed`, `cancelled` |
| `approval` | `pending` | `approved`, `rejected`, `expired`, `cancelled` |
| `form` | `pending` | `submitted`, `expired`, `cancelled` |
| `artifact` | `completed` | None; immutable |

The server sets the initial status and revision. Plan updates require
the latest `revision` and a status other than `queued`; completed, failed and
cancelled plans cannot be reopened. Stale revisions return 409. Approval/form
updates only cancel pending, unexpired requests; answers and expiration determine
their other statuses. Artifact cards cannot be updated.

An artifact requires an HTTP(S) `url` without credentials and may include
`parentID`, the message ID of an existing plan from the same bot in the same chat.

`sourceID` is different: only plans accept it, pointing to an approved approval
or submitted form from the same bot and chat. Each source permits one plan.
The server sets `planID` on that source; never supply `planID` yourself.
Links cannot be edited, and linking cards does not execute work.

A plan can contain up to 50 tasks. Updating its task list replaces the full list.
