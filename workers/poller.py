import os
import sys
import time
import requests
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from dotenv import load_dotenv
from database.postgres import get_db
from workers.term import banner, ok, warn, err
from workers.cleanup import run_cleanup_pass

load_dotenv()

_key1 = os.getenv("AIRLABS_KEY", "")
_key2 = os.getenv("AIRLABS_KEY_2", "") or _key1
API_KEYS = [k for k in [_key1, _key2] if k]

if not API_KEYS:
    raise RuntimeError("AIRLABS_KEY is not set in .env")

_key_index = 0

def next_key():
    global _key_index
    key = API_KEYS[_key_index % len(API_KEYS)]
    _key_index += 1
    return key

POLL_INTERVAL = 3600


def _naive_utc(dt):
    return dt.replace(tzinfo=None)


def _safe_status(f):
    status = f.get("status", "")
    alt = int(f.get("alt", 0) or 0)
    spd = int(f.get("speed", 0) or 0)
    if status == "landed" and (alt > 500 or spd > 100):
        return "en-route"
    if status == "en-route" and alt <= 100 and spd <= 50:
        return "landed"
    return status


# ── /flights ───────────────────────────────────────────────────────────────────

def fetch_flights():
    dep = requests.get(
        "https://airlabs.co/api/v9/flights",
        params={"api_key": next_key(), "dep_iata": "IST"},
        timeout=10
    ).json().get("response", [])

    arr = requests.get(
        "https://airlabs.co/api/v9/flights",
        params={"api_key": next_key(), "arr_iata": "IST"},
        timeout=10
    ).json().get("response", [])

    all_flights = {f["flight_iata"]: f for f in dep + arr if f.get("flight_iata")}
    return list(all_flights.values())


def save_flights(flights):
    conn = get_db()
    saved = 0
    try:
        cur = conn.cursor()
        for f in flights:
            flight_iata = f.get("flight_iata")
            if not flight_iata:
                continue
            try:
                # updated_at is always naive UTC — every reader (staleness
                # filters, is_stale) compares against UTC, never server-local
                # time.
                updated_unix = f.get("updated")
                updated_at = (
                    _naive_utc(datetime.fromtimestamp(updated_unix, tz=timezone.utc))
                    if updated_unix
                    else _naive_utc(datetime.now(timezone.utc))
                )

                # If the route changed (same flight_id, different destination) delete the stale record
                new_dep = f.get("dep_iata", "")
                new_arr = f.get("arr_iata", "")
                if new_dep and new_arr:
                    cur.execute("""
                        DELETE FROM flights
                        WHERE flight_id = %s
                          AND (from_airport <> %s OR to_airport <> %s)
                          AND (from_airport <> '' AND to_airport <> '')
                    """, (flight_iata, new_dep, new_arr))

                heading     = f.get("dir")
                heading     = int(heading) if heading is not None else None
                v_speed     = f.get("v_speed")
                v_speed_fpm = int(v_speed) if v_speed is not None else None
                flight_icao = f.get("flight_icao") or None

                cur.execute("""
                    INSERT INTO flights (
                        flight_id, flight_icao, from_airport, to_airport,
                        speed_kmh, altitude_ft, departure, arrival,
                        aircraft, status, updated_at, lat, lng, heading, v_speed_fpm
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (flight_id) DO UPDATE SET
                        flight_icao  = EXCLUDED.flight_icao,
                        from_airport = CASE WHEN EXCLUDED.from_airport <> '' THEN EXCLUDED.from_airport ELSE flights.from_airport END,
                        to_airport   = CASE WHEN EXCLUDED.to_airport   <> '' THEN EXCLUDED.to_airport   ELSE flights.to_airport   END,
                        speed_kmh    = EXCLUDED.speed_kmh,
                        altitude_ft  = EXCLUDED.altitude_ft,
                        status       = CASE
                            WHEN EXCLUDED.status = 'landed' AND (EXCLUDED.altitude_ft > 500 OR EXCLUDED.speed_kmh > 100) THEN 'en-route'
                            WHEN EXCLUDED.status = 'en-route' AND EXCLUDED.altitude_ft <= 100 AND EXCLUDED.speed_kmh <= 50 THEN 'landed'
                            ELSE EXCLUDED.status
                        END,
                        updated_at   = EXCLUDED.updated_at,
                        lat          = EXCLUDED.lat,
                        lng          = EXCLUDED.lng,
                        heading      = EXCLUDED.heading,
                        v_speed_fpm  = EXCLUDED.v_speed_fpm,
                        departure    = CASE WHEN EXCLUDED.departure <> '' THEN EXCLUDED.departure ELSE flights.departure END,
                        arrival      = CASE WHEN EXCLUDED.arrival   <> '' THEN EXCLUDED.arrival   ELSE flights.arrival   END
                """, (
                    flight_iata, flight_icao,
                    f.get("dep_iata", ""), f.get("arr_iata", ""),
                    int(f.get("speed", 0) or 0), int(f.get("alt", 0) or 0),
                    f.get("dep_time", ""), f.get("arr_time", ""),
                    f.get("aircraft_icao", ""), _safe_status(f),
                    updated_at, f.get("lat"), f.get("lng"), heading, v_speed_fpm,
                ))
                saved += 1
            except Exception as e:
                warn("flights", f"{flight_iata}: {e}")

        conn.commit()
    finally:
        conn.close()
    return saved


