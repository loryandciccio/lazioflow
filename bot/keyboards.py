"""Tastiere. I pulsanti sono SEMPRE disponibili come percorso sicuro (spec §2.2). Etichette corte: su telefono
una riga da 3 bottoni tronca oltre ~12 caratteri."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

BTN_EMERGENZA = "🚨 Emergenza"
BTN_NON_URGENTE = "🩺 Consiglio non urgente"
BTN_PS = "🏥 Pronto Soccorso"
BTN_CDC = "🏠 Casa della Comunità"
BTN_FARMACIA = "💊 Farmacia"
BTN_VISITA = "📅 Visita / esame"
BTN_NONSO = "❓ Non so dove andare"
MAIN_BUTTONS = [BTN_EMERGENZA, BTN_NON_URGENTE, BTN_PS, BTN_CDC, BTN_FARMACIA, BTN_VISITA, BTN_NONSO]

BTN_POSIZIONE = "📍 Invia posizione"
BTN_MENU = "⬅️ Menu"

PRESETS = [("nearest", "📍 Più vicino"), ("balanced", "⚖️ Equilibrato"), ("less_crowded", "👥 Attesa osservata")]
PRESET_LABEL = dict(PRESETS)
PRESET_SHORT = {"nearest": "solo viaggio", "balanced": "dati recenti, poi viaggio; attesa a parità di viaggio", "less_crowded": "solo attesa"}


def main_menu() -> ReplyKeyboardMarkup:
    rows = [[BTN_EMERGENZA, BTN_NON_URGENTE], [BTN_PS, BTN_FARMACIA], [BTN_CDC, BTN_VISITA], [BTN_NONSO]]
    return ReplyKeyboardMarkup([[KeyboardButton(b) for b in r] for r in rows], resize_keyboard=True,
                               input_field_placeholder="Scrivi cosa ti serve o usa i pulsanti")


def ask_location() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(BTN_POSIZIONE, request_location=True)], [KeyboardButton(BTN_MENU)]],
                               resize_keyboard=True, one_time_keyboard=True)


def service_type(include_ps: bool = True, include_cdc: bool = True, include_pharmacy: bool = True) -> InlineKeyboardMarkup:
    """Scelta ESPLICITA dell'utente del tipo di struttura (stati UNCERTAIN / UNKNOWN / categorie multi-tipo)."""
    rows = []
    if include_ps:
        rows.append([InlineKeyboardButton("🏥 Pronto Soccorso", callback_data="type:emergency_room")])
    if include_cdc:
        rows.append([InlineKeyboardButton("🏠 Casa della Comunità", callback_data="type:community_house")])
    if include_pharmacy:
        rows.append([InlineKeyboardButton("💊 Farmacia", callback_data="type:pharmacy")])
    rows.append(phone_buttons())
    return InlineKeyboardMarkup(rows)


def phone_buttons() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton("📞 112", callback_data="call:112"),
            InlineKeyboardButton("📞 116117", callback_data="call:116117")]


def phone_contacts() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([phone_buttons()])


def confirm_category() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confermo", callback_data="confirmcat")],
                                [InlineKeyboardButton("🔁 Non è questo, scelgo io", callback_data="wrongcat")], phone_buttons()])


def results(recs: list[dict], preference: str, can_alternatives: bool = True, with_presets: bool = True) -> InlineKeyboardMarkup:
    navigable = [r for r in recs[:3] if r.get("maps_url")]
    rows = [[InlineKeyboardButton(f"🗺 Vai a #{r['rank']}", url=r["maps_url"]) for r in navigable]] if navigable else []
    if navigable and not with_presets:
        from urllib.parse import urlencode
        rows.append([InlineKeyboardButton(f"Scheda #{r['rank']}", url="https://www.google.com/maps/search/?" + urlencode(
            {"api":1,"query":f"{r['name']} {r.get('address') or ''}"})) for r in navigable])
    if with_presets:
        rows.append([InlineKeyboardButton(("✅ " if k == preference else "") + lab, callback_data=f"pref:{k}") for k, lab in PRESETS[:2]])
        rows.append([InlineKeyboardButton(("✅ " if preference == "less_crowded" else "") + PRESET_LABEL["less_crowded"], callback_data="pref:less_crowded"),
                     InlineKeyboardButton("🔄 Aggiorna", callback_data="refresh")])
    else:
        rows.append([InlineKeyboardButton("🔄 Aggiorna", callback_data="refresh")])
    last = [InlineKeyboardButton("ℹ️ Perché", callback_data="why")] if recs else []
    if can_alternatives:
        last.insert(0, InlineKeyboardButton("➕ Altre 3", callback_data="alt"))
    if last:
        rows.append(last)
    rows.append(phone_buttons())
    return InlineKeyboardMarkup(rows)
