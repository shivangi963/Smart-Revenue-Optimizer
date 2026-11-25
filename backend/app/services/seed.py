"""First-run data: demo products + a backfilled price/sales history so every
chart has something to show on day one."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
from sqlalchemy.orm import Session

from ..models import PriceHistory, Product
from ..utils.timeutils import utcnow
from .pricing_engine import PricingEngine
from .simulator import simulate_tick
from .weather_service import WeatherService, resolve_city
from ..config import settings

SEED_PRODUCTS = [
    dict(sku="UMB-001", name="Premium Umbrella", category="umbrella", base_price=799.0, cost=400.0,
         price_min=549.0, price_max=1299.0, price_step=5.0, current_stock=140, max_stock=200),
    dict(sku="ICE-001", name="Artisanal Ice Cream", category="ice_cream", base_price=199.0, cost=85.0,
         price_min=129.0, price_max=349.0, price_step=1.0, current_stock=210, max_stock=300),
    dict(sku="TIX-001", name="Concert Ticket", category="ticket", base_price=2499.0, cost=1500.0,
         price_min=1999.0, price_max=4499.0, price_step=10.0, current_stock=60, max_stock=100),
]


def seed_products(db: Session) -> int:
    if db.query(Product).count() > 0:
        return 0
    for spec in SEED_PRODUCTS:
        db.add(Product(margin_floor=0.10, max_change_pct=0.10, is_active=True, **spec))
    db.commit()
    return len(SEED_PRODUCTS)


def backfill_history(db: Session, engine: PricingEngine, hours: int = None) -> int:
    """Replay the last N hours (one tick per hour) using deterministic simulated weather,
    so charts are populated. Idempotent: skipped once seeded history exists (live rows written
    before the model finished training do not count)."""
    hours = hours or settings.seed_history_hours
    if hours <= 0 or db.query(PriceHistory).filter(PriceHistory.source == "seed").count() > 0:
        return 0
    city = resolve_city(None)
    rng = np.random.default_rng(2026)
    start = utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours)
    products = db.query(Product).filter(Product.is_active.is_(True)).all()
    for k in range(hours):
        ts = start + timedelta(hours=k)
        weather = WeatherService.synthetic_weather(city, ts)
        simulate_tick(db, engine, ts, interval_minutes=60.0, weather=weather, source="seed", rng=rng)
        for p in products:
            engine.recommend(db, p, now_utc=ts, weather=weather, persist=True, explain=False, source="seed")
    return hours
