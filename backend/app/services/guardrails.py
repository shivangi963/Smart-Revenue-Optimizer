"""Guardrails: P = min(Pmax, max(Pmin, P*)) from the paper (margin floor, step size,
volatility cap) and admin-defined rules (/rules API).

Rule resolution: a rule scoped to a *product* beats a *category* rule, which
beats a *global* rule. Several rules at the same level -> the most restrictive wins.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from ..ml.world import category_key

# rule_type -> (human description, unit)
RULE_TYPES: Dict[str, Tuple[str, str]] = {
    "price_min": ("Minimum price", "currency"),
    "price_max": ("Maximum price", "currency"),
    "margin_floor": ("Minimum margin over cost", "fraction (0.15 = 15%)"),
    "max_discount_pct": ("Maximum discount below base price", "fraction (0.20 = 20%)"),
    "max_markup_pct": ("Maximum markup above base price", "fraction (0.30 = 30%)"),
    "max_change_pct": ("Maximum change per price update (volatility cap)", "fraction (0.10 = 10%)"),
    "price_step": ("Price step (rounding)", "currency"),
    "freeze": ("Freeze price at its current value", "ignored"),
}
SCOPES = ("global", "category", "product")
_SPECIFICITY = {"global": 0, "category": 1, "product": 2}
_LOWER_NAMES = ("price_min", "margin_floor", "max_discount")
_RESTRICTIVE_MAX = {"price_min", "margin_floor", "price_step"}          # bigger value = stricter
_RESTRICTIVE_MIN = {"price_max", "max_discount_pct", "max_markup_pct", "max_change_pct"}


@dataclass
class Constraints:
    lowers: Dict[str, float] = field(default_factory=dict)
    uppers: Dict[str, float] = field(default_factory=dict)
    price_step: float = 0.01
    max_change_pct: Optional[float] = None
    freeze: bool = False
    last_price: Optional[float] = None

    @property
    def lower(self) -> Tuple[str, float]:
        name = max(self.lowers, key=self.lowers.get)
        return name, self.lowers[name]

    @property
    def upper(self) -> Tuple[str, float]:
        name = min(self.uppers, key=self.uppers.get)
        return name, self.uppers[name]

    def bounds(self) -> Tuple[float, float]:
        lo = self.lower[1]
        hi = max(self.upper[1], lo)
        return lo, hi


@dataclass
class GuardrailResult:
    final_price: float
    hits: List[str]
    lower: float
    upper: float


def _rule_applies(rule, product) -> bool:
    if not rule.is_active:
        return False
    if rule.scope == "global":
        return True
    if rule.scope == "category":
        return category_key(rule.scope_value) == category_key(product.category)
    if rule.scope == "product":
        return str(rule.scope_value) == str(product.id)
    return False


def _effective_rules(rules: Iterable, product) -> Dict[str, float]:
    """rule_type -> value after specificity + restrictiveness resolution."""
    best: Dict[str, Tuple[int, float]] = {}
    for rule in rules:
        if not _rule_applies(rule, product) or rule.rule_type not in RULE_TYPES:
            continue
        spec = _SPECIFICITY[rule.scope]
        current = best.get(rule.rule_type)
        if current is None or spec > current[0]:
            best[rule.rule_type] = (spec, rule.value)
        elif spec == current[0]:
            pick = max if rule.rule_type in _RESTRICTIVE_MAX else min
            best[rule.rule_type] = (spec, pick(current[1], rule.value))
    return {k: v for k, (_s, v) in best.items()}


def resolve_constraints(product, rules: Iterable = (), last_price: Optional[float] = None,
                        apply_dynamics: bool = True) -> Constraints:
    """Merge the product's own limits with active admin rules."""
    eff = _effective_rules(rules, product)
    base = float(product.base_price)
    cost = float(product.cost)

    lowers = {
        "price_min": float(eff.get("price_min", product.price_min or 0.0)),
        "margin_floor": cost * (1.0 + float(eff.get("margin_floor", product.margin_floor or 0.0))),
    }
    if "max_discount_pct" in eff:
        lowers["max_discount"] = base * (1.0 - eff["max_discount_pct"])
    uppers = {"price_max": float(eff.get("price_max", product.price_max or 1e12))}
    if "max_markup_pct" in eff:
        uppers["max_markup"] = base * (1.0 + eff["max_markup_pct"])

    return Constraints(
        lowers=lowers,
        uppers=uppers,
        price_step=max(float(eff.get("price_step", product.price_step or 0.01)), 0.01),
        max_change_pct=float(eff.get("max_change_pct", product.max_change_pct or 0.0)) or None,
        freeze=("freeze" in eff) and apply_dynamics,
        last_price=last_price if apply_dynamics else None,
    )


def apply_guardrails(raw_price: float, c: Constraints) -> GuardrailResult:
    lo, hi = c.bounds()
    hits: List[str] = []

    if c.freeze and c.last_price:
        return GuardrailResult(round(c.last_price, 2), ["price_frozen"], lo, hi)

    price = float(raw_price)
    lo_name, hi_name = c.lower[0], c.upper[0]
    if price < lo:
        price = lo
        hits.append(lo_name)
    elif price > hi:
        price = hi
        hits.append(hi_name)

    # volatility cap relative to the last applied price (bounds still win)
    if c.last_price and c.max_change_pct:
        band_lo = c.last_price * (1.0 - c.max_change_pct)
        band_hi = c.last_price * (1.0 + c.max_change_pct)
        capped = min(max(price, band_lo), band_hi)
        if abs(capped - price) > 1e-9:
            price = min(max(capped, lo), hi)
            hits.append("volatility_cap")

    # round to the price step without leaving [lo, hi]
    step = c.price_step
    rounded = round(price / step) * step
    if rounded > hi:
        rounded = math.floor(hi / step) * step
    if rounded < lo:
        rounded = math.ceil(lo / step) * step
    if rounded > hi or rounded < lo:       # step too coarse for the band: stay inside it
        rounded = min(max(price, lo), hi)
    return GuardrailResult(round(rounded, 2), hits, lo, hi)
