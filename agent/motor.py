import sys
import re
import logging
logger = logging.getLogger(__name__)
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
from langchain_cohere import ChatCohere
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessageChunk
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from tools.direct_query import (
    get_flight_by_id,
    get_gate_and_terminal,
    get_delayed_flights,
    get_flights_by_status,
    get_flights_arriving_ist,
    get_flights_departing_ist,
    get_baggage_claim,
    get_flights_by_airline,
    get_altitude_trend,
    get_scheduled_times,
)
from tools.statistics import (
    get_flights_in_air_count,
    get_flights_in_air_list,
    get_fastest_flight,
    get_slowest_flight,
    get_all_destinations,
    get_top_destinations_from_istanbul,
    estimate_arrival,
    get_highest_flight,
    get_flights_on_route,
    get_current_country,
    get_total_route_distance,
    get_route_completion
)
from tools.text_to_sql import text_to_sql_query
from tools.weather import get_weather_for_airport, get_weather_by_coords
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
    temperature=0,
    max_retries=1,
    request_timeout=30,
)

@tool
def tool_get_flight_by_id(flight_id: str) -> str:
    """Get details for a single flight by code (e.g. TK2200, TK1, PC401)."""
    try:
        result = get_flight_by_id(flight_id.upper())
        if not result:
            return f"{flight_id} not found in the system."
        updated_at = result.get("updated_at", "unknown")
        if result.get("stale"):
            # No data has arrived for this flight in well over a refresh
            # cycle — it most likely landed or otherwise dropped out of the
            # live feed. We only have its last known position, not
            # confirmation of what happened, so say so plainly rather than
            # presenting stale data as if it were still current.
            return (
                str(result)
                + f"\n[WARNING: Data as of {updated_at} — no updates for several minutes. Flight may have landed or dropped from live feed. Last known state, not current.]"
            )
        return str(result) + f"\n[Source: AirLabs live data — as of {updated_at}]"
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def tool_get_flights_in_air() -> str:
    """List all flights currently airborne and return the count."""
    try:
        count = get_flights_in_air_count()
        flights = get_flights_in_air_list()
        return f"{count} flights currently airborne: {flights}"
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def tool_get_fastest_flight() -> str:
    """Get the fastest flight currently tracked."""
    try:
        result = get_fastest_flight()
        if not result:
            return "No data found."
        return str(result)
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def tool_get_slowest_flight() -> str:
    """Get the slowest flight currently tracked."""
    try:
        result = get_slowest_flight()
        if not result:
            return "No data found."
        return str(result)
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def tool_get_all_destinations() -> str:
    """List all current destinations in the system."""
    try:
        result = get_all_destinations()
        total = len(result)
        preview = ", ".join(result[:20])
        return f"{total} active destinations (showing first 20): {preview}"
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def tool_get_top_destinations_from_istanbul() -> str:
    """Get the most popular destinations from Istanbul."""
    try:
        result = get_top_destinations_from_istanbul()
        top = result[:15]
        lines = [f"{i+1}. {r['destination']} ({r['count']} flights)" for i, r in enumerate(top)]
        return "Top destinations from Istanbul:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def tool_get_highest_flight() -> str:
    """Get the flight currently at the highest altitude."""
    try:
        result = get_highest_flight()
        if not result:
            return "No data found."
        return f"Highest flight: {result['flight_id']}, {result['from']} → {result['to']}, altitude: {result['altitude_ft']} ft."
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def tool_get_flights_on_route(dep_iata: str, arr_iata: str) -> str:
    """Get the number of flights and flight list on a specific route. dep_iata: departure IATA, arr_iata: arrival IATA."""
    try:
        result = get_flights_on_route(dep_iata, arr_iata)
        if not result or result["count"] == 0:
            return f"{dep_iata}→{arr_iata} route has no active flights."
        return f"{dep_iata}→{arr_iata} route has {result['count']} active flights: {result['flights']}"
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def tool_get_current_country(flight_id: str) -> str:
    """Tell which country a flight is currently flying over."""
    try:
        result = get_current_country(flight_id)
        if not result:
            return "No position data available."
        return f"{result['flight_id']} is currently flying over {result['country']}."
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def tool_get_remaining_distance(flight_id: str, arr_iata: str) -> str:
    """Calculate remaining distance in km to the destination airport."""
    try:
        from tools.statistics import get_remaining_distance
        result = get_remaining_distance(flight_id, arr_iata)
        if not result:
            return "Cannot calculate remaining distance — no position data."
        return f"{flight_id} has {result} km remaining to {arr_iata}."
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def tool_get_total_route_distance(dep_iata: str, arr_iata: str) -> str:
    """Calculate total route distance in km between two airports."""
    try:
        result = get_total_route_distance(dep_iata, arr_iata)
        if not result:
            return "Cannot calculate distance."
        return f"Total route distance {dep_iata} → {arr_iata}: {result} km."
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def tool_get_route_completion(flight_id: str, dep_iata: str, arr_iata: str) -> str:
    """Calculate what percentage of the route has been completed. Use for questions like "how far along", "what % done". flight_id: flight code, dep_iata: departure IATA, arr_iata: arrival IATA."""
    try:
        result = get_route_completion(flight_id, dep_iata, arr_iata)
        if not result:
            return "Cannot calculate route completion — no position data."
        return f"{result['flight_id']} {result['yuzde']}% of {result['toplam_km']} km route completed. {result['tamamlanan_km']} km flown, {result['kalan_km']} km remaining."
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def tool_estimate_arrival(flight_id: str, arr_iata: str) -> str:
    """Estimate arrival time using current position and speed (haversine). flight_id: flight code, arr_iata: arrival airport IATA."""
    try:
        result = estimate_arrival(flight_id, arr_iata)
        if not result:
            return "Cannot estimate arrival — no position data."
        return f"Estimated arrival: {result['tahmini_inis_utc']} UTC. Remaining: {result['kalan_km']} km, ~{result['kalan_sure_dk']} min. (±15 min estimate)"
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def tool_get_seat_type(flight_id: str, seat: str) -> str:
    """Tell whether a seat number is a window or aisle seat. Use for questions like "is my seat a window seat", "aisle or window". Only works for Turkish Airlines (TK) flights."""
    try:
        if not flight_id.upper().startswith("TK"):
            return "Seat type information is only available for Turkish Airlines (TK) flights."
        
        flight = get_flight_by_id(flight_id.upper())
        if not flight:
            return f"{flight_id} not found."
        
        aircraft_type = flight.get("aircraft", "")
        
        from tools.statistics import get_seat_type
        result = get_seat_type(aircraft_type, seat)
        
        if result == "unknown":
            return f"{seat} seat — exact type cannot be determined, may vary by configuration."
        return f"{seat} seat is a {result} seat."
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def tool_get_gate_and_terminal(flight_id: str) -> str:
    """Get gate, terminal, delay, and baggage belt info for a flight. Use for questions like "what gate", "which terminal", "is there a delay", "where is baggage"."""
    try:
        r = get_gate_and_terminal(flight_id)
        if not r:
            return f"{flight_id} not found."
        parts = []
        if r["gate"]:       parts.append(f"Gate: {r['gate']}")
        if r["terminal"]:   parts.append(f"Terminal: {r['terminal']}")
        if r["dep_gate"] and r["dep_gate"] != r["gate"]:
            parts.append(f"Dep gate: {r['dep_gate']}")
        if r["arr_gate"] and r["arr_gate"] != r["gate"]:
            parts.append(f"Arr gate: {r['arr_gate']}")
        if r["delay_min"]:  parts.append(f"Delay: +{r['delay_min']} min")
        if r["arr_baggage"]: parts.append(f"Baggage belt: {r['arr_baggage']}")
        if r["dep_time"]:   parts.append(f"Departure: {r['dep_time']}")
        if r["arr_time"]:   parts.append(f"Arrival: {r['arr_time']}")
        if not parts:
            return f"{flight_id} has no gate/terminal data yet."
        return f"{flight_id} ({r['from']} → {r['to']}): " + " | ".join(parts)
    except Exception as e:
        return f"Error: {e}"


