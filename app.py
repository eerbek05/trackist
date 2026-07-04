from flask import Flask, render_template, request, session, redirect, jsonify, Response, stream_with_context
from tools.weather import get_weather_by_coords, get_weather_for_airport
from flask_session import Session
from dotenv import load_dotenv
from agent.motor import handle_message, handle_message_stream
from tools.direct_query import get_flight_by_id
from database.postgres import get_db
from tools.statistics import get_airport_info
import os
import uuid
import logging
import base64

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)

error_handler = logging.FileHandler('error.log')
error_handler.setLevel(logging.ERROR)

logger = logging.getLogger(__name__)
logger.addHandler(error_handler)

# Gereksiz DEBUG logları kapat
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

app = Flask(__name__)

app.secret_key = os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("FLASK_SECRET_KEY is not set — add it to .env")
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

@app.route("/")
def index():
    if "thread_id" not in session:
        session["thread_id"] = str(uuid.uuid4())
    if "history" not in session:
        session["history"] = []
    return render_template("index.html", history=session["history"])

@app.route("/chat", methods=["POST"])
def chat():
    if "thread_id" not in session:
        session["thread_id"] = str(uuid.uuid4())
    if "history" not in session:
        session["history"] = []

    soru = request.json.get("soru")

    # Append boarding pass info to the question, if present
    boarding = session.get("boarding_info")
    if boarding:
        boarding_context = f"[User's boarding pass info: flight={boarding.get('flight_code')}, seat={boarding.get('seat')}, gate={boarding.get('gate')}, departure={boarding.get('departure_time')}] "
        soru_with_context = boarding_context + soru
    else:
        soru_with_context = soru

    logger.info(f"Kullanıcı sorusu: {soru} | thread_id: {session['thread_id']}")
    cevap = handle_message(soru_with_context, session["thread_id"])
    logger.info(f"Agent cevabı: {cevap[:200]}")

    session["history"].append({"role": "user", "content": soru})
    session["history"].append({"role": "assistant", "content": cevap})

    if len(session["history"]) > 20:
        session["history"] = session["history"][-20:]

    session.modified = True
    return jsonify({"cevap": cevap})

@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    if "thread_id" not in session:
        session["thread_id"] = str(uuid.uuid4())
    if "history" not in session:
        session["history"] = []

    soru = (request.json or {}).get("soru", "").strip()
    if not soru:
        return jsonify({"error": "empty"}), 400

    boarding = session.get("boarding_info")
    if boarding:
        soru_ctx = (
            f"[User's boarding pass info: flight={boarding.get('flight_code')}, "
            f"seat={boarding.get('seat')}, gate={boarding.get('gate')}, "
            f"departure={boarding.get('departure_time')}] " + soru
        )
    else:
        soru_ctx = soru

    thread_id = session["thread_id"]
    history   = session["history"]

    @stream_with_context
    def generate():
        import json
        tokens = []
        for event in handle_message_stream(soru_ctx, thread_id):
            if event["type"] == "token":
                tokens.append(event["text"])
            yield f"data: {json.dumps(event)}\n\n"

        full_text = "".join(tokens)
        history.append({"role": "user",      "content": soru})
        history.append({"role": "assistant", "content": full_text})
        if len(history) > 20:
            history[:] = history[-20:]
        session["history"] = history
        session.modified = True

        yield 'data: {"type":"done"}\n\n'

    resp = Response(generate(), mimetype="text/event-stream")
    resp.headers["Cache-Control"]    = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@app.route("/analyze", methods=["POST"])
def analyze():
    if "thread_id" not in session:
        session["thread_id"] = str(uuid.uuid4())

    file = request.files.get("image")
    if not file:
        return jsonify({"cevap": "Could not upload the image."})

    image_data = base64.b64encode(file.read()).decode("utf-8")
    mime_type = file.content_type

    from groq import Groq
    import json, re
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_data}"}
                },
                {
                    "type": "text",
                    "text": """Bu boarding pass'tan bilgileri çıkar. Sadece düz JSON yaz, markdown kullanma:
{"flight_code": "TK12", "gate": "008", "seat": "28D", "departure_time": "22:25", "group": "B"}
Görünmeyen alanlar için null yaz."""
                }
            ]
        }],
        max_tokens=100
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r'```json|```', '', raw).strip()

    try:
        data = json.loads(raw)
    except:
        data = {"flight_code": raw}

    flight_code = str(data.get("flight_code", "")).upper().replace(" ", "")
    flight_code = re.sub(r'([A-Z]+)0+(\d+)', r'\1\2', flight_code)
    gate = data.get("gate")
    seat = data.get("seat")
    departure_time = data.get("departure_time")

    logger.info(f"Vision: uçuş={flight_code}, kapı={gate}, koltuk={seat}, kalkış={departure_time}")

    # Koltuk ve kapı bilgisini session'a kaydet
    session["boarding_info"] = {
        "flight_code": flight_code,
        "gate": gate,
        "seat": seat,
        "departure_time": departure_time
    }
    session.modified = True

    # Use a dedicated thread so this auto-query doesn't pollute the user's chat history
    cevap = handle_message(f"What is the current status, speed, and altitude of flight {flight_code}?", f"boarding-{session['thread_id']}")

    # Add seat and gate info
    extra = ""
    if seat:
        extra += f" Your seat number is {seat}."
    if gate:
        extra += f" Your gate number is {gate}."
    if departure_time:
        extra += f" Departure time: {departure_time}."

    return jsonify({"cevap": cevap + extra, "flight_code": flight_code})

