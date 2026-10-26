from telegram import ReplyKeyboardRemove, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import format as F
from ..api_client import BackendError
from ..keyboards import main_menu, phone_contacts
from ..messages import reply_html


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from ..config import DEMO_MODE
    context.user_data.clear()
    notice = "<b>DEMO: catalogo sintetico, strutture fittizie. Non usare per cercare assistenza sanitaria.</b>\n\n" if DEMO_MODE else ""
    await update.message.reply_text(notice + F.MSG_WELCOME, parse_mode=ParseMode.HTML, reply_markup=main_menu())
    await update.message.reply_text("📞 Numeri utili: tocca un pulsante per vedere il numero da comporre nell’app Telefono.",
                                    reply_markup=phone_contacts())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = ("<b>Come funziona</b>\n1. Scrivi cosa ti serve o usa un pulsante.\n2. Conferma la categoria proposta o scegli il tipo di struttura, poi invia la posizione.\n3. Ti mostro 3 strutture con viaggio e attesa osservata separati.\n"
           "Comandi: /ps /cdc /farmacia /rete /info /copertura\n\n" + F.MSG_112 + "\n\n" + F.MSG_116117)
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=main_menu())
    await update.message.reply_text("📞 Mostra il numero del servizio da chiamare:", reply_markup=phone_contacts())


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    api = context.bot_data["api"]
    try:
        src = await api.sources()
    except BackendError as ex:
        await update.message.reply_text("Il servizio dati non risponde, riprova tra poco.")
        return
    await reply_html(update.message, F.info_message(src), disable_web_page_preview=True, reply_markup=phone_contacts())


async def rete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    api = context.bot_data["api"]
    try:
        live = await api.ps_live()
    except BackendError as ex:
        await update.message.reply_text("Il servizio dati non risponde, riprova tra poco.")
        return
    await reply_html(update.message, F.rete_message(live), reply_markup=phone_contacts())


async def copertura(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        report = await context.bot_data['api'].coverage()
    except BackendError:
        await update.message.reply_text('Il servizio dati non risponde, riprova tra poco.')
        return
    await reply_html(update.message, F.coverage_message(report), disable_web_page_preview=True)


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text("Ok, mi fermo. Ho dimenticato posizione e richiesta. Scrivi /start quando vuoi ricominciare.\n"
                                    "Emergenza → 112 · consiglio → 116117", reply_markup=ReplyKeyboardRemove())


async def privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from ..config import LOCATION_TTL_S
    await update.message.reply_text(
        "Uso dei dati: Telegram riceve i messaggi e la posizione che invii. "
        "Quando l’AI è abilitata, il testo libero passa anche al provider configurato dal gestore "
        "(Anthropic o Groq). I pulsanti di ricerca non richiedono questa interpretazione. "
        "La posizione viene inviata al backend per cercare le strutture; non al parser AI. "
        "Il bot non conserva il testo originale nella sessione. Posizione, categoria e risultati "
        f"vengono cancellati dalla memoria alla scadenza della sessione ({LOCATION_TTL_S // 60} minuti "
        "dall’ultima richiesta o posizione), entro un ulteriore minuto. "
        "/stop cancella subito la sessione del bot; non elimina la cronologia Telegram né i dati "
        "eventualmente trattati dai provider. Non inviare nomi, referti o altri identificativi."
    )
