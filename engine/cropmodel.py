"""
Crop model: which crop is growing, from the Sentinel-2 NDVI curve known so far.

Input per pixel: the 24 half-month NDVI slots of the season (engine.satellite.season), slots after
"today" set to NaN, plus how many slots are known. One LightGBM model serves every day of the season
(it is trained on curves cut at random dates). A field's crop = the mean of its pixels' probabilities.

    python -m engine.cropmodel train DATA_DIR      # trains on DATA_DIR/satellite/samples, writes DATA_DIR/models/
    from engine.cropmodel import predict_pixels     # {"crop": 1110, "confidence": 0.93, "probabilities": {...}}

Labels come from the CLMS crop maps 2020-2024; the model never sees a farm or a field when training.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from engine.satellite.season import N_SLOTS, SLOT_NAMES, known_slots, slot_end

# Model classes: crop-map codes grouped. Wheat and maize are what the engine scores; the rest exist so
# the model can say "this is not wheat / maize".
CLASSES = ["wheat", "maize", "barley", "rapeseed", "other_cereal", "other_crop", "no_crop"]
CLASS_CODE = {"wheat": 1110, "maize": 1130, "barley": 1120, "rapeseed": 1430, "other_cereal": 1150,
              "other_crop": 3100, "no_crop": 0}
CUTOFFS_TRAIN = list(range(4, N_SLOTS + 1))  # known slots: from mid-October to the full season
MODEL_VERSION = "0.1.0"
SLOT_COLS = [f"ndvi_{s}" for s in SLOT_NAMES]


def class_of(code: int) -> str:
    return {1110: "wheat", 1130: "maize", 1120: "barley", 1430: "rapeseed", 1150: "other_cereal", 0: "no_crop"}.get(
        int(code), "other_crop")


def features(slots: np.ndarray, n_known: np.ndarray | int) -> np.ndarray:
    """slots: [n, 24] NDVI with unknown slots NaN. Returns [n, 24 + 6] features."""
    x = np.asarray(slots, dtype="float32")
    n = x.shape[0]
    k = np.broadcast_to(np.asarray(n_known, dtype="float32"), (n,))
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            autumn = np.nanmean(x[:, 2:8], axis=1)    # Oct - Dec: winter crops emerge
            spring = np.nanmean(x[:, 13:18], axis=1)  # Mar b - May b
            summer = np.nanmean(x[:, 20:24], axis=1)  # Jul - Aug
            peak = np.nanmax(x, axis=1)
            peak_slot = np.where(np.isfinite(x).any(axis=1), np.nanargmax(np.nan_to_num(x, nan=-9), axis=1), np.nan)
    return np.column_stack([x, k, autumn, spring, summer, peak, peak_slot]).astype("float32")


FEATURE_NAMES = SLOT_COLS + ["n_known_slots", "autumn_mean", "spring_mean", "summer_mean", "peak", "peak_slot"]


def _augment(df: pd.DataFrame, rng: np.random.Generator, copies: int) -> tuple[np.ndarray, np.ndarray]:
    slots = df[SLOT_COLS].to_numpy(dtype="float32")
    y = df["label"].map({c: i for i, c in enumerate(CLASSES)}).to_numpy()
    X, Y = [], []
    for _ in range(copies):
        k = rng.choice(CUTOFFS_TRAIN, size=len(df))
        masked = slots.copy()
        masked[np.arange(N_SLOTS)[None, :] >= k[:, None]] = np.nan
        X.append(features(masked, k)); Y.append(y)
    return np.vstack(X), np.concatenate(Y)


def load_samples(data_dir: Path) -> pd.DataFrame:
    files = sorted((data_dir / "satellite" / "samples").glob("*.parquet"))
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    df["label"] = df["crop_code"].map(class_of)
    return df


# The organisers' 2021 crop map is pixel-identical to 2022 (checked 21 Nov 2026): its labels do not match
# the 2021 imagery, so season 2021 is left out of training and testing.
BAD_LABEL_SEASONS = {2021}


def train(data_dir: Path, test_season: int = 2024, holdout_windows: int = 6, copies: int = 4,
          exclude_seasons: set[int] = BAD_LABEL_SEASONS) -> dict:
    import lightgbm as lgb
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

    df = load_samples(data_dir)
    df = df[~df.season.isin(exclude_seasons)]
    windows = sorted(df["window"].unique())
    rng = np.random.default_rng(0)
    held = set(rng.choice(windows, size=holdout_windows, replace=False).tolist())
    train_df = df[(df.season != test_season) & ~df.window.isin(held)]
    test_df = df[(df.season == test_season) & df.window.isin(held)]
    # balance classes a little: at most 25k pixels per class in training
    train_df = pd.concat(g.sample(min(len(g), 25000), random_state=0) for _, g in train_df.groupby("label"))
    Xtr, ytr = _augment(train_df, rng, copies)
    params = dict(objective="multiclass", num_class=len(CLASSES), learning_rate=0.08, num_leaves=63,
                  min_data_in_leaf=100, feature_fraction=0.9, bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=0)
    booster = lgb.train(params, lgb.Dataset(Xtr, ytr, feature_name=FEATURE_NAMES), num_boost_round=300)

    report = {"train_pixels": len(train_df), "test_pixels": len(test_df), "test_season": test_season,
              "excluded_seasons": sorted(exclude_seasons),
              "holdout_windows": sorted(int(w) for w in held), "by_cutoff": {}}
    ytest = test_df["label"].map({c: i for i, c in enumerate(CLASSES)}).to_numpy()
    slots = test_df[SLOT_COLS].to_numpy(dtype="float32")
    for k in (6, 8, 14, 16, 17, 18, 20, 22, 24):
        masked = slots.copy(); masked[:, k:] = np.nan
        p = booster.predict(features(masked, k))
        pred = p.argmax(1)
        when = slot_end(test_season, k - 1).isoformat()
        per = {c: round(float(f1_score(ytest == i, pred == i)), 3) for i, c in enumerate(CLASSES)}
        report["by_cutoff"][when] = {"known_slots": k, "accuracy": round(float(accuracy_score(ytest, pred)), 3), "f1": per}
        if k in (18, 24):
            report["by_cutoff"][when]["confusion"] = confusion_matrix(ytest, pred, labels=range(len(CLASSES))).tolist()
    out = data_dir / "models"
    out.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(out / "crop_lgbm.txt"))
    (out / "crop_model.json").write_text(json.dumps({"version": MODEL_VERSION, "classes": CLASSES, "features": FEATURE_NAMES,
                                                     "report": report}, indent=1))
    return report


@lru_cache(maxsize=1)
def _booster(path: str):
    import lightgbm as lgb
    return lgb.Booster(model_file=path)


def model_path() -> Path:
    try:
        from django.conf import settings
        base = Path(settings.BASE_DIR)
    except Exception:
        base = Path(__file__).resolve().parents[1]
    return (base / os.environ.get("DATA_DIR", "../field-under-pressure-data") / "models" / "crop_lgbm.txt").resolve()


def predict_pixels(slots: np.ndarray, season: int, today: date, path: Path | None = None) -> dict:
    """
    slots: [pixels, 24] NDVI composites of one field (from engine.satellite.season.composite).
    Only slots complete by `today` are used. Returns the field's crop and the class probabilities.
    """
    path = path or model_path()
    if not path.exists():
        raise FileNotFoundError(f"crop model not trained: {path}")
    known = known_slots(season, today)
    x = np.array(slots, dtype="float32", copy=True)
    if x.ndim == 1:
        x = x[None, :]
    x[:, ~known] = np.nan
    x = x[np.isfinite(x).any(axis=1)]
    if len(x) == 0:
        return {"crop": None, "confidence": 0.0, "probabilities": {}, "pixels": 0, "known_slots": int(known.sum())}
    p = _booster(str(path)).predict(features(x, int(known.sum()))).mean(axis=0)
    best = int(p.argmax())
    return {"crop": CLASS_CODE[CLASSES[best]], "label": CLASSES[best], "confidence": round(float(p[best]), 3),
            "probabilities": {c: round(float(v), 3) for c, v in zip(CLASSES, p)}, "pixels": int(len(x)),
            "known_slots": int(known.sum()), "as_of": today.isoformat(), "model_version": MODEL_VERSION}


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "train":
        rep = train(Path(sys.argv[2]))
        for when, r in rep["by_cutoff"].items():
            print(f"as of {when} ({r['known_slots']:2d} slots): acc {r['accuracy']:.3f}  " +
                  " ".join(f"{c}={v:.2f}" for c, v in r["f1"].items()))
        print("classes:", CLASSES)
        for when, r in rep["by_cutoff"].items():
            if "confusion" in r:
                print(f"confusion as of {when} (rows = true):")
                for c, row in zip(CLASSES, r["confusion"]):
                    print(f"  {c:13s}", row)
    else:
        print(__doc__)
