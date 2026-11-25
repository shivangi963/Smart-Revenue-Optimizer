"""Time helpers. The database stores naive UTC timestamps; the pricing model
works in the *store's local time* (so "evening peak" means evening in India)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..config import settings

try:  # zoneinfo needs the `tzdata` package on Windows (listed in requirements)
    from zoneinfo import ZoneInfo

    _TZ = ZoneInfo(settings.store_timezone)
except Exception:  # pragma: no cover - falls back to the machine's timezone
    _TZ = datetime.now().astimezone().tzinfo


def utcnow() -> datetime:
    """Naive UTC 'now' (avoids the deprecated datetime.utcnow())."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(dt_utc_naive: datetime) -> datetime:
    return dt_utc_naive.replace(tzinfo=timezone.utc).astimezone(_TZ)


def iso_z(dt: Optional[datetime]) -> Optional[str]:
    """ISO string with an explicit 'Z' so browsers parse it as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec="seconds") + "Z"


def local_tz():
    return _TZ
