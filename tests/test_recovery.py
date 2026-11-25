import asyncio
import base64
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import unittest
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from botcomm import APIError, Message
from botcomm.bot import Bot, Message as LegacyMessage

FIXTURE = json.loads((Path(__file__).resolve().parents[1] / "testdata/recovery.json").read_text())


class RecoveryContract(unittest.IsolatedAsyncioTestCase):
    async def test_transport_preserves_authentication_retries_and_errors(self):
        self.assertIs(Message, LegacyMessage)
        token = "header." + base64.urlsafe_b64encode(b'{"sub":"bot"}').decode().rstrip("=") + ".signature"
        calls = []

        async def handle(request):
            if request.path == "/token":
                self.assertEqual(dict(await request.post()), {
                    "grant_type": "client_credentials", "client_id": "id", "client_secret": "secret",
                })
                return web.json_response({"access_token": token, "expires_in": 3600})
            self.assertEqual(request.headers["Authorization"], "Bearer " + token)
            if request.path == "/updates":
                self.assertEqual(request.headers["Accept"], "text/event-stream")
                return web.Response(text=": ping\n\n", content_type="text/event-stream")
            calls.append((request.method, request.path, await request.text()))
            if len(calls) == 1:
                return web.Response(status=429, headers={"Retry-After": "0"})
            if len(calls) == 2:
                return web.json_response({"id": "message"})
            if len(calls) == 3:
                return web.Response(status=204)
            return web.Response(status=403, text=" rejected ")

        app = web.Application()
        app.router.add_route("*", "/{path:.*}", handle)
        async with TestServer(app) as server, aiohttp.ClientSession() as http:
            host = str(server.make_url("")).rstrip("/")
            with patch("botcomm.auth.AUTH_HOST", host), patch("botcomm.transport.API_HOST", host):
                bot = Bot("id", "secret")
                bot._http = http
                self.assertEqual(await bot._grant(), 3600)
                self.assertEqual(bot.id, "bot")
                self.assertEqual(await bot._do("POST", "/session/s/message", {"content": "hello"}), {"id": "message"})
                self.assertEqual(calls[0], calls[1])
                self.assertIsNone(await bot._do("DELETE", "/session/s/message/m"))
                with self.assertRaises(APIError) as caught:
                    await bot._do("GET", "/forbidden")
                self.assertEqual((caught.exception.status, caught.exception.body), (403, "rejected"))
                stream = await bot._connect()
                try:
                    self.assertEqual(await stream.text(), ": ping\n\n")
                finally:
                    stream.close()

    async def test_all_pages_order_ack_and_dedup(self):
        bot = Bot("id", "secret")
        bot.messages = asyncio.Queue(256)
        bot.commands = asyncio.Queue(256)
        bot._commands["/help"] = object()
        reads = []

        async def request(method, path, body=None):
            url = urlparse(path)
            if url.path == "/session":
                return [{"id": "s", "unreadCount": 205}]
            if method == "POST":
                self.assertGreater(
                    bot.messages.qsize() + bot.commands.qsize(), len(reads), "ack before enqueue"
                )
                reads.append(url.path.split("/")[-2])
                return {}

            query = parse_qs(url.query)
            self.assertEqual(query["order"], ["asc"])
            after = query.get("afterID", [None])[0]
            start = next((i + 1 for i, m in enumerate(FIXTURE["messages"]) if m["id"] == after), 0)
            if after:
                self.assertIn("afterTS", query)
            return FIXTURE["messages"][start:start + 100]

        bot._do = request
        await bot._backfill()
        self.assertEqual(reads, [m["id"] for m in FIXTURE["messages"]])
        self.assertEqual(bot.commands.qsize(), 1)
        await bot._dispatch(json.dumps({"type": "message", "data": FIXTURE["messages"][-1]}))
        self.assertEqual(bot.messages.qsize(), 204)
