import sys
import re
import logging
logger = logging.getLogger(__name__)
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
from langchain_cohere import ChatCohere
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk, ToolMessage
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
    get_fastest_flight,
    get_slowest_flight,
    get_highest_flight,
    get_all_destinations,
    get_top_destinations_from_istanbul,
    estimate_arrival,
    get_flights_on_route,
    get_current_country,
    get_route_completion,
)
from tools.text_to_sql import text_to_sql_query
from tools.weather import get_weather_for_airport
from tools.tz import fmt_utc_with_local, utc_to_airport_local
from agent.router import detect_complexity
from agent.language import detect_language, language_tag
from agent import llm_state
from langchain_groq import ChatGroq

load_dotenv()

llm_simple = ChatCohere(
    cohere_api_key=os.getenv("COHERE_API_KEY"),
    model="command-r-plus-08-2024",
    temperature=0
)

# max_retries=0 on every chain member: providers send Retry-After headers
# (Cerebras: 60s) and the SDKs sleep on them before retrying — one in-SDK
# retry can stall a request a full minute. Failover *is* our retry.
llm_complex = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    model="llama-3.3-70b-versatile",
    temperature=0,
    max_retries=0,
    request_timeout=30,
)

# Gemini — primary for simple questions when a key is present. Optional:
# without GOOGLE_API_KEY the chain simply doesn't include it.
# Default model is flash-lite: on the free tier the full 2.5-flash is capped
# at ~20 requests/DAY, which one agent conversation can burn; flash-lite's
# bucket is far larger. max_retries=0 because on 429 we want to fall through
# to the next provider immediately, not sit in exponential backoff.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
llm_gemini = None
if os.getenv("GOOGLE_API_KEY"):
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm_gemini = ChatGoogleGenerativeAI(model=GEMINI_MODEL, temperature=0, max_retries=0, timeout=30)
    except Exception as _e:
        logger.warning(f"Gemini kullanılamıyor: {_e}")

# Cerebras — 1M free tokens/day, OpenAI-compatible endpoint. Free tier caps
# context at ~8k tokens, which fits a fresh agent turn but not a very long
# conversation; the chain just moves on when it errors.
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")
llm_cerebras = None
if os.getenv("CEREBRAS_API_KEY"):
    try:
        from langchain_openai import ChatOpenAI
        llm_cerebras = ChatOpenAI(
            base_url="https://api.cerebras.ai/v1",
            api_key=os.getenv("CEREBRAS_API_KEY"),
            model=CEREBRAS_MODEL,
            temperature=0, max_retries=0, timeout=30,
        )
    except Exception as _e:
        logger.warning(f"Cerebras kullanılamıyor: {_e}")

# Mistral — free Experiment plan, tool calling on mistral-small.
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
llm_mistral = None
if os.getenv("MISTRAL_API_KEY"):
    try:
        from langchain_mistralai import ChatMistralAI
        llm_mistral = ChatMistralAI(
            api_key=os.getenv("MISTRAL_API_KEY"),
            model=MISTRAL_MODEL,
            temperature=0, max_retries=0, timeout=30,
        )
    except Exception as _e:
        logger.warning(f"Mistral kullanılamıyor: {_e}")


# ── Tools ──────────────────────────────────────────────────────────────────────
# Deliberately kept to ~15: with 25 near-overlapping tools the models
# regularly picked the wrong one or invented parameters. Overlapping tools
# are merged behind a parameter instead.

# Exposed tool names deliberately have no "tool_" prefix: Gemini in
# particular tends to call the semantic name ("get_flight_by_id") and a
# prefixed registry name makes that an invalid-tool error.
@tool("get_flight_by_id")
def tool_get_flight_by_id(flight_id: str) -> str:
    """Get live details for a single flight by code (e.g. TK2200, TK1, PC401): position, speed, altitude, status, route."""
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


