import sys
import logging
logger = logging.getLogger(__name__)
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cohere
import re
from dotenv import load_dotenv
from database.postgres import get_db
from agent import llm_state

load_dotenv()

_cohere_client = None

def _get_cohere():
    global _cohere_client
    if _cohere_client is None:
        _cohere_client = cohere.ClientV2(
            api_key=os.getenv("COHERE_API_KEY")
        )
    return _cohere_client

_groq_client = None

def _get_groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _groq_client

# Tablo şeması — LLM'e veritabanını tanıtmak için
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
- v_speed_fpm INTEGER — dikey hız (pozitif=tırmanış, negatif=iniş)
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
Not: Güncel/aktif uçuşlar için updated_at > (NOW() AT TIME ZONE 'UTC') - INTERVAL '121 minutes' filtresi ekle.
"""

SQL_SYSTEM_PROMPT = f"""Sen bir SQL uzmanısın.
Kullanıcının sorusunu PostgreSQL sorgusuna çevir.

{TABLE_SCHEMA}

Kurallar:
- Sadece SQL yaz, başka hiçbir şey yazma
- Metin aramalarında her zaman ILIKE ve % kullan, tam eşleşme arama
- ÖNEMLİ: departure, arrival, dep_estimated, arr_estimated kolonları METİN (VARCHAR),
  gerçek zaman tipi değil — bunlar üzerinde saat karşılaştırması, aralık sorgusu veya
  sıralama YAPMA. Zaman filtresi gerekiyorsa yalnızca updated_at (TIMESTAMP) kullan.
- Şehir adları yerine IATA kodlarını kullan:
   New York = JFK veya EWR, Londra = LHR, Tokyo = NRT,
   Paris = CDG, Frankfurt = FRA, Doha = DOH,
   Seul = ICN, Dubai = DXB, Amsterdam = AMS,
   Berlin = BER, Roma = FCO, Milano = MXP, Madrid = MAD, Barselona = BCN,
   Viyana = VIE, Münih = MUC, Zürih = ZRH, Brüksel = BRU, Kopenhag = CPH,
   Stokholm = ARN, Oslo = OSL, Atina = ATH, Kahire = CAI, Bakü = GYD,
   Tahran = IKA, Moskova = SVO, Pekin = PEK, Şanghay = PVG, Bangkok = BKK,
   Singapur = SIN, Delhi = DEL, Mumbai = BOM, Toronto = YYZ, Şikago = ORD,
   Los Angeles = LAX, Miami = MIA, Washington = IAD, Boston = BOS,
   Ankara = ESB, İzmir = ADB, Antalya = AYT
   Örnek: "New York'a giden" → WHERE to_airport IN ('JFK', 'EWR')
