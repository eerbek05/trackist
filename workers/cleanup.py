"""
Checks stale flights against OpenSky and removes confirmed-landed ones.
Called by poller.py after each poll cycle — not a standalone process.
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.postgres import get_db
from tools.direct_query import STALE_AFTER, UTC_NOW_SQL
from tools.opensky import fetch_opensky_states, check_landed_status
from workers.term import ok, warn, info


def get_stale_flights():
    """(flight_id, flight_icao) pairs — flight_icao lets us match OpenSky
    callsigns for any airline, not just the ones in the static IATA→ICAO
    table."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT flight_id, flight_icao FROM flights WHERE updated_at < {UTC_NOW_SQL} - %s",
            (STALE_AFTER,)
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return rows


def delete_flight(flight_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM flights WHERE flight_id = %s", (flight_id,))
        conn.commit()
    finally:
        conn.close()


def run_cleanup_pass():
    stale = get_stale_flights()
    if not stale:
        info("cleanup", "No stale flights")
        return

    info("cleanup", f"{len(stale)} stale flights — checking OpenSky...")
    states = fetch_opensky_states()
    if states is None:
        warn("cleanup", "Could not reach OpenSky — skipping")
        return

    for flight_id, flight_icao in stale:
        status = check_landed_status(flight_id, states, callsign=flight_icao)
        if status == "landed":
            delete_flight(flight_id)
            ok("cleanup", f"{flight_id}  confirmed on ground → removed")
        elif status == "airborne":
            info("cleanup", f"{flight_id}  still airborne → kept")
        else:
            info("cleanup", f"{flight_id}  not found in OpenSky → kept")
