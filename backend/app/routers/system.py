"""Root, health check and public config."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import settings
from ..container import engine, model_service, weather_service
from ..database import check_db, get_db
from ..models import PricingRule, Product

router = APIRouter(tags=["System"])
_scheduler_ref = {"scheduler": None}


def register_scheduler(scheduler) -> None:
    _scheduler_ref["scheduler"] = scheduler


@router.get("/")
def root():
    return {
        "message": settings.app_name, "version": settings.version, "status": "running", "docs": "/docs",
        "endpoints": {
            "products": "/products", "current_price": "/prices/{product_id}/current", "simulate": "/simulate_price",
            "history": "/history/{product_id}", "signals": "/signals", "rules": "/rules",
            "weather": "/api/weather/current", "holidays": "/api/holidays/upcoming",
            "exchange": "/api/exchange/convert", "dashboard": "/api/dashboard/stats",
            "model_metrics": "/api/model/metrics", "feature_importance": "/api/model/feature-importance",
            "revenue_curve": "/api/analytics/revenue-curve/{product_id}",
            "price_forecast": "/api/analytics/price-forecast/{product_id}",
        },
    }


@router.get("/health")
def health():
    db_ok = check_db()
    scheduler = _scheduler_ref["scheduler"]
    ml = model_service.status
    return {
        "status": "healthy" if db_ok else "degraded",
        "services": {
            "database": "operational" if db_ok else "down",
            "pricing": "operational" if model_service.ready else f"fallback ({ml.get('state')})",
            "weather": weather_service.source,
            "scheduler": ("running" if scheduler and scheduler.running else "disabled"),
        },
        "model": {"version": model_service.version, "active": model_service.model_type, "state": ml.get("state"),
                  "message": ml.get("message")},
    }


@router.get("/api/config")
def public_config(db=Depends(get_db)):
    return {"app_name": settings.app_name, "version": settings.version, "currency": settings.base_currency,
            "store_city": settings.store_city, "timezone": settings.store_timezone,
            "price_refresh_seconds": settings.price_refresh_seconds,
            "scheduler": _scheduler_ref["scheduler"].status() if _scheduler_ref["scheduler"] else {"enabled": False}}
