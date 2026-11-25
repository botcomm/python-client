import unittest

from botcomm import Bot, Command, CommandInput, Message


class InputModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_online_status_visibility(self):
        bot = Bot("id", "secret")
        bot.id = "bot"
        calls = []

        async def request(*args):
            calls.append(args)

        bot._do = request
        for visible in (True, False):
            await bot.set_online_status_visible(visible)
        self.assertEqual(calls, [
            ("POST", "/bot/bot", {"onlineStatusVisible": True}),
            ("POST", "/bot/bot", {"onlineStatusVisible": False}),
        ])

        async def fail(*args):
            raise RuntimeError("update failed")

        bot._do = fail
        with self.assertRaisesRegex(RuntimeError, "update failed"):
            await bot.set_online_status_visible(True)

    async def test_argument_routing_is_opt_in(self):
        for enabled in (False, True):
            for content, value, reply_to, command, argument, exact in [
                ("/now", "", "", "/now", "", True),
                ("/city", "", "", "/city", "", True),
                ("/city \tNew  York 🙂\r\n", "", "", "/city", "New  York 🙂", False),
                ("/citywrong Warsaw", "", "", "", "", False),
                ("/now args", "", "", "", "", False),
                ("Label", "/now", "keyboard", "", "", True),
                ("Label", "/city Warsaw", "keyboard", "", "", False),
                ("/city Warsaw", "", "keyboard", "", "", False),
            ]:
                bot = Bot("id", "secret")
                bot.argument_commands = enabled
                bot._commands = {
                    "/now": Command("Now", "/now"),
                    "/city": Command("City", "/city", input=CommandInput()),
                }
                msg = Message("m", "s", "u", content, value=value, reply_to=reply_to)
                await bot._route(msg)
                self.assertEqual(bot.commands.qsize(), int(exact or bool(enabled and command)))
                self.assertEqual(msg.content, content)
                self.assertEqual(msg.command, command if enabled else "")
                self.assertEqual(msg.argument, argument if enabled else "")

    async def test_failed_registration_keeps_previous_commands(self):
        bot = Bot("id", "secret")
        bot._commands = {"/now": Command("Now", "/now")}

        async def fail(*args):
            raise RuntimeError("registration failed")

        bot._do = fail
        with self.assertRaises(RuntimeError):
            await bot.register_commands([Command("City", "/city", input=CommandInput(required=True))])
        self.assertEqual(list(bot._commands), ["/now"])

    async def test_backfill_routes_arguments(self):
        bot = Bot("id", "secret")
        bot.argument_commands = True
        bot._commands = {"/city": Command("City", "/city", input=CommandInput())}

        async def request(method, path, body=None):
            if path == "/session":
                return [{"id": "s", "unreadCount": 1}]
            if method == "GET":
                return [{
                    "id": "m",
                    "sessionID": "s",
                    "content": "/city New York",
                    "createTS": "2026-01-01T00:00:00Z",
                }]
            return {}

        bot._do = request
        await bot._backfill()
        self.assertEqual((await bot.commands.get()).argument, "New York")
