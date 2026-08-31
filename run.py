"""Local development runner & production entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

import uvicorn

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--bot", action="store_true", help="Run the Telegram bot (polling mode).")
    parser.add_argument("--api", action="store_true", help="Run the FastAPI API.")
    parser.add_argument(
        "--prod",
        action="store_true",
        help="Run in production mode: the bot is served via webhook by the API process.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload the API on code changes (development only, API only).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="API host (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8000, help="API port (default: 8000).")
    args = parser.parse_args()

    if args.prod:
        if args.reload:
            parser.error("--reload cannot be combined with --prod.")
        if args.bot:
            parser.error("--bot cannot be combined with --prod; the bot is served via webhook automatically.")
    elif args.reload:
        if args.bot:
            parser.error("--reload only supports the API; drop --bot or run without --reload.")
        args.api = True
    elif not args.bot and not args.api:
        # Default: run both when nothing was explicitly requested.
        args.bot = args.api = True

    return args


async def run_prod(args: argparse.Namespace) -> None:
    """Production mode: register the bot webhook, then serve the API in the current event loop."""
    from config import WEBHOOK_SECRET, WEBHOOK_URL
    from telegram.bot import bot
    from telegram.dispatcher import setup_dispatcher

    if not WEBHOOK_URL:
        raise RuntimeError("WEBHOOK_URL must be set in the environment to run with --prod.")

    await setup_dispatcher()
    await bot.set_webhook(WEBHOOK_URL, secret_token=WEBHOOK_SECRET)

    from main import app

    config = uvicorn.Config(app, host=args.host, port=args.port)
    server = uvicorn.Server(config)
    await server.serve()


async def run_bot_managed(stop_event: asyncio.Event) -> None:
    """Run the bot in polling mode until stop_event is set."""
    from telegram.bot import bot
    from telegram.dispatcher import dp, setup_dispatcher

    await bot.delete_webhook(drop_pending_updates=False)
    await setup_dispatcher()
    logger.info("Bot is running in polling mode.")

    polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    await stop_event.wait()
    await dp.stop_polling()
    await polling_task


async def run_api_managed(args: argparse.Namespace, stop_event: asyncio.Event) -> None:
    """Run the API until stop_event is set."""
    from main import app

    config = uvicorn.Config(app, host=args.host, port=args.port)
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())
    await stop_event.wait()
    server.should_exit = True
    await serve_task


async def run(args: argparse.Namespace) -> None:
    from core.database import init_database

    await init_database()

    if args.prod:
        await run_prod(args)
        return

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    async with asyncio.TaskGroup() as tg:
        if args.bot:
            tg.create_task(run_bot_managed(stop_event))
        if args.api:
            tg.create_task(run_api_managed(args, stop_event))


async def run_and_cleanup(args: argparse.Namespace) -> None:
    """Run the app, then always close the shared DB client afterwards."""
    try:
        await run(args)
    finally:
        from core.database import client

        await client.close()


def main() -> None:
    args = parse_args()

    if args.reload:
        # uvicorn's reload mode manages its own subprocess/event loop, so it
        # cannot share a loop with the bot/API tasks above — run it standalone.
        uvicorn.run("main:app", host=args.host, port=args.port, reload=True)
    else:
        asyncio.run(run_and_cleanup(args))


if __name__ == "__main__":
    main()
