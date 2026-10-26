"""Invio di HTML anche oltre il limite Telegram, senza spezzare tag o entità."""
from __future__ import annotations

import html
from html.parser import HTMLParser

from telegram.constants import ParseMode


def split_html(text: str, limit: int = 4000) -> list[str]:
    """Conserva testo e formattazione; conta UTF-16, incluse le emoji fuori dal BMP."""
    if limit < 2:
        raise ValueError("limit deve essere almeno 2")

    class Splitter(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self.buffer: list[str] = []
            self.tags: list[tuple[str, str]] = []
            self.units = 0

        def flush(self):
            if self.units:
                self.parts.append("".join(self.buffer) + "".join(f"</{tag}>" for tag, _ in reversed(self.tags)))
                self.buffer = [opening for _, opening in self.tags]
                self.units = 0

        def handle_starttag(self, tag, attrs):
            opening = self.get_starttag_text()
            self.tags.append((tag, opening))
            self.buffer.append(opening)

        def handle_endtag(self, tag):
            self.buffer.append(f"</{tag}>")
            if self.tags and self.tags[-1][0] == tag:
                self.tags.pop()

        def handle_data(self, data):
            while data:
                remaining = limit - self.units
                end = 0
                used = 0
                for char in data:
                    size = 2 if ord(char) > 0xFFFF else 1
                    if used + size > remaining:
                        break
                    used += size
                    end += 1
                if not end:
                    self.flush()
                    continue
                if end < len(data):
                    # Quando possibile, passa al messaggio successivo a fine parola.
                    boundary = max(data.rfind("\n", 0, end), data.rfind(" ", 0, end))
                    if boundary >= end // 2:
                        end = boundary + 1
                piece, data = data[:end], data[end:]
                self.buffer.append(html.escape(piece, quote=False))
                self.units += len(piece.encode("utf-16-le")) // 2
                if data:
                    self.flush()

    splitter = Splitter()
    splitter.feed(text)
    splitter.close()
    splitter.flush()
    return splitter.parts


async def reply_html(message, text: str, **kwargs):
    """I pulsanti restano soltanto nell'ultimo messaggio, che viene restituito."""
    chunks = split_html(text)
    sent = None
    for index, chunk in enumerate(chunks):
        options = dict(kwargs)
        if index < len(chunks) - 1:
            options.pop("reply_markup", None)
        sent = await message.reply_text(chunk, parse_mode=ParseMode.HTML, **options)
    return sent
