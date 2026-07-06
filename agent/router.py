import re
import logging

logger = logging.getLogger(__name__)

# Users type Turkish both with and without diacritics ("yüksek" / "yuksek"),
# so the question is folded to ASCII before matching and every Turkish
# pattern below is written in folded form.
_FOLD = str.maketrans("çÇğĞıİöÖşŞüÜ", "cCgGiIoOsSuU")

# Keywords that signal a question needs multi-step reasoning or aggregation
_COMPLEX_PATTERNS = [
    r"\bkarsilastir", r"\boranla", r"\bortalama", r"\bdagilim",
    r"\bfark\b", r"\bkac kat\b", r"\bkiyasla", r"\banalyze\b",
    r"\bcompare\b", r"\baverage\b", r"\bdistribution\b",
    r"\btop[- ]?\d+\b", r"\ben (hizli|yavas|yuksek|alcak|uzun|kisa)\s+\d+",
    r"\byuksek mi\b", r"\bdaha (hizli|yavas|yuksek|alcak)\b",
    r"\bvs\b", r"\bversus\b", r"\bsirala", r"\branking\b",
    r"\btum .*(ort|mean|avg)\b", r"istatistik|statistic",
]

_COMPLEX_RE = re.compile("|".join(_COMPLEX_PATTERNS), re.IGNORECASE)

# Chain queries — "the departure city's weather of the highest flight" — need
# one tool to *select* a flight and another to answer the actual question.
# A superlative selector combined with a secondary attribute request is the
# strongest signal for that shape.
# No trailing \b on the Turkish branch — agglutinative suffixes are the norm
# ("en yüksekte uçan", "en hızlısı") and a word boundary would reject them.
_SUPERLATIVE_RE = re.compile(
    r"\ben (hizli|yavas|yuksek|alcak|uzun|kisa|gec|erken|cok|az)"
    r"|\b(fastest|slowest|highest|lowest|longest|shortest|latest|earliest)\b"
    r"|\bmost\b|\bleast\b",
    re.IGNORECASE,
)

_SECONDARY_INFO_RE = re.compile(
    r"\bhava\b|\bweather\b|sehr|\bcity\b|ulke|\bcountry\b"
    r"|kapi|\bgate\b|\bterminal\b|bagaj|\bbaggage\b"
    r"|\bne zaman\b|\bwhen\b|\bnereye\b|\bnerede\b|\bwhere\b"
    r"|\bin(er|ecek|iyor|di)\b|kalk(is|ar|ti)|gid(iyor|ecek)|\bland\b|\bdepart",
    re.IGNORECASE,
)

# Two explicit flight codes in one question ("is TK1 higher than PC2?")
_TWO_FLIGHTS_RE = re.compile(r"\b[A-Z]{2}\d{1,4}\b.*\b[A-Z]{2}\d{1,4}\b")


def detect_complexity(soru: str) -> str:
    folded = soru.translate(_FOLD)
    is_complex = bool(
        _COMPLEX_RE.search(folded)
        or (_SUPERLATIVE_RE.search(folded) and _SECONDARY_INFO_RE.search(folded))
        or _TWO_FLIGHTS_RE.search(folded.upper())
    )
    complexity = "complex" if is_complex else "simple"
    logger.info(f"Router: {'Groq' if complexity == 'complex' else 'Cohere'} | Soru: {soru}")
    return complexity
