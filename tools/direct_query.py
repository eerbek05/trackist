import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.postgres import get_db

def get_flight_by_id(flight_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT flight_id, from_airport, to_airport, speed_kmh,
               altitude_ft, departure, arrival, aircraft, status, updated_at,
               lat, lng, heading
        FROM flights
        WHERE flight_id = %s
    """, (flight_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "flight_id": row[0],
        "from": row[1],
        "to": row[2],
        "speed_kmh": row[3],
        "altitude_ft": row[4],
        "departure": row[5],
        "arrival": row[6],
        "aircraft": row[7],
        "status": row[8],
        "updated_at": row[9].strftime("%H:%M") if row[9] else "bilinmiyor",
        "lat": row[10],
        "lng": row[11],
        "heading": row[12]
    }