"""Holidays & events. Uses the `holidays` package for real, correct festival
dates (Diwali, Dussehra, Eid ... computed from the lunar calendars) and adds a few
commercial shopping events. Falls back to a built-in list if the package is
missing, so the app never fails because of it.

Event features (must match how the model was trained):
  * days_to_event - days until the next holiday (0 = today), capped at 60
  * is_holiday    - 1 if today is a holiday
  * event_score   - importance * exp(-days_to_event / 4): shopping builds up
                    as a big festival approaches
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from ..config import settings

try:
    import holidays as _holidays_lib
except Exception:  # pragma: no cover
    _holidays_lib = None

HIGH_IMPACT_KEYWORDS = (
    "diwali", "deepavali", "dussehra", "christmas", "new year", "holi", "eid", "ramzan", "id-ul",
    "independence day", "republic day", "onam", "pongal", "ganesh", "navratri", "thanksgiving",
    "black friday", "durga", "raksha", "valentine",
)
IMPACT_WEIGHT = {"high": 1.0, "medium": 0.6}
MAX_LOOKAHEAD = 60

_FALLBACK_FIXED = [
    (1, 1, "New Year's Day"), (1, 26, "Republic Day"), (2, 14, "Valentine's Day"),
    (8, 15, "Independence Day"), (10, 2, "Gandhi Jayanti"), (12, 25, "Christmas"),
]


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


class HolidayService:
    def __init__(self, country: Optional[str] = None):
        self.country = country or settings.holiday_country
        self._cache: Dict[int, Dict[date, Tuple[str, str]]] = {}

    def _impact(self, name: str) -> str:
        low = name.lower()
        return "high" if any(k in low for k in HIGH_IMPACT_KEYWORDS) else "medium"

    def _year(self, year: int) -> Dict[date, Tuple[str, str]]:
        if year in self._cache:
            return self._cache[year]
        events: Dict[date, Tuple[str, str]] = {}
        if _holidays_lib is not None:
            try:
                for d, name in _holidays_lib.country_holidays(self.country, years=year).items():
                    clean = str(name).split(";")[0].split(" (estimated")[0].strip()
                    events[d] = (clean, self._impact(clean))
            except Exception:
                events = {}
        if not events:
            for m, d, name in _FALLBACK_FIXED:
                events[date(year, m, d)] = (name, self._impact(name))
        # commercial shopping events
        events.setdefault(date(year, 2, 14), ("Valentine's Day", "medium"))
        events.setdefault(_nth_weekday(year, 11, 3, 4) + timedelta(days=1), ("Black Friday", "medium"))
        self._cache[year] = events
        return events

    def _window(self, start: date, days: int) -> List[Tuple[date, str, str]]:
        out = []
        for y in {start.year, (start + timedelta(days=days)).year}:
            for d, (name, impact) in self._year(y).items():
                if start <= d <= start + timedelta(days=days):
                    out.append((d, name, impact))
        return sorted(out)

    # ---------------------------------------------------------------- public
    def upcoming(self, days: int = 30, today: Optional[date] = None, limit: int = 10) -> List[dict]:
        today = today or date.today()
        return [
            {"name": name, "date": d.isoformat(), "days_until": (d - today).days, "impact": impact}
            for d, name, impact in self._window(today, days)
        ][:limit]

    def context_for(self, day: Optional[date] = None) -> dict:
        """Model-ready event features for a given day."""
        day = day or date.today()
        events = self._window(day, MAX_LOOKAHEAD)
        if not events:
            return {"is_holiday": 0, "holiday_name": None, "event_score": 0.0, "days_to_event": float(MAX_LOOKAHEAD),
                    "next_event": None}
        first_d, first_name, first_impact = events[0]
        days_to = (first_d - day).days
        score = max(
            IMPACT_WEIGHT[impact] * math.exp(-(d - day).days / 4.0) for d, _n, impact in events
        )
        return {
            "is_holiday": 1 if days_to == 0 else 0,
            "holiday_name": first_name if days_to == 0 else None,
            "event_score": round(float(score), 3),
            "days_to_event": float(days_to),
            "next_event": {"name": first_name, "date": first_d.isoformat(), "days_until": days_to,
                           "impact": first_impact},
        }


holiday_service = HolidayService()
