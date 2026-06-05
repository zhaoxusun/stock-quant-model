import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from ml.predict import predict, predict_signals_with_details
from ml.api_rate_limiter import get_rate_limiter, RateLimitError
from settings import ENABLE_API_RATE_LIMIT
from logger import create_log

logger = create_log("test_model")

_RAW_DIR = os.path.join(_PROJECT_ROOT, "ml", "data", "raw", "futu")
_TABFMT = "fancy_grid"

sig_types = ["normal_buy", "normal_sell", "strong_buy", "strong_sell"]
sig_labels = {"normal_buy": "正向(normal_buy)", "normal_sell": "负向(normal_sell)",
              "strong_buy": "强正向(strong_buy)", "strong_sell": "强负向(strong_sell)"}


def _fmt_tbl(data, headers, aligns, showindex=False):
    from tabulate import tabulate
    return tabulate(
        data, headers=headers, tablefmt=_TABFMT, showindex=showindex,
        disable_numparse=True,
        colalign=aligns,
    )


def _pick_longest_csv(stock_code):
    """取某个股票时间跨度最大的 K 线文件"""
    best = None
    best_rows = -1
    for fname in os.listdir(_RAW_DIR):
        if not fname.endswith(".csv"):
            continue
        if fname.split("_")[0] != stock_code:
            continue
        fpath = os.path.join(_RAW_DIR, fname)
        n = len(pd.read_csv(fpath))
        if n > best_rows:
            best_rows = n
            best = fpath
    return best


def _fetch_kline_live(code, client_ip=None):
    """根据前缀实时获取 K 线 DataFrame。返回 (kline_df, stock_code, stock_name, data_source) 或 None"""
    prefix = code.split(".")[0].upper() if "." in code else ""

    if prefix not in ("SH", "SZ", "HK", "US"):
        return None

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")

    if ENABLE_API_RATE_LIMIT and client_ip:
        limiter = get_rate_limiter()
        allowed, retry_after = limiter.check_and_record(client_ip)
        if not allowed:
            raise RateLimitError(
                f"API 请求过于频繁，请 {retry_after} 秒后再试",
                retry_after=retry_after,
            )

    if prefix in ("SH", "SZ"):
        from stock.manager_baostock import get_stock_history, init_baostock
        import baostock as bs
        if not init_baostock():
            return None
        try:
            df = get_stock_history(code, start_date, end_date)
        finally:
            bs.logout()
        if df is None or df.empty:
            return None
        name = df["stock_name"].iloc[0] if "stock_name" in df.columns else code
        return df, code, name, f"baostock ({start_date} ~ {end_date})"

    if prefix == "HK":
        from stock.manager_akshare import get_hk_stock_history
        raw = code[len("HK."):]
        df = get_hk_stock_history(raw, start_date, end_date)
        if df is None or df.empty:
            return None
        name = df["stock_name"].iloc[0] if "stock_name" in df.columns else code
        return df, code, name, f"akshare ({start_date} ~ {end_date})"

    if prefix == "US":
        from stock.manager_akshare import get_us_history
        raw = code[len("US."):]
        df = get_us_history(raw, start_date, end_date)
        if df is None or df.empty:
            return None
        name = df["stock_name"].iloc[0] if "stock_name" in df.columns else code
        return df, code, name, f"akshare ({start_date} ~ {end_date})"

    return None


