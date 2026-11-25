import unittest
from botcomm.bot import Bot, KeyboardOption, Message


class SubjectMessages(unittest.IsolatedAsyncioTestCase):
    async def test_send_keyboard_broadcast_and_subject_only_edit(self):
        bot = Bot("id", "secret")
        requests = []

        async def request(method, path, body=None):
            requests.append(body)
            return body

        bot._do = request
        message = await bot.send("s1", "Sunny", subject="Weather")
        self.assertEqual(message.subject, "Weather")
        keyboard = await bot.send_keyboard("s1", "Sunny", [KeyboardOption("OK", "ok")], subject="Weather")
        self.assertEqual(keyboard.subject, "Weather")
        broadcast = await bot.broadcast("Sunny", subject="Weather")
        self.assertEqual(broadcast.subject, "Weather")
        await bot.edit("s1", "m1", subject="")
        self.assertEqual(requests[-1], {"subject": ""})
        self.assertEqual(Message.from_json({"content": "Legacy"}).subject, "")

    async def test_card_helpers_preserve_structured_payloads(self):
        bot = Bot("id", "secret")
        calls = []

        async def request(method, path, body=None):
            calls.append((method, path, body))
            return {"id": "m", "card": (body or {}).get("card"), "fields": {"targets": ["one"]}}

        bot._do = request
        card = {"kind": "plan", "title": "Deploy", "summary": "Production"}
        self.assertEqual((await bot.send_card("s1", card))["card"], card)
        await bot.update_card("s1", "m", {"revision": 1, "status": "running"})
        self.assertEqual(calls[-1][2]["card"]["revision"], 1)
        self.assertEqual((await bot.get_card_message("s1", "answer"))["fields"]["targets"], ["one"])
        self.assertEqual(calls[-1][:2], ("GET", "/session/s1/message/answer"))

    async def test_unified_messages_include_card_and_fields_without_another_fetch(self):
        bot = Bot("id", "secret")
        calls = []

        async def request(method, path, body=None):
            calls.append((method, path, body))
            return {"id": "m", "card": (body or {}).get("card"), "fields": {"targets": ["one"]}}

        bot._do = request
        result = await bot.send_message("s1", {"card": {"kind": "plan", "title": "Report"}})
        self.assertEqual(result.card["kind"], "plan")
        self.assertEqual(result.fields["targets"], ["one"])
        self.assertEqual(len(calls), 1)
        incoming = Message.from_json({"replyTo": "form", "fields": {"topic": "Weather"}})
        self.assertEqual(incoming.fields["topic"], "Weather")

    async def test_metadata_send_broadcast_and_edit_semantics(self):
        bot = Bot("id", "secret")
        calls = []

        async def request(method, path, body=None):
            calls.append(body)
            return body

        bot._do = request
        metadata = {"debug": [True, None, {"ms": 12}]}
        self.assertEqual((await bot.send("s", "Answer", metadata=metadata)).metadata, metadata)
        self.assertEqual((await bot.send_keyboard("s", "Choose", [], metadata=metadata)).metadata, metadata)
        self.assertEqual((await bot.broadcast("Answer", metadata=metadata)).metadata, metadata)
        await bot.edit("s", "m", content="Changed")
        self.assertNotIn("metadata", calls[-1])
        await bot.edit("s", "m", metadata={})
        self.assertEqual(calls[-1], {"metadata": {}})
        await bot.edit("s", "m", metadata=None)
        self.assertEqual(calls[-1], {"metadata": None})
        self.assertIsNone(Message.from_json({}).metadata)


class StreamingMessages(unittest.IsolatedAsyncioTestCase):
    async def test_stream_and_reaction_helpers(self):
        bot = Bot("id", "secret")
        requests = []

        async def request(method, path, body=None):
            requests.append((method, path, body))
            return {"id": "m", "stream": {"status": "active", "sequence": 0}, "reactions": {"user": "❤️"}, "reactionRevision": 2}

        bot._do = request
        message = await bot.start_stream("s")
        self.assertTrue(requests[-1][2]["stream"])
        self.assertEqual(message.reaction_revision, 2)
        await bot.update_stream("s", "m", "Hello", 1)
        self.assertEqual(requests[-1][2], {"content": "Hello", "sequence": 1, "status": "active"})
        await bot.react("s", "m", "❤️")
        self.assertEqual(requests[-1][1], "/session/s/message/m/reaction")
        await bot.react("s", "m")
        self.assertEqual(requests[-1][2]["emoji"], "")
