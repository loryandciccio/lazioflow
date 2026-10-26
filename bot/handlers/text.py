"""Testo libero e pulsanti della tastiera principale."""
from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import format as F
from .. import keyboards as K
from ..api_client import BackendError
from ..state import GENERIC_CATEGORY, clear_request, decide, has_request, location, set_request
from .location import run_recommend
from .contacts import send_phone_contact

PROMPT_LOCATION = "📍 Inviami la posizione."
PROMPT_TYPE = "Cosa cerco? Scegli tu:"


async def _ask_location_or_go(update: Update, context: ContextTypes.DEFAULT_TYPE, intro: str = "", confirm: bool = False) -> None:
    loc = location(context.user_data)
    if confirm:
        context.user_data["pending_confirmation"] = True
    if intro:
        sent = await update.message.reply_text(intro, parse_mode=ParseMode.HTML, reply_markup=K.confirm_category() if confirm else None)
        if confirm:
            context.user_data["confirmation_message_id"] = sent.message_id
            return
    if loc:
        await run_recommend(update.message, context, *loc)
    else:
        await update.message.reply_text(PROMPT_LOCATION, reply_markup=K.ask_location())


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    ud = context.user_data
    api = context.bot_data["api"]
    # ---- pulsanti: percorso sicuro, senza LLM
    if text == K.BTN_EMERGENZA:
        clear_request(ud)
        await update.message.reply_text(F.MSG_112, parse_mode=ParseMode.HTML, reply_markup=K.main_menu())
        await send_phone_contact(update.message, "112")
        return
    if text == K.BTN_NON_URGENTE:
        set_request(ud, GENERIC_CATEGORY, None, "unknown", text)
        await update.message.reply_text(F.MSG_116117 + "\n\nOppure ti mostro le strutture vicine:",
                                        parse_mode=ParseMode.HTML, reply_markup=K.service_type())
        await send_phone_contact(update.message, "116117")
        return
    if text == K.BTN_PS:
        set_request(ud, GENERIC_CATEGORY, "emergency_room", "unknown", text, explicit_type=True)
        await _ask_location_or_go(update, context, "🏥 PS vicini, con viaggio stimato e attese osservate. Per filtrare per reparto scrivimi prima il problema (es. <i>storta</i>).")
        return
    if text == K.BTN_CDC:
        set_request(ud, "ASSISTENZA_TERRITORIALE", "community_house", "unknown", text, explicit_type=True)
        await _ask_location_or_go(update, context)
        return
    if text == K.BTN_FARMACIA:
        set_request(ud, "FARMACIA", "pharmacy", "unknown", text, explicit_type=True)
        await _ask_location_or_go(update, context)
        return
    if text == K.BTN_VISITA:
        set_request(ud, "ASSISTENZA_TERRITORIALE", "community_house", "unknown", text)
        await update.message.reply_text(F.MSG_VISITA, parse_mode=ParseMode.HTML, reply_markup=K.service_type(include_ps=False, include_pharmacy=False))
        return
    if text == K.BTN_NONSO:
        set_request(ud, "UNKNOWN")
        await update.message.reply_text(F.MSG_116117 + "\n\nOppure dimmi in una frase cosa succede, o scegli:",
                                        parse_mode=ParseMode.HTML, reply_markup=K.service_type())
        await send_phone_contact(update.message, "116117")
        return
    if text == K.BTN_MENU:
        clear_request(ud)
        await update.message.reply_text("Menu principale.", reply_markup=K.main_menu())
        return
    # ---- testo libero: parse + safety nel backend (il safety layer gira sul testo originale)
    presel = ud.get("facility_type") if (has_request(ud) and ud.get("explicit_type")) else None
    # Un errore sulla nuova richiesta non deve lasciare attiva quella precedente.
    clear_request(ud)
    try:
        und = await api.understand(text)
        # Le uscite di sicurezza sono già complete: non dipendono dal catalogo.
        cats = ({c["id"]: c for c in (await api._get("/categories"))["categories"]}
                if und["next_step"] == "ROUTE" else {})
    except BackendError:
        await update.message.reply_text("Il servizio dati non risponde, riprova tra poco.\nEmergenza → 112 · consiglio → 116117.",
                                        reply_markup=K.main_menu())
        return
    d = decide(und, cats, preselected_type=presel, have_location=location(ud) is not None)
    if d.action == "SHOW_112":
        clear_request(ud)
        await update.message.reply_text(F.e(d.safety_message) + "\n\n" + F.MSG_112, parse_mode=ParseMode.HTML, reply_markup=K.main_menu())
        await send_phone_contact(update.message, "112")
        return
    if d.action == "SHOW_116117_AND_ASK":
        set_request(ud, d.category or "UNKNOWN", None, d.age_group, text)
        await update.message.reply_text(F.e(d.safety_message) + "\n" + F.MSG_116117 + " Se pensi sia un'emergenza, 112.\n\nOppure scegli tu:",
                                        parse_mode=ParseMode.HTML, reply_markup=K.service_type())
        await send_phone_contact(update.message, "116117")
        return
    if d.action == "ASK_SERVICE_TYPE":
        set_request(ud, "UNKNOWN", None, d.age_group, text)
        intro = "Va bene. " if d.category == "advice" else "Non ho capito. "
        await update.message.reply_text(intro + F.MSG_116117 + "\n\nOppure scegli tu:",
                                        parse_mode=ParseMode.HTML, reply_markup=K.service_type())
        await send_phone_contact(update.message, "116117")
        return
    if d.action == "ASK_TYPE_FOR_CATEGORY":
        set_request(ud, d.category, None, d.age_group, text)
        allowed = d.allowed_types or []
        ud["allowed_types"] = allowed
        await update.message.reply_text(f"Ho capito: <b>{F.e(F.category_short(d.category))}</b>.\n" + F.MSG_116117 + "\n\n" + PROMPT_TYPE,
                                        parse_mode=ParseMode.HTML,
                                        reply_markup=K.service_type(include_ps="emergency_room" in allowed, include_cdc="community_house" in allowed,
                                                                    include_pharmacy="pharmacy" in allowed))
        return
    set_request(ud, d.category, d.facility_type, d.age_group, text, explicit_type=presel == d.facility_type)
    what = F.category_short(d.category, d.facility_type)
    where = {"emergency_room": "cerco un Pronto Soccorso", "community_house": "cerco una Casa della Comunità", "pharmacy": "cerco una farmacia"}.get(d.facility_type, "")
    await _ask_location_or_go(update, context, f"🔎 <b>{F.e(what)}</b> → {where}.", confirm=True)
