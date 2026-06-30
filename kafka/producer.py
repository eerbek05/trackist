import json
import time
import requests
import os
from kafka import KafkaProducer
from dotenv import load_dotenv

load_dotenv("../.env")

TOPIC = "iga-flights"
API_KEY = os.getenv("AIRLABS_KEY")

producer = KafkaProducer(
    bootstrap_servers="localhost:9092",
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

def fetch_flights():
    # Kalkışlar
    dep = requests.get(
        "https://airlabs.co/api/v9/flights",
        params={"api_key": API_KEY, "dep_iata": "IST"},
        timeout=10
    ).json().get("response", [])

    # Varışlar
    arr = requests.get(
        "https://airlabs.co/api/v9/flights",
        params={"api_key": API_KEY, "arr_iata": "IST"},
        timeout=10
    ).json().get("response", [])

    # Birleştir, tekrarları kaldır
    all_flights = {f["flight_iata"]: f for f in dep + arr if f.get("flight_iata")}
    return list(all_flights.values())

print("Producer başladı — LTFM uçuşları izleniyor...")

while True:
    try:
        flights = fetch_flights()
        for f in flights:
            producer.send(TOPIC, value=f)
        producer.flush()
        print(f"[+] {len(flights)} uçuş gönderildi → {TOPIC}")
    except Exception as e:
        print(f"[!] Hata: {e}")
    time.sleep(60)