@tool
def tool_get_delayed_flights(min_delay_minutes: int = 15) -> str:
    """List currently delayed flights. Use for "which flights are delayed", "most delayed", "delayed departures". min_delay_minutes: minimum delay threshold in minutes."""
    try:
        flights = get_delayed_flights(min_delay_minutes)
        if not flights:
            return f"{min_delay_minutes} min or more delay — no delayed flights."
        lines = []
        for f in flights[:15]:
            delay = f["max_delay"]
            t = f["arr_time"] or f["dep_time"] or "?"
            lines.append(f"{f['flight_id']} ({f['from']}→{f['to']}): +{delay} min delay, ETA {t}")
        return f"{len(flights)} delayed flights (≥{min_delay_minutes} min):\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@tool
def tool_get_flights_by_status(status: str) -> str:
    """Filter flights by status. status: 'en-route' (airborne), 'landed', 'scheduled'. Use for "flights that landed", "still in the air", "any landed flights"."""
    try:
        flights = get_flights_by_status(status)
        if not flights:
            return f"'{status}' status — no active flights."
        lines = [f"{f['flight_id']} {f['from']}→{f['to']} alt: {f['altitude_ft']} ft" for f in flights[:20]]
        return f"'{status}' status — {len(flights)} flights:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@tool
def tool_get_flights_arriving_ist() -> str:
    """List all flights arriving at Istanbul (IST) with gate, baggage belt, and ETA. Use for "flights coming to IST", "arriving at Istanbul", "how many flights incoming"."""
    try:
        flights = get_flights_arriving_ist()
        if not flights:
            return "No flights currently arriving at IST."
        lines = []
        for f in flights[:20]:
            parts = [f"{f['flight_id']} ({f['from']})"]
            if f["arr_time"]:    parts.append(f"ETA {f['arr_time']}")
            if f["arr_gate"]:    parts.append(f"gate {f['arr_gate']}")
            if f["arr_baggage"]: parts.append(f"belt {f['arr_baggage']}")
            if f["arr_delayed"]: parts.append(f"+{f['arr_delayed']} min")
            lines.append(" | ".join(parts))
        return f"Flights arriving at IST ({len(flights)}):\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@tool
