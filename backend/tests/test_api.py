"""End-to-end API tests against the real app (real DB, real trained model)."""


def post_sim(client, product_id, **features):
    r = client.post("/simulate_price", json={"product_id": product_id, "features": features})
    assert r.status_code == 200, r.text
    return r.json()


def test_health_and_root(client):
    h = client.get("/health").json()
    assert h["status"] == "healthy" and h["services"]["database"] == "operational"
    assert h["model"]["state"] == "ready"
    assert client.get("/").json()["status"] == "running"
    assert client.get("/api/config").json()["currency"] == "INR"


def test_products_seeded(client):
    products = client.get("/products").json()
    assert [p["category"] for p in products][:3] == ["umbrella", "ice_cream", "ticket"]
    assert all(p["current_stock"] > 0 for p in products)
    assert client.get("/products/999").status_code == 404


def test_current_price_contract(client):
    """The shape the React frontend relies on."""
    d = client.get("/prices/1/current").json()
    for key in ("product_id", "product_name", "base_price", "current_price", "final_price", "total_change", "factors",
                "explanation", "rationale", "confidence", "model_version", "timestamp", "weather", "holiday_info",
                "constraints_applied", "expected"):
        assert key in d, key
    assert d["current_price"] == d["final_price"]
    lo, hi = d["allowed_range"]["min"], d["allowed_range"]["max"]
    assert lo <= d["final_price"] <= hi
    assert {"weather", "time_of_day", "holiday_effect", "demand", "inventory", "competition"} <= set(d["factors"])
    assert 0 <= d["confidence"] <= 1
    assert client.get("/prices/1/current").json()["timestamp"] == d["timestamp"]      # served from cache
    assert client.get("/prices/1/current?refresh=true").json()["timestamp"] >= d["timestamp"]
    assert client.get("/prices/999/current").status_code == 404
    assert len(client.get("/prices/current").json()) >= 3


def test_simulation_behaves_like_the_paper_says(client):
    # umbrella (id 1): rain raises the price
    dry, wet = post_sim(client, 1, precipitation=0.0), post_sim(client, 1, precipitation=0.9)
    assert wet["final_price"] > dry["final_price"] and wet["factors"]["weather"] > 10
    assert "rain" in wet["rationale"]
    # ice cream (id 2): heat raises, cold lowers
    hot, cold = post_sim(client, 2, temperature=38), post_sim(client, 2, temperature=10)
    assert hot["final_price"] > cold["final_price"]
    # scarcity raises the price, glut lowers it
    assert post_sim(client, 3, stock_level=3)["final_price"] > post_sim(client, 3, stock_level=95)["final_price"]
    # a big competitor discount pulls the price down
    assert post_sim(client, 1, competitor_price=500)["final_price"] < post_sim(client, 1)["final_price"]
    # simulation never writes anything
    before = client.get("/history/1?hours=1").json()["count"]
    post_sim(client, 1, precipitation=0.5)
    assert client.get("/history/1?hours=1").json()["count"] == before


def test_traffic_index_scales_with_the_hour(client):
    """'Traffic vs normal' must mean the same thing at any hour: at constant traffic the demand
    factor must not swing just because the clock moved (no phantom demand penalty)."""
    neutral = dict(traffic_index=1.0, add_to_cart_rate=0.15, conversion_rate=0.30)
    demand = [post_sim(client, 1, hour_of_day=h, **neutral)["factors"]["demand"] for h in (3, 8, 13, 20)]
    assert max(demand) - min(demand) < 3.0, demand
    low, high = post_sim(client, 1, traffic_index=0.4), post_sim(client, 1, traffic_index=2.0)
    assert high["context"]["page_views_1h"] > low["context"]["page_views_1h"]
    assert high["factors"]["demand"] > low["factors"]["demand"]


