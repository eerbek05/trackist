"""
Regression tests — run with: pytest test.py -v

Four areas, all runnable without a live database, Kafka, or paid API
calls:

1. text_to_sql.validate_sql — the SQL-injection guard around the LLM-
   generated queries. Covers case-insensitivity, word-boundary false
   positives, and both Turkish- and English-language query content.
2. statistics.get_airport_coords / get_airport_info — this had a real
   lat/lng-swap bug that silently broke every distance/ETA calculation
   until it was caught; also covers the airports this project actually
   uses (Istanbul's two airports, plus a few international ones).
3. router.detect_complexity — regex/heuristic router; locks in that both
   Turkish and English questions route correctly, including chain queries
   (superlative selector + secondary attribute) that need the stronger LLM.
4. direct_query.is_stale — a flight that drops out of AirLabs's live feed
   (e.g. it landed) just stops getting updated; this is the only signal
   that distinguishes "stale last-known position" from "live position".
5. opensky.iata_flight_to_icao_callsign — the IATA→ICAO callsign mapping
   used to cross-check stale flights against OpenSky before deleting them.
"""

from datetime import datetime, timedelta

import pytest

from tools.text_to_sql import validate_sql, UnsafeSQLError
from tools.statistics import get_airport_coords, get_airport_info
from tools.direct_query import is_stale, STALE_AFTER
from tools.opensky import iata_flight_to_icao_callsign
from unittest.mock import patch, MagicMock


# ============================================================
# text_to_sql.validate_sql
# ============================================================

def test_validate_sql_allows_plain_select():
    sql = "SELECT * FROM flights WHERE to_airport = 'JFK';"
    assert validate_sql(sql) == "SELECT * FROM flights WHERE to_airport = 'JFK'"


def test_validate_sql_allows_select_without_trailing_semicolon():
    sql = "SELECT flight_id FROM flights"
    assert validate_sql(sql) == "SELECT flight_id FROM flights"


@pytest.mark.parametrize("sql", [
    "DROP TABLE flights;",
    "DELETE FROM flights;",
    "UPDATE flights SET status = 'Havada';",
    "INSERT INTO flights (flight_id) VALUES ('X1');",
    "ALTER TABLE flights ADD COLUMN hacked TEXT;",
    "TRUNCATE flights;",
    "GRANT ALL ON flights TO public;",
])
def test_validate_sql_rejects_non_select_statements(sql):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


@pytest.mark.parametrize("sql", [
    "drop table flights;",
    "Drop Table flights;",
    "DrOp TaBlE flights;",
])
def test_validate_sql_rejects_non_select_statements_case_insensitively(sql):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


def test_validate_sql_rejects_chained_statements():
    # A SELECT that *looks* safe but smuggles a second statement in.
    sql = "SELECT * FROM flights; DROP TABLE flights;"
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


def test_validate_sql_rejects_select_into():
    # SELECT ... INTO can create/overwrite a table — not a read-only query.
    sql = "SELECT * INTO backup_flights FROM flights;"
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


def test_validate_sql_rejects_non_select_opening_statement():
    with pytest.raises(UnsafeSQLError):
        validate_sql("EXPLAIN SELECT * FROM flights;")


@pytest.mark.parametrize("sql,expected_keyword", [
    ("SELECT updated_at FROM flights;", None),
    ("SELECT * FROM flights WHERE status = 'DELETE_REQUESTED';", None),
    ("SELECT * FROM flights WHERE aircraft = 'Updated Livery';", None),
])
def test_validate_sql_does_not_false_positive_on_keyword_substrings(sql, expected_keyword):
    # Column/value names that merely *contain* a forbidden word (updateD_at,
    # DELETE_REQUESTED) must not trip the filter — only the word itself,
    # on its own, should. A naive substring search would break all of these.
    assert validate_sql(sql) is not None


def test_validate_sql_allows_turkish_text_in_query():
    sql = "SELECT * FROM flights WHERE status = 'Havada' AND from_airport = 'İstanbul (IST)';"
    result = validate_sql(sql)
    assert "Havada" in result
    assert "İstanbul" in result


