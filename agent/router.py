import re
import logging

logger = logging.getLogger(__name__)

# Keywords that signal a question needs multi-step reasoning or aggregation
_COMPLEX_PATTERNS = [
    r"\bkarşılaştır", r"\boranla", r"\bortalama", r"\bdağılım",
    r"\bfark\b", r"\bkaç kat\b", r"\bkıyasla", r"\banalyze\b",
    r"\bcompare\b", r"\baverage\b", r"\bdistribution\b",
    r"\btop[- ]?\d+\b", r"\ben (hızlı|yavaş|yüksek|alçak|uzun|kısa)\s+\d+",
    r"\byüksek mi\b", r"\bdaha (hızlı|yavaş|yüksek|alçak)\b",
    r"\bvs\b", r"\bversus\b", r"\bsırala", r"\branking\b",
    r"\btüm .*(ort|mean|avg)\b", r"istatistik|statistic",
]

_COMPLEX_RE = re.compile("|".join(_COMPLEX_PATTERNS), re.IGNORECASE)

# Chain queries — "the departure city's weather of the highest flight" — need
# one tool to *select* a flight and another to answer the actual question.
# A superlative selector combined with a secondary attribute request is the
# strongest signal for that shape.
# No trailing \b on the Turkish branch — agglutinative suffixes are the norm
# ("en yüksekte uçan", "en hızlısı") and a word boundary would reject them.
_SUPERLATIVE_RE = re.compile(
    r"\ben (hızlı|yavaş|yüksek|alçak|uzun|kısa|geç|erken|çok|az)"
    r"|\b(fastest|slowest|highest|lowest|longest|shortest|latest|earliest)\b"
    r"|\bmost\b|\bleast\b",
    re.IGNORECASE,
)

_SECONDARY_INFO_RE = re.compile(
    r"\bhava\b|\bweather\b|şehr|\bcity\b|ülke|\bcountry\b"
    r"|kapı|\bgate\b|\bterminal\b|bagaj|\bbaggage\b"
    r"|\bne zaman\b|\bwhen\b|\biner\b|kalk(ış|ar|tı)|\bland\b|\bdepart",
    re.IGNORECASE,
)

# Two explicit flight codes in one question ("is TK1 higher than PC2?")
_TWO_FLIGHTS_RE = re.compile(r"\b[A-Z]{2}\d{1,4}\b.*\b[A-Z]{2}\d{1,4}\b")


def detect_complexity(soru: str) -> str:
    is_complex = bool(
        _COMPLEX_RE.search(soru)
        or (_SUPERLATIVE_RE.search(soru) and _SECONDARY_INFO_RE.search(soru))
        or _TWO_FLIGHTS_RE.search(soru.upper())
    )
    complexity = "complex" if is_complex else "simple"
    logger.info(f"Router: {'Groq' if complexity == 'complex' else 'Cohere'} | Soru: {soru}")
    return complexity
