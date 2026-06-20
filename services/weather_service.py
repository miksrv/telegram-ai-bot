"""
Weather Service
Handles weather API requests
"""

from typing import Tuple

import requests

from config.settings import WEATHER_API_KEY


# ------------------------
def get_coordinates(city: str) -> Tuple[float, float]:
    """Resolves a city name to (lat, lon) via the OpenWeatherMap geocoding API.

    Reuses the same provider as get_weather so a single API key covers both.

    Raises:
        ValueError: if the city cannot be found.
        requests.RequestException: on network/API errors.
    """
    url = "https://api.openweathermap.org/geo/1.0/direct"

    params = {
        "q": city,
        "limit": 1,
        "appid": WEATHER_API_KEY,
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()
    if not data:
        raise ValueError(f"City '{city}' not found")

    return float(data[0]["lat"]), float(data[0]["lon"])


# ------------------------
def get_weather(city: str) -> str:
    url = "https://api.openweathermap.org/data/2.5/weather"

    params = {
        "q": city,
        "appid": WEATHER_API_KEY,
        "units": "metric",
        "lang": "ru",
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()

    temp = data["main"]["temp"]
    feels = data["main"]["feels_like"]
    description = data["weather"][0]["description"]
    humidity = data["main"]["humidity"]
    wind_speed = data.get("wind", {}).get("speed", "н/д")
    pressure = data["main"].get("pressure", "н/д")
    visibility = data.get("visibility", "н/д")
    clouds = data.get("clouds", {}).get("all", "н/д")

    return (
        f"🌤 Погода {city}:\n\n"
        f"Температура: {temp}°C\n"
        f"Ощущается как: {feels}°C\n"
        f"Состояние: {description}\n"
        f"Влажность: {humidity}%\n"
        f"Ветер: {wind_speed} м/с\n"
        f"Давление: {pressure} гПа\n"
        f"Видимость: {visibility} м\n"
        f"Облачность: {clouds}%"
    )
