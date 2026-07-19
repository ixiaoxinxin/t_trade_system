# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from common import PRODUCT_VERSION, load_yaml_config, normalize_code, safe_float
from dataset_quality_report import LABEL_REVIEW_QUEUE_FILE, write_quality_report as write_dataset_quality_report
from dataset_splitter import build_time_series_split
from label_calculator import calculate_label_snapshot
from llm_labeler import build_llm_tables as build_llm_label_tables
from llm_labeler import build_provider_status_table
from sqlite_store import migrate_local_files_to_sqlite
from trade_journal import TRADE_RECORD_COLUMNS, TRADE_RECORD_FILE, load_trade_records


CONFIG_FILE = Path("config.yaml")
DATASET_DIR = Path("data/dataset")
SPLIT_DIR = Path("data/dataset/splits")
DATABASE_FILE = Path("data/dataset/trade_dataset.sqlite3")
QUALITY_REPORT_FILE = Path("output/dataset_quality_report.md")

FINAL_WATCHLIST_FILE = Path("output/final_watchlist.csv")
NEXT_DAY_REVIEW_FILE = Path("output/next_day_review.csv")
MARKET_ENV_FILE = Path("output/market_environment.json")
RUN_MANIFEST_FILE = Path("output/run_manifest.json")
DAILY_PLAN_FILE = Path("output/daily_plan.md")
CACHE_DAILY_DIR = Path("cache/daily")
CACHE_MINUTE_DIR = Path("cache/minute")


DATASET_DEFAULT_CONFIG = {
    "dataset": {
        "database": "sqlite",
        "database_path": str(DATABASE_FILE),
        "export_dir": str(DATASET_DIR),
        "split_dir": str(SPLIT_DIR),
    },
    "llm_labeling": {
        "enabled": False,
        "provider_priority": ["deepseek", "doubao", "qwen", "glm"],
        "max_daily_cost_cny": 20,
        "min_confidence": 0.7,
        "prompt_version": "v2.5-labeling-001",
    },
}


TABLE_SCHEMAS = {
    "dataset_samples": """
        sample_id TEXT PRIMARY KEY,
        stock_code TEXT,
        stock_name TEXT,
        predict_date TEXT,
        feature_date TEXT,
        target_date TEXT,
        rule_version TEXT,
        config_hash TEXT,
        run_id TEXT,
        source_files TEXT,
        data_status TEXT
    """,
    "feature_snapshot": """
        sample_id TEXT PRIMARY KEY,
        stock_code TEXT,
        feature_date TEXT,
        ret_1d REAL,
        ret_3d REAL,
        ret_5d REAL,
        ret_20d REAL,
        ma5_gap REAL,
        ma10_gap REAL,
        ma20_gap REAL,
        ma5_slope REAL,
        ma10_slope REAL,
        atr_14 REAL,
        hist_vol_20 REAL,
        range_5d REAL,
        amount REAL,
        avg_amount_5d REAL,
        turnover_rate REAL,
        volume_ratio REAL,
        body_pct REAL,
        upper_shadow_pct REAL,
        lower_shadow_pct REAL,
        gap_open_pct REAL,
        open_strength REAL,
        first_15m_return REAL,
        first_15m_drawdown REAL,
        vwap_gap REAL,
        path_rebound INTEGER,
        path_fade INTEGER,
        path_break_morning_high INTEGER,
        market_regime TEXT,
        market_risk_level TEXT,
        market_atr REAL,
        panic_score REAL,
        sector_name TEXT,
        sector_status TEXT,
        sector_rank_1d REAL,
        sector_rank_5d REAL,
        sector_breadth REAL,
        sector_leader_pct REAL,
        candidate_score REAL,
        tail_score REAL,
        final_score REAL,
        overnight_grade TEXT,
        risk_level TEXT
    """,
    "label_snapshot": """
        sample_id TEXT PRIMARY KEY,
        stock_code TEXT,
        predict_date TEXT,
        target_date TEXT,
        direction_up_close INTEGER,
        touch_buy_range INTEGER,
        hit_1pct_after_touch INTEGER,
        hit_2pct_after_touch INTEGER,
        stop_2pct_after_touch INTEGER,
        first_event TEXT,
        next_day_high_pct REAL,
        next_day_low_pct REAL,
        realized_path_type TEXT,
        execution_quality TEXT,
        label_source TEXT
    """,
    "prediction_log": """
        sample_id TEXT PRIMARY KEY,
        run_id TEXT,
        stock_code TEXT,
        stock_name TEXT,
        predict_date TEXT,
        rule_version TEXT,
        candidate_score REAL,
        tail_score REAL,
        final_score REAL,
        overnight_grade TEXT,
        risk_level TEXT,
        advice TEXT,
        created_at TEXT
    """,
    "trade_records": """
        record_id TEXT PRIMARY KEY,
        recorded_at TEXT,
        trade_date TEXT,
        trade_type TEXT,
        stock_code TEXT,
        stock_name TEXT,
        direction TEXT,
        buy_price REAL,
        sell_price REAL,
        quantity INTEGER,
        buy_commission REAL,
        sell_commission REAL,
        total_commission REAL,
        net_profit REAL,
        return_rate REAL,
        closed_status TEXT,
        strategy_source TEXT,
        followed_plan TEXT,
        note TEXT
    """,
    "llm_label_snapshot": """
        sample_id TEXT PRIMARY KEY,
        provider TEXT,
        model TEXT,
        prompt_version TEXT,
        realized_path_type TEXT,
        execution_quality TEXT,
        label_confidence REAL,
        needs_manual_review INTEGER,
        conflict_fields TEXT,
        reason TEXT,
        created_at TEXT
    """,
    "llm_provider_status": """
        provider TEXT PRIMARY KEY,
        model TEXT,
        api_key_env TEXT,
        has_api_key INTEGER,
        base_url TEXT,
        status TEXT,
        checked_at TEXT
    """,
    "api_usage_log": """
        usage_id TEXT PRIMARY KEY,
        provider TEXT,
        model TEXT,
        prompt_version TEXT,
        input_tokens INTEGER,
        output_tokens INTEGER,
        cost_estimate_cny REAL,
        status TEXT,
        created_at TEXT
    """,
    "label_review_queue": """
        sample_id TEXT,
        stock_code TEXT,
        review_type TEXT,
        severity TEXT,
        reason TEXT,
        created_at TEXT
    """,
}