- Emin olmadığın şehir için tahmin etme, soruda geçen adı ILIKE ile ara
- Açıklama yazma, sadece sorgu
- Tek satır SQL döndür
- Noktalı virgülle bitir"""


def _clean_llm_sql(sql):
    # LLM bazen markdown kod bloğu ekler — temizle
    return re.sub(r'```sql|```', '', sql).strip()


def _generate_with_cohere(user_question):
    response = _get_cohere().chat(
        model="command-r-plus-08-2024",
        messages=[
            {"role": "system", "content": SQL_SYSTEM_PROMPT},
            {"role": "user", "content": user_question},
        ]
    )
    return _clean_llm_sql(response.message.content[0].text.strip())


def _generate_with_groq(user_question):
    response = _get_groq().chat.completions.create(
        model="llama-3.3-70b-versatile",
        temperature=0,
        max_tokens=300,
        messages=[
            {"role": "system", "content": SQL_SYSTEM_PROMPT},
            {"role": "user", "content": user_question},
        ]
    )
    return _clean_llm_sql(response.choices[0].message.content.strip())


_gemini_llm = None

def _generate_with_gemini(user_question):
    global _gemini_llm
    if _gemini_llm is None:
        from langchain_google_genai import ChatGoogleGenerativeAI
        _gemini_llm = ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
            temperature=0, max_retries=1, timeout=30,
        )
    result = _gemini_llm.invoke([
        ("system", SQL_SYSTEM_PROMPT),
        ("human", user_question),
    ])
    return _clean_llm_sql(str(result.content).strip())


_cerebras_llm = None

def _generate_with_cerebras(user_question):
    global _cerebras_llm
    if _cerebras_llm is None:
        from langchain_openai import ChatOpenAI
        _cerebras_llm = ChatOpenAI(
            base_url="https://api.cerebras.ai/v1",
            api_key=os.getenv("CEREBRAS_API_KEY"),
            model=os.getenv("CEREBRAS_MODEL", "gpt-oss-120b"),
            temperature=0, max_retries=1, timeout=30,
        )
    result = _cerebras_llm.invoke([
        ("system", SQL_SYSTEM_PROMPT),
        ("human", user_question),
    ])
    return _clean_llm_sql(str(result.content).strip())


_mistral_llm = None

def _generate_with_mistral(user_question):
    global _mistral_llm
    if _mistral_llm is None:
        from langchain_mistralai import ChatMistralAI
        _mistral_llm = ChatMistralAI(
            api_key=os.getenv("MISTRAL_API_KEY"),
            model=os.getenv("MISTRAL_MODEL", "mistral-small-latest"),
            temperature=0, max_retries=1, timeout=30,
        )
    result = _mistral_llm.invoke([
        ("system", SQL_SYSTEM_PROMPT),
        ("human", user_question),
    ])
    return _clean_llm_sql(str(result.content).strip())


def generate_sql(user_question):
    """Same provider chain as the agent, sharing the rate-limit cooldowns so
    a dead provider doesn't kill this tool when the agent itself has already
    moved on to another one."""
    attempts = []
    if os.getenv("CEREBRAS_API_KEY") and not llm_state.is_exhausted("cerebras"):
        attempts.append(("cerebras", _generate_with_cerebras))
    if os.getenv("GOOGLE_API_KEY") and not llm_state.is_exhausted("gemini"):
        attempts.append(("gemini", _generate_with_gemini))
    if os.getenv("MISTRAL_API_KEY") and not llm_state.is_exhausted("mistral"):
        attempts.append(("mistral", _generate_with_mistral))
    if not llm_state.is_exhausted("groq"):
        attempts.append(("groq", _generate_with_groq))
    if not llm_state.is_exhausted("cohere"):
        attempts.append(("cohere", _generate_with_cohere))

    last_error = None
    for name, fn in attempts:
        try:
            return fn(user_question)
        except Exception as e:
            if llm_state.looks_like_rate_limit(str(e)):
                llm_state.mark_exhausted(name, str(e))
            logger.warning(f"{name} SQL üretimi başarısız ({e}) — sıradaki deneniyor")
            last_error = e
    raise last_error or RuntimeError("No SQL provider available")


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

MAX_ROWS = 50

def run_sql(sql):
    # Cap the result set so a "SELECT * FROM flights" doesn't dump the whole
    # table into the agent's context.
    if not re.search(r"\blimit\s+\d+\b", sql, re.IGNORECASE):
        sql = f"{sql} LIMIT {MAX_ROWS}"

    conn = get_db()
    try:
        conn.set_session(readonly=True)
        cur = conn.cursor()
        # Runaway queries (cartesian joins, pg_sleep) shouldn't be able to
        # hold a pooled connection hostage.
        cur.execute("SET statement_timeout = '5s'")
        cur.execute(sql)
        rows = cur.fetchall()
        col_names = [desc[0] for desc in cur.description]
        return col_names, rows
    finally:
        # The readonly flag would otherwise stick to the pooled connection
        # and break the next writer that happens to receive it.
        try:
            conn.rollback()
            conn.set_session(readonly=False)
        except Exception:
            pass
        conn.close()

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