def test_single_stock(code, strategy_name="EnhancedVolumeStrategy", client_ip=None):
    """单只股票推理——4 路信号独立统计, 返回 dict 供 API 使用"""
    live = _fetch_kline_live(code, client_ip=client_ip)

    if live is not None:
        kline, stock_code, stock_name, data_source = live
        fpath = None
    else:
        fpath = _pick_longest_csv(code)
        if fpath is None:
            return
        kline = _read_kline(fpath)
        basename = os.path.basename(fpath).replace(".csv", "")
        parts = basename.split("_")
        stock_code = parts[0]
        stock_name = parts[1] if len(parts) > 2 else stock_code
        data_source = os.path.basename(fpath)

    t0 = time.time()
    details = predict_signals_with_details(kline, strategy_name)
    elapsed = time.time() - t0

    n = len(kline)
    ms_total = elapsed * 1000
    ms_per = ms_total / n if n else 0

    counts = {t: int(details[t].sum()) for t in sig_types}
    total_signal_days = int((details[sig_types].sum(axis=1) > 0).sum())

    signal_details = []
    if total_signal_days:
        active = details[details[sig_types].sum(axis=1) > 0]
        for _, row in active.iterrows():
            entry = {"date": row["date"].strftime("%Y-%m-%d")}
            for st in sig_types:
                entry[f"prob_{st}"] = round(float(row[f"prob_{st}"]), 4)
                entry[st] = int(row[st])
            signal_details.append(entry)

    latest = {}
    recent_week = {}
    if len(details) > 0:
        last = details.iloc[-1]
        latest = {
            "date": last["date"].strftime("%Y-%m-%d"),
            "has_signal": int(any(int(last[st]) for st in sig_types)),
        }
        for st in sig_types:
            latest[f"prob_{st}"] = round(float(last[f"prob_{st}"]), 4)
            latest[st] = int(last[st])

        recent_n = min(7, len(details))
        recent = details.iloc[-recent_n:]
        week_has_signal = int((recent[sig_types].sum(axis=1) > 0).any())
        week_signal_dates = recent[recent[sig_types].sum(axis=1) > 0]["date"].dt.strftime("%Y-%m-%d").tolist()
        week_counts = {t: int(recent[t].sum()) for t in sig_types}
        week_avg_probs = {f"prob_{st}": round(float(recent[f"prob_{st}"].mean()), 4) for st in sig_types}
        recent_week = {
            "start_date": recent["date"].iloc[0].strftime("%Y-%m-%d"),
            "end_date": recent["date"].iloc[-1].strftime("%Y-%m-%d"),
            "has_signal": week_has_signal,
            "signal_dates": week_signal_dates,
            "total_signal_days": len(week_signal_dates),
            "signal_counts": week_counts,
            "avg_probs": week_avg_probs,
        }

    # ── K 线图数据（最近 400 个交易日, 含信号标注）──
    chart_n = min(400, len(kline))
    chart_df = kline[["date", "open", "high", "low", "close", "volume"]].tail(chart_n).reset_index(drop=True)
    chart_details = details.tail(chart_n).reset_index(drop=True) if len(details) >= chart_n else details
    chart_data = []
    for i in range(len(chart_df)):
        bar = {
            "date": chart_df["date"].iloc[i].strftime("%Y-%m-%d"),
            "o": round(float(chart_df["open"].iloc[i]), 2),
            "h": round(float(chart_df["high"].iloc[i]), 2),
            "l": round(float(chart_df["low"].iloc[i]), 2),
            "c": round(float(chart_df["close"].iloc[i]), 2),
            "v": round(float(chart_df["volume"].iloc[i]), 2),
        }
        if i < len(chart_details):
            for st in sig_types:
                bar[st] = int(chart_details[st].iloc[i])
        else:
            for st in sig_types:
                bar[st] = 0
        chart_data.append(bar)

    return {
        "success": True,
        "code": stock_code,
        "stock_name": stock_name,
        "strategy": strategy_name,
        "file": data_source,
        "rows": n,
        "inference_time_ms": round(ms_total, 1),
        "inference_time_per_row_ms": round(ms_per, 4),
        "total_signal_days": total_signal_days,
        "signal_counts": counts,
        "signal_details": list(reversed(signal_details)),
        "latest": latest,
        "recent_week": recent_week,
        "chart_data": chart_data,
    }