def load_config() -> dict:
    return load_yaml_config(CONFIG_FILE, DATASET_DEFAULT_CONFIG)


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    return pd.read_csv(path, dtype={"股票代码": str})


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def config_hash() -> str:
    if not CONFIG_FILE.exists():
        return ""

    raw = CONFIG_FILE.read_bytes()
    return hashlib.sha256(raw).hexdigest()[:12]


def today_text() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def next_date_text(date_text: str) -> str:
    try:
        dt = datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        return date_text

    return (dt + timedelta(days=1)).strftime("%Y-%m-%d")


def sample_id(stock_code: str, predict_date: str, rule_version: str) -> str:
    return f"{normalize_code(stock_code)}_{predict_date}_{rule_version}"


def yes_no_to_int(value: Any) -> int | None:
    text = str(value).strip()

    if text == "是":
        return 1

    if text == "否":
        return 0

    return None


def first_event(row: pd.Series) -> str:
    if yes_no_to_int(row.get("是否触发-2%止损")) == 1:
        return "stop_loss"

    if yes_no_to_int(row.get("是否达到2%")) == 1:
        return "hit_2pct"

    if yes_no_to_int(row.get("是否达到1%")) == 1:
        return "hit_1pct"

    return "no_event"


def path_flag(text: Any, keywords: list[str]) -> int:
    value = str(text)
    return int(any(keyword in value for keyword in keywords))


def none_if_nan(value: Any) -> Any:
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None

    return value


def round_or_none(value: Any, digits: int = 4) -> float | None:
    value = none_if_nan(value)

    if value is None:
        return None

    try:
        return round(float(value), digits)
    except Exception:
        return None


def pct_change(current: Any, previous: Any) -> float | None:
    current_value = safe_float(current, default=float("nan"))
    previous_value = safe_float(previous, default=float("nan"))

    if pd.isna(current_value) or pd.isna(previous_value) or previous_value == 0:
        return None

    return (current_value / previous_value - 1) * 100


