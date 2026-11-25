"""Demand/context signals."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..container import engine
from ..database import get_db
from ..models import PriceSignal
from ..schemas import SignalCreate, SignalOut
from ..security import get_current_user, require_admin, require_ingest
from ..services.simulator import simulate_tick
from ..utils.timeutils import to_local, utcnow
from .products import get_product_or_404

router = APIRouter(tags=["Signals"])


@router.post("/signals", response_model=SignalOut, status_code=201, dependencies=[Depends(require_ingest)])
def create_signal(body: SignalCreate, db: Session = Depends(get_db)):
    """Store one observation. Anything not supplied (weather, holiday, stock) is
    filled in from the live services so a minimal client only needs the funnel counts."""
    product = get_product_or_404(db, body.product_id)
    weather = engine.weather.get_weather()
    hol = engine.holidays.context_for(to_local(utcnow()).date())
    signal = PriceSignal(
        product_id=product.id,
        page_views=body.page_views, add_to_carts=body.add_to_carts, conversions=body.conversions,
        stock_level=body.stock_level if body.stock_level is not None else product.current_stock,
        temperature=body.temperature if body.temperature is not None else weather["temperature"],
        precipitation=body.precipitation if body.precipitation is not None else weather["precipitation"],
        humidity=body.humidity if body.humidity is not None else weather.get("humidity"),
        weather_code=body.weather_code if body.weather_code is not None else weather.get("weather_code"),
        is_holiday=body.is_holiday if body.is_holiday is not None else bool(hol["is_holiday"]),
        event_score=body.event_score if body.event_score is not None else hol["event_score"],
        competitor_price=body.competitor_price, source="api")
    db.add(signal)
    db.commit()
    return signal


@router.get("/signals/{product_id}", response_model=List[SignalOut], dependencies=[Depends(get_current_user)])
def list_signals(product_id: int, limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    get_product_or_404(db, product_id)
    return (db.query(PriceSignal).filter(PriceSignal.product_id == product_id)
            .order_by(PriceSignal.timestamp.desc()).limit(limit).all())


@router.post("/signals/simulate", dependencies=[Depends(require_admin)])
def simulate_signals(ticks: int = Query(1, ge=1, le=12), db: Session = Depends(get_db)):
    """Generate synthetic storefront traffic + sales now, then re-price (handy for demos)."""
    for _ in range(ticks):
        simulate_tick(db, engine, interval_minutes=5.0)
    prices = engine.refresh_all(db)
    return {"ticks": ticks, "repriced": len(prices)}
