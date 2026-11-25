"""Train (or retrain) the pricing models from the command line and print the comparison table.

    python train_model.py                 # 25,000 synthetic observations
    python train_model.py --samples 60000 --seed 7
"""
import argparse

from app.ml.registry import model_service
from app.ml.trainer import MODEL_LABELS

parser = argparse.ArgumentParser(description="Train the Smart Revenue Optimizer models")
parser.add_argument("--samples", type=int, default=25000)
parser.add_argument("--seed", type=int, default=42)
args = parser.parse_args()

model_service.status["state"] = "idle"
model_service.train(args.samples, args.seed)
m = model_service.metrics()

print(f"\nModel {m['version']}  (train={m['n_train']:,}  test={m['n_test']:,})")
print(f"{'Strategy':<22}{'MAE':>9}{'RMSE':>9}{'R2':>8}{'Rev lift%':>11}{'Profit lift%':>14}{'Latency ms':>12}")
for s in m["strategies"]:
    print(f"{s['label']:<22}{s['mae']:9.2f}{s['rmse']:9.2f}{s['r2']:8.3f}{s['revenue_lift_pct']:11.2f}"
          f"{s['profit_lift_pct']:14.2f}{s['latency_ms']:12.2f}")
print(f"\nBest ML model: {MODEL_LABELS[m['best_model']]}   Saved to: {model_service.artifact_path}")
d = m["demand_model"]
print(f"Demand model: R2 vs true demand = {d['r2_vs_expected']:.3f}, revenue-peak error = {d['optimum_mae_pct']:.1f}% of base price")