def read_daily_history(stock_code: str, feature_date: str) -> pd.DataFrame:
    path = CACHE_DAILY_DIR / f"{normalize_code(stock_code)}.csv"

    if not path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()

    required = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]

    if any(col not in df.columns for col in required):
        return pd.DataFrame()

    df = df.copy()
    df["日期_dt"] = pd.to_datetime(df["日期"], errors="coerce")
    feature_dt = pd.to_datetime(feature_date, errors="coerce")
    df = df.dropna(subset=["日期_dt"]).sort_values("日期_dt")

    if pd.notna(feature_dt):
        df = df[df["日期_dt"] <= feature_dt]

    return df.reset_index(drop=True)


def build_daily_cache_features(stock_code: str, feature_date: str) -> dict[str, Any]:
    df = read_daily_history(stock_code, feature_date)

    if df.empty:
        return {}

    numeric_columns = ["开盘", "收盘", "最高", "最低", "成交量", "成交额"]
    df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric, errors="coerce")
    df = df.dropna(subset=["开盘", "收盘", "最高", "最低"]).reset_index(drop=True)

    if df.empty:
        return {}

    close = df["收盘"]
    high = df["最高"]
    low = df["最低"]
    open_ = df["开盘"]
    amount = df["成交额"]
    volume = df["成交量"]
    latest = df.iloc[-1]
    prev_close = close.iloc[-2] if len(df) >= 2 else None

    true_range = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    daily_return = close.pct_change()

    def ret(days: int) -> float | None:
        if len(df) <= days:
            return None
        return pct_change(close.iloc[-1], close.iloc[-1 - days])

    def ma_gap(days: int) -> float | None:
        if len(df) < days:
            return None
        ma = close.tail(days).mean()
        return pct_change(close.iloc[-1], ma)

    def ma_slope(days: int) -> float | None:
        if len(df) <= days:
            return None
        current_ma = close.tail(days).mean()
        previous_ma = close.iloc[-days - 1:-1].mean()
        return pct_change(current_ma, previous_ma)

    latest_close = safe_float(latest.get("收盘", 0))
    latest_open = safe_float(latest.get("开盘", 0))
    latest_high = safe_float(latest.get("最高", 0))
    latest_low = safe_float(latest.get("最低", 0))

    avg_amount_5d = amount.tail(5).mean() if amount.notna().any() else None
    previous_volume_5d = volume.iloc[-6:-1].mean() if len(volume) >= 6 else None

    return {
        "ret_1d": round_or_none(ret(1)),
        "ret_3d": round_or_none(ret(3)),
        "ret_5d": round_or_none(ret(5)),
        "ret_20d": round_or_none(ret(20)),
        "ma5_gap": round_or_none(ma_gap(5)),
        "ma10_gap": round_or_none(ma_gap(10)),
        "ma20_gap": round_or_none(ma_gap(20)),
        "ma5_slope": round_or_none(ma_slope(5)),
        "ma10_slope": round_or_none(ma_slope(10)),
        "atr_14": round_or_none(true_range.tail(14).mean() / latest_close * 100 if latest_close else None),
        "hist_vol_20": round_or_none(daily_return.tail(20).std() * 100),
        "range_5d": round_or_none((high.tail(5).max() / low.tail(5).min() - 1) * 100 if low.tail(5).min() else None),
        "amount": round_or_none(latest.get("成交额")),
        "avg_amount_5d": round_or_none(avg_amount_5d),
        "volume_ratio": round_or_none(safe_float(latest.get("成交量", 0)) / previous_volume_5d if previous_volume_5d else None),
        "body_pct": round_or_none((latest_close - latest_open) / latest_close * 100 if latest_close else None),
        "upper_shadow_pct": round_or_none((latest_high - max(latest_open, latest_close)) / latest_close * 100 if latest_close else None),
        "lower_shadow_pct": round_or_none((min(latest_open, latest_close) - latest_low) / latest_close * 100 if latest_close else None),
        "gap_open_pct": round_or_none(pct_change(latest_open, prev_close)),
    }