@tool("get_gate_terminal_baggage")
def tool_get_gate_terminal_baggage(flight_id: str) -> str:
    """Get gate, terminal, delay, and baggage belt for a flight. Use for "what gate", "which terminal", "is there a delay", "which belt is my luggage", "where is my bag"."""
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
            return f"{flight_id} has no gate/terminal/baggage data yet."
        return f"{flight_id} ({r['from']} → {r['to']}, {r['status']}): " + " | ".join(parts)
    except Exception as e:
        return f"Error: {e}"


@tool("get_scheduled_times")
def tool_get_scheduled_times(flight_id: str) -> str:
    """Get scheduled and estimated departure/arrival times, in UTC and airport-local time. Use for "when does it depart", "when will it land", "departure time", "arrival time"."""
    try:
        r = get_scheduled_times(flight_id)
        if not r:
            return f"{flight_id} not found."
        parts = []
        dep_sched = fmt_utc_with_local(r["dep_scheduled_raw"], r["from"])
        dep_est   = fmt_utc_with_local(r["dep_estimated_raw"], r["from"])
        arr_sched = fmt_utc_with_local(r["arr_scheduled_raw"], r["to"])
        arr_est   = fmt_utc_with_local(r["arr_estimated_raw"], r["to"])
        if dep_sched:        parts.append(f"Scheduled dep: {dep_sched}")
        if dep_est:          parts.append(f"Estimated dep: {dep_est}")
        if r["dep_delayed"]: parts.append(f"Dep delay: +{r['dep_delayed']} min")
        if arr_sched:        parts.append(f"Scheduled arr: {arr_sched}")
        if arr_est:          parts.append(f"Estimated arr: {arr_est}")
        if r["arr_delayed"]: parts.append(f"Arr delay: +{r['arr_delayed']} min")
        if not parts:
            return f"{flight_id} has no schedule data yet."
        return f"{flight_id} ({r['from']}→{r['to']}, {r['status']}): " + " | ".join(parts)
    except Exception as e:
        return f"Error: {e}"


@tool("get_delayed_flights")
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


@tool("get_ist_flights")
def tool_get_ist_flights(direction: str) -> str:
    """List flights arriving at or departing from Istanbul (IST). direction: 'arriving' or 'departing'. Use for "flights coming to IST", "flights leaving Istanbul", "how many flights incoming"."""
    try:
        if direction.strip().lower().startswith("arr"):
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
        else:
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


@tool("get_flights_by_status")
def tool_get_flights_by_status(status: str) -> str:
    """Filter flights by status and count them. status: 'en-route' (currently airborne), 'landed', 'scheduled'. Use for "how many flights are in the air", "flights that landed", "still flying"."""
    try:
        flights = get_flights_by_status(status)
        if not flights:
            return f"'{status}' status — no active flights."
        lines = [f"{f['flight_id']} {f['from']}→{f['to']} alt: {f['altitude_ft']} ft" for f in flights[:20]]
        more = f" (showing first 20)" if len(flights) > 20 else ""
        return f"'{status}' status — {len(flights)} flights{more}:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@tool("get_flights_by_airline")
def tool_get_flights_by_airline(airline_iata: str) -> str:
    """List all active flights for a specific airline. Use for "Turkish Airlines flights", "Pegasus departures". airline_iata: airline code (TK, PC, EK, QR, etc.)."""
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


@tool("get_extreme_flight")
def tool_get_extreme_flight(metric: str) -> str:
    """Get the flight that is currently the fastest, slowest, or highest. metric: 'fastest', 'slowest', or 'highest'."""
    try:
        m = metric.strip().lower()
        if m.startswith("fast"):
            r = get_fastest_flight()
            if not r:
                return "No data found."
            return f"Fastest flight: {r['flight_id']} ({r['from']}→{r['to']}), {r['speed_kmh']} km/h."
        if m.startswith("slow"):
            r = get_slowest_flight()
            if not r:
                return "No data found."
            return f"Slowest airborne flight: {r['flight_id']} ({r['from']}→{r['to']}), {r['speed_kmh']} km/h."
        if m.startswith("high"):
            r = get_highest_flight()
            if not r:
                return "No data found."
            return f"Highest flight: {r['flight_id']} ({r['from']}→{r['to']}), {r['altitude_ft']} ft."
        return "Unknown metric — use 'fastest', 'slowest', or 'highest'."
    except Exception as e:
        return f"Error: {e}"


