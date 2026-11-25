"""ML model management & evaluation endpoints (metrics, importance, retrain, switch)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..container import model_service
from ..schemas import ModelSelect, RetrainRequest
from ..security import require_admin
from ..services.metrics import latency_tracker

router = APIRouter(prefix="/api/model", tags=["Model"])


@router.get("/info")
def info():
    return model_service.info()


@router.get("/status")
def status():
    return model_service.status


@router.get("/metrics")
def metrics():
    """MAE / RMSE / R2 / revenue lift / latency for every strategy (Table in the paper)."""
    return model_service.metrics()


@router.get("/feature-importance")
def feature_importance(top: int = 12):
    return model_service.feature_importance(top)


@router.get("/latency")
def latency():
    return latency_tracker.summary()


@router.post("/retrain", dependencies=[Depends(require_admin)])
def retrain(body: RetrainRequest = RetrainRequest()):
    started = model_service.train_async(body.n_samples or settings.train_samples, body.seed)
    if not started:
        raise HTTPException(409, "Training is already in progress")
    return {"message": "Training started in the background", "status": model_service.status}


@router.post("/select", dependencies=[Depends(require_admin)])
def select(body: ModelSelect):
    """Switch which trained model prices products (e.g. compare Linear vs Gradient Boosting live)."""
    try:
        model_service.set_active(body.model_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return model_service.info()