def tool_get_flights_departing_ist() -> str:
    """List all flights departing from Istanbul (IST) with gate and departure time. Use for "flights leaving IST", "departing from Istanbul", "which flights took off"."""
    try:
        flights = get_flights_departing_ist()
        if not flights:
            return "No flights currently departing from IST."
        lines = []
        for f in flights[:20]:
            parts = [f"{f['flight_id']} →{f['to']}"]
            if f["dep_time"]:    parts.append(f"dep {f['dep_time']}")
            if f["dep_gate"]:    parts.append(f"gate {f['dep_gate']}")
            if f["dep_delayed"]: parts.append(f"+{f['dep_delayed']} min")
            lines.append(" | ".join(parts))
        return f"Flights departing IST ({len(flights)}):\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@tool
def tool_get_baggage_claim(flight_id: str) -> str:
    """Get the baggage belt number for an arrived flight. Use for "which belt is my luggage", "baggage carousel", "where is my bag"."""
    try:
        r = get_baggage_claim(flight_id)
        if not r:
            return f"{flight_id} not found."
        if not r["arr_baggage"]:
            return f"{flight_id} has no baggage belt info yet."
        msg = f"{flight_id} ({r['from']} → {r['to']}): Baggage belt {r['arr_baggage']}"
        if r["arr_gate"]:  msg += f", arrival gate {r['arr_gate']}"
        if r["arr_time"]:  msg += f", estimated arrival {r['arr_time']}"
        msg += f" | Status: {r['status']}"
        return msg
    except Exception as e:
        return f"Error: {e}"


@tool
def tool_get_flights_by_airline(airline_iata: str) -> str:
    """List all active flights for a specific airline. Use for "Turkish Airlines flights", "Pegasus departures", "flights starting with TK". airline_iata: airline code (TK, PC, EK, QR, etc.)."""
    try:
        flights = get_flights_by_airline(airline_iata)
        if not flights:
            return f"{airline_iata} has no active flights."
        lines = []
        for f in flights[:25]:
            parts = [f"{f['flight_id']} {f['from']}→{f['to']}"]
            if f["dep_time"]:    parts.append(f"dep {f['dep_time']}")
            if f["arr_time"]:    parts.append(f"arr {f['arr_time']}")
            d = max(f["dep_delayed"] or 0, f["arr_delayed"] or 0)
            if d:                parts.append(f"+{d} min")
            lines.append(" | ".join(parts))
        return f"{airline_iata}: {len(flights)} active flights\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@tool
