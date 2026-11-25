from datetime import date, datetime

from app.services.exchange_service import ExchangeRateService
from app.services.holiday_service import HolidayService
from app.services.metrics import LatencyTracker
from app.services.weather_service import WeatherService, precipitation_score, wmo_to_text

OPEN_METEO_SAMPLE = {
    "current": {"time": "2026-10-03T14:15", "temperature_2m": 27.4, "relative_humidity_2m": 71, "precipitation": 1.2,
                "weather_code": 63, "wind_speed_10m": 9.5, "is_day": 1},
    "hourly": {"time": [f"2026-10-03T{h:02d}:00" for h in range(24)] + [f"2026-10-04T{h:02d}:00" for h in range(24)],
               "temperature_2m": [20 + (i % 24) * 0.3 for i in range(48)],
               "precipitation_probability": [40] * 48, "precipitation": [0.5] * 48, "weather_code": [61] * 48},
}


def test_open_meteo_parser():
    w = WeatherService.parse_live(OPEN_METEO_SAMPLE, "Bengaluru")
    assert w["temperature"] == 27.4 and w["condition"] == "Rainy" and w["humidity"] == 71
    assert 0.3 < w["precipitation"] <= 1.0 and w["source"] == "open-meteo"
    assert len(w["forecast"]) == 24 and w["forecast"][0]["temperature"] == OPEN_METEO_SAMPLE["hourly"]["temperature_2m"][14]


def test_synthetic_weather_is_deterministic_and_plausible():
    t = datetime(2026, 10, 3, 9, 0)
    a, b = WeatherService.synthetic_weather("Bengaluru", t), WeatherService.synthetic_weather("Bengaluru", t)
    assert a == b
    assert 10 < a["temperature"] < 40 and 0 <= a["precipitation"] <= 1


def test_precipitation_score_and_codes():
    assert precipitation_score(0, None, 0) == 0
    assert precipitation_score(2.0, 80, 63) > precipitation_score(0.1, 80, 63)
    assert wmo_to_text(95) == "Thunderstorm" and wmo_to_text(0, True) == "Sunny" and wmo_to_text(0, False) == "Clear"


def test_holidays_diwali_2026():
    hs = HolidayService("IN")
    ctx = hs.context_for(date(2026, 11, 1))
    assert ctx["next_event"]["name"].startswith("Diwali") and ctx["days_to_event"] == 7
    assert ctx["is_holiday"] == 0 and 0.1 < ctx["event_score"] <= 1
    today = hs.context_for(date(2026, 11, 8))
    assert today["is_holiday"] == 1 and today["days_to_event"] == 0 and today["event_score"] >= 0.99


def test_holiday_upcoming_sorted():
    items = HolidayService("IN").upcoming(60, today=date(2026, 10, 3))
    days = [i["days_until"] for i in items]
    assert days == sorted(days) and any(i["name"] == "Dussehra" and i["days_until"] == 17 for i in items)


def test_exchange_fallback_conversion(monkeypatch):
    svc = ExchangeRateService()
    svc._fail_until = 1e18                     # pretend the API is down
    r = svc.convert(100, "INR", "USD")
    assert r["success"] and r["source"] == "offline-fallback" and 0.5 < r["converted_amount"] < 3
    assert not svc.convert(1, "INR", "XXX")["success"]


def test_latency_tracker():
    t = LatencyTracker()
    assert t.summary()["count"] == 0
    for v in (1, 2, 3, 100):
        t.record(v)
    s = t.summary()
    assert s["count"] == 4 and s["max_ms"] == 100 and s["p50_ms"] < s["p95_ms"]
