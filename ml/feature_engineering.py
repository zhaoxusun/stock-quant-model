import numpy as np
import pandas as pd


def compute_features(df, params):
    df = df.copy().sort_values("date").reset_index(drop=True)

    n1 = params["n1"]
    n2 = params["n2"]
    n3 = params["n3"]
    rsi_period = params["rsi_period"]
    boll_period = params["boll_period"]
    boll_width = params["boll_width"]
    kdj_period = params["kdj_period"]

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)

    ma_vol_5 = volume.rolling(window=n2, min_periods=n2).mean()
    ma_vol_20 = volume.rolling(window=n3, min_periods=n3).mean()
    ma_close_5 = close.rolling(window=n2, min_periods=n2).mean()
    ma_close_20 = close.rolling(window=n3, min_periods=n3).mean()

    vol_std_5 = volume.rolling(window=n2, min_periods=n2).std(ddof=0)
    vol_std_20 = volume.rolling(window=n3, min_periods=n3).std(ddof=0)

    delta = close - close.shift(1)
    rsi_up = delta.clip(lower=0)
    rsi_down = (-delta).clip(lower=0)
    rsi_avg_up = rsi_up.rolling(window=rsi_period, min_periods=rsi_period).mean()
    rsi_avg_down = rsi_down.rolling(window=rsi_period, min_periods=rsi_period).mean()
    rsi = rsi_avg_up / (rsi_avg_up + rsi_avg_down + 1e-10) * 100

    boll_mid = close.rolling(window=boll_period, min_periods=boll_period).mean()
    boll_std = close.rolling(window=boll_period, min_periods=boll_period).std(ddof=0)
    boll_top = boll_mid + boll_width * boll_std
    boll_bot = boll_mid - boll_width * boll_std

    lowest_9 = low.rolling(window=kdj_period, min_periods=kdj_period).min()
    highest_3 = high.rolling(window=3, min_periods=3).max()
    lowest_3 = low.rolling(window=3, min_periods=3).min()
    rsv = (close - lowest_9) / (highest_3 - lowest_3 + 1e-10) * 100
    k = rsv.rolling(window=3, min_periods=3).mean()
    d = k.rolling(window=3, min_periods=3).mean()
    j = 3 * k - 2 * d

    vol_multiplier_5 = 0.9 + np.minimum(
        vol_std_5 / (ma_vol_5 + 1e-10), 0.6
    )
    vol_multiplier_20 = 0.8 + np.minimum(
        vol_std_20 / (ma_vol_20 + 1e-10), 0.5
    )

    volume_today = volume
    close_today = close

    vo_count_5 = np.where(
        volume_today > ma_vol_5 * vol_multiplier_5,
        volume_today - ma_vol_5,
        0.0,
    )
    vo_count_20 = np.where(
        volume_today > ma_vol_20 * vol_multiplier_20,
        volume_today - ma_vol_20,
        0.0,
    )

    price_open = df["open"].astype(float)
    is_3_down = (
        (close.shift(0) < price_open.shift(0))
        & (close.shift(1) < price_open.shift(1))
        & (close.shift(2) < price_open.shift(2))
    ).astype(int)
    is_3_up = (
        (close.shift(0) > price_open.shift(0))
        & (close.shift(1) > price_open.shift(1))
        & (close.shift(2) > price_open.shift(2))
    ).astype(int)

    ma_count_buy_5 = np.where(
        is_3_down & (ma_close_5 > close_today),
        ma_close_5 - close_today,
        0.0,
    )
    ma_count_sell_5 = np.where(
        is_3_up & (ma_close_5 < close_today),
        close_today - ma_close_5,
        0.0,
    )
    ma_count_buy_20 = np.where(
        is_3_down & (ma_close_20 > close_today),
        ma_close_20 - close_today,
        0.0,
    )
    ma_count_sell_20 = np.where(
        is_3_up & (ma_close_20 < close_today),
        close_today - ma_close_20,
        0.0,
    )

    buy_signal_5 = np.where(
        (vo_count_5 > 0) & (ma_count_buy_5 > 0),
        -vo_count_5 * ma_count_buy_5,
        0.0,
    )
    sell_signal_5 = np.where(
        (vo_count_5 > 0) & (ma_count_sell_5 > 0),
        vo_count_5 * ma_count_sell_5,
        0.0,
    )
    buy_signal_20 = np.where(
        (vo_count_20 > 0) & (ma_count_buy_20 > 0),
        -vo_count_20 * ma_count_buy_20,
        0.0,
    )
    sell_signal_20 = np.where(
        (vo_count_20 > 0) & (ma_count_sell_20 > 0),
        vo_count_20 * ma_count_sell_20,
        0.0,
    )

    buy_signal_count = (
        (buy_signal_5 != 0).astype(int)
        + (buy_signal_20 != 0).astype(int)
    )
    sell_signal_count = (
        (sell_signal_5 != 0).astype(int)
        + (sell_signal_20 != 0).astype(int)
    )

    features = pd.DataFrame({
        "date": df["date"],
        "open": price_open.astype(float),
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "ma_vol_5": ma_vol_5,
        "ma_vol_20": ma_vol_20,
        "ma_close_5": ma_close_5,
        "ma_close_20": ma_close_20,
        "vol_std_5": vol_std_5,
        "vol_std_20": vol_std_20,
        "rsi": rsi,
        "boll_mid": boll_mid,
        "boll_top": boll_top,
        "boll_bot": boll_bot,
        "rsv": rsv,
        "k": k,
        "d": d,
        "j": j,
        "vol_multiplier_5": vol_multiplier_5,
        "vol_multiplier_20": vol_multiplier_20,
        "vo_count_5": vo_count_5,
        "vo_count_20": vo_count_20,
        "is_3_up": is_3_up.astype(int),
        "is_3_down": is_3_down.astype(int),
        "ma_count_buy_5": ma_count_buy_5,
        "ma_count_sell_5": ma_count_sell_5,
        "ma_count_buy_20": ma_count_buy_20,
        "ma_count_sell_20": ma_count_sell_20,
        "buy_signal_5": buy_signal_5,
        "sell_signal_5": sell_signal_5,
        "buy_signal_20": buy_signal_20,
        "sell_signal_20": sell_signal_20,
        "buy_signal_count": buy_signal_count,
        "sell_signal_count": sell_signal_count,
    })

    return features


FEATURE_COLUMNS = [
    "open", "high", "low", "close", "volume",
    "ma_vol_5", "ma_vol_20", "ma_close_5", "ma_close_20",
    "vol_std_5", "vol_std_20",
    "rsi",
    "boll_mid", "boll_top", "boll_bot",
    "rsv", "k", "d", "j",
    "vol_multiplier_5", "vol_multiplier_20",
    "vo_count_5", "vo_count_20",
    "is_3_up", "is_3_down",
    "ma_count_buy_5", "ma_count_sell_5", "ma_count_buy_20", "ma_count_sell_20",
    "buy_signal_5", "sell_signal_5", "buy_signal_20", "sell_signal_20",
    "buy_signal_count", "sell_signal_count",
]
