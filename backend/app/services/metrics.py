"""In-memory latency tracker for the paper's 'latency' evaluation metric."""
from __future__ import annotations

import threading
from collections import deque
from typing import Deque

import numpy as np


class LatencyTracker:
    def __init__(self, maxlen: int = 500):
        self._values: Deque[float] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def record(self, ms: float) -> None:
        with self._lock:
            self._values.append(float(ms))

    def summary(self) -> dict:
        with self._lock:
            vals = list(self._values)
        if not vals:
            return {"count": 0, "mean_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None}
        a = np.array(vals)
        return {"count": len(vals), "mean_ms": round(float(a.mean()), 2), "p50_ms": round(float(np.percentile(a, 50)), 2),
                "p95_ms": round(float(np.percentile(a, 95)), 2), "max_ms": round(float(a.max()), 2)}


latency_tracker = LatencyTracker()
