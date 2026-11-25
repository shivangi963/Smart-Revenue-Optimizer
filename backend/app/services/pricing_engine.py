"""PricingEngine - the pipeline from Figure 1 of the base paper:

    internal signals + external APIs  ->  feature engineering  ->  regression model
    ->  guardrails  ->  explanation  ->  persisted recommendation / price history
"""
from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from ..config import settings
from ..ml import world
from ..ml.features import RAW_COLUMNS, engineer_features, raw_frame
from ..ml.registry import ModelService
from ..models import PriceHistory, PriceRecommendation, PriceSignal, PricingRule, Product
from ..utils.timeutils import iso_z, to_local, utcnow
from .explainer import build_rationale, shapley_contributions
from .guardrails import apply_guardrails, resolve_constraints
from .holiday_service import HolidayService
from .metrics import latency_tracker
from .weather_service import WeatherService

# What a caller may override in /simulate_price ("what-if" scenarios).
OVERRIDE_KEYS = {
    "page_views_1h", "stock_level", "competitor_price", "temperature", "precipitation", "humidity",
    "hour_of_day", "day_of_week", "month", "is_holiday", "event_score", "days_to_event",
    "add_to_cart_rate", "conversion_rate",
    "traffic_index",          # page views as a multiple of what is normal for that hour (1.0 = typical)
}
SIGNAL_MAX_AGE = timedelta(hours=12)
GRID_POINTS = 25


def _f(x) -> float:
    return float(x)


