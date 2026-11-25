"""Currency conversion so prices can be shown in the shopper's currency.
Live rates from exchangerate-api.com (no key), cached for an hour, with an
offline fallback table so the converter always works."""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional

import requests

from ..utils.timeutils import iso_z, utcnow

CURRENCIES: Dict[str, dict] = {
    "INR": {"name": "Indian Rupee", "country": "India", "symbol": "₹"},
    "USD": {"name": "US Dollar", "country": "United States", "symbol": "$"},
    "EUR": {"name": "Euro", "country": "Eurozone", "symbol": "€"},
    "GBP": {"name": "British Pound", "country": "United Kingdom", "symbol": "£"},
    "JPY": {"name": "Japanese Yen", "country": "Japan", "symbol": "¥"},
    "AUD": {"name": "Australian Dollar", "country": "Australia", "symbol": "A$"},
    "CAD": {"name": "Canadian Dollar", "country": "Canada", "symbol": "C$"},
    "CNY": {"name": "Chinese Yuan", "country": "China", "symbol": "¥"},
    "AED": {"name": "UAE Dirham", "country": "United Arab Emirates", "symbol": "د.إ"},
    "SGD": {"name": "Singapore Dollar", "country": "Singapore", "symbol": "S$"},
}

# Approximate USD-based rates used only when the live API is unreachable.
_FALLBACK_USD = {"USD": 1.0, "INR": 88.0, "EUR": 0.92, "GBP": 0.79, "JPY": 148.0, "AUD": 1.52,
                 "CAD": 1.37, "CNY": 7.10, "AED": 3.6725, "SGD": 1.34}


class ExchangeRateService:
    URL = "https://api.exchangerate-api.com/v4/latest"
    CACHE_TTL = 3600
    BACKOFF = 300

    def __init__(self) -> None:
        self._cache: Dict[str, dict] = {}
        self._fail_until = 0.0
        self._lock = threading.Lock()

    def get_latest_rates(self, base: str = "USD") -> dict:
        base = base.upper()
        with self._lock:
            hit = self._cache.get(base)
            if hit and time.time() - hit["fetched"] < self.CACHE_TTL:
                return hit["data"]
        data = None
        if time.time() >= self._fail_until:
            try:
                r = requests.get(f"{self.URL}/{base}", timeout=4)
                r.raise_for_status()
                j = r.json()
                data = {"success": True, "base": j["base"], "date": j.get("date"), "rates": j["rates"],
                        "source": "exchangerate-api", "timestamp": iso_z(utcnow())}
            except Exception:
                self._fail_until = time.time() + self.BACKOFF
        if data is None:
            data = self._fallback(base)
        with self._lock:
            self._cache[base] = {"fetched": time.time(), "data": data}
        return data

    def _fallback(self, base: str) -> dict:
        if base not in _FALLBACK_USD:
            return {"success": False, "error": f"Unsupported base currency {base}"}
        b = _FALLBACK_USD[base]
        return {"success": True, "base": base, "date": utcnow().strftime("%Y-%m-%d"),
                "rates": {c: round(v / b, 6) for c, v in _FALLBACK_USD.items()}, "source": "offline-fallback",
                "timestamp": iso_z(utcnow()), "note": "Live rates unavailable - approximate offline values"}

    def convert(self, amount: float, from_currency: str, to_currency: str) -> dict:
        rates = self.get_latest_rates(from_currency)
        if not rates.get("success"):
            return {"success": False, "error": rates.get("error", "Rates unavailable")}
        to_currency = to_currency.upper()
        if to_currency not in rates["rates"]:
            return {"success": False, "error": f"Currency {to_currency} not found"}
        rate = rates["rates"][to_currency]
        return {"success": True, "amount": amount, "from_currency": from_currency.upper(),
                "to_currency": to_currency, "converted_amount": round(amount * rate, 2), "rate": rate,
                "date": rates.get("date"), "source": rates["source"]}


exchange_service = ExchangeRateService()
