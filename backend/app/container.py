"""Shared service instances (kept in one place to avoid circular imports)."""
from .ml.registry import model_service
from .services.exchange_service import exchange_service
from .services.holiday_service import holiday_service
from .services.pricing_engine import PricingEngine
from .services.weather_service import weather_service

engine = PricingEngine(model_service, weather_service, holiday_service)

__all__ = ["engine", "model_service", "weather_service", "holiday_service", "exchange_service"]
