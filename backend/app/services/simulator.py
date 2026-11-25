"""Simulated storefront traffic.

There is no real shop attached to this project, so each tick we synthesise what a
shop would observe: page views / carts / orders (a demand *signal* the model reads
next time) and the sales that actually happen at the *current* price, drawn from
the market world. Sales are logged next to the 'keep the base price' counterfactual
so the dashboard can show realised revenue lift. Stock is consumed and restocked.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

from ..ml import world
from ..ml.features import raw_frame
from ..models import PriceSignal, Product, SalesLog
from ..utils.timeutils import to_local, utcnow
from .pricing_engine import PricingEngine

RESTOCK_THRESHOLD = 0.08
RESTOCK_LEVEL = 0.90


def simulate_tick(db: Session, engine: PricingEngine, now_utc: Optional[datetime] = None,
                  interval_minutes: float = 5.0, weather: Optional[dict] = None, source: str = "simulator",
                  rng: Optional[np.random.Generator] = None) -> int:
    """Generate one interval of signals + sales for every active product. Returns #products."""
    rng = rng or np.random.default_rng()
    now = now_utc or utcnow()
    local = to_local(now)
    weather = weather or engine.weather.get_weather()
    hol = engine.holidays.context_for(local.date())
    scale = interval_minutes / 60.0

    products = db.query(Product).filter(Product.is_active.is_(True)).all()
    for p in products:
        cat = world.category_key(p.category)
        exp_pv = float(world.expected_page_views(cat, local.hour))
        pv = int(rng.poisson(exp_pv * rng.lognormal(0.0, 0.30)))
        cart_rate = float(np.clip(rng.beta(3, 17), 0.01, 0.60))
        conv_rate = float(np.clip(rng.beta(3, 7), 0.02, 0.90))
        carts = int(round(pv * cart_rate))
        orders = int(round(carts * conv_rate))
        db.add(PriceSignal(
            product_id=p.id, timestamp=now, page_views=pv, add_to_carts=carts, conversions=orders,
            stock_level=p.current_stock, temperature=weather["temperature"], precipitation=weather["precipitation"],
            humidity=weather.get("humidity"), weather_code=weather.get("weather_code"),
            is_holiday=bool(hol["is_holiday"]), event_score=hol["event_score"],
            competitor_price=round(p.base_price * float(np.clip(rng.normal(1.0, 0.08), 0.75, 1.30)), 2),
            source=source))
        db.flush()

        ctx = engine.build_context(db, p, now, weather=weather)
        frame = raw_frame([ctx["raw"]])
        price = float(p.current_price or p.base_price)
        stock = max(int(p.current_stock or 0), 0)
        units = min(float(world.expected_units(frame, [price / p.base_price])[0]) * scale, stock)
        base_units = min(float(world.expected_units(frame, [1.0])[0]) * scale, stock)
        db.add(SalesLog(product_id=p.id, timestamp=now, price=price, units=round(units, 3),
                        revenue=round(units * price, 2), baseline_units=round(base_units, 3),
                        baseline_revenue=round(base_units * p.base_price, 2)))

        sold = int(rng.poisson(units))
        new_stock = max(0, stock - sold)
        if new_stock <= RESTOCK_THRESHOLD * (p.max_stock or 200):
            new_stock = int(RESTOCK_LEVEL * (p.max_stock or 200))
        p.current_stock = new_stock
    db.commit()
    return len(products)