def test_validate_sql_allows_english_text_in_query():
    sql = "SELECT * FROM flights WHERE status = 'En-route' AND to_airport = 'New York (JFK)';"
    result = validate_sql(sql)
    assert "En-route" in result
    assert "New York" in result


@pytest.mark.parametrize("sql", [
    "Bu bir SQL değil, sadece düz Türkçe metin.",
    "This is not SQL, just plain English text.",
])
def test_validate_sql_rejects_non_sql_text(sql):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


# ============================================================
# statistics.get_airport_coords / get_airport_info
# ============================================================

@pytest.mark.parametrize("code,lat_range,lng_range", [
    ("IST", (40, 42), (27, 30)),    # Istanbul Airport
    ("SAW", (40, 41), (28, 30)),    # Istanbul Sabiha Gökçen
    ("JFK", (39, 41), (-75, -72)),  # New York JFK (negative longitude)
    ("LHR", (50, 52), (-1, 1)),     # London Heathrow
    ("DXB", (24, 26), (54, 56)),    # Dubai
])
def test_airport_coords_are_not_swapped(code, lat_range, lng_range):
    # Regression test: airports.csv stores "lat, lng", and the lookup once
    # unpacked it backwards, silently swapping every coordinate it
    # returned. These bounds would fail loudly if that regressed — e.g. a
    # swapped IST would report lat≈28 (outside any valid latitude för this
    # airport), not lat≈41.
    lat, lng = get_airport_coords(code)
    assert lat_range[0] < lat < lat_range[1]
    assert lng_range[0] < lng < lng_range[1]


def test_airport_coords_lookup_is_case_sensitive():
    # Documents actual behavior: airports.csv stores codes uppercase, and
    # the lookup does an exact match — "ist" does not find "IST".
    assert get_airport_coords("ist") is None
    assert get_airport_coords("IST") is not None


def test_unknown_airport_code_returns_none():
    assert get_airport_coords("ZZZ") is None


def test_get_airport_info_includes_name_and_coords():
    info = get_airport_info("IST")
    assert info["iata_code"] == "IST"
    assert "Istanbul" in info["name"] or "İstanbul" in info["name"]
    assert 40 < info["lat"] < 42
    assert 27 < info["lng"] < 30


def test_get_airport_info_for_unknown_code_returns_none():
    assert get_airport_info("ZZZ") is None


# ============================================================
# router.detect_complexity
# ============================================================
# Imported lazily (function-scoped) rather than at module level, so the
# embedding-model load only happens if these tests actually run.

@pytest.fixture(scope="module")
def detect_complexity():
    from agent.router import detect_complexity as _detect_complexity
    return _detect_complexity


@pytest.mark.parametrize("question", [
    "TK3 hızı kaç?",
    "Kaç uçuş havada?",
    "What is the speed of TK3?",
    "How many flights are airborne right now?",
])
def test_router_classifies_simple_questions_in_both_languages(detect_complexity, question):
    assert detect_complexity(question) == "simple"


@pytest.mark.parametrize("question", [
    "TK3'ün hızı tüm uçuşların ortalamasından yüksek mi?",
    "Boeing B77W kullanan uçuşların ortalama irtifası kaç?",
    "Is TK3 faster than the average of all flights?",
    "Compare the average altitude of B77W flights to A333 flights.",
])
def test_router_classifies_complex_questions_in_both_languages(detect_complexity, question):
    assert detect_complexity(question) == "complex"


@pytest.mark.parametrize("question", [
    # A superlative *selector* plus a secondary attribute means one tool has
    # to pick the flight and another answers the actual question — the
    # flagship "chain query" shape from the product vision.
    "IST'e gelen en yüksek uçağın kalkış şehrinde hava nasıl?",
    "What's the weather in the departure city of the highest flight?",
    "En hızlı uçak ne zaman iner?",
    "En hızlı 5 uçuş hangileri?",   # regressed before: pattern had a literal \n
])
def test_router_classifies_chain_questions_as_complex(detect_complexity, question):
    assert detect_complexity(question) == "complex"


