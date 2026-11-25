"""Synthetic data tools for Smart Revenue Optimizer.

1) Push live-looking demand signals to the running API (simulates a storefront):
       python synthetic_data.py --push --count 30 --interval 1

2) Export the synthetic *training dataset* used by the ML models as a CSV
   (handy for the project report / viva):
       python synthetic_data.py --export training_data.csv --rows 5000
"""
import argparse
import random
import sys
import time
from pathlib import Path

import requests

BACKEND = Path(__file__).resolve().parent.parent / "backend"
PAGE_VIEW_REF = {"umbrella": 80, "ice_cream": 150, "ticket": 60, "hot_beverage": 120}


def auth_headers(api: str, args) -> dict:
    """An ingest API key (INGEST_API_KEY on the server) or an admin login."""
    if args.api_key:
        return {"X-API-Key": args.api_key}
    r = requests.post(f"{api}/auth/login", data={"username": args.user, "password": args.password}, timeout=10)
    if r.status_code != 200:
        sys.exit(f"Login failed ({r.status_code}): {r.json().get('detail')}. Use --user/--password or --api-key.")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def push_signals(api: str, count: int, interval: float, headers: dict) -> None:
    products = requests.get(f"{api}/products", headers=headers, timeout=10).json()
    if isinstance(products, dict):
        sys.exit("The API key only allows sending signals; use --user/--password so products can be listed.")
    if not products:
        sys.exit("No products found - start the backend first.")
    print(f"Pushing {count} rounds of signals for {len(products)} products to {api}")
    for n in range(1, count + 1):
        for p in products:
            views = max(1, int(random.gauss(PAGE_VIEW_REF.get(p["category"], 90), 25)))
            carts = int(views * min(max(random.betavariate(3, 17), 0.01), 0.6))
            orders = int(carts * min(max(random.betavariate(3, 7), 0.02), 0.9))
            body = {
                "product_id": p["id"], "page_views": views, "add_to_carts": carts, "conversions": orders,
                "competitor_price": round(p["base_price"] * random.uniform(0.9, 1.1), 2),
            }   # weather / holiday / stock are filled in by the server from live data
            r = requests.post(f"{api}/signals", json=body, headers=headers, timeout=10)
            print(f"  [{n}/{count}] {p['name']:<22} views={views:<4} carts={carts:<3} orders={orders:<3} -> {r.status_code}")
        time.sleep(interval)
    print("Done. Prices pick these signals up on the next refresh.")


def export_dataset(path: str, rows: int, seed: int) -> None:
    sys.path.insert(0, str(BACKEND))
    import numpy as np
    from app.ml import world

    rng = np.random.default_rng(seed)
    df = world.add_labels(world.sample_raw_contexts(rows, rng), rng)
    df = df.rename(columns={"label_ratio": "optimal_price_ratio", "true_g": "latent_willingness",
                            "obs_ratio": "observed_price_ratio", "units": "units_sold"})
    df.round(4).to_csv(path, index=False)
    print(f"Wrote {rows:,} rows x {df.shape[1]} columns to {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--push", action="store_true", help="send demand signals to the API")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="", help="admin password")
    ap.add_argument("--api-key", default="", help="INGEST_API_KEY (alternative to a login)")
    ap.add_argument("--count", type=int, default=20, help="rounds of signals to send")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between rounds")
    ap.add_argument("--export", metavar="CSV", help="write the ML training dataset to a CSV file")
    ap.add_argument("--rows", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    if a.export:
        export_dataset(a.export, a.rows, a.seed)
    if a.push or not a.export:
        push_signals(a.api, a.count, a.interval, auth_headers(a.api, a))
