"""Deterministic user-language detection.

The "answer in the user's language" rule used to live only in the system
prompt — a soft instruction the LLMs drifted away from, especially after
reading English tool output. Detecting the language in code and prepending
an explicit per-message instruction is cheap and much harder to ignore.

Turkish is detected, everything else falls back to English (the product's
two supported languages).
"""

import re

# Any Turkish-specific letter is conclusive on its own.
_TURKISH_CHARS = set("çğışöüÇĞİŞÖÜ")

# Users often type Turkish without diacritics ("ucus nerede", "kacta iner"),
# so also match common ASCII-folded Turkish words. Tokens are compared
# whole-word — short particles like "mi"/"ne" are rare as standalone English
# tokens in this domain.
_TURKISH_WORDS = {
    "nerede", "nereye", "nereden", "nasil", "kac", "kacta", "kaci",
    "hangi", "hangisi", "ucus", "ucak", "ucagi", "ucagin", "sefer",
    "saat", "saatte", "kacta", "gecikme", "gecikmeli", "gecikti", "rotar",
    "havada", "havalimani", "iniyor", "inecek", "iner", "indi",
    "kalkiyor", "kalkacak", "kalkar", "kalkti", "kalkis", "varis",
    "bagaj", "bandi", "kapi", "kapisi", "koltuk", "koltugum", "pencere",
    "koridor", "durum", "durumu", "bilgi", "bilgisi",
    "mi", "mu", "zaman", "simdi", "bugun", "yarin",
    "yok", "icin", "gelen", "giden", "kadar", "uzakta",
    "hizli", "yavas", "yuksek", "alcak", "tum", "butun",
    "listele", "goster", "soyle",
    # NOTE: deliberately excludes short tokens that also appear in English
    # ("en" as in "en route", "ne", "var", "ver") — a false Turkish positive
    # answers an English user in Turkish, which is worse than the reverse.
}

_TOKEN_RE = re.compile(r"[a-zA-ZçğışöüÇĞİŞÖÜ]+")


def detect_language(text: str) -> str:
    """Returns "tr" or "en"."""
    if any(c in _TURKISH_CHARS for c in text):
        return "tr"
    tokens = {t.lower() for t in _TOKEN_RE.findall(text)}
    if tokens & _TURKISH_WORDS:
        return "tr"
    return "en"


def language_tag(lang: str) -> str:
    """Explicit per-message instruction prepended to the agent input."""
    if lang == "tr":
        return "[Answer in Turkish.] "
    return "[Answer in English.] "
