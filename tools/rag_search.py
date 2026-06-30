import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
from database.postgres import get_db

chroma_client = chromadb.Client()
try:
    chroma_client.delete_collection("flights")
except:
    pass
collection = chroma_client.get_or_create_collection(name="flights")

def index_flights():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM flights")
    rows = cur.fetchall()
    conn.close()

    documents = []
    ids = []

    for row in rows:
        flight_id = row[0]
        text = f"{flight_id} ucusu {row[1]} havalimanindan {row[2]} havalimanina gidiyor. Hiz {row[3]} kmh, irtifa {row[4]} ft. Kalkis {row[5]}, varis {row[6]}. Ucak tipi {row[7]}. Durum: {row[8]}."
        documents.append(text)
        ids.append(flight_id)

    collection.upsert(documents=documents, ids=ids)
    print(f"{len(documents)} ucus indexlendi.")

def search_flights(query, n_results=2):
    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        include=["documents", "distances"]
    )

    distances = results['distances'][0]
    documents = results['documents'][0]

    filtered = [
        doc for doc, dist in zip(documents, distances)
        if dist < 0.7
    ]

    return filtered if filtered else None