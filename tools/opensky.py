import requests
import re
import os
import time

# OpenSky identifies aircraft by ICAO callsign (airline ICAO code + flight
# number, e.g. "THY2750"), not the IATA code our own data uses ("TK2750").
# There's no free lookup API for this mapping, so it's a small static table
# covering the airlines that actually show up in IST traffic. Anything not
# in here can't be cross-checked against OpenSky — see iata_flight_to_icao_callsign.
IATA_TO_ICAO_AIRLINE = {
    "TK": "THY",  # Turkish Airlines
    "PC": "PGT",  # Pegasus
    "XQ": "SXS",  # SunExpress
    "LH": "DLH",  # Lufthansa
    "BA": "BAW",  # British Airways
    "AF": "AFR",  # Air France
    "KL": "KLM",  # KLM
    "EK": "UAE",  # Emirates
    "QR": "QTR",  # Qatar Airways
    "EY": "ETD",  # Etihad
    "LX": "SWR",  # Swiss
    "OS": "AUA",  # Austrian
    "SU": "AFL",  # Aeroflot
    "DL": "DAL",  # Delta
    "UA": "UAL",  # United
    "AA": "AAL",  # American Airlines
    "IB": "IBE",  # Iberia
    "AZ": "ITY",  # ITA Airways
    "MS": "MSR",  # EgyptAir
    "SV": "SVA",  # Saudia
    "3U": "CSC",  # Sichuan Airlines
}


def iata_flight_to_icao_callsign(flight_id):
    """'TK2750' -> 'THY2750'. Returns None for unknown airline prefixes or
    malformed flight codes (no separate lookup API exists for this, so
    coverage is limited to IATA_TO_ICAO_AIRLINE)."""
    if not flight_id:
        return None
    match = re.match(r"^([A-Za-z]{2,3})(\d{1,4})$", flight_id.strip())
    if not match:
        return None
    prefix, number = match.groups()
    icao_prefix = IATA_TO_ICAO_AIRLINE.get(prefix.upper())
    if not icao_prefix:
        return None
    return f"{icao_prefix}{number}"


_token_cache = {"access_token": None, "expires_at": 0}

def _get_token():
    """Fetch (or return cached) OAuth2 bearer token via client credentials flow."""
    if time.time() < _token_cache["expires_at"] - 30:
        return _token_cache["access_token"]

    client_id = os.getenv("OPENSKY_CLIENT_ID")
    client_secret = os.getenv("OPENSKY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    resp = requests.post(
        "https://auth.opensky-network.org/auth/realms/opensky-network"
        "/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
    return _token_cache["access_token"]


def fetch_opensky_states():
    """One bulk request covering every currently-tracked aircraft worldwide —
    cheap to check many flights against, since it's a single call regardless
    of how many flights we're checking. Returns None on any failure (timeout,
    rate limit, etc.) so callers can treat that as "couldn't verify", not
    "confirmed not landed"."""
    try:
        headers = {}
        try:
            token = _get_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            else:
                print("[opensky] OAuth2 token alınamadı, anonim istek yapılıyor")
        except Exception as e:
            print(f"[opensky] Token hatası: {e}")

        resp = requests.get(
            "https://opensky-network.org/api/states/all",
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 429:
            retry = resp.headers.get("X-Rate-Limit-Retry-After-Seconds", "?")
            print(f"[opensky] Rate limit — {retry}s sonra tekrar denenecek")
            return None
        resp.raise_for_status()
        return resp.json().get("states") or []
    except Exception as e:
        print(f"[opensky] Hata: {e}")
        return None


def check_landed_status(flight_id, states):
    """Returns "landed", "airborne", or "unknown" (not found in OpenSky's
    current snapshot, or no states available — ambiguous, not evidence of
    anything; a flight can be missing just because it's outside ADS-B
    receiver coverage)."""
    callsign = iata_flight_to_icao_callsign(flight_id)
    if not callsign or states is None:
        return "unknown"

    for state in states:
        # State vector layout: [icao24, callsign, origin_country,
        # time_position, last_contact, lon, lat, baro_altitude, on_ground, ...]
        state_callsign = (state[1] or "").strip()
        if state_callsign == callsign:
            return "landed" if state[8] else "airborne"

    return "unknown"
