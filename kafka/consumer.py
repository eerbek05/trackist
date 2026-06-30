import json
import sys
import os
from datetime import datetime
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kafka import KafkaConsumer
from database.postgres import get_db
from tools.rag_search import collection

consumer = KafkaConsumer(
    "iga-flights",
    bootstrap_servers="localhost:9092",
    auto_offset_reset="earliest",
    group_id="iga-consumer-group-3",
    value_deserializer=lambda v: json.loads(v.decode("utf-8"))
)

print("Consumer başladı — iga-flights dinleniyor...\n")

documents = []
ids = []

for message in consumer:
    f = message.value

    flight_iata = f.get("flight_iata")
    if not flight_iata:
        continue

    try:
        updated_unix = f.get("updated")
        updated_at = datetime.fromtimestamp(updated_unix) if updated_unix else datetime.now()

        conn = get_db()
        cur = conn.cursor()
        lat = f.get("lat")
        lng = f.get("lng")

        # "dir" is the flight's heading/track in degrees (0=N, 90=E, ...),
        # used to point the aircraft icon on the map the way it's actually flying.
        heading = f.get("dir")
        heading = int(heading) if heading is not None else None

        cur.execute("""
            INSERT INTO flights (flight_id, from_airport, to_airport, speed_kmh, altitude_ft, departure, arrival, aircraft, status, updated_at, lat, lng, heading)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (flight_id) DO UPDATE SET
                speed_kmh = EXCLUDED.speed_kmh,
                altitude_ft = EXCLUDED.altitude_ft,
                status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at,
                lat = EXCLUDED.lat,
                lng = EXCLUDED.lng,
                heading = EXCLUDED.heading
        """, (
            flight_iata,
            f.get("dep_iata", ""),
            f.get("arr_iata", ""),
            int(f.get("speed", 0) or 0),
            int(f.get("alt", 0) or 0),
            f.get("dep_time", ""),
            f.get("arr_time", ""),
            f.get("aircraft_icao", ""),
            f.get("status", ""),
            updated_at,
            lat,
            lng,
            heading
            ))
        conn.commit()
        conn.close()

        text = f"{flight_iata} ucusu {f.get('dep_iata','')} havalimanindan {f.get('arr_iata','')} havalimanina gidiyor. Hiz {f.get('speed',0)} kmh, irtifa {f.get('alt',0)} ft. Durum: {f.get('status','')}."
        documents.append(text)
        ids.append(flight_iata)

        print(f"✓ {flight_iata} | {f.get('dep_iata')} → {f.get('arr_iata')} | {f.get('status')}")

        if len(documents) >= 10:
            collection.upsert(documents=documents, ids=ids)
            print(f"[ChromaDB] {len(documents)} uçuş indexlendi")
            documents = []
            ids = []

    except Exception as e:
        print(f"[!] Hata: {flight_iata} — {e}")