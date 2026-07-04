import re
import logging

logger = logging.getLogger(__name__)

# Keywords that signal a question needs multi-step reasoning or comparison
_COMPLEX_PATTERNS = [
    r"\bkarşılaştır\b", r"\borganlama\b", r"\bortalama\b", r"\bdağılım\b",
    r"\bfark\b", r"\bkaç kat\b", r"\bkıyasla\b", r"\banalyze\b",
    r"\bcompare\b", r"\baverage\b", r"\bdistribution\b",
    r"\btop[- ]?\d+\b", r"\nen (hızlı|yavaş|yüksek|alçak|uzun|kısa)\s+\d+\b",
    r"\byüksek mi\b", r"\bdaha (hızlı|yavaş|yüksek|alçak)\b",
    r"\bvs\b", r"\bversus\b", r"\bsırala\b", r"\branking\b",
    r"\btüm .*(ort|mean|avg)\b", r"\bstatistik\b",
]

_COMPLEX_RE = re.compile("|".join(_COMPLEX_PATTERNS), re.IGNORECASE)


def detect_complexity(soru: str) -> str:
    complexity = "complex" if _COMPLEX_RE.search(soru) else "simple"
    logger.info(f"Router: {'Groq' if complexity == 'complex' else 'Cohere'} | Soru: {soru}")
    return complexity
