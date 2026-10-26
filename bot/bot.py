"""LazioFlow — bot Telegram (python-telegram-bot v22, polling). Avvio:
    uvicorn backend.app.main:app --port 8000     # in un altro terminale
    python3 -m bot.bot
Il bot non contiene logica sanitaria: parse, safety e ranking sono nel backend."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import sys

from telegram import BotCommand, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, TypeHandler, filters

from .api_client import Api
from .config import BACKEND_URL, TELEGRAM_TOKEN
from .handlers.callbacks import on_callback, quick_cmd
from .handlers.location import on_location
from .handlers.start import copertura, help_cmd, info, privacy, rete, start, stop
from .handlers.text import on_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("lazioflow.bot")


async def on_error(update: object, context) -> None:
    log.exception("errore handler: %s", context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Si è verificato un errore. Riprova, oppure: emergenza → 112, consiglio non urgente → 116117.")


COMMANDS = [("privacy", "Uso dei dati"), ("start", "Ricomincia"), ("help", "Come funziona"), ("ps", "Pronto Soccorso vicini"), ("cdc", "Casa della Comunità vicina"),
            ("farmacia", "Farmacia vicina"), ("rete", "Pressione sulla rete PS"), ("info", "Fonti e limiti"), ("copertura", "Dati nelle cinque province"), ("stop", "Ferma e dimentica")]


async def _expire_before_update(update: Update, context) -> None:
    from .state import expire_session
    if context.user_data is not None:
        expire_session(context.user_data)


async def _sweep_sessions(app: Application) -> None:
    from .state import expire_session
    while True:
        await asyncio.sleep(60)
        for user_id, data in list(app.user_data.items()):
            if expire_session(data) or not data:
                app.drop_user_data(user_id)


async def _post_shutdown(app: Application) -> None:
    task = app.bot_data.pop("session_cleanup", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _post_init(app: Application) -> None:
    app.bot_data["session_cleanup"] = asyncio.create_task(_sweep_sessions(app))
    await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])
    me = await app.bot.get_me()
    log.info("bot attivo: @%s", me.username)


def build(token: str, api: Api | None = None) -> Application:
    app = Application.builder().token(token).post_init(_post_init).post_shutdown(_post_shutdown).build()
    app.bot_data["api"] = api or Api()
    app.add_handler(TypeHandler(Update, _expire_before_update), group=-1)
    app.add_handler(CommandHandler("privacy", privacy))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler(["stop", "annulla"], stop))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("copertura", copertura))
    app.add_handler(CommandHandler("rete", rete))
    app.add_handler(CommandHandler(["ps", "cdc", "farmacia"], quick_cmd))
    app.add_handler(MessageHandler(filters.LOCATION, on_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    if not TELEGRAM_TOKEN:
        print("TELEGRAM_TOKEN mancante: copia .env.example in .env e inserisci il token del bot.", file=sys.stderr)
        sys.exit(1)
    log.info("backend: %s", BACKEND_URL)
    build(TELEGRAM_TOKEN).run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
