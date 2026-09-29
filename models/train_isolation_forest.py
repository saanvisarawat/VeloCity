
"""Train an IsolationForest on synthetic urban trip profiles.

Features: [start_hour, duration_min, distance_km, avg_speed]
Artifact: models/isolation_forest.joblib

Inference:
    from models.train_isolation_forest import detect_anomaly
    is_anomaly, score = detect_anomaly({"start_hour": 9, "duration_min": 12, ...})
"""

from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = Path(__file__).resolve().parent / "isolation_forest.joblib"

FEATURES = ("start_hour", "duration_min", "distance_km", "avg_speed")
N_SAMPLES = 10_000
CONTAMINATION = 0.03
RANDOM_STATE = 42

_MODEL = None


def synthesize_trips(n: int = N_SAMPLES, rng: np.random.Generator | None = None) -> np.ndarray:
    """10k tabular urban trips: mostly plausible Bengaluru hops, ~3% outliers."""
    if rng is None:
        rng = np.random.default_rng(RANDOM_STATE)

    n_out = int(round(n * CONTAMINATION))
    n_in = n - n_out
    inliers = _normal_trips(n_in, rng)
    outliers = _anomalous_trips(n_out, rng)
    data = np.vstack([inliers, outliers])
    rng.shuffle(data)
    return data.astype(np.float64)


def _normal_trips(n: int, rng: np.random.Generator) -> np.ndarray:

    buckets = rng.choice(
        np.array([0, 1, 2, 3], dtype=int),
        size=n,
        p=[0.28, 0.30, 0.32, 0.10],
    )
    start_hour = np.empty(n, dtype=np.float64)
    morning = buckets == 0
    daytime = buckets == 1
    evening = buckets == 2
    night = buckets == 3
    start_hour[morning] = rng.uniform(7.5, 10.5, size=int(morning.sum()))
    start_hour[daytime] = rng.uniform(10.5, 17.5, size=int(daytime.sum()))
    start_hour[evening] = rng.uniform(17.5, 20.5, size=int(evening.sum()))
    start_hour[night] = rng.uniform(0.0, 24.0, size=int(night.sum()))
    start_hour = np.mod(start_hour, 24.0)


    distance_km = np.clip(rng.lognormal(mean=0.85, sigma=0.55, size=n), 0.4, 14.0)

    rush = ((start_hour >= 8.0) & (start_hour < 10.5)) | ((start_hour >= 17.5) & (start_hour < 20.5))
    avg_speed = np.empty(n, dtype=np.float64)
    avg_speed[rush] = rng.uniform(18.0, 38.0, size=int(rush.sum()))
    avg_speed[~rush] = rng.uniform(28.0, 52.0, size=int((~rush).sum()))


    duration_min = (distance_km / avg_speed) * 60.0 * rng.uniform(0.92, 1.28, size=n)
    duration_min = np.clip(duration_min, 1.5, 75.0)
    avg_speed = distance_km / (duration_min / 60.0)
    return np.column_stack([start_hour, duration_min, distance_km, avg_speed])


def _anomalous_trips(n: int, rng: np.random.Generator) -> np.ndarray:
    """Excessive speed, abnormal dwell, or odd-hour / impossible kinematics."""
    if n <= 0:
        return np.empty((0, 4), dtype=np.float64)
    kind = rng.integers(0, 3, size=n)
    rows = np.empty((n, 4), dtype=np.float64)
    for i, k in enumerate(kind):
        if k == 0:

            start_hour = float(rng.uniform(0.0, 24.0))
            distance_km = float(rng.uniform(6.0, 18.0))
            duration_min = float(rng.uniform(0.4, 2.5))
            avg_speed = distance_km / (duration_min / 60.0)
        elif k == 1:

            start_hour = float(rng.uniform(0.0, 24.0))
            distance_km = float(rng.uniform(0.3, 1.8))
            duration_min = float(rng.uniform(90.0, 240.0))
            avg_speed = distance_km / (duration_min / 60.0)
        else:

            start_hour = float(rng.choice([1.0, 2.0, 3.0, 4.0]))
            distance_km = float(rng.uniform(10.0, 22.0))
            avg_speed = float(rng.uniform(3.0, 8.0))
            duration_min = distance_km / avg_speed * 60.0
        rows[i] = [start_hour, duration_min, distance_km, avg_speed]
    return rows


