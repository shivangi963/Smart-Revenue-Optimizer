"""Weather, holidays and exchange-rate endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..container import exchange_service, holiday_service, weather_service
from ..services.exchange_service import CURRENCIES
from ..services.weather_service import CITIES

router = APIRouter(tags=["External data"])


@router.get("/api/weather/current")
def current_weather(city: str = None):
    w = dict(weather_service.get_weather(city))
    w.pop("forecast", None)
    return w


@router.get("/api/weather/forecast")
def weather_forecast(city: str = None, hours: int = Query(24, ge=1, le=48)):
    return {"city": weather_service.get_weather(city)["city"], "forecast": weather_service.forecast(city, hours)}


@router.get("/api/weather/cities")
def weather_cities():
    return {"cities": list(CITIES)}


@router.get("/api/holidays/upcoming")
def upcoming_holidays(days: int = Query(30, ge=1, le=365)):
    items = holiday_service.upcoming(days)
    return {"upcoming_holidays": items, "total_count": len(items), "days_lookahead": days,
            "country": holiday_service.country}


@router.get("/api/exchange/currencies")
def currencies():
    return {"currencies": CURRENCIES}


@router.get("/api/exchange/rates")
def rates(base: str = "INR"):
    data = exchange_service.get_latest_rates(base)
    if not data.get("success"):
        raise HTTPException(400, data.get("error", "Rates unavailable"))
    return data


@router.get("/api/exchange/convert")
def convert(amount: float = Query(gt=0), from_currency: str = "INR", to_currency: str = "USD"):
    result = exchange_service.convert(amount, from_currency, to_currency)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "Conversion failed"))
    return result