@tool("get_destinations")
def tool_get_destinations() -> str:
    """Get destinations served from Istanbul, most popular first, plus the total destination count."""
    try:
        top = get_top_destinations_from_istanbul()[:15]
        total = len(get_all_destinations())
        lines = [f"{i+1}. {r['destination']} ({r['count']} flights)" for i, r in enumerate(top)]
        return f"{total} active destinations in total. Top destinations from Istanbul:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@tool("get_altitude_trend")
def tool_get_altitude_trend(flight_id: str) -> str:
    """Get altitude trend for a flight: climbing, descending, or level. Use for "is it climbing", "is it descending"."""
    try:
        r = get_altitude_trend(flight_id)
        if not r:
            return f"{flight_id} not found."
        msg = f"{flight_id}: {r['altitude_ft']:,} ft, {r['trend']}"
        if r["detail"]: msg += f" ({r['detail']})"
        return msg
    except Exception as e:
        return f"Error: {e}"


@tool("get_route_progress")
def tool_get_route_progress(flight_id: str) -> str:
    """Route progress for a flight: total route km, distance flown, remaining km, % completed. Use for "how far along", "how many km left", "what % done". For "when will it land" use get_scheduled_times instead."""
    try:
        fid = flight_id.upper()
        flight = get_flight_by_id(fid)
        if not flight:
            return f"{flight_id} not found."
        dep, arr = flight.get("from"), flight.get("to")
        if not dep or not arr:
            return f"{flight_id}: route (departure/arrival airports) unknown — cannot compute progress."

        parts = []
        comp = get_route_completion(fid, dep, arr)
        if comp:
            parts.append(
                f"{comp['yuzde']}% of the {comp['toplam_km']} km {dep}→{arr} route completed "
                f"({comp['tamamlanan_km']} km flown, {comp['kalan_km']} km remaining)"
            )
        eta = estimate_arrival(fid, arr)
        if eta:
            eta_txt = f"{eta['tahmini_inis_utc']} UTC"
            local = utc_to_airport_local(eta.get("tahmini_inis_dt"), arr)
            if local is not None:
                eta_txt += f" ({local.strftime('%H:%M')} local time at {arr})"
            parts.append(f"estimated arrival ~{eta_txt}, in ~{eta['kalan_sure_dk']} min")
        if not parts:
            return f"{flight_id}: no position data — cannot compute route progress."
        if flight.get("stale"):
            parts.append("[WARNING: based on a stale last-known position — flight may already have landed]")
        return f"{fid}: " + "; ".join(parts) + (
            ". Note: straight-line estimate from current speed — actual arrival can differ by 30+ minutes; "
            "for reliable times use the scheduled/estimated times."
        )
    except Exception as e:
        return f"Error: {e}"


@tool("get_current_country")
def tool_get_current_country(flight_id: str) -> str:
    """Tell which country a flight is currently flying over."""
    try:
        result = get_current_country(flight_id)
        if not result:
            return "No position data available."
        return f"{result['flight_id']} is currently flying over {result['country']}."
    except Exception as e:
        return f"Error: {str(e)}"


@tool("get_seat_type")
def tool_get_seat_type(flight_id: str, seat: str) -> str:
    """Tell whether a seat number is a window or aisle seat. Use for "is my seat a window seat", "aisle or window". Only works for Turkish Airlines (TK) flights."""
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


@tool("get_weather")
def tool_get_weather(iata_code: str) -> str:
    """Get current weather for the city where an airport is located. Use for "weather at IST", "weather at destination". iata_code: airport IATA code (e.g. IST, JFK, LHR)."""
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