@pytest.mark.parametrize("question", [
    "En yüksek uçak hangisi?",   # single superlative → single tool → simple
    "TK12 nerede?",
    "Which flight is the fastest?",
])
def test_router_single_tool_superlative_stays_simple(detect_complexity, question):
    assert detect_complexity(question) == "simple"


# ============================================================
# direct_query.is_stale
# ============================================================

def test_fresh_update_is_not_stale():
    now = datetime(2026, 1, 1, 12, 0, 0)
    updated_at = now - timedelta(seconds=30)
    assert is_stale(updated_at, now=now) is False


def test_update_right_at_the_threshold_is_not_yet_stale():
    now = datetime(2026, 1, 1, 12, 0, 0)
    updated_at = now - STALE_AFTER
    assert is_stale(updated_at, now=now) is False


def test_update_past_the_threshold_is_stale():
    now = datetime(2026, 1, 1, 12, 0, 0)
    updated_at = now - STALE_AFTER - timedelta(seconds=1)
    assert is_stale(updated_at, now=now) is True


def test_long_dropped_flight_is_stale():
    # A flight that dropped off the live feed well past the STALE_AFTER
    # window (currently 75 minutes) — definitely stale.
    now = datetime(2026, 1, 1, 12, 0, 0)
    updated_at = now - STALE_AFTER - timedelta(minutes=30)
    assert is_stale(updated_at, now=now) is True


def test_missing_updated_at_is_not_considered_stale():
    # No timestamp at all (e.g. a freshly-seeded row) shouldn't be flagged
    # stale — that's a different "we don't know" case, not "this is old".
    assert is_stale(None) is False


def test_is_stale_default_clock_is_utc():
    # updated_at is stored as naive UTC; the default "now" must be UTC too.
    # With a local-time default, any machine ahead of UTC (e.g. Turkey,
    # UTC+3) would flag every freshly-written row as hours old.
    from tools.direct_query import utcnow
    assert is_stale(utcnow() - timedelta(minutes=1)) is False
    assert is_stale(utcnow() - STALE_AFTER - timedelta(minutes=1)) is True


# ============================================================
# statistics.get_route_completion — zero-remaining edge case
# ============================================================

from tools.statistics import get_route_completion


@patch("tools.statistics.get_remaining_distance")
@patch("tools.statistics.get_total_route_distance")
def test_route_completion_zero_remaining_means_100_percent(mock_total, mock_remaining):
    # 0 km remaining is a valid "arrived / on final" state, not a failed
    # calculation — a falsy check here used to return None instead of 100%.
    mock_total.return_value = 1500
    mock_remaining.return_value = 0
    r = get_route_completion("TK1", "IST", "JFK")
    assert r is not None
    assert r["yuzde"] == 100
    assert r["kalan_km"] == 0


@patch("tools.statistics.get_remaining_distance")
@patch("tools.statistics.get_total_route_distance")
def test_route_completion_failed_lookup_returns_none(mock_total, mock_remaining):
    mock_total.return_value = 1500
    mock_remaining.return_value = None
    assert get_route_completion("TK1", "IST", "JFK") is None


# ============================================================
# agent.language — deterministic user-language detection
# ============================================================

from agent.language import detect_language


@pytest.mark.parametrize("text", [
    "TK12 nerede?",                      # Turkish keyword, no diacritics
    "ucus ne zaman kalkiyor",            # ASCII-folded Turkish
    "Uçağım hangi kapıdan kalkıyor?",    # Turkish characters
    "bagaj bandi hangisi",
    "kac ucus havada",
])
def test_detect_language_turkish(text):
    assert detect_language(text) == "tr"


@pytest.mark.parametrize("text", [
    "Where is TK12?",
    "The flight is en route to JFK",     # "en" must not trigger Turkish
    "When does my flight land?",
    "list delayed flights",
    "TK12",                              # bare flight code defaults to English
])
def test_detect_language_english(text):
    assert detect_language(text) == "en"