def test_batch(strategy_name="EnhancedVolumeStrategy"):
    """批量推理——每只股票逐一跑，最后汇总"""
    logger.info("%s — 批量性能", strategy_name)

    files = _stock_csv_files(_RAW_DIR)
    if not files:
        logger.warning("K 线文件不存在")
        return

    rows = []
    t0 = time.time()
    for fpath in files:
        kline = _read_kline(fpath)
        predict(kline, strategy_name)
        rows.append({
            "code": os.path.basename(fpath).split("_")[0],
            "n": len(kline),
        })

    total_time = time.time() - t0
    total_rows = sum(r["n"] for r in rows)
    avg_ms = total_time / total_rows * 1000 if total_rows else 0

    data = []
    for r in rows:
        data.append({"股票": r["code"], "行数": r["n"], "占比": f"{r['n']/total_rows*100:.1f}%"})
    data.append({"股票": "─── 合计 ───", "行数": total_rows, "占比": "100%"})

    logger.info("总耗时: %.2fs  |  均耗时: %.3f ms/行\n%s", total_time, avg_ms, _fmt_tbl(data, "keys", ("left", "right", "right")))


def test_compare_with_actual(strategy_name="EnhancedVolumeStrategy"):
    """与原始信号逐日对比——每个信号类型独立二分类评估"""
    logger.info("%s — 信号对比评估", strategy_name)

    from ml.train import find_signal_for_stock

    files = _stock_csv_files(_RAW_DIR)
    if not files:
        logger.warning("K 线文件不存在")
        return

    stats = {t: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for t in sig_types}
    total_dates = 0
    matched = 0
    skipped = 0

    for fpath in files:
        code = os.path.basename(fpath).split("_")[0]
        stripped = code.split(".")[-1] if "." in code else code

        sig_path = find_signal_for_stock(stripped, strategy_name)
        if sig_path is None:
            skipped += 1
            continue
        matched += 1

        kline = _read_kline(fpath)
        signals_df = _read_kline(sig_path)

        details = predict_signals_with_details(kline, strategy_name)
        actual_sigs = signals_df.groupby("date")["signal_type"].apply(set)

        for _, row in details.iterrows():
            total_dates += 1
            actual_set = actual_sigs.get(row["date"], set())

            for t in sig_types:
                pred = row[t]
                actual = 1 if t in actual_set else 0
                if pred == 1 and actual == 1:
                    stats[t]["tp"] += 1
                elif pred == 1 and actual == 0:
                    stats[t]["fp"] += 1
                elif pred == 0 and actual == 1:
                    stats[t]["fn"] += 1
                else:
                    stats[t]["tn"] += 1

    if total_dates == 0:
        logger.warning("无信号数据匹配（%d 只股票无信号数据）", skipped)
        return

    logger.info("股票: %d 只  |  日期: %d 天  |  跳过: %d 只", matched, total_dates, skipped)

    rows = []
    for t in sig_types:
        s = stats[t]
        tp, fp, fn = s["tp"], s["fp"], s["fn"]
        precision = tp / (tp + fp) * 100 if tp + fp else 0
        recall = tp / (tp + fn) * 100 if tp + fn else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
        rows.append([
            sig_labels[t],
            str(tp + fn),
            str(tp),
            str(fp),
            str(fn),
            f"{precision:.1f}%",
            f"{recall:.1f}%",
            f"{f1:.1f}%",
        ])

    logger.info("\n" + _fmt_tbl(
        rows,
        ["信号", "实际", "TP(正确检出)", "FP(误报)", "FN(漏报)", "精确率", "召回率", "F1(综合)"],
        ("left", "right", "right", "right", "right", "right", "right", "right"),
    ))


