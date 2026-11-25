"""Weather: live data from Open-Meteo (free, no API key) with a cache, a failure
back-off, and a *deterministic* simulated fallback so the app works offline and
the numbers do not jump around on every refresh."""
from __future__ import annotations

import hashlib
import math
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import requests

from ..config import settings
from ..utils.timeutils import iso_z, to_local, utcnow

CITIES: Dict[str, dict] = {
    "Bengaluru": {"lat": 12.9716, "lon": 77.5946, "t_mean": 24.0, "t_amp": 2.5},
    "Mumbai": {"lat": 19.0760, "lon": 72.8777, "t_mean": 28.0, "t_amp": 2.5},
    "Delhi": {"lat": 28.6139, "lon": 77.2090, "t_mean": 25.0, "t_amp": 9.0},
    "Chennai": {"lat": 13.0827, "lon": 80.2707, "t_mean": 29.0, "t_amp": 3.0},
    "Hyderabad": {"lat": 17.3850, "lon": 78.4867, "t_mean": 27.0, "t_amp": 4.0},
    "Kolkata": {"lat": 22.5726, "lon": 88.3639, "t_mean": 27.0, "t_amp": 5.0},
    "Pune": {"lat": 18.5204, "lon": 73.8567, "t_mean": 25.0, "t_amp": 4.0},
    "London": {"lat": 51.5074, "lon": -0.1278, "t_mean": 11.0, "t_amp": 7.0},
    "New York": {"lat": 40.7128, "lon": -74.0060, "t_mean": 13.0, "t_amp": 12.0},
    "Tokyo": {"lat": 35.6762, "lon": 139.6503, "t_mean": 16.0, "t_amp": 10.0},
    "Sydney": {"lat": -33.8688, "lon": 151.2093, "t_mean": 18.0, "t_amp": 5.0},
    "Dubai": {"lat": 25.2048, "lon": 55.2708, "t_mean": 28.0, "t_amp": 8.0},
    "Singapore": {"lat": 1.3521, "lon": 103.8198, "t_mean": 28.0, "t_amp": 1.0},
    "Paris": {"lat": 48.8566, "lon": 2.3522, "t_mean": 12.0, "t_amp": 8.0},
}
_ALIASES = {"bangalore": "Bengaluru", "bengaluru": "Bengaluru", "new delhi": "Delhi", "bombay": "Mumbai"}

RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
SNOW_CODES = {71, 73, 75, 77, 85, 86}


def resolve_city(name: Optional[str]) -> str:
    name = (name or settings.store_city).strip()
    key = _ALIASES.get(name.lower(), name)
    for known in CITIES:
        if known.lower() == key.lower():
            return known
    return settings.store_city if settings.store_city in CITIES else "Bengaluru"


def wmo_to_text(code: int, is_day: bool = True) -> str:
    if code in (0, 1):
        return "Sunny" if is_day else "Clear"
    if code == 2:
        return "Partly cloudy"
    if code == 3:
        return "Cloudy"
    if code in (45, 48):
        return "Fog"
    if code in (51, 53, 55, 56, 57):
        return "Drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "Rainy"
    if code in SNOW_CODES:
        return "Snowy"
    if code in (95, 96, 99):
        return "Thunderstorm"
    return "Cloudy"


def precipitation_score(mm: float, probability: Optional[float], code: int) -> float:
    """Rain *intensity* in [0, 1] - the scale the model was trained on."""
    score = 0.0
    if mm and mm > 0:
        score = min(1.0, 0.35 + mm / 4.0)
    elif code in RAIN_CODES:
        score = 0.30
    if probability:
        score = max(score, min(0.25, probability / 100.0 * 0.25))
    return round(float(score), 3)


