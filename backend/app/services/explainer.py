"""Explainability layer ("explanation and visualisation layer" in the paper).

For the six factor groups (weather, time, events, demand, inventory, competition)
we compute *exact Shapley values* of the model's price ratio: every subset of
groups is either left at its real value or reset to a neutral value, the model
is queried for all 2^6 = 64 combinations in one batch, and each group's
contribution is its average marginal effect. The contributions add up exactly to
(prediction - prediction in a neutral context).
"""
from __future__ import annotations

from itertools import combinations
from math import factorial
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from ..ml.features import EXPLAIN_GROUPS, GROUP_RAW_COLUMNS, RAW_COLUMNS, neutral_values
from ..ml.world import category_key

K = len(EXPLAIN_GROUPS)


def shapley_contributions(predict_ratio: Callable[[pd.DataFrame], np.ndarray], raw_row: dict) -> dict:
    """Return {'contributions': {group: pct_of_base}, 'neutral_offset_pct': x, 'full_ratio': r}."""
    neutral = neutral_values(raw_row)
    rows = []
    for mask in range(1 << K):
        row = dict(raw_row)
        for i, group in enumerate(EXPLAIN_GROUPS):
            if not (mask >> i) & 1:                     # group switched OFF -> neutral values
                for col in GROUP_RAW_COLUMNS[group]:
                    row[col] = neutral[col]
        rows.append(row)
    frame = pd.DataFrame(rows)[RAW_COLUMNS]
    v = np.asarray(predict_ratio(frame), dtype=float)   # v[mask] = predicted ratio for that coalition

    weights = [factorial(s) * factorial(K - s - 1) / factorial(K) for s in range(K)]
    phi = np.zeros(K)
    for i in range(K):
        others = [j for j in range(K) if j != i]
        for size in range(K):
            for subset in combinations(others, size):
                m = sum(1 << j for j in subset)
                phi[i] += weights[size] * (v[m | (1 << i)] - v[m])
    return {
        "contributions": {g: float(phi[i] * 100.0) for i, g in enumerate(EXPLAIN_GROUPS)},
        "neutral_offset_pct": float((v[0] - 1.0) * 100.0),
        "full_ratio": float(v[(1 << K) - 1]),
    }


# --------------------------------------------------------------------------- text
def _weather_phrase(pos: bool, ctx: dict) -> str:
    if pos:
        if ctx["precipitation"] >= 0.3:
            return "rainy weather"
        if ctx["temperature"] >= 30:
            return "hot weather"
        if ctx["temperature"] <= 18:
            return "cold weather"
        return "favourable weather"
    if ctx["precipitation"] >= 0.3:
        return "rain suppressing demand"
    return "weather reducing demand"


_HIT_NAMES = {"price_min": "minimum price", "price_max": "maximum price", "margin_floor": "margin floor",
              "max_discount": "maximum-discount rule", "max_markup": "maximum-markup rule",
              "volatility_cap": "volatility cap (limits how fast prices move)", "price_frozen": "price freeze"}


def _driver_phrases(category: str, ctx: dict, factors_pct: Dict[str, float], model_change_pct: float,
                    holiday_name: Optional[str], next_event: Optional[dict]) -> List[str]:
    real = [(g, v) for g, v in factors_pct.items() if g not in ("guardrails", "manual_adjustment") and abs(v) >= 0.5]
    same_sign = [(g, v) for g, v in real if (v > 0) == (model_change_pct > 0)]
    ranked = sorted(same_sign or real, key=lambda kv: -abs(kv[1]))[:3]
    phrases = []
    for group, value in ranked:
        pos = value > 0
        if group == "weather":
            phrases.append(_weather_phrase(pos, ctx))
        elif group == "time_of_day":
            if not pos:
                phrases.append("off-peak hours")
            elif ctx["hour_of_day"] >= 17:
                phrases.append("evening peak hours")
            elif ctx["day_of_week"] >= 5:
                phrases.append("weekend demand")
            else:
                phrases.append("seasonal demand")
        elif group == "holiday_effect":
            if holiday_name:
                phrases.append(f"{holiday_name} today")
            elif next_event and next_event["days_until"] <= 14:
                phrases.append(f"{next_event['name']} approaching ({next_event['days_until']}d)")
            else:
                phrases.append("upcoming festival demand")
        elif group == "demand":
            phrases.append("high demand" if pos else "low demand")
        elif group == "inventory":
            phrases.append("low stock" if pos else "excess stock clearance")
        elif group == "competition":
            phrases.append("higher competitor prices" if pos else "competitor undercutting")
    return phrases


def build_rationale(category: str, ctx: dict, factors_pct: Dict[str, float], model_change_pct: float,
                    final_change_pct: float, constraints_hit: List[str], holiday_name: Optional[str],
                    next_event: Optional[dict]) -> str:
    """Plain-English reason. Describes what the *model* wants, then (if a guardrail
    changed the outcome) why the final price differs."""
    hit_text = ", ".join(_HIT_NAMES.get(h, h) for h in constraints_hit)
    if "price_frozen" in constraints_hit:
        return "Price is frozen by an admin rule, so it was not changed."
    if abs(model_change_pct) < 0.5:
        base = "Conditions are close to normal, so the model keeps the price near the base price"
    else:
        why = _driver_phrases(category, ctx, factors_pct, model_change_pct, holiday_name, next_event)
        verb = "increase" if model_change_pct > 0 else "decrease"
        base = f"Model suggests a {abs(model_change_pct):.1f}% {verb}"
        if why:
            base += " due to " + ", ".join(why)
    if constraints_hit:
        return f"{base}; final price ({final_change_pct:+.1f}% vs base) is limited by the {hit_text}."
    return base + "."