def read_minute_history(stock_code: str, feature_date: str) -> pd.DataFrame:
    path = CACHE_MINUTE_DIR / f"{normalize_code(stock_code)}_1m.csv"

    if not path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()

    required = ["datetime", "open", "high", "low", "close", "volume", "amount"]

    if any(col not in df.columns for col in required):
        return pd.DataFrame()

    df = df.copy()
    df["datetime_dt"] = pd.to_datetime(df["datetime"], errors="coerce")
    feature_dt = pd.to_datetime(feature_date, errors="coerce")
    df = df.dropna(subset=["datetime_dt"]).sort_values("datetime_dt")

    if pd.notna(feature_dt):
        same_day = df[df["datetime_dt"].dt.date == feature_dt.date()]

        if not same_day.empty:
            df = same_day
        else:
            df = df[df["datetime_dt"] <= feature_dt + pd.Timedelta(hours=23, minutes=59, seconds=59)]
            if not df.empty:
                latest_day = df["datetime_dt"].dt.date.max()
                df = df[df["datetime_dt"].dt.date == latest_day]

    return df.reset_index(drop=True)


def build_minute_cache_features(stock_code: str, feature_date: str, prev_close: Any) -> dict[str, Any]:
    df = read_minute_history(stock_code, feature_date)

    if df.empty:
        return {}

    numeric_columns = ["open", "high", "low", "close", "volume", "amount"]
    df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric, errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)

    if df.empty:
        return {}

    first_window = df.head(15)
    first_open = safe_float(df.iloc[0].get("open", 0))
    close_15m = safe_float(first_window.iloc[-1].get("close", 0))
    low_15m = safe_float(first_window["low"].min())
    total_amount = safe_float(df["amount"].sum())
    total_volume = safe_float(df["volume"].sum())
    last_close = safe_float(df.iloc[-1].get("close", 0))
    vwap = total_amount / total_volume if total_volume else None

    return {
        "open_strength": round_or_none(pct_change(first_open, prev_close)),
        "first_15m_return": round_or_none(pct_change(close_15m, first_open)),
        "first_15m_drawdown": round_or_none(pct_change(low_15m, first_open)),
        "vwap_gap": round_or_none(pct_change(last_close, vwap)),
    }


def ensure_database(conn: sqlite3.Connection) -> None:
    for table_name, schema in TABLE_SCHEMAS.items():
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({schema})")
        conn.execute(f"DELETE FROM {table_name}")

    conn.commit()


def insert_dataframe(conn: sqlite3.Connection, table_name: str, df: pd.DataFrame) -> None:
    if df.empty:
        return

    df.to_sql(table_name, conn, if_exists="append", index=False)


def combine_frames(frames: list[pd.DataFrame], dedupe_key: str) -> pd.DataFrame:
    usable = [
        df.dropna(axis=1, how="all")
        for df in frames
        if not df.empty
    ]

    if not usable:
        return pd.DataFrame()

    return pd.concat(usable, ignore_index=True).drop_duplicates(dedupe_key, keep="first")


def build_samples(
    final_df: pd.DataFrame,
    manifest: dict,
    sources: list[str],
) -> pd.DataFrame:
    generated_at = str(manifest.get("generated_at", today_text()))[:10]
    rule_version = f"v{PRODUCT_VERSION}"
    run_id = manifest.get("generated_at", "")
    cfg_hash = config_hash()
    rows = []

    for _, row in final_df.iterrows():
        code = normalize_code(row.get("股票代码", ""))

        if not code:
            continue

        rows.append({
            "sample_id": sample_id(code, generated_at, rule_version),
            "stock_code": code,
            "stock_name": str(row.get("股票名称", "")),
            "predict_date": generated_at,
            "feature_date": generated_at,
            "target_date": next_date_text(generated_at),
            "rule_version": rule_version,
            "config_hash": cfg_hash,
            "run_id": run_id,
            "source_files": ";".join(sources),
            "data_status": "ready",
        })

    return pd.DataFrame(rows)


def build_review_samples(
    next_day_df: pd.DataFrame,
    manifest: dict,
    sources: list[str],
) -> pd.DataFrame:
    rule_version = f"v{PRODUCT_VERSION}"
    run_id = manifest.get("generated_at", "")
    cfg_hash = config_hash()
    rows = []

    for _, row in next_day_df.iterrows():
        code = normalize_code(row.get("股票代码", ""))
        predict_date = str(row.get("验证日期", ""))[:10]

        if not code or not predict_date:
            continue

        rows.append({
            "sample_id": sample_id(code, predict_date, rule_version),
            "stock_code": code,
            "stock_name": str(row.get("股票名称", "")),
            "predict_date": predict_date,
            "feature_date": predict_date,
            "target_date": str(row.get("次日日期", ""))[:10],
            "rule_version": rule_version,
            "config_hash": cfg_hash,
            "run_id": run_id,
            "source_files": ";".join(sources),
            "data_status": "ready_from_review",
        })

    return pd.DataFrame(rows)