def tool_get_altitude_trend(flight_id: str) -> str:
    """Get altitude trend for a flight: climbing, descending, or level. Use for "is it climbing", "is it descending", "is altitude changing"."""
    try:
        r = get_altitude_trend(flight_id)
        if not r:
            return f"{flight_id} not found."
        trend_tr = {"climbing": "climbing", "descending": "descending", "level": "level", "unknown": "unknown"}
        msg = f"{flight_id}: {r['altitude_ft']:,} ft, {trend_tr.get(r['trend'], r['trend'])}"
        if r["detail"]: msg += f" ({r['detail']})"
        return msg
    except Exception as e:
        return f"Error: {e}"


@tool
def tool_get_scheduled_times(flight_id: str) -> str:
    """Get scheduled and estimated departure/arrival times in UTC. Use for "when does it depart", "when will it land", "departure time", "arrival time"."""
    try:
        r = get_scheduled_times(flight_id)
        if not r:
            return f"{flight_id} not found."
        parts = []
        if r["dep_scheduled"]: parts.append(f"Scheduled dep: {r['dep_scheduled']}")
        if r["dep_estimated"]: parts.append(f"Estimated dep: {r['dep_estimated']}")
        if r["dep_delayed"]:   parts.append(f"Dep delay: +{r['dep_delayed']} min")
        if r["arr_scheduled"]: parts.append(f"Scheduled arr: {r['arr_scheduled']}")
        if r["arr_estimated"]: parts.append(f"Estimated arr: {r['arr_estimated']}")
        if r["arr_delayed"]:   parts.append(f"Arr delay: +{r['arr_delayed']} min")
        if not parts:
            return f"{flight_id} has no schedule data yet."
        return f"{flight_id} ({r['from']}→{r['to']}, {r['status']}): " + " | ".join(parts)
    except Exception as e:
        return f"Error: {e}"


@tool
def tool_get_weather(iata_code: str) -> str:
    """Get current weather for the city where an airport is located. Use for "weather at IST", "what's the weather in New York", "weather at destination". iata_code: airport IATA code (e.g. IST, JFK, LHR)."""
    try:
        result = get_weather_for_airport(iata_code.upper())
        if not result:
            return f"{iata_code} weather data unavailable."
        return (
            f"{result['airport_name']} ({result['airport']}) current weather: "
            f"{result['emoji']} {result['condition']}, {result['temp_c']}°C, "
            f"wind {result['wind_kmh']} km/h."
        )
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def tool_text_to_sql(question: str) -> str:
    """Use for any question that cannot be answered by other tools. Searches the database with SQL for specific queries like aircraft type, flight count, custom filters."""
    try:
        result, _ = text_to_sql_query(question)
        return f"Query result: {result}"
    except Exception as e:
        return f"Query error: {str(e)}"


tools = [
    tool_get_flight_by_id,
    tool_get_gate_and_terminal,
    tool_get_scheduled_times,
    tool_get_delayed_flights,
    tool_get_flights_by_status,
    tool_get_flights_arriving_ist,
    tool_get_flights_departing_ist,
    tool_get_baggage_claim,
    tool_get_flights_by_airline,
    tool_get_altitude_trend,
    tool_get_flights_in_air,
    tool_get_fastest_flight,
    tool_get_slowest_flight,
    tool_get_all_destinations,
    tool_get_top_destinations_from_istanbul,
    tool_text_to_sql,
    tool_estimate_arrival,
    tool_get_remaining_distance,
    tool_get_highest_flight,
    tool_get_flights_on_route,
    tool_get_current_country,
    tool_get_total_route_distance,
    tool_get_route_completion,
    tool_get_seat_type,
    tool_get_weather,
]

AGENT_PROMPT = """You are TrackIST, a flight information assistant specialized in Istanbul Airport (IST).

LANGUAGE RULE — highest priority:
Detect the language of the user's message and reply in EXACTLY that language.
Tool results may contain Turkish words (e.g. "Havada", "unknown") — translate them into the user's language.
If the user writes in English → reply in English.
If the user writes in Turkish → reply in Turkish.
If only an image was sent with no text → reply in English.

RESPONSE RULE:
Start your answer directly. NEVER write your reasoning steps, tool selection process, or phrases like
"I will use tool_x", "let me check", "I'll call tool_y to find out". Go straight to the answer.

Tool selection order:
1. Flight code present → tool_get_flight_by_id (general), tool_get_gate_and_terminal (gate/delay),
   tool_get_scheduled_times (times), tool_get_baggage_claim (baggage), tool_get_altitude_trend (trend)
2. List questions → tool_get_flights_arriving_ist / tool_get_flights_departing_ist /
   tool_get_delayed_flights / tool_get_flights_by_airline / tool_get_flights_by_status
3. Statistics → statistics tools
4. Route, city, country, custom filter → tool_text_to_sql

Answer guidelines:
- Add relevant context beyond just the raw answer
- If tool result contains [UYARI] or [WARNING], clearly tell the user the data is stale and this is
  the last known state, not the current one — do not present stale speed/altitude as live data.
- If estimated arrival time is in UTC, convert it to the destination airport's local time.
- If information is not available, say so clearly in the user's language.
- Never dump the entire database in one response."""

