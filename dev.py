"""Local development runner."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

import uvicorn

logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--bot", action="store_true", help="Run the Telegram bot (polling mode)")
parser.add_argument("--api", action="store_true", help="Run the FastAPI API")
parser.add_argument("--host", default="127.0.0.1", help="API host (default: 127.0.0.1)")
parser.add_argument("--port", type=int, default=8000, help="API port (default: 8000)")
parser.add_argument("--reload", action="store_true", help="Auto-reload the API on code changes.")
args = parser.parse_args()

if not args.bot and not args.api:
    if args.reload:
        logger.warning("--reload is enabled. The bot will be disabled; only the API will run.")
        args.bot, args.api = False, True

    else:
        args.bot = args.api = True


async def run() -> None:
    from app.database import init_database

    await init_database()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    async def run_bot_managed() -> None:
        from app.bot import bot, dp, init_bot

        await bot.delete_webhook(drop_pending_updates=False)
        await init_bot()
        logger.info("Bot is running in polling mode")
        polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
        await stop_event.wait()
        await dp.stop_polling()
        await polling_task

    async def run_api_managed() -> None:
        from main import app

        config = uvicorn.Config(app, host=args.host, port=args.port)
        server = uvicorn.Server(config)
        serve_task = asyncio.create_task(server.serve())
        await stop_event.wait()
        server.should_exit = True
        await serve_task

    async with asyncio.TaskGroup() as tg:
        if args.bot:
            tg.create_task(run_bot_managed())
        if args.api:
            tg.create_task(run_api_managed())


if __name__ == "__main__":
    if args.reload:
        if args.bot:
            parser.error("--reload only supports the API; drop --bot or run without --reload.")
        # uvicorn.run() manages its own subprocess/event loop for reload, so it
        # can't share a loop with the bot task above — run it standalone.
        uvicorn.run("main:app", host=args.host, port=args.port, reload=True)
    else:
        asyncio.run(run())
