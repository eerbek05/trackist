"""Airport-local time conversion, done in code.

The agent prompt used to ask the LLM to convert UTC times to the destination
airport's local time — with no timezone data and no tool, so the model did
the conversion from memory (frequently wrong, DST especially). Tools now
attach the local time themselves and the prompt forbids the model from doing
timezone math.
"""

import re
import sys
import os
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

_tf = None
_tz_cache = {}


def _get_finder():
    global _tf
    if _tf is None:
        from timezonefinder import TimezoneFinder
        _tf = TimezoneFinder()
    return _tf


def airport_timezone(iata_code):
    """IANA timezone name for an airport, resolved from its coordinates.
    Returns None when the airport (or its timezone) is unknown."""
    iata_code = (iata_code or "").upper()
    if not iata_code:
        return None
    if iata_code in _tz_cache:
        return _tz_cache[iata_code]

    from tools.statistics import get_airport_coords
    tz_name = None
    try:
        coords = get_airport_coords(iata_code)
        if coords:
            tz_name = _get_finder().timezone_at(lat=coords[0], lng=coords[1])
    except Exception as e:
        logger.warning(f"airport_timezone({iata_code}): {e}")
    _tz_cache[iata_code] = tz_name
    return tz_name


_DT_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})")


def parse_utc(dt_str):
    """Parse the DB's 'YYYY-MM-DD HH:MM' UTC strings into aware datetimes."""
    if not dt_str:
        return None
    m = _DT_RE.search(str(dt_str))
    if not m:
        return None
    y, mo, d, h, mi = map(int, m.groups())
    try:
        return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)
    except ValueError:
        return None


def utc_to_airport_local(dt, iata_code):
    """Convert an aware-or-naive-UTC datetime to airport local time.
    Returns an aware datetime, or None if the timezone can't be resolved."""
    if dt is None:
        return None
    tz_name = airport_timezone(iata_code)
    if not tz_name:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        return dt.astimezone(ZoneInfo(tz_name))
    except Exception:
        return None


def fmt_utc_with_local(dt_str, iata_code):
    """'2026-07-01 14:12' + 'JFK' → '14:12 UTC (10:12 local time at JFK)'.
    Falls back to plain UTC when the timezone is unknown."""
    dt = parse_utc(dt_str)
    if not dt:
        return None
    utc_part = dt.strftime("%H:%M UTC")
    local = utc_to_airport_local(dt, iata_code)
    if local is None:
        return utc_part
    return f"{utc_part} ({local.strftime('%H:%M')} local time at {iata_code.upper()})"
