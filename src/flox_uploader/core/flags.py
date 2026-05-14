"""Drapeaux emoji pour langues et pays.

Un emoji drapeau Unicode est composé de 2 "regional indicator symbols" qui
correspondent aux 2 lettres ISO 3166-1 alpha-2 du pays. On expose donc :
- `flag_for_country(iso3166_2)` : code pays ISO -> emoji
- `flag_for_language(iso639)` : code langue ISO -> emoji (mapping vers pays principal)

Pour les langues parlées dans plusieurs pays, on choisit une convention
identique à l'ancien system_prompt (en→US, pt→PT par défaut, etc.). La
fonction `flag_for_language_with_context` permet d'ajuster (par ex. pt→BR
si la production_country est Brésil).
"""
from __future__ import annotations

# Décalage Unicode pour passer de A (0x41) au regional indicator A (0x1F1E6)
_REGIONAL_INDICATOR_OFFSET = 0x1F1E6 - ord("A")


def flag_for_country(iso3166_2: str) -> str:
    """Retourne l'emoji drapeau pour un code pays ISO 3166-1 alpha-2.

    Ex: 'FR' -> '🇫🇷', 'US' -> '🇺🇸'. Retourne chaîne vide si invalide.
    """
    if not iso3166_2 or len(iso3166_2) != 2:
        return ""
    code = iso3166_2.upper()
    if not code.isalpha():
        return ""
    return "".join(chr(ord(c) + _REGIONAL_INDICATOR_OFFSET) for c in code)


# ============================================================
# MAPPING ISO 639-1/639-2 -> ISO 3166-1 alpha-2 (pays principal)
# ============================================================
# La convention reproduit celle de l'ancien system_prompt :
#   en -> US, fr -> FR, ja -> JP, pt -> PT (FR n'a pas la nuance brésilienne par défaut)
# Pour ajuster pt -> BR ou en -> GB selon le contexte, voir
# `flag_for_language_with_context`.

LANGUAGE_TO_COUNTRY: dict[str, str] = {
    # Langues les plus fréquentes en premier
    "fr": "FR", "fra": "FR", "fre": "FR",
    "en": "US", "eng": "US",
    "es": "ES", "spa": "ES",
    "de": "DE", "deu": "DE", "ger": "DE",
    "it": "IT", "ita": "IT",
    "pt": "PT", "por": "PT",
    "ja": "JP", "jpn": "JP",
    "ko": "KR", "kor": "KR",
    "zh": "CN", "zho": "CN", "chi": "CN",
    "ru": "RU", "rus": "RU",
    "ar": "SA", "ara": "SA",
    "hi": "IN", "hin": "IN",
    "tr": "TR", "tur": "TR",
    "pl": "PL", "pol": "PL",
    "nl": "NL", "nld": "NL", "dut": "NL",
    "sv": "SE", "swe": "SE",
    "no": "NO", "nor": "NO", "nob": "NO", "nno": "NO",
    "da": "DK", "dan": "DK",
    "fi": "FI", "fin": "FI",
    "cs": "CZ", "ces": "CZ", "cze": "CZ",
    "sk": "SK", "slk": "SK", "slo": "SK",
    "hu": "HU", "hun": "HU",
    "ro": "RO", "ron": "RO", "rum": "RO",
    "bg": "BG", "bul": "BG",
    "el": "GR", "ell": "GR", "gre": "GR",
    "uk": "UA", "ukr": "UA",
    "he": "IL", "heb": "IL",
    "th": "TH", "tha": "TH",
    "vi": "VN", "vie": "VN",
    "id": "ID", "ind": "ID",
    "ms": "MY", "msa": "MY", "may": "MY",
    "fa": "IR", "fas": "IR", "per": "IR",
    "ur": "PK", "urd": "PK",
    "bn": "BD", "ben": "BD",
    "ta": "IN", "tam": "IN",
    "te": "IN", "tel": "IN",
    "ml": "IN", "mal": "IN",
    "mr": "IN", "mar": "IN",
    "kn": "IN", "kan": "IN",
    "pa": "IN", "pan": "IN",
    "gu": "IN", "guj": "IN",
    "ne": "NP", "nep": "NP",
    "si": "LK", "sin": "LK",
    "my": "MM", "mya": "MM", "bur": "MM",
    "km": "KH", "khm": "KH",
    "lo": "LA", "lao": "LA",
    "mn": "MN", "mon": "MN",
    "ka": "GE", "kat": "GE", "geo": "GE",
    "hy": "AM", "hye": "AM", "arm": "AM",
    "az": "AZ", "aze": "AZ",
    "kk": "KZ", "kaz": "KZ",
    "uz": "UZ", "uzb": "UZ",
    "ky": "KG", "kir": "KG",
    "tg": "TJ", "tgk": "TJ",
    "tk": "TM", "tuk": "TM",
    "ps": "AF", "pus": "AF",
    "is": "IS", "isl": "IS", "ice": "IS",
    "ga": "IE", "gle": "IE",
    "cy": "GB", "cym": "GB", "wel": "GB",
    "gd": "GB", "gla": "GB",
    "eu": "ES", "eus": "ES", "baq": "ES",
    "ca": "ES", "cat": "ES",
    "gl": "ES", "glg": "ES",
    "br": "FR", "bre": "FR",
    "co": "FR", "cos": "FR",
    "oc": "FR", "oci": "FR",
    "lb": "LU", "ltz": "LU",
    "mt": "MT", "mlt": "MT",
    "sq": "AL", "sqi": "AL", "alb": "AL",
    "sr": "RS", "srp": "RS",
    "hr": "HR", "hrv": "HR",
    "bs": "BA", "bos": "BA",
    "mk": "MK", "mkd": "MK", "mac": "MK",
    "sl": "SI", "slv": "SI",
    "et": "EE", "est": "EE",
    "lv": "LV", "lav": "LV",
    "lt": "LT", "lit": "LT",
    "be": "BY", "bel": "BY",
    "mo": "MD", "mol": "MD",
    "af": "ZA", "afr": "ZA",
    "sw": "TZ", "swa": "TZ",
    "am": "ET", "amh": "ET",
    "yo": "NG", "yor": "NG",
    "ha": "NG", "hau": "NG",
    "ig": "NG", "ibo": "NG",
    "zu": "ZA", "zul": "ZA",
    "xh": "ZA", "xho": "ZA",
    "tl": "PH", "tgl": "PH",
    # Langues sans pays moderne associé : on omet (latin, espéranto, etc.)
    # Le code retournera "" et le renderer affichera "Inconnue".
}


