import sys
import logging
logger = logging.getLogger(__name__)
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cohere
import re
from dotenv import load_dotenv
from database.postgres import get_db

load_dotenv()

co = cohere.ClientV2(os.getenv("COHERE_API_KEY"))

# Tablo şeması — Cohere'e veritabanını tanıtmak için
TABLE_SCHEMA = """
Tablo adı: flights
Kolonlar:
- flight_id VARCHAR(10) — uçuş kodu (örn: TK2200)
- flight_icao VARCHAR(10) — ICAO uçuş kodu (örn: THY2200)
- from_airport VARCHAR(100) — kalkış havalimanı IATA kodu (örn: IST)
- to_airport VARCHAR(100) — varış havalimanı IATA kodu (örn: JFK)
- speed_kmh INTEGER — hız km/h cinsinden
- altitude_ft INTEGER — irtifa feet cinsinden
- departure VARCHAR(20) — planlanan kalkış saati UTC (örn: 2026-07-01 10:30)
- arrival VARCHAR(20) — planlanan varış saati UTC (örn: 2026-07-01 14:45)
- aircraft VARCHAR(50) — uçak tipi ICAO kodu (örn: B77W, A321)
- status VARCHAR(20) — durum (en-route, landed, scheduled)
- lat FLOAT — anlık enlem
- lng FLOAT — anlık boylam
- heading INTEGER — uçuş yönü derece cinsinden (0=Kuzey)
- prev_altitude_ft INTEGER — bir önceki irtifa (trend hesabı için)
- v_speed_fpm INTEGER — dikey hız km/h (pozitif=tırmanış, negatif=iniş)
- dep_gate VARCHAR(20) — kalkış kapısı (örn: A12)
- arr_gate VARCHAR(20) — iniş kapısı
- dep_terminal VARCHAR(20) — kalkış terminali
- arr_terminal VARCHAR(20) — iniş terminali
- arr_baggage VARCHAR(20) — bagaj bandı numarası
- dep_delayed INTEGER — kalkış gecikmesi dakika cinsinden
- arr_delayed INTEGER — varış gecikmesi dakika cinsinden
- dep_estimated VARCHAR(20) — tahmini kalkış saati UTC
- arr_estimated VARCHAR(20) — tahmini varış saati UTC
- updated_at TIMESTAMP — son güncelleme zamanı UTC
"""

def generate_sql(user_question):
    response = co.chat(
        model="command-r-plus-08-2024",
        messages=[
            {
                "role": "system",
                "content": f"""Sen bir SQL uzmanısın. 
Kullanıcının sorusunu PostgreSQL sorgusuna çevir.

{TABLE_SCHEMA}

Kurallar:
- Sadece SQL yaz, başka hiçbir şey yazma
- Metin aramalarında her zaman ILIKE ve % kullan, tam eşleşme arama
- Şehir adları yerine IATA kodlarını kullan:
   New York = JFK veya EWR, Londra = LHR, Tokyo = NRT,
   Paris = CDG, Frankfurt = FRA, Doha = DOH, 
   Güney Kore = ICN, Dubai = DXB, Amsterdam = AMS
   Örnek: "New York'a giden" → WHERE to_airport = 'JFK'
- Açıklama yazma, sadece sorgu
- Tek satır SQL döndür
- Noktalı virgülle bitir"""
            },
            {
                "role": "user",
                "content": user_question
            }
        ]
    )
    sql = response.message.content[0].text.strip()
    # Cohere bazen markdown kod bloğu ekler — temizle
    sql = re.sub(r'```sql|```', '', sql).strip()
    return sql

FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "truncate",
    "create", "grant", "revoke", "exec", "execute", "merge",
    "call", "copy", "vacuum", "comment", "into",
)

class UnsafeSQLError(Exception):
    pass

def validate_sql(sql):
    cleaned = sql.strip().rstrip(";").strip()

    if ";" in cleaned:
        raise UnsafeSQLError("Birden fazla SQL ifadesi tespit edildi.")

    if not re.match(r"^\s*select\b", cleaned, re.IGNORECASE):
        raise UnsafeSQLError("Sadece SELECT sorgularına izin veriliyor.")

    lowered = cleaned.lower()
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lowered):
            raise UnsafeSQLError(f"Yasaklı anahtar kelime tespit edildi: {keyword}")

    return cleaned

def run_sql(sql):
    conn = get_db()
    conn.set_session(readonly=True)
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    col_names = [desc[0] for desc in cur.description]
    conn.close()
    return col_names, rows

def text_to_sql_query(user_question):
    # SQL üret
    sql = generate_sql(user_question)
    logger.info(f"Üretilen SQL: {sql}")

    try:
        sql = validate_sql(sql)
    except UnsafeSQLError as e:
        logger.error(f"Güvensiz SQL reddedildi: {sql} | Sebep: {e}")
        return "Bu sorgu güvenlik nedeniyle çalıştırılamadı.", sql

    # SQL çalıştır
    col_names, rows = run_sql(sql)
    
    # Sonucu formatla
    if not rows:
        return "Sorgunuza uygun sonuç bulunamadı.", sql
    
    result = []
    for row in rows:
        result.append(dict(zip(col_names, row)))
    
    return result, sql