def build_feature_snapshot(
    final_df: pd.DataFrame,
    market_env: dict,
    manifest: dict,
) -> pd.DataFrame:
    generated_at = str(manifest.get("generated_at", today_text()))[:10]
    rule_version = f"v{PRODUCT_VERSION}"
    rows = []

    for _, row in final_df.iterrows():
        code = normalize_code(row.get("股票代码", ""))

        if not code:
            continue

        structure = str(row.get("分时结构标签", ""))
        daily_features = build_daily_cache_features(code, generated_at)
        minute_features = build_minute_cache_features(code, generated_at, row.get("昨收", 0))

        rows.append({
            "sample_id": sample_id(code, generated_at, rule_version),
            "stock_code": code,
            "feature_date": generated_at,
            "ret_1d": daily_features.get("ret_1d", safe_float(row.get("今日涨跌幅", 0))),
            "ret_3d": daily_features.get("ret_3d"),
            "ret_5d": daily_features.get("ret_5d", safe_float(row.get("最近5日涨幅", 0))),
            "ret_20d": daily_features.get("ret_20d"),
            "ma5_gap": daily_features.get("ma5_gap", safe_float(row.get("距MA5偏离率", 0))),
            "ma10_gap": daily_features.get("ma10_gap"),
            "ma20_gap": daily_features.get("ma20_gap"),
            "ma5_slope": daily_features.get("ma5_slope"),
            "ma10_slope": daily_features.get("ma10_slope"),
            "atr_14": daily_features.get("atr_14"),
            "hist_vol_20": daily_features.get("hist_vol_20"),
            "range_5d": daily_features.get("range_5d", safe_float(row.get("最近5日振幅", row.get("今日振幅", 0)))),
            "amount": daily_features.get("amount", safe_float(row.get("今日成交额", 0))),
            "avg_amount_5d": daily_features.get("avg_amount_5d", safe_float(row.get("最近5日平均成交额", 0))),
            "turnover_rate": None,
            "volume_ratio": daily_features.get("volume_ratio", safe_float(row.get("尾盘放量倍数", 0))),
            "body_pct": daily_features.get("body_pct"),
            "upper_shadow_pct": daily_features.get("upper_shadow_pct"),
            "lower_shadow_pct": daily_features.get("lower_shadow_pct"),
            "gap_open_pct": daily_features.get("gap_open_pct"),
            "open_strength": minute_features.get("open_strength"),
            "first_15m_return": minute_features.get("first_15m_return"),
            "first_15m_drawdown": minute_features.get("first_15m_drawdown"),
            "vwap_gap": minute_features.get("vwap_gap"),
            "path_rebound": path_flag(structure, ["修复", "回升", "转强"]),
            "path_fade": path_flag(structure, ["回落", "失败", "弱势"]),
            "path_break_morning_high": int(str(row.get("是否突破上午高点", "")) == "是"),
            "market_regime": str(market_env.get("市场环境", "")),
            "market_risk_level": str(market_env.get("风险等级", "")),
            "market_atr": None,
            "panic_score": None,
            "sector_name": str(row.get("所属板块", "")),
            "sector_status": str(row.get("板块数据状态", "")),
            "sector_rank_1d": safe_float(row.get("板块当日资金排名", 0)),
            "sector_rank_5d": safe_float(row.get("板块近5日排名", 0)),
            "sector_breadth": safe_float(row.get("板块广度", 0)),
            "sector_leader_pct": safe_float(row.get("龙头涨幅", 0)),
            "candidate_score": safe_float(row.get("候选评分", 0)),
            "tail_score": safe_float(row.get("尾盘评分", 0)),
            "final_score": safe_float(row.get("最终评分", 0)),
            "overnight_grade": str(row.get("隔夜建议等级", "")),
            "risk_level": str(row.get("风险等级", "")),
        })

    return pd.DataFrame(rows)


