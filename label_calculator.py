# -*- coding: utf-8 -*-

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from common import PRODUCT_VERSION, normalize_code, safe_float


DATABASE_FILE = Path("data/dataset/trade_dataset.sqlite3")
NEXT_DAY_REVIEW_FILE = Path("output/next_day_review.csv")

LABEL_COLUMNS = [
    "sample_id",
    "stock_code",
    "predict_date",
    "target_date",
    "direction_up_close",
    "touch_buy_range",
    "hit_1pct_after_touch",
    "hit_2pct_after_touch",
    "stop_2pct_after_touch",
    "first_event",
    "next_day_high_pct",
    "next_day_low_pct",
    "realized_path_type",
    "execution_quality",
    "label_source",
]


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
    touch = label_bool(row, "是否触达低吸区间", "touch")
    hit_1 = label_bool(row, "是否达到1%", "hit_1pct")
    hit_2 = label_bool(row, "是否达到2%", "hit_2pct")
    stop = label_bool(row, "是否触发-2%止损", "stop_loss")

    if touch == 0:
        return "no_touch"

    if stop == 1 and (hit_1 == 1 or hit_2 == 1):
        return "ambiguous_ohlc_path"

    if stop == 1:
        return "stop_loss"

    if hit_2 == 1:
        return "hit_2pct"

    if hit_1 == 1:
        return "hit_1pct"

    return "no_event"


def execution_quality(row: pd.Series) -> str:
    touch = label_bool(row, "是否触达低吸区间", "touch")
    success = yes_no_to_int(row.get("是否验证成功"))
    stop_loss = label_bool(row, "是否触发-2%止损", "stop_loss")
    hit_1 = label_bool(row, "是否达到1%", "hit_1pct")
    hit_2 = label_bool(row, "是否达到2%", "hit_2pct")

    if touch == 0:
        return "未触达"

    if touch is None:
        return "数据不足"

    if stop_loss == 1 and (hit_1 == 1 or hit_2 == 1):
        return "需分时确认"

    if stop_loss == 1:
        return "可执行止损"

    if success == 1:
        return "可执行盈利"

    return "可执行失败"


def calc_touch_by_ohlc(row: pd.Series) -> int | None:
    buy_price = safe_float(row.get("买入参考价", 0))
    next_high = safe_float(row.get("次日最高", 0))
    next_low = safe_float(row.get("次日最低", 0))

    if buy_price <= 0 or next_high <= 0 or next_low <= 0:
        return None

    return int(next_low <= buy_price <= next_high)


def calc_target_by_ohlc(row: pd.Series, pct: float) -> int | None:
    touch = calc_touch_by_ohlc(row)
    buy_price = safe_float(row.get("买入参考价", 0))
    next_high = safe_float(row.get("次日最高", 0))

    if touch is None or buy_price <= 0 or next_high <= 0:
        return None

    if touch == 0:
        return 0

    return int(next_high >= buy_price * (1 + pct))


def calc_stop_by_ohlc(row: pd.Series) -> int | None:
    touch = calc_touch_by_ohlc(row)
    buy_price = safe_float(row.get("买入参考价", 0))
    next_low = safe_float(row.get("次日最低", 0))

    if touch is None or buy_price <= 0 or next_low <= 0:
        return None

    if touch == 0:
        return 0

    return int(next_low <= buy_price * 0.98)


def label_bool(row: pd.Series, source_field: str, calc_type: str) -> int | None:
    if calc_type == "touch":
        calculated = calc_touch_by_ohlc(row)
    elif calc_type == "hit_1pct":
        calculated = calc_target_by_ohlc(row, 0.01)
    elif calc_type == "hit_2pct":
        calculated = calc_target_by_ohlc(row, 0.02)
    elif calc_type == "stop_loss":
        calculated = calc_stop_by_ohlc(row)
    else:
        calculated = None

    if calculated is not None:
        return calculated

    return yes_no_to_int(row.get(source_field))


def calculate_label_snapshot(
    next_day_df: pd.DataFrame,
    rule_version: str | None = None,
) -> pd.DataFrame:
    rows = []
    version = rule_version or f"v{PRODUCT_VERSION}"

    for _, row in next_day_df.iterrows():
        data_status = str(row.get("数据状态", "ready") or "ready")
        if data_status not in ["", "ready"]:
            continue

        code = normalize_code(row.get("股票代码", ""))
        predict_date = str(row.get("验证日期", ""))[:10]

        if not predict_date:
            predict_date = str(row.get("预测日期", ""))[:10]

        if not code or not predict_date:
            continue

        close_pct = safe_float(row.get("次日收盘涨幅", 0))

        rows.append({
            "sample_id": sample_id(code, predict_date, version),
            "stock_code": code,
            "predict_date": predict_date,
            "target_date": str(row.get("次日日期", ""))[:10],
            "direction_up_close": int(close_pct > 0),
            "touch_buy_range": label_bool(row, "是否触达低吸区间", "touch"),
            "hit_1pct_after_touch": label_bool(row, "是否达到1%", "hit_1pct"),
            "hit_2pct_after_touch": label_bool(row, "是否达到2%", "hit_2pct"),
            "stop_2pct_after_touch": label_bool(row, "是否触发-2%止损", "stop_loss"),
            "first_event": first_event(row),
            "next_day_high_pct": safe_float(row.get("次日最高涨幅", 0)),
            "next_day_low_pct": safe_float(row.get("次日最低涨幅", 0)),
            "realized_path_type": str(row.get("分时结构标签", "")),
            "execution_quality": execution_quality(row),
            "label_source": "next_day_review",
        })

    return pd.DataFrame(rows, columns=LABEL_COLUMNS)


def run_label_calculator() -> dict:
    if not NEXT_DAY_REVIEW_FILE.exists():
        return {"success": False, "reason": f"missing {NEXT_DAY_REVIEW_FILE}"}

    next_day_df = pd.read_csv(NEXT_DAY_REVIEW_FILE, dtype={"股票代码": str})
    label_df = calculate_label_snapshot(next_day_df)
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DATABASE_FILE) as conn:
        label_df.to_sql("label_snapshot", conn, if_exists="replace", index=False)

    print(f"标签已写入 SQLite：label_snapshot，记录数：{len(label_df)}")

    return {"success": True, "rows": len(label_df), "database": str(DATABASE_FILE)}


if __name__ == "__main__":
    run_label_calculator()
