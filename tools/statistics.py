import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.postgres import get_db
from geopy.geocoders import Nominatim

import math
import os
import pandas as pd

# Havalimanı koordinatları — bir kez yükle
_airports_df = None

def get_airport_coords(iata_code):
    global _airports_df
    if _airports_df is None:
        csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "airports.csv")
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
        csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "airports.csv")
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

def get_remaining_distance(flight_id, arr_iata):
    from tools.direct_query import get_flight_by_id
    
    flight = get_flight_by_id(flight_id)
    if not flight:
        return None
    
    lat1 = flight.get("lat")
    lng1 = flight.get("lng")
    
    if not lat1 or not lng1:
        return None
    
    arr_coords = get_airport_coords(arr_iata)
    if not arr_coords:
        return None
    
    lat2, lng2 = arr_coords
    
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    mesafe_km = R * 2 * math.asin(math.sqrt(a))
    
    return round(mesafe_km)

def estimate_arrival(flight_id, arr_iata):
    from datetime import datetime, timedelta
    from tools.direct_query import get_flight_by_id

    flight = get_flight_by_id(flight_id)
    if not flight:
        return None

    lat1 = flight.get("lat")
    lng1 = flight.get("lng")
    speed = flight.get("speed_kmh")

    if not lat1 or not lng1 or not speed:
        return None

    arr_coords = get_airport_coords(arr_iata)
    if not arr_coords:
        return None

    lat2, lng2 = arr_coords

    # Haversine
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    mesafe_km = R * 2 * math.asin(math.sqrt(a))

    kalan_saat = mesafe_km / speed
    simdi = datetime.utcnow()
    tahmini_inis = simdi + timedelta(hours=kalan_saat)

    return {
        "flight_id": flight_id,
        "kalan_km": round(mesafe_km),
        "kalan_sure_dk": round(kalan_saat * 60),
        "tahmini_inis_utc": tahmini_inis.strftime("%H:%M"),
    }

def get_flights_in_air_count():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM flights WHERE status IN ('Havada', 'en-route')")
    count = cur.fetchone()[0]
    conn.close()
    return count

def get_flights_in_air_list():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT flight_id, from_airport, to_airport FROM flights WHERE status IN ('Havada', 'en-route')")
    rows = cur.fetchall()
    conn.close()
    return [{"flight_id": r[0], "from": r[1], "to": r[2]} for r in rows]

def get_fastest_flight():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT flight_id, from_airport, to_airport, speed_kmh FROM flights ORDER BY speed_kmh DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"flight_id": row[0], "from": row[1], "to": row[2], "speed_kmh": row[3]}

def get_slowest_flight():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT flight_id, from_airport, to_airport, speed_kmh FROM flights ORDER BY speed_kmh ASC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"flight_id": row[0], "from": row[1], "to": row[2], "speed_kmh": row[3]}

def get_longest_flight():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT flight_id, from_airport, to_airport, duration_minutes FROM flights ORDER BY duration_minutes DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"flight_id": row[0], "from": row[1], "to": row[2], "duration_minutes": row[3]}

def get_shortest_flight():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT flight_id, from_airport, to_airport, duration_minutes FROM flights ORDER BY duration_minutes ASC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"flight_id": row[0], "from": row[1], "to": row[2], "duration_minutes": row[3]}

def get_all_destinations():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT to_airport FROM flights ORDER BY to_airport")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_flights_to_airport(airport):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM flights WHERE to_airport ILIKE %s", (f"%{airport}%",))
    count = cur.fetchone()[0]
    conn.close()
    return count

def get_top_destinations_from_istanbul():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT to_airport, COUNT(*) as sefer_sayisi
        FROM flights
        WHERE from_airport ILIKE '%IST%'
           OR from_airport ILIKE '%SAW%'
        GROUP BY to_airport
        ORDER BY sefer_sayisi DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return [{"destination": r[0], "count": r[1]} for r in rows]

def get_highest_flight():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT flight_id, from_airport, to_airport, altitude_ft 
        FROM flights 
        WHERE status IN ('Havada', 'en-route')
        ORDER BY altitude_ft DESC 
        LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"flight_id": row[0], "from": row[1], "to": row[2], "altitude_ft": row[3]}

def get_flights_on_route(dep_iata, arr_iata):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*), array_agg(flight_id)
        FROM flights
        WHERE from_airport = %s AND to_airport = %s
        AND status IN ('Havada', 'en-route')
    """, (dep_iata, arr_iata))
    row = cur.fetchone()
    conn.close()
    return {"count": row[0], "flights": row[1]}



def get_current_country(flight_id):
    from tools.direct_query import get_flight_by_id
    flight = get_flight_by_id(flight_id)
    if not flight or not flight.get("lat"):
        return None
    
    geolocator = Nominatim(user_agent="iga-chatbot")
    location = geolocator.reverse(f"{flight['lat']}, {flight['lng']}", language="tr")
    if not location:
        return None
    
    country = location.raw.get("address", {}).get("country", "bilinmiyor")
    return {"flight_id": flight_id, "country": country, "lat": flight["lat"], "lng": flight["lng"]}


def get_total_route_distance(dep_iata, arr_iata):
    dep_coords = get_airport_coords(dep_iata)
    arr_coords = get_airport_coords(arr_iata)
    
    if not dep_coords or not arr_coords:
        return None
    
    lat1, lng1 = dep_coords
    lat2, lng2 = arr_coords
    
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    mesafe_km = R * 2 * math.asin(math.sqrt(a))
    
    return round(mesafe_km)

def get_route_completion(flight_id, dep_iata, arr_iata):
    from tools.direct_query import get_flight_by_id
    
    toplam = get_total_route_distance(dep_iata, arr_iata)
    kalan = get_remaining_distance(flight_id, arr_iata)
    
    if not toplam or not kalan:
        return None
    
    tamamlanan = toplam - kalan
    yuzde = round((tamamlanan / toplam) * 100)
    
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
    seat_letter = ''.join(filter(str.isalpha, seat)).upper()
    seat_map = THY_SEAT_MAPS.get(aircraft_type.upper())
    if not seat_map:
        return "bilinmiyor"
    if seat_letter in seat_map["window"]:
        return "pencere kenarı"
    elif seat_letter in seat_map["aisle"]:
        return "koridor kenarı"
    return "bilinmiyor"