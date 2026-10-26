from __future__ import annotations

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from .. import format as F
from .. import keyboards as K
from ..api_client import BackendError
from ..config import ALT_N, TOP_N
from ..messages import reply_html, split_html
from ..state import clear_request, has_request, set_location
from .contacts import send_phone_contact


async def run_recommend(message: Message, context: ContextTypes.DEFAULT_TYPE, lat: float, lng: float,
                        offset: int = 0, edit: bool = False) -> None:
    ud = context.user_data
    api = context.bot_data["api"]
    if not has_request(ud):
        set_location(ud, lat, lng)
        await message.reply_text("Posizione ricevuta. Cosa ti serve?", reply_markup=K.main_menu())
        return
    if ud.get("pending_confirmation"):
        await message.reply_text("Conferma prima la categoria con il pulsante nel messaggio precedente.")
        return
    if not ud.get("facility_type"):
        allowed = ud.get("allowed_types") or ("emergency_room", "community_house", "pharmacy")
        await message.reply_text("Posizione ricevuta. Scegli prima il tipo di struttura:",
                                 reply_markup=K.service_type(include_ps="emergency_room" in allowed,
                                                             include_cdc="community_house" in allowed,
                                                             include_pharmacy="pharmacy" in allowed))
        return
    limit = ALT_N if offset else TOP_N
    try:
        res = await api.recommend(ud["category"], lat, lng, ud.get("preference", "balanced"), ud.get("age_group", "unknown"),
                                  ud.get("facility_type"), limit=limit)
    except BackendError:
        await message.reply_text("Non riesco a leggere i dati adesso, non voglio inventare: riprova tra poco.\n"
                                 "Emergenza → 112 · consiglio → 116117.", reply_markup=K.main_menu())
        return
    if res.get("escalation"):
        clear_request(ud)
        safety = F.MSG_112 if res["escalation"] == "112" else F.MSG_116117
        await message.reply_text(F.e(res.get("escalation_text")) + "\n\n" + safety, parse_mode=ParseMode.HTML, reply_markup=K.main_menu())
        await send_phone_contact(message, res["escalation"])
        return
    recs = res["recommendations"][offset: offset + TOP_N] if offset else res["recommendations"][:TOP_N]
    ud["last_result"] = res
    ud["last_recs"] = recs
    ud["offset"] = offset
    txt = F.results_message(res, recs, offset)
    kb = K.results(recs, ud.get("preference", "balanced"), can_alternatives=(offset == 0 and res.get("candidates_considered", 0) > TOP_N),
                   with_presets=(ud.get("facility_type") == "emergency_room"))
    if edit and len(split_html(txt)) == 1:
        try:
            await message.edit_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)
            if isinstance(getattr(message, "message_id", None), int):
                ud["result_message_id"] = message.message_id
            return
        except BadRequest as ex:
            if "message is not modified" in str(ex).lower():
                return
            # Un messaggio non più modificabile viene sostituito da un nuovo risultato.
    sent = await reply_html(message, txt, reply_markup=kb, disable_web_page_preview=True)
    if isinstance(getattr(sent, "message_id", None), int):
        ud["result_message_id"] = sent.message_id
    if offset == 0:
        await message.reply_text("Altro? Usa i pulsanti.", reply_markup=K.main_menu())


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    loc = update.message.location
    set_location(context.user_data, loc.latitude, loc.longitude)
    await run_recommend(update.message, context, loc.latitude, loc.longitude)