# ============================================================
# tools.tz — airport-local time conversion (code, not LLM)
# ============================================================

from tools.tz import parse_utc, utc_to_airport_local, fmt_utc_with_local, airport_timezone


def test_airport_timezone_resolution():
    assert airport_timezone("IST") == "Europe/Istanbul"
    assert airport_timezone("JFK") == "America/New_York"
    assert airport_timezone("ZZZ") is None


def test_parse_utc():
    dt = parse_utc("2026-07-04 18:55")
    assert dt is not None and (dt.hour, dt.minute) == (18, 55)
    assert parse_utc(None) is None
    assert parse_utc("garbage") is None


def test_utc_to_airport_local_istanbul_offset():
    # Istanbul is UTC+3 year-round (no DST since 2016)
    local = utc_to_airport_local(parse_utc("2026-07-04 10:00"), "IST")
    assert (local.hour, local.minute) == (13, 0)


def test_utc_to_airport_local_jfk_dst():
    # July: New York is on EDT (UTC-4) — a hardcoded/LLM "UTC-5" would fail here
    local = utc_to_airport_local(parse_utc("2026-07-04 18:55"), "JFK")
    assert (local.hour, local.minute) == (14, 55)


def test_fmt_utc_with_local_falls_back_to_utc_for_unknown_airport():
    assert fmt_utc_with_local("2026-07-04 10:00", "ZZZ") == "10:00 UTC"
    assert "13:00" in fmt_utc_with_local("2026-07-04 10:00", "IST")


# ============================================================
# opensky.iata_flight_to_icao_callsign
# ============================================================

@pytest.mark.parametrize("flight_id,expected", [
    ("TK2750", "THY2750"),
    ("TK1", "THY1"),
    ("PC401", "PGT401"),
    ("tk2750", "THY2750"),       # case-insensitive
    (" TK2750 ", "THY2750"),     # tolerates surrounding whitespace
])
def test_iata_flight_to_icao_callsign_known_airlines(flight_id, expected):
    assert iata_flight_to_icao_callsign(flight_id) == expected


@pytest.mark.parametrize("flight_id", [
    "XX99",       # airline prefix we don't have a mapping for
    "TK",         # no flight number at all
    "",
    None,
    "TOOLONG123", # doesn't match the IATA flight-code shape
])
def test_iata_flight_to_icao_callsign_returns_none_when_unmappable(flight_id):
    assert iata_flight_to_icao_callsign(flight_id) is None


# ============================================================
# tools.direct_query — all tests use mocked DB, no live connection needed
# ============================================================

from tools.direct_query import (
    _fmt_time,
    get_gate_and_terminal,
    get_delayed_flights,
    get_flights_by_status,
    get_flights_arriving_ist,
    get_flights_departing_ist,
    get_baggage_claim,
    get_flights_by_airline,
    get_altitude_trend,
    get_scheduled_times,
)


def _mock_db(rows):
    """Return a get_db() mock whose cursor().fetchone/fetchall returns rows."""
    cur = MagicMock()
    cur.fetchone.return_value = rows[0] if rows else None
    cur.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


# ── _fmt_time ──────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("2026-07-01 14:12",    "14:12 UTC"),
    ("2026-07-01 09:05",    "09:05 UTC"),
    ("2026-07-01 14:12:00", "14:12 UTC"),
    (None,                  None),
    ("",                    None),
])
def test_fmt_time(raw, expected):
    assert _fmt_time(raw) == expected


# ── get_gate_and_terminal ──────────────────────────────────

@patch("tools.direct_query.get_db")
def test_gate_departing_from_ist(mock_get_db):
    # dep_gate is B2, arr_gate is null — departing IST so gate = dep_gate
    mock_get_db.return_value = _mock_db([
        ("TK968", "IST", "ECN", "F6A", None, None, None, 7, None, None,
         "", "", "2026-07-01 10:22", "2026-07-01 12:01", "en-route")
    ])
    r = get_gate_and_terminal("TK968")
    assert r["gate"] == "F6A"
    assert r["delay_min"] == 7
    assert r["dep_time"] == "10:22 UTC"
    assert r["arr_time"] == "12:01 UTC"