memory = MemorySaver()

_agents = {}
_cohere_quota_exhausted = False

def _get_agent(llm):
    key = id(llm)
    if key not in _agents:
        _agents[key] = create_react_agent(
            model=llm,
            tools=tools,
            checkpointer=memory,
            prompt=AGENT_PROMPT
        )
    return _agents[key]

_REASONING_RE = re.compile(
    r'tool[_\w]*\s*(kullan|çağır)|kullanacağım|öğrenmek için|çağıracağım'
    r'|aracını kullanacağım|aracı kullanacağım|kullanarak.*bilgi'
    r'|bu soruyu yanıtlamak için|soruyu cevaplamak için'
    r'|kullanıcıya .{0,40}(listeleyeceğim|göstereceğim|sunacağım|söyleyeceğim)'
    r'|şimdi .{0,40}(öğrenmek|kontrol etmek|aramak|sorgulamak) için'
    r'|kullanıcı[,\s].{0,30}(soruyor|sormuş|istiyor)'
    r"|i('ll| (also |now |next )?(will|am going to)).{0,40}(tool|check|look|find|fetch|use|call)"
    r"|let me.{0,30}(tool|check|look|find|fetch|use|call)"
    r"|using the \w+_tool|i will also use",
    re.IGNORECASE,
)

_NON_PRINTABLE_RE = re.compile(
    r'[^\x00-\x7FÀ-ɏɐ-ʯ'   # ASCII + Latin extended
    r' -⁯₠-⃏'               # punctuation, currency
    r'Ѐ-ӿ'                             # Cyrillic (place names)
    r'°•→←↑↓⛅☀️🌧️🌩️❄️🌫️'
    r']+',
    re.UNICODE,
)

def _strip_reasoning(text: str) -> str:
    """Remove reasoning sentences and non-printable/foreign characters."""
    sentences = re.split(r'(?<=[.!?])\s*', text)
    clean = [s for s in sentences if not _REASONING_RE.search(s)]
    result = ' '.join(clean).strip()
    return _NON_PRINTABLE_RE.sub('', result)


def _text_from_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b)
            for b in content
        )
    return ""


