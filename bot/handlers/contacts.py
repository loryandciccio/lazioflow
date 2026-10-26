"""Numeri brevi: testo copiabile, senza contatti normalizzati con prefissi errati."""
from telegram import Message
from telegram.constants import ParseMode

CONTACTS = {"112": "Numero Unico di Emergenza", "116117": "Consiglio sanitario non urgente"}


async def send_phone_contact(message: Message, number: str) -> None:
    if number not in CONTACTS:
        return
    await message.reply_text(
        f"📞 <b>{CONTACTS[number]}</b>\nNumero da comporre nell’app Telefono: <code>{number}</code>\n"
        "Digita il numero senza prefissi internazionali. Questo pulsante mostra il numero, non avvia una chiamata.",
        parse_mode=ParseMode.HTML,
    )