@patch("tools.direct_query.get_db")
def test_gate_arriving_at_ist(mock_get_db):
    # arr_gate is 16, dep_gate null — arriving IST so gate = arr_gate
    mock_get_db.return_value = _mock_db([
        ("EK121", "DXB", "IST", None, "16", None, None, None, 5, "16",
         "", "", "2026-07-01 09:48", "2026-07-01 14:18", "en-route")
    ])
    r = get_gate_and_terminal("EK121")
    assert r["gate"] == "16"
    assert r["arr_baggage"] == "16"
    assert r["delay_min"] == 5


@patch("tools.direct_query.get_db")
def test_gate_unknown_flight_returns_none(mock_get_db):
    mock_get_db.return_value = _mock_db([])
    assert get_gate_and_terminal("XX999") is None


# ── get_delayed_flights ────────────────────────────────────

@patch("tools.direct_query.get_db")
def test_delayed_flights_sorted_by_worst_delay(mock_get_db):
    mock_get_db.return_value = _mock_db([
        ("TK1", "IST", "JFK", "en-route", 83, None, "2026-07-01 10:00", "2026-07-01 20:00"),
        ("PC2", "IST", "AYT", "en-route", None, 30, "2026-07-01 11:00", "2026-07-01 12:00"),
    ])
    results = get_delayed_flights(min_delay=15)
    assert len(results) == 2
    assert results[0]["flight_id"] == "TK1"
    assert results[0]["max_delay"] == 83
    assert results[1]["max_delay"] == 30


@patch("tools.direct_query.get_db")
def test_delayed_flights_empty_when_none(mock_get_db):
    mock_get_db.return_value = _mock_db([])
    assert get_delayed_flights() == []


# ── get_flights_by_status ──────────────────────────────────

@patch("tools.direct_query.get_db")
def test_flights_by_status_returns_correct_fields(mock_get_db):
    mock_get_db.return_value = _mock_db([
        ("TK5", "IST", "ORD", "en-route", 35000, 975, "2026-07-01 11:17", "2026-07-01 20:15"),
    ])
    results = get_flights_by_status("en-route")
    assert len(results) == 1
    assert results[0]["status"] == "en-route"
    assert results[0]["dep_time"] == "11:17 UTC"


@patch("tools.direct_query.get_db")
def test_flights_by_status_landed_empty(mock_get_db):
    mock_get_db.return_value = _mock_db([])
    assert get_flights_by_status("landed") == []


# ── get_flights_arriving_ist ───────────────────────────────

@patch("tools.direct_query.get_db")
def test_flights_arriving_ist_fields(mock_get_db):
    mock_get_db.return_value = _mock_db([
        ("EK121", "DXB", "en-route", "16", None, "16", 5,
         "2026-07-01 09:48", "2026-07-01 14:18", 35000),
    ])
    results = get_flights_arriving_ist()
    assert results[0]["flight_id"] == "EK121"
    assert results[0]["arr_baggage"] == "16"
    assert results[0]["arr_time"] == "14:18 UTC"
    assert results[0]["altitude_ft"] == 35000


@patch("tools.direct_query.get_db")
def test_flights_arriving_ist_empty(mock_get_db):
    mock_get_db.return_value = _mock_db([])
    assert get_flights_arriving_ist() == []


# ── get_flights_departing_ist ──────────────────────────────

@patch("tools.direct_query.get_db")
def test_flights_departing_ist_fields(mock_get_db):
    mock_get_db.return_value = _mock_db([
        ("TK968", "ECN", "en-route", "F6A", None, 7,
         "2026-07-01 10:22", "2026-07-01 12:01", 985),
    ])
    results = get_flights_departing_ist()
    assert results[0]["dep_gate"] == "F6A"
    assert results[0]["dep_delayed"] == 7
    assert results[0]["dep_time"] == "10:22 UTC"


# ── get_baggage_claim ──────────────────────────────────────