def handle_message_stream(soru, thread_id="default"):
    """Generator yielding dicts: {type: 'tool'|'token'|'error', ...}"""
    global _cohere_quota_exhausted
    if len(soru.strip()) < 3 or not any(c.isalpha() for c in soru):
        yield {"type": "token", "text": "Please enter a valid question."}
        return

    complexity = detect_complexity(soru)
    llm = llm_complex if complexity == "complex" else llm_simple
    # Skip Cohere entirely if quota is known-exhausted
    if llm is llm_simple and _cohere_quota_exhausted:
        llm = llm_complex
        logger.info("Cohere quota exhausted — using Groq directly")
    agent = _get_agent(llm)
    logger.info(f"Stream model: {'Groq' if llm is llm_complex else 'Cohere'} | {soru}")

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}

    seen_tools = set()
    # Buffer tokens until first sentence boundary to strip Cohere reasoning
    _buf = []
    _clean_started = False

    def _flush_buf():
        nonlocal _buf, _clean_started
        combined = "".join(_buf)
        _buf = []
        if not combined:
            return
        if _REASONING_RE.search(combined):
            return  # discard reasoning sentence
        _clean_started = True
        return combined

    try:
        for chunk, metadata in agent.stream(
            {"messages": [HumanMessage(content=soru)]},
            config=config,
            stream_mode="messages",
        ):
            if not isinstance(chunk, AIMessageChunk):
                continue

            for tc in (chunk.tool_call_chunks or []):
                name = tc.get("name")
                if name and name not in seen_tools:
                    seen_tools.add(name)
                    yield {"type": "tool", "name": name}

            if not chunk.tool_call_chunks:
                text = _text_from_content(chunk.content)
                if not text:
                    continue
                if _clean_started:
                    yield {"type": "token", "text": text}
                else:
                    _buf.append(text)
                    combined = "".join(_buf)
                    # flush on sentence boundary
                    if any(c in combined for c in ".!?\n"):
                        parts = re.split(r"(?<=[.!?\n])", combined, maxsplit=1)
                        sentence, rest = parts[0], parts[1] if len(parts) > 1 else ""
                        if _REASONING_RE.search(sentence):
                            _buf = [rest] if rest else []
                        else:
                            _clean_started = True
                            _buf = []
                            yield {"type": "token", "text": combined}

        # emit anything remaining in buffer
        if _buf:
            remaining = "".join(_buf)
            if not _REASONING_RE.search(remaining):
                yield {"type": "token", "text": remaining}

    except Exception as e:
        error_str = str(e)
        logger.error(f"STREAM HATA: {error_str}")
        is_rate_limit = any(k in error_str.lower() for k in ("429", "rate_limit", "trial key", "rate limit"))
        if is_rate_limit:
            if llm is llm_simple:
                _cohere_quota_exhausted = True
            fallback_llm = llm_complex if llm is llm_simple else llm_simple
            fallback_name = "Groq" if fallback_llm is llm_complex else "Cohere"
            logger.info(f"Rate limit — falling back to {fallback_name} (stream)")
            try:
                fb_seen_tools = set()
                for chunk, metadata in _get_agent(fallback_llm).stream(
                    {"messages": [HumanMessage(content=soru)]},
                    config=config,
                    stream_mode="messages",
                ):
                    if not isinstance(chunk, AIMessageChunk):
                        continue
                    for tc in (chunk.tool_call_chunks or []):
                        name = tc.get("name")
                        if name and name not in fb_seen_tools:
                            fb_seen_tools.add(name)
                            yield {"type": "tool", "name": name}
                    if not chunk.tool_call_chunks:
                        text = _text_from_content(chunk.content)
                        if text:
                            yield {"type": "token", "text": text}
                return
            except Exception as e2:
                error2 = str(e2)
                is_rl2 = any(k in error2.lower() for k in ("429", "rate_limit", "rate limit"))
                if is_rl2:
                    yield {"type": "token", "text": "Both AI services are currently busy. Please try again in a moment."}
                else:
                    yield {"type": "error", "text": error2}
                return
        yield {"type": "error", "text": error_str}


def handle_message(soru, thread_id="default"):
    global _cohere_quota_exhausted
    if len(soru.strip()) < 3:
        return "Please enter a valid question."
    if not any(c.isalpha() for c in soru):
        return "Please enter a valid question."

    complexity = detect_complexity(soru)
    llm = llm_complex if complexity == "complex" else llm_simple
    if llm is llm_simple and _cohere_quota_exhausted:
        llm = llm_complex
    agent = _get_agent(llm)
    logger.info(f"Model seçimi: {'Groq' if llm is llm_complex else 'Cohere'} | Soru: {soru}")

    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 50
    }

    try:
        result = agent.invoke(
            {"messages": [HumanMessage(content=soru)]},
            config=config
        )

        for msg in result["messages"]:
            msg_type = msg.__class__.__name__
            content = str(msg.content)[:300]
            logger.info(f"[{msg_type}]: {content}")

        return _strip_reasoning(result["messages"][-1].content)
    except Exception as e:
        error_str = str(e)
        logger.error(f"AGENT HATA: {error_str}")
        is_rate_limit = any(k in error_str.lower() for k in ("429", "rate_limit", "trial key", "rate limit"))
        if is_rate_limit:
            if llm is llm_simple:
                _cohere_quota_exhausted = True
            fallback_llm = llm_complex if llm is llm_simple else llm_simple
            fallback_name = "Groq" if fallback_llm is llm_complex else "Cohere"
            logger.info(f"Rate limit — falling back to {fallback_name}")
            try:
                result = _get_agent(fallback_llm).invoke(
                    {"messages": [HumanMessage(content=soru)]},
                    config=config
                )
                return _strip_reasoning(result["messages"][-1].content)
            except Exception as e2:
                return f"An error occurred: {str(e2)}"
        if "HALLUCINATED_ALL_TOOL_CALLS" in error_str:
            return "I couldn't understand this question. Please ask something more specific."
        return f"An error occurred: {error_str}"