def flag_for_language(iso639: str) -> str:
    """Retourne l'emoji drapeau pour un code de langue ISO 639-1 ou 639-2.

    Ex: 'fr' -> '🇫🇷', 'eng' -> '🇺🇸'. Retourne "" si la langue n'est pas
    mappée.
    """
    if not iso639:
        return ""
    key = iso639.strip().lower()
    country = LANGUAGE_TO_COUNTRY.get(key)
    if not country:
        return ""
    return flag_for_country(country)


# Quelques règles de contexte pour les langues parlées dans plusieurs pays.
# Si le contexte (production_country) suggère un pays alternatif, on l'utilise.
_CONTEXT_OVERRIDES: dict[str, dict[str, str]] = {
    "fr": {  # Français
        "Canada": "CA",
        "Québec": "CA",
        "Quebec": "CA",
        "Belgium": "BE",
        "Belgique": "BE",
        "Switzerland": "CH",
        "Suisse": "CH",
    },
    "en": {
        # Convention legacy : Anglais -> US par defaut, meme si production UK
        # ou autre. On override seulement si la production est exclusivement
        # non-US (cas tres rare ; pour l'instant on ne specialise pas).
    },
    "pt": {  # Portugais
        "Brazil": "BR",
        "Brésil": "BR",
        "Brasil": "BR",
    },
    "es": {  # Espagnol
        "Mexico": "MX",
        "Mexique": "MX",
        "Argentina": "AR",
        "Chile": "CL",
        "Colombia": "CO",
        "Cuba": "CU",
    },
    "de": {  # Allemand
        "Austria": "AT",
        "Autriche": "AT",
        "Switzerland": "CH",
        "Suisse": "CH",
    },
    "zh": {  # Chinois
        "Taiwan": "TW",
        "Hong Kong": "HK",
    },
}


def flag_for_language_with_context(
    iso639: str, production_countries: list[str] | None = None
) -> str:
    """Retourne le drapeau en tenant compte du contexte (pays de production).

    Ex: pour la langue 'pt' et un film brésilien, retourne 🇧🇷 au lieu de 🇵🇹.

    Cas particulier (FR) : si la France figure dans les pays de production, on
    garde 🇫🇷 quel que soit le reste (Belgique, Canada, Suisse). Cas typique :
    "Delicieux" co-prod France+Belgique -> 🇫🇷 (et non 🇧🇪).
    """
    if not iso639:
        return ""
    key = iso639.strip().lower()

    # Priorite France pour le francais : si la France figure dans les pays
    # de production, on garde 🇫🇷 quel que soit le reste (Belgique, Canada,
    # Suisse). Cas typique : "Delicieux" co-prod France+Belgique -> 🇫🇷.
    if key == "fr" and production_countries:
        if any("france" in (c or "").lower() for c in production_countries):
            return flag_for_language(iso639)

    overrides = _CONTEXT_OVERRIDES.get(key, {})
    if overrides and production_countries:
        for country in production_countries:
            if country in overrides:
                return flag_for_country(overrides[country])
    return flag_for_language(iso639)