def build_review_feature_snapshot(next_day_df: pd.DataFrame) -> pd.DataFrame:
    rule_version = f"v{PRODUCT_VERSION}"
    rows = []

    for _, row in next_day_df.iterrows():
        code = normalize_code(row.get("股票代码", ""))
        predict_date = str(row.get("验证日期", ""))[:10]

        if not code or not predict_date:
            continue

        structure = str(row.get("分时结构标签", ""))
        daily_features = build_daily_cache_features(code, predict_date)
        minute_features = build_minute_cache_features(code, predict_date, row.get("预测日收盘价", row.get("昨收", 0)))

        rows.append({
            "sample_id": sample_id(code, predict_date, rule_version),
            "stock_code": code,
            "feature_date": predict_date,
            "ret_1d": daily_features.get("ret_1d"),
            "ret_3d": daily_features.get("ret_3d"),
            "ret_5d": daily_features.get("ret_5d"),
            "ret_20d": daily_features.get("ret_20d"),
            "ma5_gap": daily_features.get("ma5_gap"),
            "ma10_gap": daily_features.get("ma10_gap"),
            "ma20_gap": daily_features.get("ma20_gap"),
            "ma5_slope": daily_features.get("ma5_slope"),
            "ma10_slope": daily_features.get("ma10_slope"),
            "atr_14": daily_features.get("atr_14"),
            "hist_vol_20": daily_features.get("hist_vol_20"),
            "range_5d": daily_features.get("range_5d"),
            "amount": daily_features.get("amount"),
            "avg_amount_5d": daily_features.get("avg_amount_5d"),
            "turnover_rate": None,
            "volume_ratio": daily_features.get("volume_ratio"),
            "body_pct": daily_features.get("body_pct"),
            "upper_shadow_pct": daily_features.get("upper_shadow_pct"),
            "lower_shadow_pct": daily_features.get("lower_shadow_pct"),
            "gap_open_pct": daily_features.get("gap_open_pct"),
            "open_strength": minute_features.get("open_strength"),
            "first_15m_return": minute_features.get("first_15m_return"),
            "first_15m_drawdown": minute_features.get("first_15m_drawdown"),
            "vwap_gap": minute_features.get("vwap_gap"),
            "path_rebound": path_flag(structure, ["修复", "回升", "转强"]),
            "path_fade": path_flag(structure, ["回落", "失败", "弱势"]),
            "path_break_morning_high": None,
            "market_regime": "",
            "market_risk_level": "",
            "market_atr": None,
            "panic_score": None,
            "sector_name": str(row.get("所属板块", "")),
            "sector_status": "",
            "sector_rank_1d": None,
            "sector_rank_5d": None,
            "sector_breadth": None,
            "sector_leader_pct": None,
            "candidate_score": safe_float(row.get("候选评分", 0)),
            "tail_score": safe_float(row.get("尾盘评分", 0)),
            "final_score": safe_float(row.get("最终评分", 0)),
            "overnight_grade": str(row.get("隔夜建议等级", "")),
            "risk_level": "",
        })

    return pd.DataFrame(rows)