@tool("query_database")
def tool_text_to_sql(question: str) -> str:
    """Last resort for questions no other tool covers, e.g. filtering by aircraft type or by specific route. Cannot answer time-of-day comparisons (schedule columns are text). Prefer the dedicated tools whenever one fits."""
    try:
        result, _ = text_to_sql_query(question)
        return f"Query result: {result}"
    except Exception as e:
        return f"Query error: {str(e)}"


tools = [
    tool_get_flight_by_id,
    tool_get_gate_terminal_baggage,
    tool_get_scheduled_times,
    tool_get_delayed_flights,
    tool_get_ist_flights,
    tool_get_flights_by_status,
    tool_get_flights_by_airline,
    tool_get_extreme_flight,
    tool_get_destinations,
    tool_get_altitude_trend,
    tool_get_route_progress,
    tool_get_current_country,
    tool_get_seat_type,
    tool_get_weather,
    tool_text_to_sql,
]

AGENT_PROMPT = """You are TrackIST, a flight information assistant specialized in Istanbul Airport (IST).

LANGUAGE RULE — highest priority:
Every user message starts with an explicit instruction like [Answer in Turkish.] or [Answer in English.].
Obey it exactly, for the entire answer. Tool results are in English — translate them into the requested
language. Never mix languages in one answer.

RESPONSE RULE:
Start your answer directly. NEVER write your reasoning steps, tool selection process, or phrases like
"I will use tool_x", "let me check", "I'll call tool_y to find out". Go straight to the answer.

TIME RULE:
Tool results already include airport-local times next to UTC where available. Use them as given.
NEVER compute timezone conversions yourself. If a tool gives only UTC, present it as UTC and say so.
All times coming from query_database (departure, arrival, estimates) are UTC — label them "UTC",
never as local time of any city.

Tool selection order:
1. Flight code present → get_flight_by_id (position/status), get_gate_terminal_baggage
   (gate/terminal/delay/baggage), get_scheduled_times (times), get_altitude_trend (trend),
   get_route_progress (distance/percentage)
2. List questions → get_ist_flights / get_delayed_flights / get_flights_by_airline /
   get_flights_by_status
3. Extremes → get_extreme_flight; destinations → get_destinations
4. Anything else (aircraft type, custom filters) → query_database

Answer guidelines:
- Add relevant context beyond just the raw answer, but never invent data that is not in a tool result.
- If a tool result contains [WARNING], clearly tell the user the data is stale and this is the last
  known state, not the current one — do not present stale speed/altitude as live data.
- If information is not available, say so clearly in the requested language.
- Never dump the entire database in one response."""


def _make_checkpointer():
    """PostgresSaver when available (conversation memory survives restarts,
    shared across workers), MemorySaver otherwise — the agent works either
    way, persistence is best-effort."""
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        try:
            from psycopg_pool import ConnectionPool
            from psycopg.rows import dict_row
            from langgraph.checkpoint.postgres import PostgresSaver
            pool = ConnectionPool(
                db_url,
                min_size=1,
                max_size=5,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            )
            saver = PostgresSaver(pool)
            saver.setup()
            # Close the pool on interpreter exit — otherwise psycopg_pool's
            # worker threads stall shutdown for 5s each and spam warnings.
            import atexit
            atexit.register(pool.close)
            logger.info("Checkpointer: PostgresSaver — konuşma hafızası restart'ta kalıcı")
            return saver
        except Exception as e:
            logger.warning(f"PostgresSaver kurulamadı ({e}) — MemorySaver kullanılıyor")
    return MemorySaver()


memory = _make_checkpointer()