# ── /schedules ─────────────────────────────────────────────────────────────────

def fetch_schedules():
    dep = requests.get(
        "https://airlabs.co/api/v9/schedules",
        params={"api_key": next_key(), "dep_iata": "IST"},
        timeout=15,
    ).json().get("response", [])

    arr = requests.get(
        "https://airlabs.co/api/v9/schedules",
        params={"api_key": next_key(), "arr_iata": "IST"},
        timeout=15,
    ).json().get("response", [])

    by_iata = {}
    for f in dep + arr:
        iata = f.get("flight_iata")
        if iata:
            by_iata[iata] = f
    return list(by_iata.values())


def save_schedules(flights):
    conn = get_db()
    updated = 0
    try:
        cur = conn.cursor()
        for f in flights:
            iata = f.get("flight_iata")
            if not iata:
                continue
            cur.execute("""
                UPDATE flights SET
                    dep_gate      = COALESCE(%s, dep_gate),
                    arr_gate      = COALESCE(%s, arr_gate),
                    dep_terminal  = COALESCE(%s, dep_terminal),
                    arr_terminal  = COALESCE(%s, arr_terminal),
                    arr_baggage   = COALESCE(%s, arr_baggage),
                    dep_delayed   = COALESCE(%s, dep_delayed),
                    arr_delayed   = COALESCE(%s, arr_delayed),
                    departure     = COALESCE(%s, departure),
                    arrival       = COALESCE(%s, arrival),
                    dep_estimated = COALESCE(%s, dep_estimated),
                    arr_estimated = COALESCE(%s, arr_estimated),
                    status        = COALESCE(%s, status)
                WHERE flight_id = %s
            """, (
                f.get("dep_gate"), f.get("arr_gate"),
                f.get("dep_terminal"), f.get("arr_terminal"),
                f.get("arr_baggage"),
                f.get("dep_delayed"), f.get("arr_delayed"),
                f.get("dep_time_utc"), f.get("arr_time_utc"),
                f.get("dep_estimated_utc") or f.get("dep_actual_utc"),
                f.get("arr_estimated_utc") or f.get("arr_actual_utc"),
                f.get("status") if f.get("status") != "landed" else None,
                iata,
            ))
            if cur.rowcount:
                updated += 1
        conn.commit()
    finally:
        conn.close()
    return updated


# ── Main loop ──────────────────────────────────────────────────────────────────

banner(
    "TrackIST · Poller",
    "AirLabs /flights + /schedules  →  PostgreSQL",
    f"interval: {POLL_INTERVAL}s   keys: {len(API_KEYS)}",
)

while True:
    try:
        flights = fetch_flights()
        n_saved = save_flights(flights)
        ok("flights", f"{n_saved}/{len(flights)} flights saved")
    except Exception as e:
        err("flights", str(e))

    try:
        schedules = fetch_schedules()
        n_updated = save_schedules(schedules)
        ok("schedules", f"{n_updated} flights updated  (gate / terminal / delay)")
    except Exception as e:
        err("schedules", str(e))

    try:
        run_cleanup_pass()
    except Exception as e:
        err("cleanup", str(e))

    time.sleep(POLL_INTERVAL)