def train_model(X: np.ndarray) -> IsolationForest:
    clf = IsolationForest(
        contamination=CONTAMINATION,
        random_state=RANDOM_STATE,
        n_estimators=200,
    )
    clf.fit(X)
    return clf


def save_model(model: IsolationForest, path: Path = MODEL_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    return path


def load_model(path: Path = MODEL_PATH) -> IsolationForest:
    global _MODEL
    if _MODEL is None or path != MODEL_PATH:
        if not path.exists():
            raise FileNotFoundError(f"Missing {path}. Run models/train_isolation_forest.py first.")
        loaded = joblib.load(path)
        _MODEL = loaded["model"] if isinstance(loaded, dict) else loaded
    return _MODEL


def _vector(trip_dict: dict) -> np.ndarray:
    missing = [k for k in FEATURES if k not in trip_dict]
    if missing:
        raise KeyError(f"trip_dict missing features {missing}; expected {list(FEATURES)}")
    return np.array([[float(trip_dict[k]) for k in FEATURES]], dtype=np.float64)


def detect_anomaly(trip_dict: dict) -> tuple[bool, float]:
    """Return (is_anomaly, raw IsolationForest decision_function score).

    sklearn convention: decision_function > 0 is inlier; predict() == -1 is anomaly.
    """
    model = load_model()
    x = _vector(trip_dict)
    score = float(model.decision_function(x)[0])
    is_anomaly = bool(model.predict(x)[0] == -1)
    return is_anomaly, score


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train IsolationForest on urban trip features")
    parser.add_argument("--output", type=Path, default=MODEL_PATH, help="joblib output path")
    return parser.parse_args()


def main() -> None:
    global _MODEL
    args = parse_args()
    rng = np.random.default_rng(RANDOM_STATE)
    X = synthesize_trips(N_SAMPLES, rng)
    if X.shape != (N_SAMPLES, len(FEATURES)):
        raise ValueError(f"Expected {(N_SAMPLES, len(FEATURES))} training rows, got {X.shape}")

    model = train_model(X)
    out = save_model(model, args.output)
    _MODEL = model

    flags = model.predict(X)
    n_flagged = int((flags == -1).sum())
    print(f"Trained IsolationForest on {N_SAMPLES} rows  features={list(FEATURES)}")
    print(f"contamination={CONTAMINATION}  random_state={RANDOM_STATE}")
    print(f"Wrote {out}")
    print(f"Training-set flagged: {n_flagged}/{N_SAMPLES} ({n_flagged / N_SAMPLES:.1%})")

    normal = {
        "start_hour": 9.0,
        "duration_min": 14.0,
        "distance_km": 6.5,
        "avg_speed": 27.9,
    }
    speeding = {
        "start_hour": 14.0,
        "duration_min": 1.2,
        "distance_km": 11.0,
        "avg_speed": 550.0,
    }
    dwell = {
        "start_hour": 3.0,
        "duration_min": 180.0,
        "distance_km": 0.8,
        "avg_speed": 0.27,
    }

    print("\nVerification test cases  detect_anomaly(trip) -> (is_anomaly, score)")
    for label, trip in (("normal commute", normal), ("excessive speed", speeding), ("abnormal dwell", dwell)):
        is_anom, score = detect_anomaly(trip)
        print(f"  {label:18}  {trip}  ->  ({is_anom}, {score:.4f})")


if __name__ == "__main__":
    main()
