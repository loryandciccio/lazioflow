"""Pulsanti inline: scelta esplicita del tipo, preset, alternative, aggiorna, perché."""
from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import format as F
from .. import keyboards as K
from ..api_client import BackendError
from ..messages import reply_html
from ..state import TYPE_TO_CATEGORY, category_for_explicit_type, location, set_request
from .contacts import CONTACTS, send_phone_contact
from .location import run_recommend


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None:
        return
    ud = context.user_data
    api = context.bot_data["api"]
    data = q.data or ""
    await q.answer()
    if q.message is None or not callable(getattr(q.message, "reply_text", None)):
        return
    if data.startswith("call:"):
        number = data.split(":", 1)[1]
        if number in CONTACTS:
            await send_phone_contact(q.message, number)
        return
    if data in ("confirmcat", "wrongcat"):
        if not ud.get("pending_confirmation") or getattr(q.message, "message_id", None) != ud.get("confirmation_message_id"):
            await q.message.reply_text("Questa conferma non è più attiva. Usa il messaggio più recente.")
            return
        ud.pop("pending_confirmation", None)
        ud.pop("confirmation_message_id", None)
        if data == "confirmcat":
            loc = location(ud)
            if loc:
                await run_recommend(q.message, context, *loc)
            else:
                await q.message.reply_text("📍 Inviami la posizione.", reply_markup=K.ask_location())
            return
    if data.startswith("type:"):
        if ud.get("pending_confirmation") or not ud.get("category"):
            await q.message.reply_text("Usa la scelta attiva o ricomincia dal menu.")
            return
        ftype = data.split(":", 1)[1]
        if ftype not in TYPE_TO_CATEGORY:
            await q.message.reply_text("Scelta non disponibile. Seleziona un tipo di struttura:", reply_markup=K.service_type())
            return
        try:
            cats = {c["id"]: c for c in (await api._get("/categories"))["categories"]}
        except BackendError:
            await q.message.reply_text("Il servizio dati non risponde, riprova tra poco. Emergenza → 112 · consiglio → 116117.",
                                        reply_markup=K.phone_contacts())
            return
        cat = category_for_explicit_type(ud, ftype, cats)
        set_request(ud, cat, ftype, ud.get("age_group", "unknown"), ud.get("last_text", ""), explicit_type=True)
        loc = location(ud)
        if loc:
            await run_recommend(q.message, context, *loc)
        else:
            await q.message.reply_text("📍 Inviami la posizione.", reply_markup=K.ask_location())
        return
    if data.startswith("pref:") and data.split(":", 1)[1] not in K.PRESET_LABEL:
        await q.message.reply_text("Preferenza non disponibile. Usa i pulsanti dell'ultimo risultato.")
        return
    if data.startswith("pref:") or data in ("refresh", "alt", "why"):
        if not ud.get("last_result") or not ud.get("facility_type"):
            await q.message.reply_text("Questa ricerca non è più attiva. Scegli cosa cercare dal menu.", reply_markup=K.main_menu())
            return
        if (ud.get("result_message_id") is not None and
                getattr(q.message, "message_id", None) != ud["result_message_id"]):
            await q.message.reply_text("Usa i pulsanti dell'ultimo risultato: questa ricerca è stata aggiornata.")
            return
    if data == "wrongcat":
        set_request(ud, "UNKNOWN", None, ud.get("age_group", "unknown"), ud.get("last_text", ""))
        await q.message.reply_text("Ok, annullo la categoria proposta. Scegli il tipo di struttura oppure scrivi una descrizione più precisa:", reply_markup=K.service_type())
        return
    if data.startswith("pref:"):
        ud["preference"] = data.split(":", 1)[1]
        loc = location(ud)
        if loc and ud.get("category"):
            await run_recommend(q.message, context, *loc, edit=True)
        else:
            await q.message.reply_text("📍 Inviami la posizione.", reply_markup=K.ask_location())
        return
    if data in ("refresh", "alt"):
        loc = location(ud)
        if not loc or not ud.get("category"):
            await q.message.reply_text("La posizione è scaduta: inviamela di nuovo.", reply_markup=K.ask_location())
            return
        await run_recommend(q.message, context, *loc, offset=3 if data == "alt" else 0, edit=(data == "refresh"))
        return
    if data == "why":
        res, recs = ud.get("last_result"), ud.get("last_recs")
        if not recs:
            await q.message.reply_text("Non ho ancora un risultato da spiegare.")
            return
        expl = None
        try:
            expl = await api.explain("", recs)
        except BackendError:
            pass
        await reply_html(q.message, F.why_message(res, recs, expl), disable_web_page_preview=True, reply_markup=K.phone_contacts())
        return


async def quick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ps /cdc /farmacia: ricerca diretta."""
    cmd = (update.message.text or "").split()[0].lstrip("/").split("@")[0]
    mapping = {"ps": ("PROBLEMA_GENERICO_NON_URGENTE", "emergency_room"), "cdc": ("ASSISTENZA_TERRITORIALE", "community_house"),
               "farmacia": ("FARMACIA", "pharmacy")}
    cat, ftype = mapping[cmd]
    set_request(context.user_data, cat, ftype, "unknown", update.message.text, explicit_type=True)
    loc = location(context.user_data)
    if loc:
        await run_recommend(update.message, context, *loc)
    else:
        await update.message.reply_text("📍 Inviami la posizione.", reply_markup=K.ask_location())