def check_stock_signal(stock_code, date=None, strategy_name="EnhancedVolumeStrategy"):
    """
    输入股票代码，判断当天（或指定日期）是否有参考信号。

    Parameters
    ----------
    stock_code : str
        股票代码，支持 "HK.03968" "03968" "00700" 等格式
    date : str or None
        日期 "YYYY-MM-DD"，默认取该股票最新日期
    strategy_name : str
        信号策略名称
    """
    stock_code = str(stock_code)

    # 匹配K线文件（支持 HK.03968 / 03968 / 00700.HK 等格式）
    stripped = stock_code.split(".")[-1] if "." in stock_code else stock_code
    best = None
    best_rows = -1
    best_code = None
    for fname in os.listdir(_RAW_DIR):
        if not fname.endswith(".csv"):
            continue
        code_part = fname.split("_")[0]
        code_stripped = code_part.split(".")[-1] if "." in code_part else code_part
        if not (code_part == stock_code or code_part == stripped
                or code_stripped == stock_code or code_stripped == stripped):
            continue
        fpath = os.path.join(_RAW_DIR, fname)
        n = len(pd.read_csv(fpath))
        if n > best_rows:
            best_rows = n
            best = fpath
            best_code = code_part

    if best is None:
        logger.warning("未找到股票 %s 的K线文件", stock_code)
        return

    # 提取股票中文名
    basename = os.path.basename(best).replace(".csv", "")
    parts = basename.split("_")
    stock_name = parts[1] if len(parts) > 2 else best_code

    kline = _read_kline(best)
    details = predict_signals_with_details(kline, strategy_name)

    if date is not None:
        target = pd.to_datetime(date)
        row = details[details["date"] == target]
        if row.empty:
            available = f"{details['date'].min().strftime('%Y-%m-%d')} ~ {details['date'].max().strftime('%Y-%m-%d')}"
            logger.warning("日期 %s 不在 %s 数据范围内（%s）", date, stock_name, available)
            return
        date_str = date
    else:
        row = details.iloc[-1:]
        target = details["date"].iloc[-1]
        date_str = target.strftime("%Y-%m-%d")

    signals = {}
    for st in sig_types:
        prob_val = row[f"prob_{st}"].values[0]
        sig_val = row[st].values[0]
        signals[st] = (prob_val, sig_val)

    has_signal = any(v for _, v in signals.values())
    status_icon = "⚠️  有参考信号" if has_signal else "✅  无参考信号"

    tbl = []
    for st in sig_types:
        prob, sig = signals[st]
        status = "✓ 信号触发" if sig else "—"
        tbl.append([
            sig_labels[st],
            f"{prob:.1%}",
            status,
        ])
    logger.info("%s（%s）— %s\n%s\n%s", stock_name, best_code, date_str, status_icon,
                _fmt_tbl(tbl, ["信号类型", "概率", "状态"], ("left", "right", "left")))

    return {st: {"prob": float(prob), "signal": int(sig)}
            for st, (prob, sig) in signals.items()}


# ─────────────────────────── helpers ──


def _stock_csv_files(raw_dir):
    seen = set()
    files = []
    for fname in sorted(os.listdir(raw_dir)):
        if not fname.endswith(".csv"):
            continue
        code = fname.split("_")[0]
        if code not in seen:
            seen.add(code)
            files.append(os.path.join(raw_dir, fname))
    return files


def _read_kline(fpath):
    df = pd.read_csv(fpath)
    df["date"] = pd.to_datetime(df["date"])
    return df


if __name__ == "__main__":
    import tabulate as _tab
    import wcwidth
    _tab.wcwidth = wcwidth
    _tab.WIDE_CHARS_MODE = True

    strategy = "EnhancedVolumeStrategy"
    code = "HK.03968"

    result = test_single_stock(code, strategy)
    logger.info("返回数据: code=%s, signal_days=%s", result['code'], result['total_signal_days'])
    test_batch(strategy)
    test_compare_with_actual(strategy)

    check_stock_signal("HK.03968")  # 最新交易日
    check_stock_signal("03968", date="2025-05-12")  # 指定日期
    check_stock_signal("00700", date="2025-11-04")  # 获取返回dict

    logger.info("全部测试完成 ✓")
