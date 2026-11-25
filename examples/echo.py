"""A minimal BotComm bot that echoes every message back to the sender.

Configuration (environment):

    CLIENT_ID     - bot client id (shown once on bot creation)
    CLIENT_SECRET - bot client secret (shown once on bot creation)
"""

import asyncio
import logging
import os
import signal

from botcomm import Bot, Command, SettingField


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    client_id = os.environ.get("CLIENT_ID", "")
    client_secret = os.environ.get("CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise SystemExit("CLIENT_ID and CLIENT_SECRET are required")

    bot = Bot(client_id, client_secret)
    bot.input_mode = "messages"

    async def greet(session):
        logging.info("new session %s", session.id)
        await bot.send(session.id, "Hello! I repeat everything you say.")

    bot.on_new_session = greet

    await bot.run()
    await bot.register_commands([Command("Ping", "/ping", "Check the bot is alive")])
    await bot.register_settings([SettingField("shout", "Shout replies", "toggle", default="false")])
    logging.info("echo bot %s is running", bot.id)

    async def echo_messages():
        while True:
            msg = await bot.messages.get()
            await bot.typing(msg.session_id)
            sent = await bot.send(msg.session_id, msg.content)
            logging.info("echoed as %s", sent.id)

    async def echo_commands():
        while True:
            msg = await bot.commands.get()
            if msg.content == "/ping":
                await bot.send(msg.session_id, "pong")
            else:
                await bot.send(msg.session_id, "command received: " + msg.content)

    async def watch_settings():
        while True:
            change = await bot.settings.get()
            logging.info("settings of %s: %s", change.session_id, change.settings)

    workers = [
        asyncio.create_task(echo_messages()),
        asyncio.create_task(echo_commands()),
        asyncio.create_task(watch_settings()),
    ]

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    for task in workers:
        task.cancel()
    await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