@app.route("/api/flights")
def api_flights():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT flight_id, from_airport, to_airport, speed_kmh,
               altitude_ft, status, lat, lng, heading
        FROM flights
        WHERE lat IS NOT NULL AND lng IS NOT NULL
          AND updated_at > NOW() - INTERVAL '121 minutes'
    """)
    rows = cur.fetchall()
    conn.close()

    flights = [
        {
            "flight_id": r[0],
            "from": r[1],
            "to": r[2],
            "speed_kmh": r[3],
            "altitude_ft": r[4],
            "status": r[5],
            "lat": r[6],
            "lng": r[7],
            "heading": r[8],
        }
        for r in rows
    ]
    return jsonify(flights)

@app.route("/api/flights/<flight_id>")
def api_flight_single(flight_id):
    # Used by the map to fly to a specific flight even if it briefly dropped
    # out of /api/flights's full list (e.g. a momentary null position from
    # the feed) — same lookup the chatbot itself uses, so the two stay in sync.
    flight = get_flight_by_id(flight_id.upper())
    if not flight or flight.get("lat") is None or flight.get("lng") is None or flight.get("stale"):
        # Stale (likely landed/dropped off the live feed) flights shouldn't
        # sit on the map as frozen "ghost" markers forever — treat them the
        # same as having no position data at all.
        return jsonify(None), 404
    return jsonify(flight)

@app.route("/api/route/<flight_id>")
def api_route(flight_id):
    # Departure/arrival airport coordinates for drawing a flight's route on
    # the map, plus its current position so the traveled vs. remaining
    # portions can be drawn differently.
    flight = get_flight_by_id(flight_id.upper())
    if not flight:
        return jsonify(None), 404

    dep_info = get_airport_info(flight.get("from"))
    arr_info = get_airport_info(flight.get("to"))
    if not dep_info or not arr_info:
        return jsonify(None), 404

    current = None
    if flight.get("lat") is not None and flight.get("lng") is not None and not flight.get("stale"):
        # Don't draw a "current position" marker from a stale (likely
        # landed) last-known fix — fall back to the full dep→arr line with
        # no flown/remaining split, since we can't actually vouch for where
        # the aircraft is anymore.
        current = {"lat": flight["lat"], "lng": flight["lng"]}

    return jsonify({
        "flight_id": flight["flight_id"],
        "dep": dep_info,
        "arr": arr_info,
        "current": current
    })

@app.route("/api/weather")
def api_weather():
    iata = request.args.get("iata", "").upper()
    lat  = request.args.get("lat", type=float)
    lng  = request.args.get("lng", type=float)
    if iata:
        data = get_weather_for_airport(iata)
    elif lat is not None and lng is not None:
        data = get_weather_by_coords(lat, lng)
    else:
        return jsonify(None), 400
    if not data:
        return jsonify(None), 404
    return jsonify(data)

@app.route("/clear")
def clear():
    session.clear()
    return redirect("/")

@app.route("/api/ist-ground")
def ist_ground():
    """Return aircraft currently on the ground at IST from our own DB."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT flight_id, lat, lng, heading
            FROM flights
            WHERE status = 'landed'
              AND lat BETWEEN 41.20 AND 41.33
              AND lng BETWEEN 28.65 AND 28.85
              AND updated_at > NOW() - INTERVAL '3 hours'
        """)
        rows = cur.fetchall()
        conn.close()
        return jsonify([
            {"callsign": r[0], "lat": r[1], "lng": r[2], "heading": int(r[3]) if r[3] else 0}
            for r in rows
        ])
    except Exception as e:
        logger.error(f"ist-ground error: {e}")
        return jsonify([])

if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=5001)