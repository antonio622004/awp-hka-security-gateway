"""Sprache der Person (HKA-101): Deutsch oder Englisch.

Das Gateway speichert die Wahl im Cookie ``hka_gateway_lang``, weil es Cookies auf dem Weg zu Portal und Apps entfernt.
Portal und Apps bekommen die Sprache als ``Accept-Language`` (``de`` oder ``en``); der Login-Server bekommt ``ui_locales``.
"""

from __future__ import annotations

import math
from typing import Final

LANGUAGES: Final = ("de", "en")
DEFAULT_LANGUAGE: Final = "de"
MAX_ACCEPT_LANGUAGE_LENGTH: Final = 256
COOKIE_MAX_AGE: Final = 365 * 24 * 3600


def pick_language(cookie: str | None, accept_language: str | None) -> str:
    """Sprache einer Anfrage bestimmen.

    Ein gültiges Cookie gewinnt. Sonst zählt die erste unterstützte Sprache aus ``Accept-Language`` nach ihrem
    Gewicht (``q``); ``en-GB`` zählt als ``en``. Ohne Treffer gilt Deutsch.

    :param cookie: Wert des Sprach-Cookies oder ``None``
    :param accept_language: Wert des Headers ``Accept-Language`` oder ``None``
    :return: ``de`` oder ``en``
    :rtype: str
    """
    if cookie in LANGUAGES:
        return cookie
    if not accept_language or len(accept_language) > MAX_ACCEPT_LANGUAGE_LENGTH:
        return DEFAULT_LANGUAGE
    ranked: list[tuple[float, int, str]] = []
    for position, item in enumerate(accept_language.split(",")):
        tag, *params = (part.strip() for part in item.split(";"))
        weight = 1.0
        for param in params:
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    weight = float(value)
                except ValueError:
                    weight = 0.0
                if not math.isfinite(weight):
                    weight = 0.0
        primary = tag.split("-")[0].lower()
        if weight > 0 and primary in LANGUAGES:
            ranked.append((-weight, position, primary))
    return min(ranked)[2] if ranked else DEFAULT_LANGUAGE
