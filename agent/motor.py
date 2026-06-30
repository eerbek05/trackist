import sys
import logging
logger = logging.getLogger(__name__)
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
from langchain_cohere import ChatCohere
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from tools.direct_query import get_flight_by_id
from tools.statistics import (
    get_flights_in_air_count,
    get_flights_in_air_list,
    get_fastest_flight,
    get_slowest_flight,
    get_all_destinations,
    get_top_destinations_from_istanbul,
    get_longest_flight,
    get_shortest_flight,
    estimate_arrival,
    get_highest_flight,
    get_flights_on_route,
    get_current_country,
    get_total_route_distance,
    get_route_completion
)
from tools.text_to_sql import text_to_sql_query
from tools.rag_search import index_flights, search_flights
from agent.router import detect_complexity
from langchain_groq import ChatGroq

load_dotenv()

llm_simple = ChatCohere(
    cohere_api_key=os.getenv("COHERE_API_KEY"),
    model="command-r-plus-08-2024",
    temperature=0
)

llm_complex = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    model="llama-3.3-70b-versatile",
    temperature=0
)

index_flights()

@tool
def tool_get_flight_by_id(flight_id: str) -> str:
    """Uçuş kodu ile tek bir uçuşun bilgilerini getirir. TK2200, TK1, PC401 gibi kodlar için kullan."""
    try:
        result = get_flight_by_id(flight_id.upper())
        if not result:
            return f"{flight_id} sistemde kayıtlı değil."
        updated_at = result.get("updated_at", "bilinmiyor")
        return str(result) + f"\n[Kaynak: AirLabs canlı verisi — {updated_at} itibarıyla]"
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_get_flights_in_air() -> str:
    """Şu an havada olan uçuşları listeler ve sayısını verir."""
    try:
        count = get_flights_in_air_count()
        flights = get_flights_in_air_list()
        return f"Havada {count} uçuş var: {flights}"
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_get_fastest_flight() -> str:
    """En hızlı uçuşu getirir."""
    try:
        result = get_fastest_flight()
        if not result:
            return "Veri bulunamadı."
        return str(result)
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_get_slowest_flight() -> str:
    """En yavaş uçuşu getirir."""
    try:
        result = get_slowest_flight()
        if not result:
            return "Veri bulunamadı."
        return str(result)
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_get_longest_flight() -> str:
    """En uzun süreli uçuşu getirir."""
    try:
        result = get_longest_flight()
        if not result or result.get('duration_minutes') is None:
            return "Uçuş süresi verisi mevcut değil."
        saat = result['duration_minutes'] // 60
        dakika = result['duration_minutes'] % 60
        return f"En uzun uçuş: {result['flight_id']}, {result['from']} → {result['to']}, süre: {saat} saat {dakika} dakika"
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_get_shortest_flight() -> str:
    """En kısa süreli uçuşu getirir."""
    try:
        result = get_shortest_flight()
        if not result or result.get('duration_minutes') is None:
            return "Uçuş süresi verisi mevcut değil."
        saat = result['duration_minutes'] // 60
        dakika = result['duration_minutes'] % 60
        return f"En kısa uçuş: {result['flight_id']}, {result['from']} → {result['to']}, süre: {saat} saat {dakika} dakika"
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_get_all_destinations() -> str:
    """Mevcut tüm destinasyonları listeler."""
    try:
        result = get_all_destinations()
        return f"Mevcut destinasyonlar: {result}"
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_get_top_destinations_from_istanbul() -> str:
    """İstanbul'dan en çok gidilen destinasyonları getirir."""
    try:
        result = get_top_destinations_from_istanbul()
        return str(result)
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_get_highest_flight() -> str:
    """Şu an en yüksek irtifada uçan uçuşu getirir."""
    try:
        result = get_highest_flight()
        if not result:
            return "Veri bulunamadı."
        return f"En yüksek irtifadaki uçuş: {result['flight_id']}, {result['from']} → {result['to']}, irtifa: {result['altitude_ft']} feet."
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_get_flights_on_route(dep_iata: str, arr_iata: str) -> str:
    """Belirli bir rotadaki uçuş sayısını ve uçuşları getirir. dep_iata: kalkış IATA kodu, arr_iata: varış IATA kodu."""
    try:
        result = get_flights_on_route(dep_iata, arr_iata)
        if not result or result["count"] == 0:
            return f"{dep_iata}→{arr_iata} rotasında aktif uçuş yok."
        return f"{dep_iata}→{arr_iata} rotasında {result['count']} uçuş var: {result['flights']}"
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_get_current_country(flight_id: str) -> str:
    """Uçuşun şu an hangi ülke üzerinde olduğunu söyler."""
    try:
        result = get_current_country(flight_id)
        if not result:
            return "Konum verisi bulunamadı."
        return f"{result['flight_id']} uçuşu şu an {result['country']} üzerinde uçuyor."
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_get_remaining_distance(flight_id: str, arr_iata: str) -> str:
    """Uçuşun varış noktasına kalan mesafeyi km cinsinden hesaplar."""
    try:
        from tools.statistics import get_remaining_distance
        result = get_remaining_distance(flight_id, arr_iata)
        if not result:
            return "Kalan mesafe hesaplanamadı — konum verisi eksik."
        return f"{flight_id} uçuşunun {arr_iata} havalimanına kalan mesafesi: {result} km."
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_get_total_route_distance(dep_iata: str, arr_iata: str) -> str:
    """Kalkış ve varış havalimanları arasındaki toplam rota mesafesini hesaplar."""
    try:
        result = get_total_route_distance(dep_iata, arr_iata)
        if not result:
            return "Mesafe hesaplanamadı."
        return f"{dep_iata} → {arr_iata} toplam rota mesafesi: {result} km."
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_get_route_completion(flight_id: str, dep_iata: str, arr_iata: str) -> str:
    """Uçuşun yüzde kaçının tamamlandığını hesaplar. 'Yüzde kaç tamamlandı', 'ne kadarını uçtu' gibi sorular için MUTLAKA bu tool'u kullan. flight_id: uçuş kodu, dep_iata: kalkış IATA, arr_iata: varış IATA."""
    try:
        result = get_route_completion(flight_id, dep_iata, arr_iata)
        if not result:
            return "Rota tamamlanma hesaplanamadı — konum verisi eksik."
        return f"{result['flight_id']} uçuşu: toplam {result['toplam_km']} km rotanın %{result['yuzde']}'i tamamlandı. {result['tamamlanan_km']} km geçildi, {result['kalan_km']} km kaldı."
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_estimate_arrival(flight_id: str, arr_iata: str) -> str:
    """Uçuşun tahmini iniş saatini hesaplar. Anlık konum ve hız kullanarak haversine formülüyle hesaplar. flight_id: uçuş kodu, arr_iata: varış havalimanı IATA kodu."""
    try:
        result = estimate_arrival(flight_id, arr_iata)
        if not result:
            return "Tahmini iniş hesaplanamadı — konum verisi eksik."
        return f"Tahmini iniş: {result['tahmini_inis_utc']} UTC. Kalan mesafe: {result['kalan_km']} km, kalan süre: {result['kalan_sure_dk']} dakika. Bu bir tahmindir, ±15 dakika sapabilir."
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_get_seat_type(flight_id: str, seat: str) -> str:
    """Koltuk numarasının pencere kenarı mı koridor kenarı mı olduğunu söyler. 'Koltugum pencere kenarı mı', 'cam kenarı mı', 'koridor mu' gibi sorular için MUTLAKA bu tool'u kullan. Sadece THY (TK) uçuşları için çalışır."""
    try:
        if not flight_id.upper().startswith("TK"):
            return "Koltuk tipi bilgisi sadece THY uçuşları için mevcuttur."
        
        flight = get_flight_by_id(flight_id.upper())
        if not flight:
            return f"{flight_id} bulunamadı."
        
        aircraft_type = flight.get("aircraft", "")
        
        from tools.statistics import get_seat_type
        result = get_seat_type(aircraft_type, seat)
        
        if result == "bilinmiyor":
            return f"{seat} koltuğu için kesin bilgi veremiyorum — konfigürasyona göre değişebilir."
        return f"{seat} koltuğu {result}."
    except Exception as e:
        return f"Hata: {str(e)}"


