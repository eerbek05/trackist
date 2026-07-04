"""
Polls OpenSky Network every 60 seconds and updates the live position
(lat, lng, speed_kmh, altitude_ft, heading) for flights already in the DB.

Only updates existing rows — never inserts. Route/schedule info (dep_iata,
arr_iata, arr_time, etc.) comes from AirLabs and is left untouched.

OpenSky state vector indices used here:
  [1]  callsign      (ICAO, e.g. "THY2750")
  [5]  longitude     (degrees)
  [6]  latitude      (degrees)
  [7]  baro_altitude (metres → convert to feet)
  [8]  on_ground     (bool)
  [9]  velocity      (m/s → convert to km/h)
  [10] true_track    (degrees clockwise from north = heading)
"""

import os
import sys
import time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from database.postgres import get_db
from tools.opensky import fetch_opensky_states
from workers.term import banner, ok, warn, err, info

load_dotenv()

POLL_INTERVAL = 60


def get_active_flights():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT flight_id, flight_icao FROM flights WHERE flight_icao IS NOT NULL")
    rows = cur.fetchall()
    conn.close()
    return rows


def update_positions(states):
    if not states:
        return 0

    callsign_map = {}
    for s in states:
        cs = (s[1] or "").strip()
        if cs:
            callsign_map[cs] = s

    flights = get_active_flights()
    updated = 0

    conn = get_db()
    cur = conn.cursor()

    for flight_id, flight_icao in flights:
        state = callsign_map.get(flight_icao)
        if not state:
            continue

        lng       = state[5]
        lat       = state[6]
        alt_m     = state[7]
        on_ground = state[8]
        vel_ms    = state[9]
        track     = state[10]

        if on_ground:
            cur.execute("""
                UPDATE flights SET status = 'landed', updated_at = NOW()
                WHERE flight_id = %s
            """, (flight_id,))
            updated += 1
            continue

        if lat is None or lng is None:
            continue

        alt_ft    = int(alt_m * 3.28084) if alt_m is not None else None
        speed_kmh = int(vel_ms * 3.6)    if vel_ms is not None else None
        heading   = int(track)            if track  is not None else None

        cur.execute("""
            UPDATE flights
            SET prev_altitude_ft = altitude_ft,
                lat = %s, lng = %s, altitude_ft = %s,
                speed_kmh = %s, heading = %s, updated_at = NOW()
            WHERE flight_id = %s
        """, (lat, lng, alt_ft, speed_kmh, heading, flight_id))
        updated += 1

    conn.commit()
    conn.close()
    return updated


banner(
    "TrackIST · OpenSky Position",
    "ADS-B live positions  →  PostgreSQL",
    f"interval: {POLL_INTERVAL}s   source: opensky-network.org",
)

while True:
    try:
        states = fetch_opensky_states()
        if states is None:
            warn("opensky", "Could not reach OpenSky — skipping this cycle")
        else:
            n = update_positions(states)
            ok("opensky", f"{n} positions updated")
    except Exception as e:
        err("opensky", str(e))
    time.sleep(POLL_INTERVAL)