def test_simulation_input_handling(client):
    r = client.post("/simulate_price", json={"product_id": 1, "features": {"temperature": None, "bogus": "x",
                                                                           "stock_level": "50"}})
    assert r.status_code == 200
    assert client.post("/simulate_price", json={"product_id": 999, "features": {}}).status_code == 404
    up = client.post("/simulate_price", json={"product_id": 1, "features": {}, "manual_adjustments": {"markup_pct": 5}})
    assert up.json()["factors"].get("manual_adjustment", 0) != 0 or up.json()["constraints_applied"]


def test_history_forecast_and_recommendations(client):
    h = client.get("/history/1?hours=24").json()
    assert h["count"] > 5 and h["stats"]["min"] <= h["stats"]["current"] <= h["stats"]["max"]
    assert all(p["timestamp"].endswith("Z") for p in h["history"])
    assert client.get("/history/1?hours=24&max_points=10").json()["count"] <= 10
    f = client.get("/api/analytics/price-forecast/1?hours=24").json()
    assert len(f["forecast"]) == 24 and f["summary"]["min"] <= f["summary"]["max"]
    assert f["forecast"][0]["label"].endswith(":00")
    recs = client.get("/recommendations/1?limit=5").json()
    assert recs["count"] == 5 and "final_price" in recs["recommendations"][0]


def test_revenue_curve(client):
    c = client.get("/api/analytics/revenue-curve/1").json()
    assert len(c["curve"]) == 40
    revs = [p["revenue"] for p in c["curve"]]
    assert max(revs) > revs[0] and max(revs) > revs[-1]            # a real hump, not a straight line
    assert c["curve"][0]["price"] <= c["optimal_price"] <= c["curve"][-1]["price"]
    assert c["allowed_range"]["min"] <= c["optimal_price_allowed"] <= c["allowed_range"]["max"]


def test_signals_ingestion_and_validation(client):
    ok = client.post("/signals", json={"product_id": 1, "page_views": 120, "add_to_carts": 30, "conversions": 9,
                                       "competitor_price": 780})
    assert ok.status_code == 201 and ok.json()["temperature"] is not None      # weather auto-filled
    assert client.post("/signals", json={"product_id": 1, "page_views": 10, "add_to_carts": 50}).status_code == 422
    assert client.post("/signals", json={"product_id": 999}).status_code == 404
    assert len(client.get("/signals/1?limit=5").json()) == 5
    assert client.post("/signals/simulate?ticks=1").json()["repriced"] >= 3


def test_stock_update_reprices(client):
    before = client.get("/prices/3/current?refresh=true").json()["factors"]["inventory"]
    r = client.post("/products/3/update_stock", json={"new_stock": 2})
    assert r.status_code == 200 and r.json()["product"]["current_stock"] == 2
    assert r.json()["price"]["factors"]["inventory"] > before
    assert client.post("/products/3/update_stock", json={"new_stock": -1}).status_code == 422
    client.post("/products/3/update_stock", json={"new_stock": 60})


def test_rules_lifecycle_changes_prices_immediately(client):
    capped = client.post("/rules", json={"scope": "product", "scope_value": "1", "rule_type": "max_markup_pct",
                                         "value": 0.02, "note": "test"})
    assert capped.status_code == 201
    rule_id = capped.json()["id"]
    sim = post_sim(client, 1, precipitation=0.9)
    assert sim["final_price"] <= 799 * 1.02 + 0.01 and "max_markup" in sim["constraints_applied"]
    assert client.get("/prices/1/current").json()["final_price"] <= 799 * 1.02 + 0.01
    assert any(r["id"] == rule_id for r in client.get("/rules").json())
    assert client.put(f"/rules/{rule_id}", json={"is_active": False}).json()["is_active"] is False
    assert post_sim(client, 1, precipitation=0.9)["final_price"] > 799 * 1.1
    assert client.delete(f"/rules/{rule_id}").status_code == 200
    assert client.delete(f"/rules/{rule_id}").status_code == 404
    assert "price_max" in [t["type"] for t in client.get("/rules/types").json()["rule_types"]]