def build_label_snapshot(next_day_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    rule_version = f"v{PRODUCT_VERSION}"

    for _, row in next_day_df.iterrows():
        code = normalize_code(row.get("股票代码", ""))
        predict_date = str(row.get("验证日期", ""))[:10] or today_text()

        if not code:
            continue

        close_pct = safe_float(row.get("次日收盘涨幅", 0))
        success = yes_no_to_int(row.get("是否验证成功"))

        rows.append({
            "sample_id": sample_id(code, predict_date, rule_version),
            "stock_code": code,
            "predict_date": predict_date,
            "target_date": str(row.get("次日日期", ""))[:10],
            "direction_up_close": int(close_pct > 0),
            "touch_buy_range": yes_no_to_int(row.get("是否触达低吸区间")),
            "hit_1pct_after_touch": yes_no_to_int(row.get("是否达到1%")),
            "hit_2pct_after_touch": yes_no_to_int(row.get("是否达到2%")),
            "stop_2pct_after_touch": yes_no_to_int(row.get("是否触发-2%止损")),
            "first_event": first_event(row),
            "next_day_high_pct": safe_float(row.get("次日最高涨幅", 0)),
            "next_day_low_pct": safe_float(row.get("次日最低涨幅", 0)),
            "realized_path_type": str(row.get("分时结构标签", "")),
            "execution_quality": "可执行盈利" if success == 1 else "可执行止损或失败",
            "label_source": "next_day_review",
        })

    return pd.DataFrame(rows)


def build_prediction_log(final_df: pd.DataFrame, manifest: dict) -> pd.DataFrame:
    generated_at = str(manifest.get("generated_at", today_text()))[:10]
    created_at = str(manifest.get("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    rule_version = f"v{PRODUCT_VERSION}"
    run_id = manifest.get("generated_at", "")
    rows = []

    for _, row in final_df.iterrows():
        code = normalize_code(row.get("股票代码", ""))

        if not code:
            continue

        rows.append({
            "sample_id": sample_id(code, generated_at, rule_version),
            "run_id": run_id,
            "stock_code": code,
            "stock_name": str(row.get("股票名称", "")),
            "predict_date": generated_at,
            "rule_version": rule_version,
            "candidate_score": safe_float(row.get("候选评分", 0)),
            "tail_score": safe_float(row.get("尾盘评分", 0)),
            "final_score": safe_float(row.get("最终评分", 0)),
            "overnight_grade": str(row.get("隔夜建议等级", "")),
            "risk_level": str(row.get("风险等级", "")),
            "advice": str(row.get("隔夜建议说明", "")),
            "created_at": created_at,
        })

    return pd.DataFrame(rows)


def build_trade_record_table() -> pd.DataFrame:
    trade_df = load_trade_records(TRADE_RECORD_FILE)

    if trade_df.empty:
        return pd.DataFrame(columns=[
            "record_id",
            "recorded_at",
            "trade_date",
            "trade_type",
            "stock_code",
            "stock_name",
            "direction",
            "buy_price",
            "sell_price",
            "quantity",
            "buy_commission",
            "sell_commission",
            "total_commission",
            "net_profit",
            "return_rate",
            "closed_status",
            "strategy_source",
            "followed_plan",
            "note",
        ])

    rename_map = dict(zip(TRADE_RECORD_COLUMNS, [
        "record_id",
        "recorded_at",
        "trade_date",
        "trade_type",
        "stock_code",
        "stock_name",
        "direction",
        "buy_price",
        "sell_price",
        "quantity",
        "buy_commission",
        "sell_commission",
        "total_commission",
        "net_profit",
        "return_rate",
        "closed_status",
        "strategy_source",
        "followed_plan",
        "note",
    ]))

    return trade_df.rename(columns=rename_map)[list(rename_map.values())].copy()


def export_tables(conn: sqlite3.Connection, export_dir: Path) -> list[str]:
    export_dir.mkdir(parents=True, exist_ok=True)
    outputs = []

    for table_name in TABLE_SCHEMAS:
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
        output_path = export_dir / f"{table_name}.csv"
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        outputs.append(str(output_path))

    return outputs


def build_split(samples_df: pd.DataFrame, split_dir: Path) -> str:
    split_dir.mkdir(parents=True, exist_ok=True)
    output_path = split_dir / "latest.json"

    if samples_df.empty:
        split = {
            "method": "chronological",
            "train": [],
            "validation": [],
            "test": [],
            "note": "样本为空，暂不能切分。",
        }
    else:
        ordered = samples_df.sort_values(["predict_date", "sample_id"]).reset_index(drop=True)
        n = len(ordered)
        train_end = max(1, int(n * 0.7))
        validation_end = max(train_end, int(n * 0.85))

        split = {
            "method": "chronological",
            "train": ordered.iloc[:train_end]["sample_id"].tolist(),
            "validation": ordered.iloc[train_end:validation_end]["sample_id"].tolist(),
            "test": ordered.iloc[validation_end:]["sample_id"].tolist(),
            "counts": {
                "total": n,
                "train": train_end,
                "validation": max(0, validation_end - train_end),
                "test": max(0, n - validation_end),
            },
            "note": "按预测日期排序切分，不随机打乱。样本量增大后再启用2年/3个月/1个月滚动窗口。",
        }

    output_path.write_text(json.dumps(split, ensure_ascii=False, indent=2), encoding="utf-8")

    return str(output_path)


def write_quality_report(
    table_counts: dict[str, int],
    db_path: Path,
    split_path: str,
    outputs: list[str],
    llm_enabled: bool,
) -> None:
    QUALITY_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# v2.5 数据集质量报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 一、数据库",
        "",
        f"- 数据库类型：SQLite",
        f"- 数据库文件：`{db_path}`",
        "",
        "## 二、表记录数",
        "",
        "| 表 | 记录数 |",
        "|---|---:|",
    ]

    for table_name, count in table_counts.items():
        lines.append(f"| `{table_name}` | {count} |")

    lines.extend([
        "",
        "## 三、LLM 辅助标签",
        "",
        f"- 当前开关：{'开启' if llm_enabled else '关闭'}",
        "- 未配置或关闭时，不阻断样本、特征、标签、交易记录生成。",
        "",
        "## 四、时间序列切分",
        "",
        f"- 切分文件：`{split_path}`",
        "",
        "## 五、导出文件",
        "",
    ])

    for output in outputs:
        lines.append(f"- `{output}`")

    QUALITY_REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_dataset() -> dict:
    config = load_config()
    dataset_config = config.get("dataset", {})
    export_dir = Path(dataset_config.get("export_dir", DATASET_DIR))
    split_dir = Path(dataset_config.get("split_dir", SPLIT_DIR))
    db_path = Path(dataset_config.get("database_path", DATABASE_FILE))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    final_df = read_csv(FINAL_WATCHLIST_FILE)
    next_day_df = read_csv(NEXT_DAY_REVIEW_FILE)
    market_env = read_json(MARKET_ENV_FILE)
    manifest = read_json(RUN_MANIFEST_FILE)
    sources = [
        str(path) for path in [
            FINAL_WATCHLIST_FILE,
            NEXT_DAY_REVIEW_FILE,
            MARKET_ENV_FILE,
            RUN_MANIFEST_FILE,
            DAILY_PLAN_FILE,
            TRADE_RECORD_FILE,
        ] if path.exists()
    ]

    samples_df = combine_frames([
        build_samples(final_df, manifest, sources),
        build_review_samples(next_day_df, manifest, sources),
    ], "sample_id")
    feature_df = combine_frames([
        build_feature_snapshot(final_df, market_env, manifest),
        build_review_feature_snapshot(next_day_df),
    ], "sample_id")
    label_df = calculate_label_snapshot(next_day_df)
    prediction_df = build_prediction_log(final_df, manifest)
    trade_df = build_trade_record_table()
    llm_df, usage_df = build_llm_label_tables(config, samples_df, label_df)
    provider_status_df = build_provider_status_table(config)

    with sqlite3.connect(db_path) as conn:
        ensure_database(conn)
        insert_dataframe(conn, "dataset_samples", samples_df)
        insert_dataframe(conn, "feature_snapshot", feature_df)
        insert_dataframe(conn, "label_snapshot", label_df)
        insert_dataframe(conn, "prediction_log", prediction_df)
        insert_dataframe(conn, "trade_records", trade_df)
        insert_dataframe(conn, "llm_label_snapshot", llm_df)
        insert_dataframe(conn, "llm_provider_status", provider_status_df)
        insert_dataframe(conn, "api_usage_log", usage_df)
        conn.commit()

        table_counts = {
            table_name: int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
            for table_name in TABLE_SCHEMAS
        }
        outputs = []

    split_path = build_time_series_split(samples_df, split_dir)
    outputs.append(split_path)
    outputs.append(str(db_path))
    outputs.append(str(QUALITY_REPORT_FILE))
    outputs.append(str(LABEL_REVIEW_QUEUE_FILE))

    write_dataset_quality_report(
        table_counts=table_counts,
        db_path=db_path,
        split_path=split_path,
        outputs=outputs,
        llm_enabled=bool(config.get("llm_labeling", {}).get("enabled", False)),
    )
    migration_summary = migrate_local_files_to_sqlite(db_path)

    print("v2.5 数据集已生成。")
    print(f"SQLite 数据库：{db_path}")
    print(f"质量报告：{QUALITY_REPORT_FILE}")
    print(f"样本数量：{table_counts.get('dataset_samples', 0)}")
    print(f"标签数量：{table_counts.get('label_snapshot', 0)}")
    print(f"真实交易记录数量：{table_counts.get('trade_records', 0)}")

    return {
        "database": str(db_path),
        "quality_report": str(QUALITY_REPORT_FILE),
        "outputs": outputs,
        "counts": table_counts,
        "migration": migration_summary,
    }


if __name__ == "__main__":
    build_dataset()
