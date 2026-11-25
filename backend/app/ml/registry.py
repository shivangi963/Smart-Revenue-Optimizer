"""ModelService: owns the trained bundle (load / save / retrain / switch model)
and is the single entry point the pricing engine uses for predictions."""
from __future__ import annotations

import json
import threading
import time
import warnings
from pathlib import Path
from typing import Dict, Optional, Tuple

import joblib
import numpy as np
import pandas as pd

from ..config import settings
from ..utils.timeutils import iso_z, utcnow
from . import world
from .baselines import rule_based_ratio
from .demand import predict_units as _predict_units
from .features import FEATURE_COLUMNS, GROUP_LABELS, engineer_features
from .trainer import MODEL_LABELS, ML_MODELS, train_all

FALLBACK_VERSION = "rule-based-fallback"


class ModelService:
    def __init__(self, model_dir: Optional[Path] = None):
        self.model_dir = Path(model_dir or settings.model_dir)
        self.artifact_path = self.model_dir / "smart_revenue_model.joblib"
        self._active_file = self.model_dir / "active_model.json"
        self._lock = threading.RLock()
        self._bundle: Optional[dict] = None
        self.active_type: Optional[str] = None
        self.status: Dict[str, object] = {"state": "idle", "message": "Model not loaded", "started_at": None,
                                          "finished_at": None}
        self._on_ready = []     # callbacks fired after a successful train/load

    # ------------------------------------------------------------------ state
    @property
    def ready(self) -> bool:
        return self._bundle is not None

    @property
    def version(self) -> str:
        return self._bundle["version"] if self._bundle else FALLBACK_VERSION

    @property
    def model_type(self) -> str:
        return self.active_type if self._bundle and self.active_type else "rule_based"

    def on_ready(self, callback) -> None:
        self._on_ready.append(callback)

    def _set_status(self, state: str, message: str, **extra) -> None:
        self.status = {**self.status, "state": state, "message": message, **extra}

    # ------------------------------------------------------------- persistence
    def load(self) -> bool:
        """Load the saved artifact. Returns False (instead of raising) if it is
        missing or was produced by an incompatible version, so we can retrain."""
        if not self.artifact_path.exists():
            return False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                bundle = joblib.load(self.artifact_path)
            if bundle.get("feature_columns") != FEATURE_COLUMNS:
                raise ValueError("feature set changed since the model was trained")
            # smoke-test so a broken unpickle is caught now, not on the first request
            probe = pd.DataFrame([{c: 0.0 for c in FEATURE_COLUMNS}])
            bundle["models"][bundle["best_model"]].predict(probe)
        except Exception as exc:
            self._set_status("idle", f"Saved model unusable ({exc}); retraining needed")
            return False
        self._install(bundle)
        return True

    def _install(self, bundle: dict) -> None:
        with self._lock:
            self._bundle = bundle
            chosen = bundle["best_model"]
            if self._active_file.exists():
                try:
                    saved = json.loads(self._active_file.read_text()).get("active")
                    if saved in bundle["models"]:
                        chosen = saved
                except Exception:
                    pass
            self.active_type = chosen
        self._set_status("ready", f"Model {bundle['version']} ready ({MODEL_LABELS[chosen]})",
                         finished_at=iso_z(utcnow()))
        for cb in self._on_ready:
            try:
                cb()
            except Exception:  # a failing hook must never break serving
                pass

    def _save(self, bundle: dict) -> None:
        self.model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, self.artifact_path, compress=3)

    # ---------------------------------------------------------------- training
    def train(self, n_samples: Optional[int] = None, seed: int = 42) -> dict:
        n_samples = int(n_samples or settings.train_samples)
        with self._lock:
            if self.status.get("state") == "training":
                return self.status
            self._set_status("training", "Starting training...", started_at=iso_z(utcnow()), finished_at=None)
        try:
            bundle = train_all(n_samples, seed, progress=lambda m: self._set_status("training", m))
            self._save(bundle)
            self._active_file.unlink(missing_ok=True)       # new model -> use its best candidate
            self._install(bundle)
        except Exception as exc:
            self._set_status("error", f"Training failed: {exc}", finished_at=iso_z(utcnow()))
            raise
        return self.status

    def train_async(self, n_samples: Optional[int] = None, seed: int = 42) -> bool:
        if self.status.get("state") == "training":
            return False

        def _run():
            try:
                self.train(n_samples, seed)
            except Exception:
                pass

        threading.Thread(target=_run, name="model-training", daemon=True).start()
        # make the 'training' state visible immediately
        self._set_status("training", "Starting training...", started_at=iso_z(utcnow()), finished_at=None)
        return True

    def set_active(self, model_type: str) -> None:
        if not self._bundle:
            raise ValueError("No trained model available yet")
        if model_type not in self._bundle["models"]:
            raise ValueError(f"Unknown model '{model_type}'. Choose from {list(self._bundle['models'])}")
        with self._lock:
            self.active_type = model_type
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self._active_file.write_text(json.dumps({"active": model_type}))
        self._set_status("ready", f"Model {self._bundle['version']} ready ({MODEL_LABELS[model_type]})")

    # -------------------------------------------------------------- prediction
    def predict_ratio_features(self, features: pd.DataFrame) -> np.ndarray:
        with self._lock:
            pipe = self._bundle["models"][self.active_type]
        return np.asarray(pipe.predict(features), dtype=float)

    def predict_ratio(self, raw: pd.DataFrame) -> Tuple[np.ndarray, str, str]:
        """raw store context -> price ratio (price / base price)."""
        if not self.ready:
            return rule_based_ratio(raw), FALLBACK_VERSION, "rule_based"
        return self.predict_ratio_features(engineer_features(raw)), self.version, self.active_type

    def predict_fn(self):
        """A raw-DataFrame -> ratio callable (used by the Shapley explainer)."""
        if not self.ready:
            return rule_based_ratio
        return lambda raw: self.predict_ratio_features(engineer_features(raw))

    def predict_units(self, raw: pd.DataFrame, ratios, features: Optional[pd.DataFrame] = None) -> Optional[np.ndarray]:
        """Expected units/hour at the given price ratios (None if no demand model yet).
        `raw` and `features` must have one row per ratio."""
        if not self.ready:
            return None
        feats = features if features is not None else engineer_features(raw)
        vol = world.demand_volume(raw)
        return _predict_units(self._bundle["demand_model"], feats, ratios, vol)

    # -------------------------------------------------------------------- info
    def info(self) -> dict:
        b = self._bundle
        base = {"ready": self.ready, "status": self.status, "active_model": self.active_type,
                "active_model_label": MODEL_LABELS.get(self.active_type or "", "Rule-based (fallback)")}
        if not b:
            return {**base, "version": FALLBACK_VERSION}
        return {**base, "version": b["version"], "trained_at": b["trained_at"], "best_model": b["best_model"],
                "n_samples": b["n_samples"], "n_train": b["n_train"], "n_test": b["n_test"],
                "available_models": list(b["models"]), "sklearn_version": b["sklearn_version"],
                "training_seconds": round(b["total_seconds"], 1)}

    def metrics(self) -> dict:
        if not self._bundle:
            return {"ready": False, "status": self.status}
        m = self._bundle["metrics"]
        rows = []
        for key, vals in m["strategies"].items():
            rows.append({"key": key, "label": MODEL_LABELS[key], "is_ml": key in ML_MODELS,
                         "is_active": key == self.active_type, **{k: round(v, 4) for k, v in vals.items()}})
        return {"ready": True, "version": self.version, "best_model": self._bundle["best_model"],
                "active_model": self.active_type, "n_train": self._bundle["n_train"],
                "n_test": self._bundle["n_test"], "trained_at": self._bundle["trained_at"],
                "strategies": rows,
                "demand_model": {k: round(v, 4) for k, v in m["demand_model"].items()}}

    def feature_importance(self, top: int = 12) -> dict:
        if not self._bundle:
            return {"ready": False}
        imp = self._bundle["importance"][self.active_type]
        groups = self._bundle["group_importance"][self.active_type]
        grouped = sorted(
            ({"group": g, "label": GROUP_LABELS[g], "importance": round(v, 4), "pct": round(v * 100, 1)}
             for g, v in groups.items()), key=lambda r: -r["importance"])
        feats = sorted(imp.items(), key=lambda kv: -kv[1])[:top]
        return {"ready": True, "model": self.active_type, "model_label": MODEL_LABELS[self.active_type],
                "grouped": grouped,
                "top_features": [{"feature": k, "importance": round(v, 4), "pct": round(v * 100, 1)} for k, v in feats]}


model_service = ModelService()