def test_rule_validation(client):
    assert client.post("/rules", json={"scope": "nope", "rule_type": "price_max", "value": 1}).status_code == 422
    assert client.post("/rules", json={"scope": "global", "rule_type": "wat", "value": 1}).status_code == 422
    assert client.post("/rules", json={"scope": "product", "rule_type": "price_max", "value": 1}).status_code == 422
    assert client.post("/rules", json={"scope": "product", "scope_value": "999", "rule_type": "price_max",
                                       "value": 1}).status_code == 404
    assert client.post("/rules", json={"scope": "global", "rule_type": "max_change_pct", "value": 10}).status_code == 422


def test_product_crud(client):
    body = {"sku": "TEST-HOT", "name": "Filter Coffee", "category": "hot beverage", "base_price": 120, "cost": 40,
            "price_min": 90, "price_max": 200, "price_step": 1, "current_stock": 80, "max_stock": 150}
    created = client.post("/products", json=body)
    assert created.status_code == 201
    pid = created.json()["id"]
    assert created.json()["current_price"] is not None                   # priced straight away
    assert client.post("/products", json=body).status_code == 409
    assert client.post("/products", json={**body, "sku": "X", "price_min": 500}).status_code == 422
    assert client.post("/products", json={**body, "sku": "Y", "base_price": -5}).status_code == 422
    cold = post_sim(client, pid, temperature=10, precipitation=0.6)["final_price"]    # unknown-spelling category maps
    warm = post_sim(client, pid, temperature=35)["final_price"]
    assert cold > warm
    assert client.put(f"/products/{pid}", json={"name": "Filter Coffee XL"}).json()["name"] == "Filter Coffee XL"
    assert client.delete(f"/products/{pid}").status_code == 200
    assert pid not in [p["id"] for p in client.get("/products").json()]
    assert pid in [p["id"] for p in client.get("/products?include_inactive=true").json()]


def test_model_endpoints(client):
    info = client.get("/api/model/info").json()
    assert info["ready"] and info["active_model"] == info["best_model"]
    m = client.get("/api/model/metrics").json()
    keys = [s["key"] for s in m["strategies"]]
    assert {"oracle", "static", "rule_based", "linear", "random_forest", "gradient_boosting"} == set(keys)
    fi = client.get("/api/model/feature-importance").json()
    assert abs(sum(g["importance"] for g in fi["grouped"]) - 1.0) < 0.01

    assert client.post("/api/model/select", json={"model_type": "linear"}).json()["active_model"] == "linear"
    assert client.get("/prices/1/current").json()["model_type"] == "linear"            # cache respects the switch
    assert client.post("/api/model/select", json={"model_type": "static"}).status_code == 400
    client.post("/api/model/select", json={"model_type": info["best_model"]})
    assert client.get("/api/model/latency").json()["count"] > 0


def test_dashboard_stats_and_revenue(client):
    s = client.get("/api/dashboard/stats").json()
    assert s["summary"]["active_products"] >= 3 and s["revenue"]["total"]["baseline_revenue"] > 0
    assert len(s["recent_changes"]) > 0 and s["model_performance"]["r2"] > 0.5
    r = client.get("/api/analytics/revenue-summary?hours=24").json()
    assert len(r["per_product"]) >= 3 and len(r["hourly"]) > 3


def test_external_endpoints(client):
    w = client.get("/api/weather/current").json()
    assert {"temperature", "condition", "precipitation", "city", "humidity"} <= set(w) and "forecast" not in w
    assert len(client.get("/api/weather/forecast?hours=12").json()["forecast"]) == 12
    h = client.get("/api/holidays/upcoming?days=90").json()
    assert h["total_count"] > 0 and {"name", "days_until", "impact"} <= set(h["upcoming_holidays"][0])
    assert "INR" in client.get("/api/exchange/currencies").json()["currencies"]
    c = client.get("/api/exchange/convert?amount=100&from_currency=INR&to_currency=USD").json()
    assert c["success"] and c["converted_amount"] > 0
    assert client.get("/api/exchange/convert?amount=100&from_currency=INR&to_currency=XXX").status_code == 400
    assert client.get("/api/exchange/convert?amount=-5").status_code == 422