def _sanitize_history(state):
    """One provider's failed or half-merged run can leave artifacts in the
    shared thread history that another provider then rejects wholesale.
    Seen in production, both from Mistral: an assistant message with neither
    content nor tool_calls (error 3240), and one carrying the same tool call
    id twice from a bad chunk merge (error 3230) — the latter poisons the
    thread permanently. Filter the LLM *input* only; the checkpointed state
    stays as-is."""
    cleaned = []
    seen_tool_results = set()
    for m in state["messages"]:
        if isinstance(m, AIMessage):
            tool_calls = getattr(m, "tool_calls", None) or []
            if not tool_calls and not _text_from_content(m.content).strip():
                continue
            seen_ids, uniq = set(), []
            for tc in tool_calls:
                if tc.get("id") in seen_ids:
                    continue
                seen_ids.add(tc.get("id"))
                uniq.append(tc)
            if len(uniq) != len(tool_calls):
                m = m.model_copy(update={"tool_calls": uniq})
        elif isinstance(m, ToolMessage):
            # Drop the duplicate *results* of any deduped call ids too.
            tcid = getattr(m, "tool_call_id", None)
            if tcid in seen_tool_results:
                continue
            seen_tool_results.add(tcid)
        cleaned.append(m)
    return {"llm_input_messages": cleaned}


_agents = {}

def _get_agent(llm):
    key = id(llm)
    if key not in _agents:
        _agents[key] = create_react_agent(
            model=llm,
            tools=tools,
            checkpointer=memory,
            prompt=AGENT_PROMPT,
            pre_model_hook=_sanitize_history,
        )
    return _agents[key]


def _provider_chain(complexity):
    """Ordered (name, llm) candidates for this question, skipping providers
    that are missing a key or inside a rate-limit cooldown. Simple questions
    prefer the roomiest free tiers; complex ones the strongest models.
    Cerebras leads both: 1M free tokens/day dwarfs every other quota."""
    if complexity == "complex":
        order = [
            ("cerebras", llm_cerebras), ("groq", llm_complex),
            ("gemini", llm_gemini), ("mistral", llm_mistral), ("cohere", llm_simple),
        ]
    else:
        order = [
            ("cerebras", llm_cerebras), ("gemini", llm_gemini),
            ("mistral", llm_mistral), ("cohere", llm_simple), ("groq", llm_complex),
        ]
    return [(n, l) for (n, l) in order if l is not None and not llm_state.is_exhausted(n)]


# Strip the machine-added prefixes ([Answer in ...], boarding pass context)
# when showing messages back to the user.
_CONTEXT_TAG_RE = re.compile(
    r"^(?:\[Answer in (?:Turkish|English)\.\]\s*)?(?:\[User's boarding pass info:[^\]]*\]\s*)?"
)


def get_history(thread_id, limit=20):
    """Chat history for UI rendering, derived from the agent checkpointer —
    the single source of truth — instead of a separately-maintained session
    copy that can drift or get lost mid-stream."""
    try:
        checkpoint = memory.get({"configurable": {"thread_id": thread_id}})
    except Exception as e:
        logger.warning(f"get_history: checkpoint okunamadı: {e}")
        return []
    if not checkpoint:
        return []
    msgs = checkpoint.get("channel_values", {}).get("messages", []) or []
    history = []
    for m in msgs:
        if isinstance(m, HumanMessage):
            text = _CONTEXT_TAG_RE.sub("", _text_from_content(m.content)).strip()
            if text:
                history.append({"role": "user", "content": text})
        elif isinstance(m, AIMessage) and not getattr(m, "tool_calls", None):
            text = _text_from_content(m.content).strip()
            if text:
                history.append({"role": "assistant", "content": text})
    return history[-limit:]


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
    r' -⁯₠-⃏'               # punctuation, currency
    r'Ѐ-ӿ'                             # Cyrillic (place names)
    r'°•→←↑↓✈️'
    r'☀️🌤️⛅☁️🌫️🌦️🌧️🌨️🌩️⛈️❄️🌡️'   # weather emojis used by tool_get_weather
    r']+',
    re.UNICODE,
)

