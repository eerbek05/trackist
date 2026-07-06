"""Process-wide LLM provider availability state.

Lives in its own module so agent.motor and tools.text_to_sql can share the
same "provider X is rate-limited" signal without a circular import.

Free-tier 429s are almost always transient windows (per-minute bursts,
daily token buckets refilling on a rolling basis), so a provider is marked
unavailable for a cooldown period rather than forever — marking it dead
until restart would silently shrink the fallback chain.
"""

import threading
import time

_lock = threading.Lock()
_exhausted_until = {}  # provider name -> unix timestamp

# Per-minute buckets (RPM/TPM) refill within a minute — a long cooldown after
# one of those needlessly benches a healthy provider. Daily/monthly buckets
# (TPD/RPD/trial-month) won't recover soon, so back off much longer.
SHORT_COOLDOWN = 75
LONG_COOLDOWN = 30 * 60

# "check your plan and billing" is Gemini's free-tier *daily* quota message —
# without it the provider would be retried every 75s all day long.
_LONG_MARKERS = ("per day", "tpd", "rpd", "perday", "month", "daily",
                 "check your plan and billing")


def is_exhausted(provider: str) -> bool:
    return time.time() < _exhausted_until.get(provider, 0.0)


def mark_exhausted(provider: str, error_str: str = ""):
    s = error_str.lower()
    cooldown = LONG_COOLDOWN if any(k in s for k in _LONG_MARKERS) else SHORT_COOLDOWN
    with _lock:
        _exhausted_until[provider] = time.time() + cooldown


# Backwards-compatible helpers (used by tools.text_to_sql)
def cohere_exhausted() -> bool:
    return is_exhausted("cohere")


def mark_cohere_exhausted():
    mark_exhausted("cohere")


def looks_like_rate_limit(error_str: str) -> bool:
    """True for any 'provider is busy right now' error — not just 429s.
    503/overloaded responses recover the same way (wait and retry later),
    so they get the same treatment: bench the provider, move down the chain."""
    s = error_str.lower()
    return any(k in s for k in (
        "429", "rate_limit", "trial key", "rate limit", "quota",
        "resource_exhausted", "resource has been exhausted",
        "503", "high demand", "overloaded", "service unavailable",
        "temporarily unavailable", "over capacity",
    ))
