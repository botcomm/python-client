import json
import unittest

from botcomm import Bot, CollectionField, CollectionItem, CollectionResult


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_collection_does_not_enter_chat(self):
        bot = Bot("id", "secret")
        await bot._dispatch(json.dumps({
            "type": "collection_request",
            "data": {
                "id": "r",
                "sessionID": "s",
                "key": "channels",
                "action": "remove",
                "itemID": "1",
                "revision": 4,
                "expiresTS": "2026-10-09T20:00:00Z",
            },
        }))
        request = bot.collection_requests.get_nowait()
        self.assertEqual(request.item_id, "1")
        self.assertEqual(request.revision, 4)
        self.assertTrue(bot.messages.empty())
        self.assertTrue(bot.commands.empty())
        calls = []

        async def record(*args):
            calls.append(args)

        bot._do = record
        result = CollectionResult([CollectionItem("1", "News")], revision=4)
        await bot.respond_collection(request, result)
        self.assertEqual(calls[0], ("POST", "/session/s/collections/channels/result/r", result.to_json()))
        await bot.register_collections([CollectionField("channels", "Channels", 20)])
        self.assertEqual(calls[1][2]["collections"][0]["maxItems"], 20)
