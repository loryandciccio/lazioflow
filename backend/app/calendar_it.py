"""Festività italiane (nazionali + patrono di Roma) per capire se oggi è 'sab/dom/festivi'."""
from __future__ import annotations

from datetime import date, timedelta

FIXED = {(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)}
ROME_PATRON = (6, 29)


def easter(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def is_holiday(d: date, rome: bool = False) -> bool:
    if (d.month, d.day) in FIXED:
        return True
    if rome and (d.month, d.day) == ROME_PATRON:
        return True
    return d == easter(d.year) + timedelta(days=1)  # Lunedì dell'Angelo


def is_weekend_or_holiday(d: date, rome: bool = False) -> bool:
    return d.weekday() >= 5 or is_holiday(d, rome)