@patch("tools.direct_query.get_db")
def test_baggage_claim_found(mock_get_db):
    mock_get_db.return_value = _mock_db([
        ("EK121", "DXB", "IST", "16", "16", "2026-07-01 14:18", "landed")
    ])
    r = get_baggage_claim("EK121")
    assert r["arr_baggage"] == "16"
    assert r["status"] == "landed"


@patch("tools.direct_query.get_db")
def test_baggage_claim_no_belt_yet(mock_get_db):
    mock_get_db.return_value = _mock_db([
        ("QR240", "DOH", "IST", None, None, "2026-07-01 14:50", "en-route")
    ])
    r = get_baggage_claim("QR240")
    assert r["arr_baggage"] is None


@patch("tools.direct_query.get_db")
def test_baggage_claim_unknown_flight(mock_get_db):
    mock_get_db.return_value = _mock_db([])
    assert get_baggage_claim("ZZ999") is None


# ── get_flights_by_airline ─────────────────────────────────

@patch("tools.direct_query.get_db")
def test_flights_by_airline_tk(mock_get_db):
    mock_get_db.return_value = _mock_db([
        ("TK1", "IST", "JFK", "en-route", 35000, 900, 83, None,
         "2026-07-01 10:00", "2026-07-01 20:00"),
        ("TK5", "IST", "ORD", "en-route", 33000, 975, None, None,
         "2026-07-01 11:17", "2026-07-01 20:15"),
    ])
    results = get_flights_by_airline("TK")
    assert len(results) == 2
    assert all(f["flight_id"].startswith("TK") for f in results)


@patch("tools.direct_query.get_db")
def test_flights_by_airline_unknown(mock_get_db):
    mock_get_db.return_value = _mock_db([])
    assert get_flights_by_airline("XX") == []


# ── get_altitude_trend ─────────────────────────────────────

@patch("tools.direct_query.get_db")
def test_altitude_trend_climbing_via_vspeed(mock_get_db):
    mock_get_db.return_value = _mock_db([
        ("TK1", 35000, 34500, 12, "en-route")
    ])
    r = get_altitude_trend("TK1")
    assert r["trend"] == "climbing"
    assert "12" in r["detail"]


@patch("tools.direct_query.get_db")
def test_altitude_trend_descending_via_vspeed(mock_get_db):
    mock_get_db.return_value = _mock_db([
        ("TK1", 10000, 12000, -18, "en-route")
    ])
    r = get_altitude_trend("TK1")
    assert r["trend"] == "descending"


@patch("tools.direct_query.get_db")
def test_altitude_trend_level_vspeed_zero(mock_get_db):
    mock_get_db.return_value = _mock_db([
        ("TK1", 35000, 35000, 0, "en-route")
    ])
    r = get_altitude_trend("TK1")
    assert r["trend"] == "level"


@patch("tools.direct_query.get_db")
def test_altitude_trend_fallback_to_prev_alt_diff(mock_get_db):
    # No v_speed, falls back to prev_altitude_ft diff
    mock_get_db.return_value = _mock_db([
        ("TK1", 35000, 34000, None, "en-route")
    ])
    r = get_altitude_trend("TK1")
    assert r["trend"] == "climbing"


@patch("tools.direct_query.get_db")
def test_altitude_trend_ignores_absurd_diff(mock_get_db):
    # >3000 ft diff with no v_speed → sanity cap → unknown
    mock_get_db.return_value = _mock_db([
        ("TK1", 35000, 8000, None, "en-route")
    ])
    r = get_altitude_trend("TK1")
    assert r["trend"] == "unknown"


@patch("tools.direct_query.get_db")
def test_altitude_trend_unknown_flight(mock_get_db):
    mock_get_db.return_value = _mock_db([])
    assert get_altitude_trend("ZZ999") is None


# ── get_scheduled_times ────────────────────────────────────

