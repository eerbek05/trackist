import sys
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.postgres import get_db

STALE_MINUTES = 121
STALE_AFTER   = timedelta(minutes=STALE_MINUTES)
ACTIVE_WINDOW = f"{STALE_MINUTES} minutes"

# updated_at is stored as naive UTC (the poller writes UTC timestamps).
# NOW() returns the DB session's time zone, so every freshness filter must
# compare in UTC explicitly — on a non-UTC server/DB the staleness window
# would otherwise shift by hours and either hide live flights or flag
# everything as stale.
UTC_NOW_SQL = "(NOW() AT TIME ZONE 'UTC')"


def utcnow():
    """Naive UTC now — directly comparable to the naive-UTC updated_at column."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_stale(updated_at, now=None):
    if not updated_at:
        return False
    now = now or utcnow()
    return now - updated_at > STALE_AFTER


def _fmt_time(dt_str):
    if not dt_str:
        return None
    m = re.search(r"(\d{2}):(\d{2})", dt_str)
    return f"{m.group(1)}:{m.group(2)} UTC" if m else dt_str


# ── Single flight ──────────────────────────────────────────────────────────────

def get_flight_by_id(flight_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT flight_id, from_airport, to_airport, speed_kmh,
                   altitude_ft, departure, arrival, aircraft, status, updated_at,
                   lat, lng, heading, prev_altitude_ft, v_speed_fpm,
                   dep_gate, arr_gate, dep_terminal, arr_terminal,
                   arr_baggage, dep_delayed, arr_delayed, dep_estimated, arr_estimated
            FROM flights
            WHERE flight_id = %s
        """, (flight_id,))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None

    updated_at = row[9]
    return {
        "flight_id":      row[0],
        "from":           row[1],
        "to":             row[2],
        "speed_kmh":      row[3],
        "altitude_ft":    row[4],
        "departure":      row[5],
        "arrival":        row[6],
        "aircraft":       row[7],
        "status":         row[8],
        "updated_at":     updated_at.strftime("%H:%M UTC") if updated_at else "bilinmiyor",
        "lat":            row[10],
        "lng":            row[11],
        "heading":        row[12],
        "prev_altitude_ft": row[13],
        "v_speed_fpm":    row[14],
        "dep_gate":       row[15],
        "arr_gate":       row[16],
        "dep_terminal":   row[17],
        "arr_terminal":   row[18],
        "arr_baggage":    row[19],
        "dep_delayed":    row[20],
        "arr_delayed":    row[21],
        "dep_estimated":  row[22],
        "arr_estimated":  row[23],
        "stale":          is_stale(updated_at),
    }


def get_gate_and_terminal(flight_id: str) -> Optional[dict]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT flight_id, from_airport, to_airport,
                   dep_gate, arr_gate, dep_terminal, arr_terminal,
                   dep_delayed, arr_delayed, arr_baggage,
                   departure, arrival, dep_estimated, arr_estimated, status
            FROM flights WHERE flight_id = %s
        """, (flight_id.upper(),))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None

    is_dep = row[1] == "IST"
    return {
        "flight_id":    row[0],
        "from":         row[1],
        "to":           row[2],
        "dep_gate":     row[3],
        "arr_gate":     row[4],
        "dep_terminal": row[5],
        "arr_terminal": row[6],
        "dep_delayed":  row[7],
        "arr_delayed":  row[8],
        "arr_baggage":  row[9],
        "dep_time":     _fmt_time(row[12] or row[10]),
        "arr_time":     _fmt_time(row[13] or row[11]),
        "status":       row[14],
        "gate":         row[3] if is_dep else row[4],
        "terminal":     row[5] if is_dep else row[6],
        "delay_min":    row[7] if is_dep else row[8],
    }


def get_baggage_claim(flight_id: str) -> Optional[dict]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT flight_id, from_airport, to_airport,
                   arr_baggage, arr_gate, arr_estimated, status
            FROM flights WHERE flight_id = %s
        """, (flight_id.upper(),))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "flight_id":   row[0],
        "from":        row[1],
        "to":          row[2],
        "arr_baggage": row[3],
        "arr_gate":    row[4],
        "arr_time":    _fmt_time(row[5]),
        "status":      row[6],
    }


def get_altitude_trend(flight_id: str) -> Optional[dict]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT flight_id, altitude_ft, prev_altitude_ft, v_speed_fpm, status
            FROM flights WHERE flight_id = %s
        """, (flight_id.upper(),))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None

    alt      = row[1]
    prev_alt = row[2]
    vspeed   = row[3]
    trend    = "unknown"
    detail   = None

    if vspeed is not None:
        if vspeed > 1:
            trend  = "climbing"
            detail = f"+{round(vspeed)} km/h dikey hız"
        elif vspeed < -1:
            trend  = "descending"
            detail = f"{round(vspeed)} km/h dikey hız"
        else:
            trend = "level"
    elif alt and prev_alt:
        diff = alt - prev_alt
        if abs(diff) <= 3000:
            if diff > 100:
                trend  = "climbing"
                detail = f"+{round(diff)} ft since last fix"
            elif diff < -100:
                trend  = "descending"
                detail = f"{round(diff)} ft since last fix"
            else:
                trend = "level"

    return {
        "flight_id":   row[0],
        "altitude_ft": alt,
        "trend":       trend,
        "detail":      detail,
        "status":      row[4],
    }


def get_scheduled_times(flight_id: str) -> Optional[dict]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT flight_id, from_airport, to_airport, status,
                   departure, arrival, dep_estimated, arr_estimated,
                   dep_delayed, arr_delayed
            FROM flights WHERE flight_id = %s
        """, (flight_id.upper(),))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "flight_id":     row[0],
        "from":          row[1],
        "to":            row[2],
        "status":        row[3],
        "dep_scheduled": _fmt_time(row[4]),
        "arr_scheduled": _fmt_time(row[5]),
        "dep_estimated": _fmt_time(row[6]),
        "arr_estimated": _fmt_time(row[7]),
        "dep_delayed":   row[8],
        "arr_delayed":   row[9],
        # Raw 'YYYY-MM-DD HH:MM' UTC strings — the chatbot tool layer converts
        # these to airport-local time in code (the LLM must not do tz math).
        "dep_scheduled_raw": row[4],
        "arr_scheduled_raw": row[5],
        "dep_estimated_raw": row[6],
        "arr_estimated_raw": row[7],
    }


