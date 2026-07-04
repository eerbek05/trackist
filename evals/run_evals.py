#!/usr/bin/env python3
"""TrackIST chatbot eval harness.

Modes:
  python evals/run_evals.py --offline
      No LLM, no DB. Checks the deterministic layers against the dataset:
      router classification (route field) and question-language detection.

  python evals/run_evals.py --seed
      Loads evals/fixtures.sql into DATABASE_URL (WIPES the flights table),
      then exits. Run against a disposable/eval database, never production.

  python evals/run_evals.py [--only CASE_ID] [--sleep SECONDS]
      Live eval: runs every dataset question through the real agent
      (needs COHERE_API_KEY/GROQ_API_KEY and a seeded DB) and scores:
        content  — at least one expected substring appears in the answer
        language — answer language matches the question language
        no-leak  — no reasoning phrases leaked into the answer

Interpreting results: content is the accuracy signal; language and no-leak
are quality signals. Track the numbers over time — a change that drops any
category is a regression, whatever it "feels" like in manual testing.
"""

import argparse
import os
import sys
import time

# Windows consoles default to a legacy code page (cp1254 on Turkish systems)
# that can't print '→' etc. from LLM answers — force UTF-8, never crash on
# an unprintable character.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals.dataset import CASES


def check_offline():
    from agent.router import detect_complexity
    from agent.language import detect_language

    route_pass = route_total = 0
    lang_pass = 0
    failures = []

    for case in CASES:
        detected_lang = detect_language(case["question"])
        if detected_lang == case["lang"]:
            lang_pass += 1
        else:
            failures.append(f"  LANG {case['id']}: expected {case['lang']}, got {detected_lang}")

        if "route" in case:
            route_total += 1
            got = detect_complexity(case["question"])
            if got == case["route"]:
                route_pass += 1
            else:
                failures.append(f"  ROUTE {case['id']}: expected {case['route']}, got {got}")

    print(f"language detection: {lang_pass}/{len(CASES)}")
    print(f"router:             {route_pass}/{route_total}")
    for f in failures:
        print(f)
    return not failures


def seed():
    from database.postgres import get_db
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures.sql")
    with open(path, encoding="utf-8") as fh:
        sql = fh.read()
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM flights")
        n = cur.fetchone()[0]
    finally:
        conn.close()
    print(f"Fixtures loaded — flights table now has {n} rows.")


def _check_fixture_freshness():
    """Fixtures older than the product's 121-minute staleness window make
    every list/stats case fail with 'no active flights' — that's the tools
    working correctly on stale data, not a real regression. Refuse to run."""
    from database.postgres import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT EXTRACT(EPOCH FROM ((NOW() AT TIME ZONE 'UTC') - MAX(updated_at))) / 60 FROM flights")
        age_min = cur.fetchone()[0]
    finally:
        conn.close()
    if age_min is None:
        print("HATA: flights tablosu boş — önce fixture yükleyin: python evals/run_evals.py --seed")
        return False
    if age_min > 100:
        print(f"HATA: fixture'lar {age_min:.0f} dakika eski (>100) — staleness penceresi dolmak üzere/dolmuş.")
        print("Önce yeniden yükleyin: python evals/run_evals.py --seed")
        return False
    return True


def run_live(only=None, sleep_s=2.0):
    from agent.motor import handle_message, _REASONING_RE
    from agent.language import detect_language

    if not _check_fixture_freshness():
        return False

    cases = [c for c in CASES if only is None or c["id"] == only]
    if not cases:
        print(f"No case with id {only!r}")
        return False

    results = []
    for i, case in enumerate(cases):
        thread_id = f"eval-{case['id']}-{int(time.time())}"
        try:
            answer = handle_message(case["question"], thread_id)
        except Exception as e:
            answer = f"<EXCEPTION: {e}>"

        low = answer.lower()
        content_ok = any(exp.lower() in low for exp in case["expect_any"])
        lang_ok = detect_language(answer) == case["lang"]
        leak_ok = not _REASONING_RE.search(answer)

        results.append({
            "case": case, "answer": answer,
            "content": content_ok, "language": lang_ok, "leak": leak_ok,
        })
        status = "PASS" if content_ok else "FAIL"
        flags = ("" if lang_ok else " [lang!]") + ("" if leak_ok else " [leak!]")
        print(f"[{i+1}/{len(cases)}] {status}{flags}  {case['id']}: {answer[:120]!r}")
        if i < len(cases) - 1:
            time.sleep(sleep_s)  # be gentle to free-tier rate limits

    # scorecard
    print("\n── Scorecard ─────────────────────────────")
    by_cat = {}
    for r in results:
        by_cat.setdefault(r["case"]["category"], []).append(r)
    for cat, rs in sorted(by_cat.items()):
        ok = sum(1 for r in rs if r["content"])
        print(f"  {cat:<14} content {ok}/{len(rs)}")
    n = len(results)
    content = sum(1 for r in results if r["content"])
    lang = sum(1 for r in results if r["language"])
    leak = sum(1 for r in results if r["leak"])
    print(f"\n  TOTAL   content {content}/{n}   language {lang}/{n}   no-leak {leak}/{n}")

    failed = [r for r in results if not r["content"]]
    if failed:
        print("\n── Content failures ──────────────────────")
        for r in failed:
            print(f"  {r['case']['id']}: Q={r['case']['question']!r}")
            print(f"    expected any of {r['case']['expect_any']}")
            print(f"    got: {r['answer'][:300]!r}")
    return not failed


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="router + language checks only (no LLM/DB)")
    ap.add_argument("--seed", action="store_true", help="load fixtures.sql into DATABASE_URL and exit")
    ap.add_argument("--only", help="run a single case id")
    ap.add_argument("--sleep", type=float, default=2.0, help="seconds between live calls (default 2)")
    args = ap.parse_args()

    if args.seed:
        seed()
        sys.exit(0)
    if args.offline:
        sys.exit(0 if check_offline() else 1)
    sys.exit(0 if run_live(only=args.only, sleep_s=args.sleep) else 1)