@patch("tools.direct_query.get_db")
def test_scheduled_times_full_data(mock_get_db):
    mock_get_db.return_value = _mock_db([
        ("SV258", "IST", "MED", "en-route",
         "2026-07-01 10:17", "2026-07-01 14:03",
         "2026-07-01 10:17", "2026-07-01 14:16",
         None, 13)
    ])
    r = get_scheduled_times("SV258")
    assert r["dep_scheduled"] == "10:17 UTC"
    assert r["arr_scheduled"] == "14:03 UTC"
    assert r["arr_estimated"] == "14:16 UTC"
    assert r["arr_delayed"] == 13
    assert r["dep_delayed"] is None


@patch("tools.direct_query.get_db")
def test_scheduled_times_no_data(mock_get_db):
    mock_get_db.return_value = _mock_db([
        ("RJ261", "IST", "AMM", "en-route",
         None, None, None, None, None, None)
    ])
    r = get_scheduled_times("RJ261")
    assert r["dep_scheduled"] is None
    assert r["arr_estimated"] is None


@patch("tools.direct_query.get_db")
def test_scheduled_times_unknown_flight(mock_get_db):
    mock_get_db.return_value = _mock_db([])
    assert get_scheduled_times("ZZ999") is None


# ============================================================
# agent.llm_state — quota-aware provider cooldowns (429/503)
# ============================================================
# The reliability core: a failing provider is benched (not surfaced), and
# the *kind* of failure decides for how long. These lock in the exact
# classification the failover chain depends on — a misclassification here
# would either bench a healthy provider for 30 min or hammer a dead one
# every 75s all day.

import agent.llm_state as llm_state_mod


@pytest.mark.parametrize("error_str", [
    "Error code: 429 - too many requests",
    "rate_limit_exceeded",
    "RATE LIMIT reached",                                  # case-insensitive
    "quota exceeded for this model",
    "resource_exhausted",
    "This model is currently experiencing high demand",   # Gemini 503 wording
    "503 Service Unavailable",
    "The model is overloaded, please try again",
    "server temporarily unavailable",
])
def test_looks_like_rate_limit_true(error_str):
    assert llm_state_mod.looks_like_rate_limit(error_str) is True


@pytest.mark.parametrize("error_str", [
    "400 Bad Request: invalid tool schema",
    "AuthenticationError: invalid api key",
    "ValueError: something unrelated broke",
    "",
])
def test_looks_like_rate_limit_false(error_str):
    # A non-transient error must NOT be treated as "busy" — otherwise a real
    # bug (bad schema, wrong key) would be silently swallowed by failover.
    assert llm_state_mod.looks_like_rate_limit(error_str) is False


def test_is_exhausted_unknown_provider_is_false():
    assert llm_state_mod.is_exhausted("provider-never-benched") is False


def test_per_minute_429_uses_short_cooldown():
    ls = llm_state_mod
    with patch("agent.llm_state.time.time", return_value=1000.0):
        ls.mark_exhausted("t_short", "Error 429: rate limit, requests per minute exceeded")
    with patch("agent.llm_state.time.time", return_value=1000.0 + ls.SHORT_COOLDOWN - 1):
        assert ls.is_exhausted("t_short") is True     # still benched inside the window
    with patch("agent.llm_state.time.time", return_value=1000.0 + ls.SHORT_COOLDOWN + 1):
        assert ls.is_exhausted("t_short") is False    # recovered just after


def test_daily_quota_uses_long_cooldown():
    ls = llm_state_mod
    with patch("agent.llm_state.time.time", return_value=2000.0):
        ls.mark_exhausted("t_long", "Rate limit reached on tokens per day (TPD)")
    # a short cooldown would already have expired here — a daily quota must not
    with patch("agent.llm_state.time.time", return_value=2000.0 + ls.SHORT_COOLDOWN + 5):
        assert ls.is_exhausted("t_long") is True
    with patch("agent.llm_state.time.time", return_value=2000.0 + ls.LONG_COOLDOWN + 1):
        assert ls.is_exhausted("t_long") is False