@tool
def tool_rag_search(query: str) -> str:
    """Uçuş kodu bilinmediğinde anlam bazlı arama yapar. Rota, şehir, yön gibi sorular için kullan."""
    try:
        results = search_flights(query)
        if not results:
            return "İlgili uçuş bulunamadı."
        return f"İlgili uçuşlar: {results}"
    except Exception as e:
        return f"Hata: {str(e)}"

@tool
def tool_text_to_sql(question: str) -> str:
    """Diğer tool'larla cevaplanamayan her türlü soru için kullan. Uçak tipi, sefer sayısı, filtreleme gibi spesifik sorgularda veritabanında SQL ile arama yapar."""
    try:
        result, sql = text_to_sql_query(question)
        return f"Sorgu sonucu: {result}"
    except Exception as e:
        return f"Sorgu hatası: {str(e)}"


tools = [
    tool_get_flight_by_id,
    tool_get_flights_in_air,
    tool_get_fastest_flight,
    tool_get_slowest_flight,
    tool_get_longest_flight,
    tool_get_shortest_flight,
    tool_get_all_destinations,
    tool_get_top_destinations_from_istanbul,
    tool_rag_search,
    tool_text_to_sql,
    tool_estimate_arrival,
    tool_get_remaining_distance,
    tool_get_highest_flight,
    tool_get_flights_on_route,
    tool_get_current_country,
    tool_get_total_route_distance,
    tool_get_route_completion,
    tool_get_seat_type,
]

