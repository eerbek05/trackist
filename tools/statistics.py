import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.postgres import get_db
from tools.direct_query import ACTIVE_WINDOW, UTC_NOW_SQL, utcnow
from geopy.geocoders import Nominatim

import math
import pandas as pd

# Havalimanı koordinatları — bir kez yükle
_airports_df = None

def get_airport_coords(iata_code):
    global _airports_df
    if _airports_df is None:
        csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "airports.csv")
        _airports_df = pd.read_csv(csv_path)

    row = _airports_df[_airports_df["iata_code"] == iata_code]
    if row.empty:
        return None

    # airports.csv stores "coordinates" as "lat, lng" (e.g. IST is
    # "41.274874, 28.732136" — 41 is its latitude), not "lng, lat".
    coords = row.iloc[0]["coordinates"]
    lat, lng = map(float, coords.split(", "))
    return lat, lng

def get_airport_info(iata_code):
    # Like get_airport_coords, but also returns the airport's display name —
    # used to label departure/arrival airports on the map.
    global _airports_df
    if _airports_df is None:
        csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "airports.csv")
        _airports_df = pd.read_csv(csv_path)

    row = _airports_df[_airports_df["iata_code"] == iata_code]
    if row.empty:
        return None

    r = row.iloc[0]
    lat, lng = map(float, r["coordinates"].split(", "))
    return {
        "iata_code": iata_code,
        "name": r["name"],
        "municipality": r["municipality"],
        "lat": lat,
        "lng": lng
    }

def _haversine_km(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def get_remaining_distance(flight_id, arr_iata):
    from tools.direct_query import get_flight_by_id

    flight = get_flight_by_id(flight_id)
    if not flight:
        return None

    lat1 = flight.get("lat")
    lng1 = flight.get("lng")

    if lat1 is None or lng1 is None:
        return None

    arr_coords = get_airport_coords(arr_iata)
    if not arr_coords:
        return None

    lat2, lng2 = arr_coords
    return round(_haversine_km(lat1, lng1, lat2, lng2))

def estimate_arrival(flight_id, arr_iata):
    from datetime import timedelta
    from tools.direct_query import get_flight_by_id

    flight = get_flight_by_id(flight_id)
    if not flight:
        return None

    lat1 = flight.get("lat")
    lng1 = flight.get("lng")
    speed = flight.get("speed_kmh")

    if lat1 is None or lng1 is None or not speed or speed <= 0:
        return None

    arr_coords = get_airport_coords(arr_iata)
    if not arr_coords:
        return None

    lat2, lng2 = arr_coords
    mesafe_km = _haversine_km(lat1, lng1, lat2, lng2)

    kalan_saat = mesafe_km / speed
    tahmini_inis = utcnow() + timedelta(hours=kalan_saat)

    return {
        "flight_id": flight_id,
        "kalan_km": round(mesafe_km),
        "kalan_sure_dk": round(kalan_saat * 60),
        "tahmini_inis_utc": tahmini_inis.strftime("%H:%M"),
        "tahmini_inis_dt": tahmini_inis,  # naive UTC, for local-time conversion
    }

def get_flights_in_air_count():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT COUNT(*) FROM flights
            WHERE status = 'en-route'
              AND updated_at > {UTC_NOW_SQL} - INTERVAL %s
        """, (ACTIVE_WINDOW,))
        count = cur.fetchone()[0]
    finally:
        conn.close()
    return count

def get_flights_in_air_list():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT flight_id, from_airport, to_airport FROM flights
            WHERE status = 'en-route'
              AND updated_at > {UTC_NOW_SQL} - INTERVAL %s
        """, (ACTIVE_WINDOW,))
        rows = cur.fetchall()
    finally:
        conn.close()
    return [{"flight_id": r[0], "from": r[1], "to": r[2]} for r in rows]

def get_fastest_flight():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT flight_id, from_airport, to_airport, speed_kmh FROM flights
            WHERE status = 'en-route'
              AND updated_at > {UTC_NOW_SQL} - INTERVAL %s
            ORDER BY speed_kmh DESC NULLS LAST LIMIT 1
        """, (ACTIVE_WINDOW,))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"flight_id": row[0], "from": row[1], "to": row[2], "speed_kmh": row[3]}

def get_slowest_flight():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT flight_id, from_airport, to_airport, speed_kmh FROM flights
            WHERE speed_kmh > 0 AND status = 'en-route'
              AND updated_at > {UTC_NOW_SQL} - INTERVAL %s
            ORDER BY speed_kmh ASC LIMIT 1
        """, (ACTIVE_WINDOW,))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"flight_id": row[0], "from": row[1], "to": row[2], "speed_kmh": row[3]}

def get_all_destinations():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT DISTINCT to_airport FROM flights
            WHERE updated_at > {UTC_NOW_SQL} - INTERVAL %s
            ORDER BY to_airport
        """, (ACTIVE_WINDOW,))
        rows = cur.fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]

def get_top_destinations_from_istanbul():
    # Covers both Istanbul airports (IST and SAW).
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT to_airport, COUNT(*) as sefer_sayisi
            FROM flights
            WHERE from_airport IN ('IST', 'SAW')
              AND updated_at > {UTC_NOW_SQL} - INTERVAL %s
            GROUP BY to_airport
            ORDER BY sefer_sayisi DESC
        """, (ACTIVE_WINDOW,))
        rows = cur.fetchall()
    finally:
        conn.close()
    return [{"destination": r[0], "count": r[1]} for r in rows]

