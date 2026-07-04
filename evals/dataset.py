"""Golden eval questions for the TrackIST chatbot.

Every expected value derives from evals/fixtures.sql — load it first
(python evals/run_evals.py --seed). Cases are TR/EN pairs across the
question categories the product vision promises.

Fields:
  id          unique case id
  question    what the user types
  lang        expected answer language ("tr"/"en")
  category    reporting bucket
  expect_any  case-insensitive substrings — at least ONE must appear in the
              answer for the content check to pass
  route       optional: expected router decision ("simple"/"complex"),
              checked in --offline mode
"""

CASES = [
    # ── Single flight ────────────────────────────────────────────────
    {"id": "single_tr", "question": "TK9001 şu an nerede, durumu ne?",
     "lang": "tr", "category": "single_flight",
     "expect_any": ["JFK"], "route": "simple"},
    {"id": "single_en", "question": "Where is flight TK9001 right now?",
     "lang": "en", "category": "single_flight",
     # A position-based answer ("45N 30W over the Atlantic") is as correct
     # as naming the destination — accept either.
     "expect_any": ["JFK", "Atlantic", "45"], "route": "simple"},

    # ── Gate / terminal / baggage ────────────────────────────────────
    {"id": "gate_tr", "question": "TK9001 hangi kapıdan kalkıyor?",
     "lang": "tr", "category": "ground_info",
     "expect_any": ["F6"], "route": "simple"},
    {"id": "gate_en", "question": "What gate does TK9001 depart from?",
     "lang": "en", "category": "ground_info",
     "expect_any": ["F6"], "route": "simple"},
    {"id": "baggage_tr", "question": "EK9002 uçuşunun bagajı hangi bantta?",
     "lang": "tr", "category": "ground_info",
     "expect_any": ["7"], "route": "simple"},
    {"id": "baggage_en", "question": "Which baggage belt for EK9002?",
     "lang": "en", "category": "ground_info",
     "expect_any": ["7"], "route": "simple"},

    # ── Times (UTC + airport-local computed in code) ─────────────────
    {"id": "times_tr", "question": "TK9001 ne zaman inecek?",
     "lang": "tr", "category": "times",
     # 18:55 UTC; JFK local is 14:55 (EDT) — either satisfies
     "expect_any": ["18:55", "14:55"]},
    {"id": "times_en", "question": "When will TK9001 land?",
     "lang": "en", "category": "times",
     "expect_any": ["18:55", "14:55"]},

    # ── Delays ───────────────────────────────────────────────────────
    {"id": "delay_tr", "question": "Gecikmeli uçuşlar hangileri?",
     "lang": "tr", "category": "lists",
     "expect_any": ["LH9003"], "route": "simple"},
    {"id": "delay_en", "question": "Which flights are delayed by more than 30 minutes?",
     "lang": "en", "category": "lists",
     "expect_any": ["LH9003"]},

    # ── Counts / status lists ────────────────────────────────────────
    {"id": "airborne_tr", "question": "Şu an kaç uçak havada?",
     "lang": "tr", "category": "lists",
     "expect_any": ["4", "dört"], "route": "simple"},
    {"id": "airborne_en", "question": "How many flights are airborne right now?",
     "lang": "en", "category": "lists",
     "expect_any": ["4", "four"], "route": "simple"},
    {"id": "arriving_tr", "question": "İstanbul'a gelen uçuşları listele",
     "lang": "tr", "category": "lists",
     "expect_any": ["LH9003", "QR9006"]},
    {"id": "departing_en", "question": "List the flights departing from IST",
     "lang": "en", "category": "lists",
     "expect_any": ["TK9001", "PC9004"]},
    {"id": "airline_tr", "question": "TK uçuşları hangileri?",
     "lang": "tr", "category": "lists",
     "expect_any": ["TK9001", "TK9005"]},

    # ── Extremes ─────────────────────────────────────────────────────
    {"id": "fastest_tr", "question": "En hızlı uçak hangisi?",
     "lang": "tr", "category": "stats",
     "expect_any": ["TK9001"], "route": "simple"},
    {"id": "highest_en", "question": "Which flight is currently flying the highest?",
     "lang": "en", "category": "stats",
     "expect_any": ["QR9006"]},
    {"id": "slowest_tr", "question": "En yavaş uçan uçak hangisi?",
     "lang": "tr", "category": "stats",
     "expect_any": ["PC9004"]},

    # ── Route progress ───────────────────────────────────────────────
    {"id": "progress_tr", "question": "TK9001 yolun yüzde kaçını tamamladı?",
     "lang": "tr", "category": "route",
     "expect_any": ["%", "km"]},
    {"id": "progress_en", "question": "How far along its route is TK9001?",
     "lang": "en", "category": "route",
     "expect_any": ["%", "km"]},

    # ── Chain queries (selector + secondary attribute) ───────────────
    {"id": "chain_tr", "question": "En yüksekte uçan uçağın kalkış şehrinde hava nasıl?",
     "lang": "tr", "category": "chain",
     "expect_any": ["Doha", "DOH", "Hamad"], "route": "complex"},
    {"id": "chain_en", "question": "What's the weather in the departure city of the highest flight?",
     "lang": "en", "category": "chain",
     "expect_any": ["Doha", "DOH", "Hamad"], "route": "complex"},

    # ── Trend ────────────────────────────────────────────────────────
    {"id": "trend_tr", "question": "TK9001 tırmanıyor mu, alçalıyor mu?",
     "lang": "tr", "category": "single_flight",
     "expect_any": ["tırman", "yüksel", "climb"]},

    # ── Seat map ─────────────────────────────────────────────────────
    {"id": "seat_tr", "question": "TK9005 uçuşunda 12A koltuğu pencere kenarı mı?",
     "lang": "tr", "category": "seat",
     "expect_any": ["pencere", "window"]},
    {"id": "seat_en", "question": "Is seat 12C on TK9005 a window or aisle seat?",
     "lang": "en", "category": "seat",
     "expect_any": ["aisle"]},

    # ── text_to_sql fallback ─────────────────────────────────────────
    {"id": "sql_tr", "question": "B77W tipi uçak kullanan uçuşlar hangileri?",
     "lang": "tr", "category": "sql",
     "expect_any": ["TK9001"]},
    {"id": "sql_en", "question": "Which flights use a Boeing 787 (B788) aircraft?",
     "lang": "en", "category": "sql",
     "expect_any": ["QR9006"]},
]
