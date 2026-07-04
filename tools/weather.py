import requests

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm + slight hail", 99: "Thunderstorm + heavy hail",
}

WMO_EMOJI = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️",
    71: "❄️", 73: "❄️", 75: "❄️", 77: "❄️",
    80: "🌦️", 81: "🌧️", 82: "⛈️",
    85: "🌨️", 86: "🌨️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}


def get_weather_by_coords(lat, lng):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lng}"
        "&current=temperature_2m,wind_speed_10m,wind_direction_10m,weather_code"
        "&wind_speed_unit=kmh&timezone=auto"
    )
    try:
        resp = requests.get(url, timeout=6)
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {})
        code = current.get("weather_code", 0)
        return {
            "temp_c": current.get("temperature_2m"),
            "wind_kmh": round(current.get("wind_speed_10m", 0)),
            "wind_dir": current.get("wind_direction_10m"),
            "condition": WMO_CODES.get(code, "Unknown"),
            "emoji": WMO_EMOJI.get(code, "🌡️"),
            "weather_code": code,
        }
    except Exception:
        return None


def get_weather_for_airport(iata_code):
    from tools.statistics import get_airport_info
    info = get_airport_info(iata_code)
    if not info:
        return None
    weather = get_weather_by_coords(info["lat"], info["lng"])
    if not weather:
        return None
    weather["airport"] = iata_code
    weather["airport_name"] = info.get("name", iata_code)
    weather["city"] = info.get("municipality", "")
    return weather