def _strip_reasoning(text: str) -> str:
    """Drop reasoning sentences while preserving the whitespace/formatting of
    everything that stays (joining with a single space would flatten lists
    and line breaks in the answer)."""
    parts = re.split(r'((?<=[.!?])\s+)', text)
    out = []
    for i in range(0, len(parts), 2):
        sentence = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        if sentence and _REASONING_RE.search(sentence):
            continue
        out.append(sentence + sep)
    result = "".join(out).strip()
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


# ── LLM-free emergency answers ─────────────────────────────────────────────────
# When every provider is rate-limited the product core (single-flight status,
# delays, arrivals/departures, airborne count) keeps working on raw tool
# output. Less conversational than the agent, far better than an apology.

_FLIGHT_CODE_RE = re.compile(r"\b([A-Z]{2}\d{1,4})\b")


def _direct_note(lang):
    if lang == "tr":
        return "[Not: AI asistan şu an yoğun — ham veri gösteriliyor.]\n"
    return "[Note: AI assistant is busy — showing raw data.]\n"


def _direct_answer(soru, lang):
    """Best-effort answer without any LLM. Returns None when no simple intent
    matches — callers then fall back to the 'busy' message."""
    s = soru.lower()
    note = _direct_note(lang)
    try:
        m = _FLIGHT_CODE_RE.search(soru.upper().replace("İ", "I"))
        if m and m.group(1) != "IST":
            return note + tool_get_flight_by_id.invoke({"flight_id": m.group(1)})
        if any(k in s for k in ("gecik", "delay", "rötar", "rotar")):
            return note + tool_get_delayed_flights.invoke({"min_delay_minutes": 15})
        if any(k in s for k in ("gelen", "arriv", "inen")):
            return note + tool_get_ist_flights.invoke({"direction": "arriving"})
        if any(k in s for k in ("giden", "kalkan", "depart")):
            return note + tool_get_ist_flights.invoke({"direction": "departing"})
        if any(k in s for k in ("havada", "airborne", "in the air", "kaç uçuş", "kac ucus", "how many flight")):
            return note + tool_get_flights_by_status.invoke({"status": "en-route"})
    except Exception as e:
        logger.error(f"_direct_answer hata: {e}")
    return None


def _busy_message(soru, lang):
    direct = _direct_answer(soru, lang)
    if direct:
        return direct
    if lang == "tr":
        return "Tüm AI sağlayıcıları şu an yoğun. Lütfen birazdan tekrar deneyin."
    return "All AI providers are currently busy. Please try again in a moment."