def get_highest_flight():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT flight_id, from_airport, to_airport, altitude_ft
            FROM flights
            WHERE status = 'en-route'
              AND updated_at > {UTC_NOW_SQL} - INTERVAL %s
            ORDER BY altitude_ft DESC NULLS LAST
            LIMIT 1
        """, (ACTIVE_WINDOW,))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"flight_id": row[0], "from": row[1], "to": row[2], "altitude_ft": row[3]}

def get_flights_on_route(dep_iata, arr_iata):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT COUNT(*), array_agg(flight_id)
            FROM flights
            WHERE from_airport = %s AND to_airport = %s
              AND status = 'en-route'
              AND updated_at > {UTC_NOW_SQL} - INTERVAL %s
        """, (dep_iata, arr_iata, ACTIVE_WINDOW))
        row = cur.fetchone()
    finally:
        conn.close()
    return {"count": row[0], "flights": row[1]}


# Reverse-geocode cache — a flight moves ~15 km/min, so at 0.2° (~20 km)
# resolution repeated questions about the same flight in a conversation hit
# the cache instead of Nominatim (which rate-limits at 1 req/s).
_country_cache = {}

def get_current_country(flight_id):
    from tools.direct_query import get_flight_by_id
    flight = get_flight_by_id(flight_id)
    if not flight or flight.get("lat") is None:
        return None

    cache_key = (round(flight["lat"] / 0.2), round(flight["lng"] / 0.2))
    country = _country_cache.get(cache_key)
    if country is None:
        geolocator = Nominatim(user_agent="trackist-chatbot", timeout=5)
        try:
            location = geolocator.reverse(f"{flight['lat']}, {flight['lng']}", language="en", timeout=5)
        except Exception:
            return None
        if not location:
            return None
        country = location.raw.get("address", {}).get("country", "unknown")
        _country_cache[cache_key] = country

    return {"flight_id": flight_id, "country": country, "lat": flight["lat"], "lng": flight["lng"]}


def get_total_route_distance(dep_iata, arr_iata):
    dep_coords = get_airport_coords(dep_iata)
    arr_coords = get_airport_coords(arr_iata)

    if not dep_coords or not arr_coords:
        return None

    lat1, lng1 = dep_coords
    lat2, lng2 = arr_coords
    return round(_haversine_km(lat1, lng1, lat2, lng2))

def get_route_completion(flight_id, dep_iata, arr_iata):
    toplam = get_total_route_distance(dep_iata, arr_iata)
    kalan = get_remaining_distance(flight_id, arr_iata)

    # "kalan == 0" is a valid state (arrived / on final) — only None means
    # the calculation failed, so don't treat zero as falsy here.
    if not toplam or kalan is None:
        return None

    tamamlanan = max(toplam - kalan, 0)
    yuzde = min(round((tamamlanan / toplam) * 100), 100)

    return {
        "flight_id": flight_id,
        "toplam_km": toplam,
        "kalan_km": kalan,
        "tamamlanan_km": tamamlanan,
        "yuzde": yuzde
    }

THY_SEAT_MAPS = {
    # Geniş gövde — B777/B787/A330 tipi
    "B77W": {"window": ["A","K"], "aisle": ["C","H"]},
    "B77L": {"window": ["A","K"], "aisle": ["C","H"]},
    "B773": {"window": ["A","K"], "aisle": ["C","H"]},
    "B788": {"window": ["A","K"], "aisle": ["C","H"]},
    "B789": {"window": ["A","K"], "aisle": ["C","H"]},
    "A333": {"window": ["A","K"], "aisle": ["C","H"]},
    "A332": {"window": ["A","K"], "aisle": ["C","H"]},
    # Dar gövde — 3-3
    "A321": {"window": ["A","F"], "aisle": ["C","D"]},
    "A21N": {"window": ["A","F"], "aisle": ["C","D"]},
    "A320": {"window": ["A","F"], "aisle": ["C","D"]},
    "A319": {"window": ["A","F"], "aisle": ["C","D"]},
    "B738": {"window": ["A","F"], "aisle": ["C","D"]},
    "B739": {"window": ["A","F"], "aisle": ["C","D"]},
    "B39M": {"window": ["A","F"], "aisle": ["C","D"]},
    "B38M": {"window": ["A","F"], "aisle": ["C","D"]},
}

def get_seat_type(aircraft_type, seat):
    # Returns English tokens ("window" / "aisle" / "unknown") — the agent
    # prompt translates tool output into the user's language.
    seat_letter = ''.join(filter(str.isalpha, seat)).upper()
    seat_map = THY_SEAT_MAPS.get(aircraft_type.upper())
    if not seat_map:
        return "unknown"
    if seat_letter in seat_map["window"]:
        return "window"
    elif seat_letter in seat_map["aisle"]:
        return "aisle"
    return "unknown"