class WeatherService:
    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    CACHE_TTL = 600        # seconds
    BACKOFF = 300          # seconds to leave the API alone after a failure

    def __init__(self) -> None:
        self._cache: Dict[str, dict] = {}
        self._fail_until = 0.0
        self._lock = threading.Lock()

    # -------------------------------------------------------------- public API
    def get_weather(self, city: Optional[str] = None) -> dict:
        city = resolve_city(city)
        with self._lock:
            hit = self._cache.get(city)
            if hit and time.time() - hit["fetched"] < self.CACHE_TTL:
                return hit["data"]
        data = None
        if time.time() >= self._fail_until:
            try:
                data = self._fetch_live(city)
            except Exception:
                self._fail_until = time.time() + self.BACKOFF
        if data is None:
            data = self.synthetic_weather(city, utcnow())
            data["forecast"] = [self._forecast_point(city, utcnow() + timedelta(hours=i)) for i in range(24)]
        with self._lock:
            self._cache[city] = {"fetched": time.time(), "data": data}
        return data

    def forecast(self, city: Optional[str] = None, hours: int = 24) -> List[dict]:
        w = self.get_weather(city)
        pts = w.get("forecast") or []
        return pts[:hours]

    @property
    def source(self) -> str:
        for entry in self._cache.values():
            return entry["data"].get("source", "unknown")
        return "not-fetched"

    # --------------------------------------------------------------- live data
    def _fetch_live(self, city: str) -> dict:
        c = CITIES[city]
        params = {
            "latitude": c["lat"], "longitude": c["lon"], "timezone": "auto", "forecast_days": 2,
            "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,is_day",
            "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code",
        }
        resp = requests.get(self.BASE_URL, params=params, timeout=4)
        resp.raise_for_status()
        return self.parse_live(resp.json(), city)

    @staticmethod
    def parse_live(payload: dict, city: str) -> dict:
        cur = payload["current"]
        code = int(cur.get("weather_code", 0))
        is_day = bool(cur.get("is_day", 1))
        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        # locate the current hour inside the hourly arrays
        start = 0
        hour_key = str(cur.get("time", ""))[:13]
        for i, t in enumerate(times):
            if str(t)[:13] == hour_key:
                start = i
                break
        probs = hourly.get("precipitation_probability") or []
        prob_now = probs[start] if start < len(probs) else None
        mm = float(cur.get("precipitation") or 0.0)

        forecast = []
        base = utcnow().replace(minute=0, second=0, microsecond=0)
        for k in range(24):
            i = start + k
            if i >= len(times):
                break
            fc_code = int((hourly.get("weather_code") or [0] * len(times))[i])
            fc_mm = float((hourly.get("precipitation") or [0] * len(times))[i] or 0.0)
            fc_prob = (probs[i] if i < len(probs) else None)
            forecast.append({
                "time": iso_z(base + timedelta(hours=k)),
                "temperature": float(hourly["temperature_2m"][i]),
                "precipitation": precipitation_score(fc_mm, fc_prob, fc_code),
                "precipitation_probability": fc_prob,
                "weather_code": fc_code,
            })
        return {
            "city": city,
            "temperature": round(float(cur["temperature_2m"]), 1),
            "humidity": float(cur.get("relative_humidity_2m", 60)),
            "precipitation": precipitation_score(mm, prob_now, code),
            "precipitation_mm": mm,
            "precipitation_probability": prob_now,
            "condition": wmo_to_text(code, is_day),
            "weather_code": code,
            "wind_speed": float(cur.get("wind_speed_10m", 0.0)),
            "timestamp": iso_z(utcnow()),
            "source": "open-meteo",
            "forecast": forecast,
        }

    # --------------------------------------------------- deterministic fallback
    @staticmethod
    def synthetic_weather(city: str, when_utc: datetime) -> dict:
        """Plausible weather that is a pure function of (city, date, 3-hour block)."""
        city = resolve_city(city)
        c = CITIES[city]
        local = to_local(when_utc)
        seed = int(hashlib.md5(f"{city}-{local:%Y%m%d}-{local.hour // 3}".encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)

        doy = local.timetuple().tm_yday
        hemisphere = 1 if c["lat"] >= 0 else -1
        seasonal = c["t_amp"] * math.sin(2 * math.pi * (doy - 110) / 365.0) * hemisphere
        diurnal = 4.5 * math.sin(2 * math.pi * (local.hour - 9) / 24.0)
        tropical = abs(c["lat"]) < 25
        monsoon = tropical and 6 <= local.month <= 10
        rain_prob = 0.50 if monsoon else (0.20 if tropical else 0.28)
        raining = rng.random() < rain_prob
        mm = float(rng.gamma(2.0, 1.2)) if raining else 0.0
        code = 63 if raining else (3 if rng.random() < 0.35 else (2 if rng.random() < 0.4 else 0))
        temp = c["t_mean"] + seasonal + diurnal + float(rng.normal(0, 1.2)) - (2.5 if raining else 0.0)
        is_day = 6 <= local.hour < 19
        return {
            "city": city,
            "temperature": round(temp, 1),
            "humidity": round(float(np.clip(55 + (28 if raining else 0) + rng.normal(0, 8), 25, 100)), 0),
            "precipitation": precipitation_score(mm, 60 if raining else 10, code),
            "precipitation_mm": round(mm, 2),
            "precipitation_probability": 70 if raining else 10,
            "condition": wmo_to_text(code, is_day),
            "weather_code": code,
            "wind_speed": round(float(rng.uniform(2, 14)), 1),
            "timestamp": iso_z(when_utc),
            "source": "simulated",
        }

    def _forecast_point(self, city: str, when_utc: datetime) -> dict:
        w = self.synthetic_weather(city, when_utc)
        return {"time": iso_z(when_utc), "temperature": w["temperature"], "precipitation": w["precipitation"],
                "precipitation_probability": w["precipitation_probability"], "weather_code": w["weather_code"]}


weather_service = WeatherService()