def handle_message_stream(soru, thread_id="default"):
    """Generator yielding dicts: {type: 'tool'|'token'|'error', ...}"""
    if len(soru.strip()) < 3 or not any(c.isalpha() for c in soru):
        yield {"type": "token", "text": "Please enter a valid question."}
        return

    lang = detect_language(soru)
    soru_llm = language_tag(lang) + soru

    complexity = detect_complexity(soru)
    chain = _provider_chain(complexity)
    logger.info(f"Stream zinciri: {[n for n, _ in chain]} | lang={lang} | {soru}")
    if not chain:
        yield {"type": "token", "text": _busy_message(soru, lang)}
        return

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}
    state = {"emitted": False}

    def _run(llm_to_use):
        """Stream one agent run, buffering until the first sentence boundary
        so leading reasoning ("I'll use tool_x...") never reaches the user."""
        agent = _get_agent(llm_to_use)
        seen_tools = set()
        buf = []
        clean_started = False

        for chunk, metadata in agent.stream(
            {"messages": [HumanMessage(content=soru_llm)]},
            config=config,
            stream_mode="messages",
        ):
            if not isinstance(chunk, AIMessageChunk):
                continue
            # stream_mode="messages" also surfaces LLM calls made *inside*
            # tools (the text-to-SQL generator) — without this filter their
            # output (raw SQL) streams to the user as if it were the answer.
            if metadata.get("langgraph_node") != "agent":
                continue

            for tc in (chunk.tool_call_chunks or []):
                name = tc.get("name")
                if name and name not in seen_tools:
                    seen_tools.add(name)
                    yield {"type": "tool", "name": name}

            if chunk.tool_call_chunks:
                continue
            text = _text_from_content(chunk.content)
            if not text:
                continue
            if clean_started:
                state["emitted"] = True
                yield {"type": "token", "text": text}
            else:
                buf.append(text)
                combined = "".join(buf)
                # flush on sentence boundary
                if any(c in combined for c in ".!?\n"):
                    parts = re.split(r"(?<=[.!?\n])", combined, maxsplit=1)
                    sentence, rest = parts[0], parts[1] if len(parts) > 1 else ""
                    if _REASONING_RE.search(sentence):
                        buf = [rest] if rest else []
                    else:
                        clean_started = True
                        buf = []
                        state["emitted"] = True
                        yield {"type": "token", "text": combined}

        # emit anything remaining in buffer
        if buf:
            remaining = "".join(buf)
            if not _REASONING_RE.search(remaining):
                state["emitted"] = True
                yield {"type": "token", "text": remaining}

    for name, llm in chain:
        try:
            yield from _run(llm)
            if state["emitted"]:
                return
            # Finished without producing any answer text — try the next
            # provider on the same thread.
            logger.info(f"{name} boş cevap üretti — sıradaki sağlayıcı deneniyor")
            continue
        except Exception as e:
            error_str = str(e)
            logger.error(f"STREAM HATA ({name}): {error_str[:300]}")
            if state["emitted"]:
                # Tokens already reached the user — a fresh fallback run
                # would append a second, duplicate answer after the partial.
                yield {"type": "error", "text": "Connection to the AI service was interrupted. Please try again."}
                return
            if llm_state.looks_like_rate_limit(error_str):
                llm_state.mark_exhausted(name, error_str)
            # Nothing reached the user yet, so *any* failure — quota or a
            # provider-specific 4xx — is survivable: move down the chain
            # instead of surfacing a raw API error.
            continue

    # Every provider was rate-limited or produced nothing.
    yield {"type": "token", "text": _busy_message(soru, lang)}


def handle_message(soru, thread_id="default"):
    if len(soru.strip()) < 3:
        return "Please enter a valid question."
    if not any(c.isalpha() for c in soru):
        return "Please enter a valid question."

    lang = detect_language(soru)
    soru_llm = language_tag(lang) + soru

    complexity = detect_complexity(soru)
    chain = _provider_chain(complexity)
    logger.info(f"Model zinciri: {[n for n, _ in chain]} | lang={lang} | Soru: {soru}")
    if not chain:
        return _busy_message(soru, lang)

    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 50
    }

    def _invoke(llm_to_use):
        result = _get_agent(llm_to_use).invoke(
            {"messages": [HumanMessage(content=soru_llm)]},
            config=config
        )
        for msg in result["messages"]:
            msg_type = msg.__class__.__name__
            content = str(msg.content)[:300]
            logger.info(f"[{msg_type}]: {content}")
        return _strip_reasoning(_text_from_content(result["messages"][-1].content))

    for name, llm in chain:
        try:
            answer = _invoke(llm)
            if not answer.strip():
                logger.info(f"{name} boş cevap üretti — sıradaki sağlayıcı deneniyor")
                continue
            return answer
        except Exception as e:
            error_str = str(e)
            logger.error(f"AGENT HATA ({name}): {error_str[:300]}")
            if llm_state.looks_like_rate_limit(error_str):
                llm_state.mark_exhausted(name, error_str)
                continue
            if "HALLUCINATED_ALL_TOOL_CALLS" in error_str:
                return "I couldn't understand this question. Please ask something more specific."
            # Provider-specific failure (e.g. a 4xx over history it can't
            # parse) — the next provider may still answer; don't surface a
            # raw API error while the chain has members left.
            continue

    # Every provider was rate-limited or produced nothing.
    return _busy_message(soru, lang)