class PricingEngine:
    def __init__(self, models: ModelService, weather: WeatherService, holidays: HolidayService):
        self.models = models
        self.weather = weather
        self.holidays = holidays

    # ------------------------------------------------------------------ context
    def signal_summary(self, db: Session, product: Product, now_utc, n: int = 3) -> Optional[dict]:
        """Smooth the demand signals over the last n observations (a moving average -
        one hour with 5 carts is far too noisy to move a price on its own)."""
        rows = (db.query(PriceSignal)
                .filter(PriceSignal.product_id == product.id, PriceSignal.timestamp <= now_utc)
                .order_by(PriceSignal.timestamp.desc()).limit(n).all())
        rows = [r for r in rows if now_utc - r.timestamp <= SIGNAL_MAX_AGE]
        if not rows:
            return None
        cat = world.category_key(product.category)
        ratios = [r.page_views / max(float(world.expected_page_views(cat, to_local(r.timestamp).hour)), 1.0)
                  for r in rows]
        views, carts, orders = (sum(r.page_views for r in rows), sum(r.add_to_carts for r in rows),
                                sum(r.conversions for r in rows))
        return {
            "traffic_ratio": float(np.clip(np.mean(ratios), 0.2, 3.0)),
            "cart_rate": float(np.clip(carts / max(views, 1), 0.01, 0.60)),
            "conv_rate": float(np.clip(orders / max(carts, 1), 0.02, 0.90)),
            "competitor_price": rows[0].competitor_price,
            "n": len(rows),
        }

    def build_context(self, db: Session, product: Product, now_utc=None, overrides: Optional[dict] = None,
                      weather: Optional[dict] = None) -> dict:
        now_utc = now_utc or utcnow()
        local = to_local(now_utc)
        ov = {k: v for k, v in (overrides or {}).items() if k in OVERRIDE_KEYS and v is not None}
        cat = world.category_key(product.category)
        cat_defaults = world.CATEGORIES[cat]

        weather = weather or self.weather.get_weather()
        hol = self.holidays.context_for(local.date())
        sig = self.signal_summary(db, product, now_utc)

        hour = int(ov.get("hour_of_day", local.hour))
        exp_pv = _f(world.expected_page_views(cat, hour))
        base = _f(product.base_price)

        sig_cart = sig["cart_rate"] if sig else 0.15
        sig_conv = sig["conv_rate"] if sig else 0.30
        sig_pv = sig["traffic_ratio"] * exp_pv if sig else exp_pv     # smoothed traffic, adjusted to this hour

        raw = {
            "category": product.category,
            "base_price": base,
            "cost": _f(product.cost),
            "hour_of_day": hour,
            "day_of_week": int(ov.get("day_of_week", local.weekday())),
            "month": int(ov.get("month", local.month)),
            "page_views_1h": _f(ov["page_views_1h"] if "page_views_1h" in ov else
                                ov["traffic_index"] * exp_pv if "traffic_index" in ov else sig_pv),
            "expected_page_views": exp_pv,
            "add_to_cart_rate": _f(ov.get("add_to_cart_rate", sig_cart)),
            "conversion_rate": _f(ov.get("conversion_rate", sig_conv)),
            "stock_level": int(ov.get("stock_level", product.current_stock or 0)),
            "max_stock": int(product.max_stock or cat_defaults["max_stock"]),
            "temperature": _f(ov.get("temperature", weather["temperature"])),
            "precipitation": _f(ov.get("precipitation", weather["precipitation"])),
            "humidity": _f(ov.get("humidity", weather.get("humidity", 60.0))),
            "is_holiday": int(ov.get("is_holiday", hol["is_holiday"])),
            "event_score": _f(ov.get("event_score", hol["event_score"])),
            "days_to_event": _f(ov.get("days_to_event", hol["days_to_event"])),
            "competitor_price": _f(ov.get("competitor_price", (sig["competitor_price"] if sig and sig["competitor_price"] else base))),
        }
        return {"raw": raw, "weather": weather, "holiday": hol, "has_signal": sig is not None,
                "overridden": sorted(ov)}

    # --------------------------------------------------------- recommendation
    def recommend(self, db: Session, product: Product, *, overrides: Optional[dict] = None, now_utc=None,
                  weather: Optional[dict] = None, persist: bool = False, explain: bool = True,
                  apply_dynamics: bool = True, manual_adjustments: Optional[dict] = None,
                  rules: Optional[List[PricingRule]] = None, source: str = "model") -> dict:
        t0 = time.perf_counter()
        now_utc = now_utc or utcnow()
        ctx = self.build_context(db, product, now_utc, overrides, weather)
        raw = ctx["raw"]
        frame = raw_frame([raw])
        base = _f(product.base_price)

        ratio, version, model_type = self.models.predict_ratio(frame)
        model_price = _f(ratio[0]) * base

        manual_pct = 0.0
        adjusted = model_price
        if manual_adjustments and manual_adjustments.get("markup_pct"):
            manual_pct = _f(manual_adjustments["markup_pct"])
            adjusted = model_price * (1.0 + manual_pct / 100.0)

        if rules is None:
            rules = db.query(PricingRule).filter(PricingRule.is_active.is_(True)).all()
        constraints = resolve_constraints(product, rules, last_price=product.current_price,
                                          apply_dynamics=apply_dynamics)
        guard = apply_guardrails(adjusted, constraints)
        final = guard.final_price

        total_change = (final / base - 1.0) * 100.0
        factors: Dict[str, float] = {}
        rationale = ""
        if explain:
            sh = shapley_contributions(self.models.predict_fn(), raw)
            factors = dict(sh["contributions"])
            if abs(manual_pct) > 0.05:
                factors["manual_adjustment"] = (adjusted - model_price) / base * 100.0
            guard_pct = (final - adjusted) / base * 100.0
            if abs(guard_pct) >= 0.05:
                factors["guardrails"] = guard_pct
            rationale = build_rationale(product.category, raw, factors, (adjusted / base - 1.0) * 100.0,
                                        total_change, guard.hits, ctx["holiday"].get("holiday_name"),
                                        ctx["holiday"].get("next_event"))

        expected, confidence = self._score_price(frame, base, final, guard.lower, guard.upper)

        w = ctx["weather"]
        latency_ms = (time.perf_counter() - t0) * 1000.0
        payload = {
            "product_id": product.id,
            "product_name": product.name,
            "category": product.category,
            "base_price": round(base, 2),
            "recommended_price": round(adjusted, 2),
            "final_price": final,
            "current_price": final,
            "total_change": round(total_change, 1),
            "factors": {k: round(v, 1) for k, v in factors.items()},
            "explanation": rationale,
            "rationale": rationale,
            "confidence": round(confidence, 3),
            "model_version": version,
            "model_type": model_type,
            "constraints_applied": guard.hits,
            "allowed_range": {"min": round(guard.lower, 2), "max": round(guard.upper, 2)},
            "timestamp": iso_z(now_utc),
            "weather": {
                "city": w.get("city"), "temperature": round(raw["temperature"], 1),
                "condition": w.get("condition") if "temperature" not in ctx["overridden"] else "Custom",
                "precipitation": round(raw["precipitation"], 2), "humidity": round(raw["humidity"]),
                "source": w.get("source"),
            },
            "holiday_info": {
                "is_holiday": bool(raw["is_holiday"]), "holiday_name": ctx["holiday"].get("holiday_name"),
                "next_event": ctx["holiday"].get("next_event"), "event_score": raw["event_score"],
            },
            "expected": expected,
            "context": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in raw.items()
                        if k not in ("category", "base_price", "cost")},
            "latency_ms": round(latency_ms, 2),
        }
        if explain:                      # only the full user-facing pipeline counts (not backfill/forecast sweeps)
            latency_tracker.record(latency_ms)

        if persist:
            self._persist(db, product, payload, adjusted, guard.hits, now_utc, source)
        return payload

    def _score_price(self, frame: pd.DataFrame, base: float, final: float, lo: float, hi: float):
        """Use the learned demand model to estimate units/revenue at the chosen price and
        how close it is to the best price inside the allowed range."""
        if not self.models.ready:
            return None, 0.5
        feats = engineer_features(frame)
        prices = np.unique(np.concatenate([np.linspace(lo, hi, GRID_POINTS), [final, base]]))
        ratios = prices / base
        rep_raw = pd.concat([frame] * len(prices), ignore_index=True)
        rep_feats = pd.concat([feats] * len(prices), ignore_index=True)
        units = self.models.predict_units(rep_raw, ratios, features=rep_feats)
        revenue = units * prices
        i_final = int(np.argmin(np.abs(prices - final)))
        i_base = int(np.argmin(np.abs(prices - base)))
        in_range = (prices >= lo - 1e-9) & (prices <= hi + 1e-9)
        best = float(revenue[in_range].max()) if in_range.any() else float(revenue.max())
        rev_final, rev_base = float(revenue[i_final]), float(revenue[i_base])
        confidence = float(np.clip(rev_final / best, 0.0, 1.0)) if best > 0 else 0.5
        expected = {
            "units_per_hour_base": round(float(units[i_base]), 2),
            "units_per_hour_final": round(float(units[i_final]), 2),
            "revenue_per_hour_base": round(rev_base, 2),
            "revenue_per_hour_final": round(rev_final, 2),
            "revenue_lift_pct": round((rev_final / rev_base - 1.0) * 100.0, 2) if rev_base > 0 else 0.0,
        }
        return expected, confidence

    def _persist(self, db: Session, product: Product, payload: dict, raw_price: float, hits: List[str],
                 now_utc, source: str) -> None:
        db.add(PriceRecommendation(
            product_id=product.id, timestamp=now_utc, recommended_price=raw_price, base_price=payload["base_price"],
            final_price=payload["final_price"], model_version=payload["model_version"],
            model_type=payload["model_type"], confidence=payload["confidence"], rationale=payload["rationale"],
            constraints_hit=json.dumps(hits), payload_json=json.dumps(payload), latency_ms=payload["latency_ms"]))
        db.add(PriceHistory(product_id=product.id, timestamp=now_utc, price=payload["final_price"], source=source))
        product.current_price = payload["final_price"]
        db.commit()

    # -------------------------------------------------------------- live prices
    def current_price(self, db: Session, product: Product, force: bool = False) -> dict:
        """Fresh stored recommendation if recent enough, otherwise compute + store a new one."""
        if not force:
            rec = (db.query(PriceRecommendation).filter(PriceRecommendation.product_id == product.id)
                   .order_by(PriceRecommendation.timestamp.desc()).first())
            if rec and rec.payload_json:
                age = (utcnow() - rec.timestamp).total_seconds()
                same_model = rec.model_version == self.models.version and rec.model_type == self.models.model_type
                if 0 <= age < settings.price_refresh_seconds and same_model:
                    return json.loads(rec.payload_json)
        return self.recommend(db, product, persist=True)

    def refresh_product(self, db: Session, product: Product) -> dict:
        return self.recommend(db, product, persist=True)

    def refresh_all(self, db: Session) -> List[dict]:
        rules = db.query(PricingRule).filter(PricingRule.is_active.is_(True)).all()
        out = []
        for product in db.query(Product).filter(Product.is_active.is_(True)).all():
            out.append(self.recommend(db, product, persist=True, rules=rules))
        return out
