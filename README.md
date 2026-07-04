# TrackIST

A flight-information chatbot for Istanbul air traffic. A LangGraph ReAct
agent (Cohere/Groq, routed by query complexity) answers questions about
live flights using a RAG search, a text-to-SQL tool, and a set of
statistics tools, backed by a Kafka pipeline that streams live positions
from AirLabs into Postgres. The web UI includes a live flight map
(Leaflet) with routes, headings, and boarding-pass photo lookup.

## Quick start (Docker — recommended)

One command brings up everything: Postgres, Kafka + Zookeeper, the AirLabs
producer, the DB-writing consumer, and the web app.

```bash
cp .env.example .env   # fill in your API keys
make up                # or: docker-compose up --build
```

Then open **http://localhost:5001**.

- `make down` — stop everything
- `make logs` — tail all container logs

## Required environment variables

Create a `.env` file in the project root (never commit this — it's
gitignored):

| Variable | Used for |
|---|---|
| `COHERE_API_KEY` | The "simple question" LLM and the text-to-SQL tool |
| `GROQ_API_KEY` | The "complex question" LLM and boarding-pass image analysis |
| `AIRLABS_KEY` | Live flight data (the Kafka producer) |
| `FLASK_SECRET_KEY` | Flask session signing — generate one with `python3 -c "import secrets; print(secrets.token_hex(32))"` |

## Running without Docker

Useful for local development (faster iteration than rebuilding images).
Requires a local Postgres and a running Kafka broker (e.g. `docker-compose
up db zookeeper kafka` to just get the infra, then run the rest locally):

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python app.py              # web app — http://localhost:5001
./venv/bin/python kafka/producer.py   # in a separate terminal
./venv/bin/python kafka/consumer.py   # in another separate terminal
```

## Tests

```bash
./venv/bin/python -m pytest test.py -v
```

Covers the text-to-SQL safety guard (rejects anything that isn't a plain
`SELECT`) and the airport coordinate lookup.

## Project layout

```
app.py                 Flask routes (chat, image analysis, map API)
agent/motor.py          LangGraph ReAct agent + tool definitions
agent/router.py         Picks Cohere (simple) vs. Groq (complex) per question
tools/                  direct_query, statistics, rag_search, text_to_sql
database/postgres.py    DB connection helper
kafka/producer.py       Polls AirLabs, publishes to Kafka
kafka/consumer.py       Reads Kafka, writes to Postgres + indexes for RAG
templates/index.html    Chat UI + Leaflet flight map
```
