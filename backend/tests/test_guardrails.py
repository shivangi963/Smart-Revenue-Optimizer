from types import SimpleNamespace as NS

from app.services.guardrails import apply_guardrails, resolve_constraints


def product(**kw):
    base = dict(id=1, category="umbrella", base_price=100.0, cost=50.0, price_min=70.0, price_max=150.0,
                price_step=1.0, margin_floor=0.10, max_change_pct=0.10)
    base.update(kw)
    return NS(**base)


def rule(rule_type, value=0.0, scope="global", scope_value=None, active=True):
    return NS(rule_type=rule_type, value=value, scope=scope, scope_value=scope_value, is_active=active)


def run(raw, p=None, rules=(), last=None, dynamics=True):
    c = resolve_constraints(p or product(), rules, last_price=last, apply_dynamics=dynamics)
    return apply_guardrails(raw, c)


def test_clamps_to_min_and_max():
    assert run(10).final_price == 70 and "price_min" in run(10).hits
    assert run(999).final_price == 150 and "price_max" in run(999).hits
    assert run(100).hits == []


def test_margin_floor_beats_low_price_min():
    r = run(10, product(price_min=0.0, cost=80.0, margin_floor=0.25))     # floor = 100
    assert r.final_price == 100 and "margin_floor" in r.hits


def test_step_rounding_stays_inside_bounds():
    r = run(149.7, product(price_step=5.0))
    assert r.final_price == 150.0            # 149.7 rounds to 150, which is exactly the allowed maximum
    r = run(151, product(price_step=7.0))
    assert 70 <= r.final_price <= 150 and r.final_price % 7 == 0


def test_volatility_cap_limits_move():
    r = run(140, last=100.0)                  # model wants +40%, cap is 10%
    assert r.final_price == 110 and "volatility_cap" in r.hits
    r = run(60, last=100.0)
    assert r.final_price == 90 and "volatility_cap" in r.hits


def test_simulation_ignores_dynamics():
    assert run(140, last=100.0, dynamics=False).final_price == 140


def test_freeze_rule():
    r = run(140, rules=[rule("freeze")], last=95.0)
    assert r.final_price == 95.0 and r.hits == ["price_frozen"]
    assert run(140, rules=[rule("freeze")], last=95.0, dynamics=False).final_price == 140


def test_markup_and_discount_rules():
    rules = [rule("max_markup_pct", 0.20), rule("max_discount_pct", 0.10)]
    assert run(500, rules=rules).final_price == 120 and "max_markup" in run(500, rules=rules).hits
    assert run(1, rules=rules).final_price == 90


def test_rule_specificity_product_beats_global():
    rules = [rule("price_max", 120.0), rule("price_max", 130.0, scope="product", scope_value="1")]
    assert run(999, rules=rules).final_price == 130


def test_rule_category_scope_and_inactive():
    p = product(category="ice_cream")
    assert run(999, p, [rule("price_max", 90, scope="category", scope_value="umbrella")]).final_price == 150
    assert run(999, p, [rule("price_max", 90, scope="category", scope_value="ice cream")]).final_price == 90
    assert run(999, p, [rule("price_max", 90, active=False)]).final_price == 150


def test_most_restrictive_wins_at_same_level():
    rules = [rule("price_max", 140.0), rule("price_max", 125.0)]
    assert run(999, rules=rules).final_price == 125


def test_conflicting_bounds_never_crash():
    r = run(100, product(price_min=200.0, price_max=150.0))
    assert r.final_price == 200 and r.lower == r.upper
