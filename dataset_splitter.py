# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pandas as pd


DATABASE_FILE = Path("data/dataset/trade_dataset.sqlite3")
SPLIT_DIR = Path("data/dataset/splits")


def date_range(values: pd.Series) -> dict:
    if values.empty:
        return {"start": "", "end": ""}

    return {
        "start": str(values.min())[:10],
        "end": str(values.max())[:10],
    }


def build_time_series_split(samples_df: pd.DataFrame, split_dir: Path = SPLIT_DIR) -> str:
    split_dir.mkdir(parents=True, exist_ok=True)
    output_path = split_dir / "latest.json"

    if samples_df.empty:
        split = {
            "method": "rolling_window_or_chronological",
            "train": [],
            "validation": [],
            "test": [],
            "date_ranges": {},
            "counts": {"total": 0, "train": 0, "validation": 0, "test": 0},
            "note": "样本为空，暂不能切分。",
        }
        output_path.write_text(json.dumps(split, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(output_path)

    ordered = samples_df.copy()
    ordered["predict_date_dt"] = pd.to_datetime(ordered["predict_date"], errors="coerce")
    ordered = ordered.dropna(subset=["predict_date_dt"]).sort_values(["predict_date_dt", "sample_id"]).reset_index(drop=True)

    if ordered.empty:
        split = {
            "method": "invalid_date",
            "train": [],
            "validation": [],
            "test": [],
            "date_ranges": {},
            "counts": {"total": 0, "train": 0, "validation": 0, "test": 0},
            "note": "样本日期无效，暂不能切分。",
        }
        output_path.write_text(json.dumps(split, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(output_path)

    max_date = ordered["predict_date_dt"].max()
    min_date = ordered["predict_date_dt"].min()
    span_days = int((max_date - min_date).days)

    if span_days >= 850:
        test_start = max_date - timedelta(days=30)
        validation_start = test_start - timedelta(days=90)
        train_start = validation_start - timedelta(days=730)
        train_df = ordered[(ordered["predict_date_dt"] >= train_start) & (ordered["predict_date_dt"] < validation_start)]
        validation_df = ordered[(ordered["predict_date_dt"] >= validation_start) & (ordered["predict_date_dt"] < test_start)]
        test_df = ordered[ordered["predict_date_dt"] >= test_start]
        method = "rolling_time_window"
        note = "训练2年、验证3个月、测试1个月，按时间向前滚动，不随机打乱。"
    else:
        n = len(ordered)
        train_end = max(1, int(n * 0.7))
        validation_end = max(train_end + 1, int(n * 0.85)) if n >= 3 else train_end
        validation_end = min(validation_end, n)
        train_df = ordered.iloc[:train_end]
        validation_df = ordered.iloc[train_end:validation_end]
        test_df = ordered.iloc[validation_end:]
        method = "chronological_fallback"
        note = "样本历史跨度不足850天，暂按预测日期70%/15%/15%切分，不随机打乱。"

    split = {
        "method": method,
        "train": train_df["sample_id"].tolist(),
        "validation": validation_df["sample_id"].tolist(),
        "test": test_df["sample_id"].tolist(),
        "date_ranges": {
            "all": date_range(ordered["predict_date_dt"]),
            "train": date_range(train_df["predict_date_dt"]),
            "validation": date_range(validation_df["predict_date_dt"]),
            "test": date_range(test_df["predict_date_dt"]),
        },
        "counts": {
            "total": int(len(ordered)),
            "train": int(len(train_df)),
            "validation": int(len(validation_df)),
            "test": int(len(test_df)),
        },
        "note": note,
    }

    output_path.write_text(json.dumps(split, ensure_ascii=False, indent=2), encoding="utf-8")

    return str(output_path)


def run_dataset_splitter() -> dict:
    if not DATABASE_FILE.exists():
        return {"success": False, "reason": f"missing {DATABASE_FILE}"}

    with sqlite3.connect(DATABASE_FILE) as conn:
        samples_df = pd.read_sql_query("SELECT * FROM dataset_samples", conn)

    split_path = build_time_series_split(samples_df)
    print(f"时间序列切分已生成：{split_path}")

    return {"success": True, "split_path": split_path, "rows": len(samples_df)}


if __name__ == "__main__":
    run_dataset_splitter()