# ── Flight lists ───────────────────────────────────────────────────────────────

def get_delayed_flights(min_delay: int = 1) -> List[dict]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT flight_id, from_airport, to_airport, status,
                   dep_delayed, arr_delayed, dep_estimated, arr_estimated
            FROM flights
            WHERE updated_at > {UTC_NOW_SQL} - INTERVAL %s
              AND (dep_delayed >= %s OR arr_delayed >= %s)
            ORDER BY GREATEST(COALESCE(dep_delayed,0), COALESCE(arr_delayed,0)) DESC
        """, (ACTIVE_WINDOW, min_delay, min_delay))
        rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "flight_id":   r[0],
            "from":        r[1],
            "to":          r[2],
            "status":      r[3],
            "dep_delayed": r[4],
            "arr_delayed": r[5],
            "dep_time":    _fmt_time(r[6]),
            "arr_time":    _fmt_time(r[7]),
            "max_delay":   max(r[4] or 0, r[5] or 0),
        }
        for r in rows
    ]


def get_flights_by_status(status: str) -> List[dict]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT flight_id, from_airport, to_airport, status,
                   altitude_ft, speed_kmh, dep_estimated, arr_estimated
            FROM flights
            WHERE updated_at > {UTC_NOW_SQL} - INTERVAL %s
              AND LOWER(status) = LOWER(%s)
            ORDER BY flight_id
        """, (ACTIVE_WINDOW, status))
        rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "flight_id":   r[0],
            "from":        r[1],
            "to":          r[2],
            "status":      r[3],
            "altitude_ft": r[4],
            "speed_kmh":   r[5],
            "dep_time":    _fmt_time(r[6]),
            "arr_time":    _fmt_time(r[7]),
        }
        for r in rows
    ]


def get_flights_arriving_ist() -> List[dict]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT flight_id, from_airport, status,
                   arr_gate, arr_terminal, arr_baggage,
                   arr_delayed, dep_estimated, arr_estimated, altitude_ft
            FROM flights
            WHERE to_airport = 'IST'
              AND updated_at > {UTC_NOW_SQL} - INTERVAL %s
            ORDER BY arr_estimated NULLS LAST, flight_id
        """, (ACTIVE_WINDOW,))
        rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "flight_id":    r[0],
            "from":         r[1],
            "status":       r[2],
            "arr_gate":     r[3],
            "arr_terminal": r[4],
            "arr_baggage":  r[5],
            "arr_delayed":  r[6],
            "dep_time":     _fmt_time(r[7]),
            "arr_time":     _fmt_time(r[8]),
            "altitude_ft":  r[9],
        }
        for r in rows
    ]


def get_flights_departing_ist() -> List[dict]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT flight_id, to_airport, status,
                   dep_gate, dep_terminal, dep_delayed,
                   dep_estimated, arr_estimated, altitude_ft
            FROM flights
            WHERE from_airport = 'IST'
              AND updated_at > {UTC_NOW_SQL} - INTERVAL %s
            ORDER BY dep_estimated NULLS LAST, flight_id
        """, (ACTIVE_WINDOW,))
        rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "flight_id":    r[0],
            "to":           r[1],
            "status":       r[2],
            "dep_gate":     r[3],
            "dep_terminal": r[4],
            "dep_delayed":  r[5],
            "dep_time":     _fmt_time(r[6]),
            "arr_time":     _fmt_time(r[7]),
            "altitude_ft":  r[8],
        }
        for r in rows
    ]


def get_flights_by_airline(airline_iata: str) -> List[dict]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT flight_id, from_airport, to_airport, status,
                   altitude_ft, speed_kmh, dep_delayed, arr_delayed,
                   dep_estimated, arr_estimated
            FROM flights
            WHERE flight_id LIKE %s
              AND updated_at > {UTC_NOW_SQL} - INTERVAL %s
            ORDER BY flight_id
        """, (f"{airline_iata.upper()}%", ACTIVE_WINDOW))
        rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "flight_id":   r[0],
            "from":        r[1],
            "to":          r[2],
            "status":      r[3],
            "altitude_ft": r[4],
            "speed_kmh":   r[5],
            "dep_delayed": r[6],
            "arr_delayed": r[7],
            "dep_time":    _fmt_time(r[8]),
            "arr_time":    _fmt_time(r[9]),
        }
        for r in rows
    ]