def test_gemini_billing_message_uses_long_cooldown():
    # Gemini's free-tier daily limit says "check your plan and billing", with
    # no "per day" text — it must still trigger the long cooldown.
    ls = llm_state_mod
    with patch("agent.llm_state.time.time", return_value=3000.0):
        ls.mark_exhausted("t_gem", "429 exceeded quota, check your plan and billing details")
    with patch("agent.llm_state.time.time", return_value=3000.0 + ls.SHORT_COOLDOWN + 5):
        assert ls.is_exhausted("t_gem") is True


# ============================================================
# agent.motor — shared-thread sanitization & reasoning stripping
# ============================================================
# Imported lazily so the (heavier) agent module only loads if these run.

def _motor():
    import agent.motor as m
    return m


def test_sanitize_history_drops_empty_assistant_messages():
    # One provider's failed turn can leave a contentless assistant message
    # that others (Mistral 3240) reject wholesale.
    from langchain_core.messages import HumanMessage, AIMessage
    m = _motor()
    msgs = [HumanMessage(content="TK1 nerede?"),
            AIMessage(content=""),
            AIMessage(content="TK1 en route to JFK.")]
    out = m._sanitize_history({"messages": msgs})["llm_input_messages"]
    assert len(out) == 2
    assert not any(isinstance(x, AIMessage) and not x.content and not x.tool_calls for x in out)


def test_sanitize_history_dedupes_tool_calls_and_results():
    # A bad chunk merge can duplicate a tool_call id (Mistral 3230), which
    # then poisons the thread for that provider permanently.
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
    m = _motor()
    ai = AIMessage(content="", tool_calls=[
        {"name": "get_flight_by_id", "args": {"flight_id": "TK1"}, "id": "call_a"},
        {"name": "get_flight_by_id", "args": {"flight_id": "TK1"}, "id": "call_a"},
    ])
    t1 = ToolMessage(content="result 1", tool_call_id="call_a")
    t2 = ToolMessage(content="result 2", tool_call_id="call_a")
    out = m._sanitize_history({"messages": [HumanMessage(content="q"), ai, t1, t2]})["llm_input_messages"]
    kept_ai = [x for x in out if isinstance(x, AIMessage)]
    kept_tool = [x for x in out if isinstance(x, ToolMessage)]
    assert len(kept_ai[0].tool_calls) == 1
    assert len(kept_tool) == 1


def test_sanitize_history_keeps_normal_conversation_intact():
    from langchain_core.messages import HumanMessage, AIMessage
    m = _motor()
    msgs = [HumanMessage(content="TK1 nerede?"), AIMessage(content="TK1 JFK'e gidiyor.")]
    out = m._sanitize_history({"messages": msgs})["llm_input_messages"]
    assert len(out) == 2


@pytest.mark.parametrize("text,must_have,must_not_have", [
    ("Let me check the flights. TK1 is at 35000 ft.", "TK1 is at 35000 ft.", "Let me check"),
    ("tool_get_flight_by_id kullanacağım. TK1 35000 fitte.", "35000 fitte", "kullanacağım"),
])
def test_strip_reasoning_removes_thinking_keeps_answer(text, must_have, must_not_have):
    m = _motor()
    out = m._strip_reasoning(text)
    assert must_have in out
    assert must_not_have not in out


def test_strip_reasoning_leaves_clean_answer_untouched():
    m = _motor()
    clean = "TK1 is en route to JFK at 35000 ft."
    assert m._strip_reasoning(clean) == clean


@pytest.mark.parametrize("content,expected", [
    ("plain string", "plain string"),
    ([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}], "ab"),
    ([], ""),
    (12345, ""),
])
def test_text_from_content(content, expected):
    m = _motor()
    assert m._text_from_content(content) == expected


# ============================================================
# router.detect_complexity — diacritic-insensitive chain queries
# ============================================================
# Turkish is typed both with and without diacritics; a chain query must be
# recognized either way (this regressed for the diacritic-free form before).

@pytest.mark.parametrize("question", [
    "en yuksekte ucan ucak nereye inecek",
    "en hizli ucak ne zaman iner",
    "en yuksekte ucan ucagin gidecegi sehirde hava nasil",
])
def test_router_chain_query_diacritic_insensitive(detect_complexity, question):
    assert detect_complexity(question) == "complex"
