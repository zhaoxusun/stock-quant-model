import os
import sys
import json
import glob
import pickle

import numpy as np
import pandas as pd
from sklearn.multioutput import MultiOutputClassifier

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml.config import (
    STRATEGIES, RAW_DATA_DIR, SIGNAL_DATA_DIR, MODEL_DIR,
    FEATURE_CACHE_DIR, LABEL_MAP, LABEL_INVERSE, SIGNAL_PRIORITY, XGB_PARAMS,
    SIGNAL_TYPES,
)
from ml.feature_engineering import compute_features, FEATURE_COLUMNS


def load_kline_csv(filepath):
    df = pd.read_csv(filepath)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def extract_stock_code(filename):
    name = filename.replace(".csv", "")
    parts = name.split("_")
    return parts[0]


def find_signal_for_stock(stock_code, strategy_name):
    best_file = None
    best_mtime = -1

    stripped = stock_code.split(".")[-1] if "." in stock_code else stock_code

    for entry in os.listdir(SIGNAL_DATA_DIR):
        entry_path = os.path.join(SIGNAL_DATA_DIR, entry)
        if not os.path.isdir(entry_path):
            continue
        entry_stock_code = entry.split("_")[0]
        entry_stripped = entry_stock_code.split(".")[-1] if "." in entry_stock_code else entry_stock_code
        if not (entry_stock_code == stock_code
                or entry_stock_code == stripped
                or entry_stripped == stock_code
                or entry_stripped == stripped):
            continue

        strategy_path = os.path.join(entry_path, strategy_name)
        if not os.path.isdir(strategy_path):
            continue

        for root, dirs, files in os.walk(strategy_path):
            for f in files:
                if f.startswith("stock_signals_") and f.endswith(".csv"):
                    fpath = os.path.join(root, f)
                    mtime = os.path.getmtime(fpath)
                    if mtime > best_mtime:
                        best_file = fpath
                        best_mtime = mtime

    return best_file


def load_signals(stock_code, strategy_name):
    fpath = find_signal_for_stock(stock_code, strategy_name)
    if fpath is None:
        return None
    df = pd.read_csv(fpath)
    df["date"] = pd.to_datetime(df["date"])
    return df


def build_multilabel_matrix(signals_df):
    if signals_df is None or signals_df.empty:
        return {}

    signals_df = signals_df.drop_duplicates(subset=["date", "signal_type"])
    result = {}
    for date, group in signals_df.groupby("date"):
        types = set(group["signal_type"])
        result[date] = {st: (1 if st in types else 0) for st in SIGNAL_TYPES}
    return result


def build_features_and_labels(strategy_name, strategy_params):
    raw_files = []
    for root, dirs, files in os.walk(RAW_DATA_DIR):
        for f in files:
            if f.endswith(".csv"):
                raw_files.append(os.path.join(root, f))

    if not raw_files:
        print(f"[{strategy_name}] No raw K-line files found in {RAW_DATA_DIR}")
        return None, None

    out_cols = ["date", "stock_code", "data_source"] + FEATURE_COLUMNS + SIGNAL_TYPES
    batches = []
    batch_rows = []
    total_rows = 0

    for fpath in sorted(raw_files):
        rel = os.path.relpath(fpath, RAW_DATA_DIR)
        parts = rel.replace("\\", "/").split("/")
        data_source = parts[0] if len(parts) > 1 else "unknown"
        filename = parts[-1]
        stock_code = extract_stock_code(filename)

        print(f"  Processing {stock_code} ({data_source}) ...")

        kline = load_kline_csv(fpath)
        features = compute_features(kline, strategy_params)
        features["stock_code"] = stock_code
        features["data_source"] = data_source

        signals = load_signals(stock_code, strategy_name)
        label_dict = build_multilabel_matrix(signals)

        for st in SIGNAL_TYPES:
            features[st] = features["date"].map(
                lambda d: label_dict.get(d, {}).get(st, 0)
            ).astype(int)

        counts = {st: features[st].sum() for st in SIGNAL_TYPES}
        print(f"    → {len(features)} rows, labels: {counts}")

        total_pos = sum(counts.values())
        if total_pos == 0:
            print(f"    ⤷ Skipped (0 signal labels — would bias model to predict all zeros)")
            continue

        batch_rows.append(features[out_cols])
        total_rows += len(features)

        if len(batch_rows) >= 50:
            batches.append(pd.concat(batch_rows, ignore_index=True))
            batch_rows = []

    if batch_rows:
        batches.append(pd.concat(batch_rows, ignore_index=True))

    if not batches:
        print(f"[{strategy_name}] No data processed.")
        return None, None

    if len(batches) == 1:
        full = batches[0]
    else:
        print(f"  Merging {len(batches)} batches ({total_rows} rows) ...")
        full = pd.concat(batches, ignore_index=True)

    return full, full[SIGNAL_TYPES]


def train_model(X, y, strategy_name):
    from xgboost import XGBClassifier

    print(f"\n[{strategy_name}] Training XGBoost (multi-label, 4 binary classifiers) ...")
    print(f"  Samples: {len(X)}, Features: {X.shape[1]}")
    for st in SIGNAL_TYPES:
        n_pos = y[st].sum()
        print(f"    {st}: {n_pos} positive ({n_pos/len(y)*100:.1f}%)")

    base = XGBClassifier(**XGB_PARAMS)
    model = MultiOutputClassifier(base, n_jobs=1)
    model.fit(X, y)

    save_dir = os.path.join(MODEL_DIR, strategy_name)
    os.makedirs(save_dir, exist_ok=True)

    model_path = os.path.join(save_dir, "model.pkl")
    with open(model_path, "wb") as f:
        pickle.dump(model, f)

    cols_path = os.path.join(save_dir, "feature_columns.json")
    with open(cols_path, "w") as f:
        json.dump(list(X.columns), f, indent=2)

    print(f"  Model saved to {model_path}")
    print(f"  Feature columns saved to {cols_path}")

    return model


def main():
    for strategy_name, cfg in STRATEGIES.items():
        if not cfg.get("enabled", False):
            print(f"\n{'='*60}")
            print(f"[{strategy_name}] Skipped (disabled in config)")
            continue

        print(f"\n{'='*60}")
        print(f"[{strategy_name}] Building features and labels ...")
        print(f"{'='*60}")

        df, y = build_features_and_labels(strategy_name, cfg["params"])
        if df is None or y is None:
            print(f"[{strategy_name}] No data available, skipping.")
            continue

        cache_feat = os.path.join(FEATURE_CACHE_DIR, f"features_{strategy_name}.csv")
        cache_label = os.path.join(FEATURE_CACHE_DIR, f"labels_{strategy_name}.csv")
        df[FEATURE_COLUMNS].to_csv(cache_feat, index=False)
        y.to_csv(cache_label, index=False)
        print(f"  Features cached to {cache_feat}")
        print(f"  Labels cached to {cache_label}")

        if cfg.get("train_model", False):
            train_model(df[FEATURE_COLUMNS], y, strategy_name)
        else:
            print(f"  Model training skipped (train_model=False)")

    print("\nDone.")


if __name__ == "__main__":
    main()