AGENT_PROMPT = """Sen IGA İstanbul Havalimanı'nın uçuş bilgi asistanısın.

Tool kullanma sırası:
1. Uçuş kodu varsa → tool_get_flight_by_id
2. İstatistik sorusu ise → istatistik tool'ları
3. Rota, şehir, ülke sorusu → önce tool_rag_search, bulamazsa MUTLAKA tool_text_to_sql
4. tool_rag_search "bulunamadı" dönerse → tool_text_to_sql çağır

ZORUNLU KURAL: tool_rag_search "bulunamadı" veya boş sonuç döndürürse,
bir sonraki adımda MUTLAKA tool_text_to_sql kullan.

Cevap verirken şunları yap:
- Sadece soruyu cevapla değil, ilgili ek bilgi ekle
- Hız verirken bağlam ekle
- İrtifa verirken karşılaştırma yap
- Tool'dan gelen veride [Kaynak: ...] etiketi varsa cevabının sonuna ekle
- Tahmini iniş saati UTC olarak gelirse, varış havalimanının yerel saatine çevir ve öyle söyle.

DİL KURALI: Kullanıcının sorusunu hangi dilde yazdığını tespit et ve cevabını MUTLAKA o dilde ver.
Tool'lardan dönen veriler Türkçe olabilir (örn. "Havada", "bilinmiyor") — bunları cevabını yazarken
kullanıcının diline çevir. Kullanıcı İngilizce sorarsa İngilizce, Türkçe sorarsa Türkçe cevap ver.
Hangi dilde sorulduğu belirsizse İngilizce cevap ver.

Doğal ve bilgilendirici ol.
Veride olmayan bilgiler için kullanıcının dilinde 'Bu bilgi elimde yok' / 'I don't have this information' de.
Tüm veritabanını tek seferde dökme."""

memory = MemorySaver()

def handle_message(soru, thread_id="default"):
    if len(soru.strip()) < 3:
        return "Please enter a valid question."
    if not any(c.isalpha() for c in soru):
        return "Please enter a valid question."

    complexity = detect_complexity(soru)
    llm = llm_complex if complexity == "complex" else llm_simple
    logger.info(f"Model seçimi: {'Groq' if complexity == 'complex' else 'Cohere'} | Soru: {soru}")

    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 50
    }

    agent = create_react_agent(
        model=llm,
        tools=tools,
        checkpointer=memory,
        prompt=AGENT_PROMPT
    )

    try:
        result = agent.invoke(
            {"messages": [HumanMessage(content=soru)]},
            config=config
        )

        for msg in result["messages"]:
            msg_type = msg.__class__.__name__
            content = str(msg.content)[:300]
            logger.info(f"[{msg_type}]: {content}")

        return result["messages"][-1].content
    except Exception as e:
        error_str = str(e)
        logger.error(f"AGENT HATA: {error_str}")
        if "rate_limit_exceeded" in error_str:
            logger.info("Groq rate limit — Cohere'e geçiliyor")
            agent = create_react_agent(
                model=llm_simple,
                tools=tools,
                checkpointer=memory,
                prompt=AGENT_PROMPT
            )
            try:
                result = agent.invoke(
                    {"messages": [HumanMessage(content=soru)]},
                    config=config
                )
                return result["messages"][-1].content
            except Exception as e2:
                return f"An error occurred: {str(e2)}"
        if "HALLUCINATED_ALL_TOOL_CALLS" in error_str:
            return "I couldn't understand this question. Please ask something more specific."
        return f"An error occurred: {error_str}"