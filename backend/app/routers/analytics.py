"""Analytics: dashboard KPIs, the revenue response curve (paper Fig. 4), the
24-hour price trend (paper Fig. 3) and realised revenue vs. static pricing."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..container import engine, model_service
from ..database import get_db
from ..ml import world
from ..ml.demand import peak_from_curve
from ..ml.features import engineer_features, raw_frame
from ..models import PriceHistory, PricingRule, Product, SalesLog
from ..services.guardrails import resolve_constraints
from ..services.metrics import latency_tracker
from ..services.weather_service import WeatherService
from ..utils.timeutils import iso_z, to_local, utcnow
from .products import get_product_or_404

router = APIRouter(tags=["Analytics"])


def _revenue_summary(db: Session, hours: int) -> dict:
    since = utcnow() - timedelta(hours=hours)
    rows = db.query(SalesLog).filter(SalesLog.timestamp >= since).order_by(SalesLog.timestamp).all()
    names = {p.id: p.name for p in db.query(Product).all()}
    per_product = defaultdict(lambda: {"revenue": 0.0, "baseline_revenue": 0.0, "units": 0.0, "baseline_units": 0.0})
    hourly = defaultdict(lambda: {"revenue": 0.0, "baseline_revenue": 0.0})
    for r in rows:
        pp = per_product[r.product_id]
        pp["revenue"] += r.revenue
        pp["baseline_revenue"] += r.baseline_revenue
        pp["units"] += r.units
        pp["baseline_units"] += r.baseline_units
        bucket = r.timestamp.replace(minute=0, second=0, microsecond=0)
        hourly[bucket]["revenue"] += r.revenue
        hourly[bucket]["baseline_revenue"] += r.baseline_revenue

    def lift(a, b):
        return round((a / b - 1.0) * 100.0, 2) if b > 0 else 0.0

    total_rev = sum(v["revenue"] for v in per_product.values())
    total_base = sum(v["baseline_revenue"] for v in per_product.values())
    return {
        "hours": hours,
        "total": {"revenue": round(total_rev, 2), "baseline_revenue": round(total_base, 2),
                  "lift_pct": lift(total_rev, total_base), "gain": round(total_rev - total_base, 2)},
        "per_product": [{"product_id": pid, "product_name": names.get(pid, str(pid)),
                         **{k: round(v, 2) for k, v in vals.items()},
                         "lift_pct": lift(vals["revenue"], vals["baseline_revenue"])}
                        for pid, vals in sorted(per_product.items())],
        "hourly": [{"time": iso_z(t), "revenue": round(v["revenue"], 2),
                    "baseline_revenue": round(v["baseline_revenue"], 2)} for t, v in sorted(hourly.items())],
    }


@router.get("/api/analytics/revenue-summary")
def revenue_summary(hours: int = Query(24, ge=1, le=720), db: Session = Depends(get_db)):
    """Realised (simulated) revenue vs. what static base pricing would have earned."""
    return _revenue_summary(db, hours)


@router.get("/api/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.is_active.is_(True)).all()
    since = utcnow() - timedelta(hours=24)
    updates = db.query(func.count(PriceHistory.id)).filter(PriceHistory.timestamp >= since).scalar() or 0
    changes = [(p.current_price / p.base_price - 1) * 100 for p in products if p.current_price]
    recent = (db.query(PriceHistory, Product).join(Product, Product.id == PriceHistory.product_id)
              .order_by(PriceHistory.timestamp.desc()).limit(8).all())
    metrics = model_service.metrics()
    best = None
    if metrics.get("ready"):
        row = next((s for s in metrics["strategies"] if s["key"] == metrics["active_model"]), None)
        best = row and {"r2": row["r2"], "mae": row["mae"], "rmse": row["rmse"], "revenue_lift_pct": row["revenue_lift_pct"]}
    return {
        "summary": {
            "total_products": db.query(Product).count(), "active_products": len(products),
            "avg_price_change": round(sum(changes) / len(changes), 2) if changes else 0.0,
            "total_price_updates": updates, "model_version": model_service.version,
            "model_type": model_service.model_type,
        },
        "recent_changes": [{"product_id": p.id, "product_name": p.name, "current_price": h.price,
                            "change": round((h.price / p.base_price - 1) * 100, 1), "timestamp": iso_z(h.timestamp)}
                           for h, p in recent],
        "revenue": _revenue_summary(db, 24),
        "model_performance": best,
        "latency": latency_tracker.summary(),
    }


@router.get("/api/analytics/revenue-curve/{product_id}")
def revenue_curve(product_id: int, points: int = Query(40, ge=10, le=100), db: Session = Depends(get_db)):
    """Expected revenue vs. candidate price, from the learned demand model."""
    if not model_service.ready:
        raise HTTPException(503, "The ML model is still training - try again in a moment")
    product = get_product_or_404(db, product_id)
    ctx = engine.build_context(db, product)
    frame = raw_frame([ctx["raw"]])
    feats = engineer_features(frame)
    base = float(product.base_price)

    rules = db.query(PricingRule).filter(PricingRule.is_active.is_(True)).all()
    lo, hi = resolve_constraints(product, rules, apply_dynamics=False).bounds()

    ratios = np.linspace(world.RATIO_MIN, world.RATIO_MAX, points)
    prices = ratios * base
    rep_raw = pd.concat([frame] * points, ignore_index=True)
    rep_feats = pd.concat([feats] * points, ignore_index=True)
    units = model_service.predict_units(rep_raw, ratios, features=rep_feats)
    revenue = units * prices
    profit = units * (prices - float(product.cost))
    peak_ratio, smooth = peak_from_curve(ratios, revenue)
    optimal = peak_ratio * base

    rec = engine.recommend(db, product, persist=False, explain=False, apply_dynamics=False)
    return {
        "product_id": product_id, "product_name": product.name, "base_price": round(base, 2),
        "recommended_price": rec["final_price"], "model_price": rec["recommended_price"],
        "optimal_price": round(optimal, 2),
        "optimal_price_allowed": round(min(max(optimal, lo), hi), 2),
        "allowed_range": {"min": round(lo, 2), "max": round(hi, 2)},
        "curve": [{"price": round(float(p), 2), "ratio": round(float(r), 3), "units": round(float(u), 2),
                   "revenue": round(float(v), 2), "revenue_smooth": round(float(s), 2), "profit": round(float(pr), 2)}
                  for p, r, u, v, s, pr in zip(prices, ratios, units, revenue, smooth, profit)],
    }


@router.get("/api/analytics/price-forecast/{product_id}")
def price_forecast(product_id: int, hours: int = Query(24, ge=1, le=48), db: Session = Depends(get_db)):
    """Recommended price for each of the next N hours, using the weather forecast,
    the holiday calendar and the typical daily traffic curve."""
    product = get_product_or_404(db, product_id)
    now = utcnow()
    start = now.replace(minute=0, second=0, microsecond=0)
    start -= timedelta(minutes=to_local(start).minute)      # align to the store's local clock hour (e.g. IST is UTC+5:30)
    cur = engine.weather.get_weather()
    forecast = engine.weather.forecast(hours=48)
    cat = world.category_key(product.category)

    sig = engine.signal_summary(db, product, now)
    if sig:
        ratio_now = sig["traffic_ratio"]
        base_ov = {"add_to_cart_rate": sig["cart_rate"], "conversion_rate": sig["conv_rate"]}
        if sig["competitor_price"]:
            base_ov["competitor_price"] = sig["competitor_price"]
    else:
        ratio_now, base_ov = 1.0, {}
    traffic_ratio = float(np.clip(ratio_now, 0.5, 2.0))

    pts = []
    for k in range(hours):
        ts = start + timedelta(hours=k)
        local = to_local(ts)
        fc = forecast[k] if k < len(forecast) else WeatherService.synthetic_weather(cur["city"], ts)
        w = {"city": cur["city"], "temperature": fc["temperature"], "precipitation": fc["precipitation"],
             "humidity": cur.get("humidity", 60.0), "condition": cur.get("condition"), "source": cur.get("source")}
        ov = {**base_ov, "page_views_1h": traffic_ratio * float(world.expected_page_views(cat, local.hour))}
        rec = engine.recommend(db, product, overrides=ov, now_utc=ts, weather=w, persist=False, explain=False,
                               apply_dynamics=False)
        pts.append({"time": iso_z(ts), "label": local.strftime("%H:%M"), "hour": local.hour,
                    "price": rec["final_price"], "change_pct": rec["total_change"],
                    "temperature": round(fc["temperature"], 1), "precipitation": round(fc["precipitation"], 2),
                    "event": rec["holiday_info"]["holiday_name"]})
    prices = [p["price"] for p in pts]
    return {"product_id": product_id, "product_name": product.name, "base_price": product.base_price,
            "hours": hours, "forecast": pts,
            "summary": {"min": min(prices), "max": max(prices),
                        "best_hour": pts[int(np.argmax(prices))]["label"],
                        "cheapest_hour": pts[int(np.argmin(prices))]["label"]}}
