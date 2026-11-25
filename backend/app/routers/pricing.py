"""Prices, what-if simulation, history and the recommendation audit trail."""
from __future__ import annotations

import json
import math
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..container import engine
from ..database import get_db
from ..models import PriceHistory, PriceRecommendation, Product
from ..schemas import SimulationRequest
from ..utils.timeutils import iso_z, utcnow
from .products import get_product_or_404

router = APIRouter(tags=["Pricing"])


@router.get("/prices/current")
def current_prices(db: Session = Depends(get_db)):
    """Current price of every active product (one call for the dashboard grid)."""
    products = db.query(Product).filter(Product.is_active.is_(True)).order_by(Product.id).all()
    return [engine.current_price(db, p) for p in products]


@router.get("/prices/{product_id}/current")
def current_price(product_id: int, refresh: bool = False, db: Session = Depends(get_db)):
    product = get_product_or_404(db, product_id)
    return engine.current_price(db, product, force=refresh)


@router.post("/simulate_price")
def simulate_price(body: SimulationRequest, db: Session = Depends(get_db)):
    """What-if: price under hypothetical conditions. Nothing is stored and the
    volatility cap / freeze rules (which depend on the live price) are not applied."""
    product = get_product_or_404(db, body.product_id)
    numeric = {}
    for key, value in body.features.items():
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            numeric[key] = v
    return engine.recommend(db, product, overrides=numeric, manual_adjustments=body.manual_adjustments,
                            persist=False, explain=True, apply_dynamics=False)


@router.get("/history/{product_id}")
def price_history(product_id: int, hours: int = Query(24, ge=1, le=720), max_points: int = Query(300, ge=10, le=2000),
                  db: Session = Depends(get_db)):
    product = get_product_or_404(db, product_id)
    since = utcnow() - timedelta(hours=hours)
    rows = (db.query(PriceHistory).filter(PriceHistory.product_id == product_id, PriceHistory.timestamp >= since)
            .order_by(PriceHistory.timestamp).all())
    points = [{"timestamp": iso_z(r.timestamp), "price": r.price, "source": r.source} for r in rows]
    if len(points) > max_points:                       # bucket-average so charts stay light
        size = math.ceil(len(points) / max_points)
        merged = []
        for i in range(0, len(points), size):
            chunk = points[i:i + size]
            merged.append({"timestamp": chunk[len(chunk) // 2]["timestamp"],
                           "price": round(sum(c["price"] for c in chunk) / len(chunk), 2), "source": "aggregated"})
        points = merged
    prices = [p["price"] for p in points]
    stats = None
    if prices:
        stats = {"min": min(prices), "max": max(prices), "avg": round(sum(prices) / len(prices), 2),
                 "current": prices[-1], "base_price": product.base_price,
                 "change_pct": round((prices[-1] / prices[0] - 1) * 100, 2) if prices[0] else 0.0}
    return {"product_id": product_id, "hours": hours, "count": len(points), "history": points, "stats": stats}


@router.get("/recommendations/{product_id}")
def recommendations(product_id: int, limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)):
    """Audit trail: why was each price chosen?"""
    get_product_or_404(db, product_id)
    rows = (db.query(PriceRecommendation).filter(PriceRecommendation.product_id == product_id)
            .order_by(PriceRecommendation.timestamp.desc()).limit(limit).all())
    out = []
    for r in rows:
        payload = json.loads(r.payload_json) if r.payload_json else {}
        out.append({"id": r.id, "timestamp": iso_z(r.timestamp), "model_version": r.model_version,
                    "model_type": r.model_type, "base_price": r.base_price, "model_price": r.recommended_price,
                    "final_price": r.final_price, "confidence": r.confidence, "rationale": r.rationale,
                    "constraints_hit": json.loads(r.constraints_hit or "[]"), "factors": payload.get("factors", {}),
                    "latency_ms": r.latency_ms})
    return {"product_id": product_id, "count": len(out), "recommendations": out}
