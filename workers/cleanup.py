"""
Checks stale flights against OpenSky and removes confirmed-landed ones.
Called by poller.py after each poll cycle — not a standalone process.
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.postgres import get_db
from tools.direct_query import STALE_AFTER
from tools.opensky import fetch_opensky_states, check_landed_status
from workers.term import ok, warn, info


def get_stale_flight_ids():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT flight_id FROM flights WHERE updated_at < NOW() - %s",
        (STALE_AFTER,)
    )
    ids = [row[0] for row in cur.fetchall()]
    conn.close()
    return ids


def delete_flight(flight_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM flights WHERE flight_id = %s", (flight_id,))
    conn.commit()
    conn.close()


def run_cleanup_pass():
    stale_ids = get_stale_flight_ids()
    if not stale_ids:
        info("cleanup", "No stale flights")
        return

    info("cleanup", f"{len(stale_ids)} stale flights — checking OpenSky...")
    states = fetch_opensky_states()
    if states is None:
        warn("cleanup", "Could not reach OpenSky — skipping")
        return

    for flight_id in stale_ids:
        status = check_landed_status(flight_id, states)
        if status == "landed":
            delete_flight(flight_id)
            ok("cleanup", f"{flight_id}  confirmed on ground → removed")
        elif status == "airborne":
            info("cleanup", f"{flight_id}  still airborne → kept")
        else:
            info("cleanup", f"{flight_id}  not found in OpenSky → kept")
