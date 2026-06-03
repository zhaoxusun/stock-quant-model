import os
import json
import pickle

import pandas as pd
import numpy as np

from ml.config import MODEL_DIR, SIGNAL_TYPES
from ml.feature_engineering import compute_features, FEATURE_COLUMNS

_model_cache = {}


def load_model(strategy_name):
    if strategy_name in _model_cache:
        return _model_cache[strategy_name]

    model_path = os.path.join(MODEL_DIR, strategy_name, "model.pkl")
    cols_path = os.path.join(MODEL_DIR, strategy_name, "feature_columns.json")

    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"Model not found: {model_path}. "
            f"Run `python ml/train.py` first."
        )
    if not os.path.exists(cols_path):
        raise FileNotFoundError(
            f"Feature columns not found: {cols_path}."
        )

    with open(model_path, "rb") as f:
        model = pickle.load(f)

    with open(cols_path, "r") as f:
        feature_columns = json.load(f)

    _model_cache[strategy_name] = (model, feature_columns)
    return model, feature_columns


def predict(kline_df, strategy_name="EnhancedVolumeStrategy", threshold=0.5):
    """返回 date + 4 路二进制信号列，无合并"""
    model, feature_columns = load_model(strategy_name)

    params = _get_strategy_params(strategy_name)
    features = compute_features(kline_df, params)

    missing = set(feature_columns) - set(features.columns)
    if missing:
        for col in missing:
            features[col] = np.nan

    X = features[feature_columns]
    y_proba = model.predict_proba(X)

    result = pd.DataFrame({"date": kline_df["date"].values})
    for i, st in enumerate(SIGNAL_TYPES):
        proba_col = y_proba[i]
        if proba_col.ndim == 2 and proba_col.shape[1] == 2:
            result[st] = (proba_col[:, 1] >= threshold).astype(int)
        else:
            result[st] = (proba_col >= threshold).astype(int)

    return result[["date"] + SIGNAL_TYPES]


def predict_last(kline_df, strategy_name="EnhancedVolumeStrategy", threshold=0.5):
    """返回最后一天的 dict: { signal_type: 0/1 }"""
    signals = predict(kline_df, strategy_name, threshold=threshold)
    return signals.iloc[-1].to_dict()


def predict_signals_with_details(kline_df, strategy_name="EnhancedVolumeStrategy", threshold=0.5):
    """返回 date + prob_* + 二进制信号列，无合并"""
    model, feature_columns = load_model(strategy_name)

    params = _get_strategy_params(strategy_name)
    features = compute_features(kline_df, params)

    missing = set(feature_columns) - set(features.columns)
    if missing:
        for col in missing:
            features[col] = np.nan

    X = features[feature_columns]
    y_proba = model.predict_proba(X)

    result = pd.DataFrame({"date": kline_df["date"].values})
    for i, st in enumerate(SIGNAL_TYPES):
        proba_col = y_proba[i]
        if proba_col.ndim == 2 and proba_col.shape[1] == 2:
            result[f"prob_{st}"] = proba_col[:, 1]
            result[st] = (proba_col[:, 1] >= threshold).astype(int)
        else:
            result[f"prob_{st}"] = proba_col
            result[st] = (proba_col >= threshold).astype(int)

    cols = ["date"] + [f"prob_{st}" for st in SIGNAL_TYPES] + SIGNAL_TYPES
    return result[cols]


def _get_strategy_params(strategy_name):
    from ml.config import STRATEGIES
    cfg = STRATEGIES.get(strategy_name)
    if cfg is None:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    return cfg["params"]
