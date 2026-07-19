# -*- coding: utf-8 -*-

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from common import normalize_code, safe_float
from direction_model import PREDICTION_FILE as DIRECTION_PREDICTION_FILE
from direction_model import MODEL_VERSION as DIRECTION_MODEL_VERSION
from direction_model import metric_text, now_text
from model_calibration import CALIBRATED_PREDICTION_FILE
from model_calibration import MODEL_VERSION as CALIBRATION_MODEL_VERSION
from probability_model import MODEL_VERSION as PROFIT_MODEL_VERSION
from probability_model import PREDICTION_FILE as PROFIT_PREDICTION_FILE

DATABASE_FILE = Path("data/dataset/trade_dataset.sqlite3")
PREDICTION_REVIEW_FILE = Path("output/prediction_review_v2.9.csv")
MODEL_SCORECARD_FILE = Path("output/model_scorecard_v2.9.csv")
PREDICTION_REVIEW_REPORT_FILE = Path("output/prediction_review_v2.9.md")

MODEL_VERSION = "v2.9-prediction-review-001"


def ensure_review_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prediction_review_results (
            review_id TEXT PRIMARY KEY,
            sample_id TEXT,
            stock_code TEXT,
            stock_name TEXT,
            predict_date TEXT,
            target_date TEXT,
            direction_model_version TEXT,
            profit_model_version TEXT,
            calibration_model_version TEXT,
            next_day_up_probability REAL,
            hit_1pct_probability REAL,
            hit_2pct_probability REAL,
            stop_2pct_probability REAL,
            calibrated_hit_1pct_probability REAL,
            calibrated_hit_2pct_probability REAL,
            calibrated_stop_2pct_probability REAL,
            direction_up_close INTEGER,
            hit_1pct_after_touch INTEGER,
            hit_2pct_after_touch INTEGER,
            stop_2pct_after_touch INTEGER,
            direction_hit INTEGER,
            hit_1pct_bucket TEXT,
            hit_2pct_bucket TEXT,
            stop_2pct_bucket TEXT,
            market_regime TEXT,
            sector_name TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_scorecard (
            scorecard_id TEXT PRIMARY KEY,
            model_version TEXT,
            metric_name TEXT,
            segment_type TEXT,
            segment_value TEXT,
            sample_count INTEGER,
            score REAL,
            created_at TEXT
        )
    """)
    conn.commit()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    return pd.read_csv(path, dtype={"stock_code": str})


def read_labels(db_path: Path = DATABASE_FILE) -> pd.DataFrame:
    if not db_path.exists():
        return pd.DataFrame()

    query = """
        SELECT
            s.sample_id,
            s.stock_code,
            s.stock_name,
            s.predict_date,
            s.target_date,
            f.market_regime,
            f.sector_name,
            l.direction_up_close,
            l.hit_1pct_after_touch,
            l.hit_2pct_after_touch,
            l.stop_2pct_after_touch
        FROM dataset_samples s
        LEFT JOIN feature_snapshot f ON s.sample_id = f.sample_id
        LEFT JOIN label_snapshot l ON s.sample_id = l.sample_id
    """

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(query, conn)

    return df.loc[:, ~df.columns.duplicated()].copy()


def probability_bucket(value: Any) -> str:
    probability = max(0.0, min(1.0, safe_float(value, 0.0)))
    if probability < 0.2:
        return "0-20%"
    if probability < 0.4:
        return "20-40%"
    if probability < 0.6:
        return "40-60%"
    if probability < 0.8:
        return "60-80%"
    return "80-100%"


def build_review_frame(
    labels_df: pd.DataFrame,
    direction_df: pd.DataFrame,
    profit_df: pd.DataFrame,
    calibrated_df: pd.DataFrame,
) -> pd.DataFrame:
    if labels_df.empty:
        return pd.DataFrame()

    review = labels_df.copy()

    if not direction_df.empty:
        direction_cols = [
            "sample_id",
            "model_version",
            "next_day_up_probability",
        ]
        review = review.merge(
            direction_df[[col for col in direction_cols if col in direction_df.columns]].rename(columns={
                "model_version": "direction_model_version",
            }),
            on="sample_id",
            how="left",
        )

    if not profit_df.empty:
        profit_cols = [
            "sample_id",
            "model_version",
            "hit_1pct_probability",
            "hit_2pct_probability",
            "stop_2pct_probability",
        ]
        review = review.merge(
            profit_df[[col for col in profit_cols if col in profit_df.columns]].rename(columns={
                "model_version": "profit_model_version",
            }),
            on="sample_id",
            how="left",
        )

    if not calibrated_df.empty:
        calibrated_cols = [
            "sample_id",
            "calibration_model_version",
            "calibrated_hit_1pct_probability",
            "calibrated_hit_2pct_probability",
            "calibrated_stop_2pct_probability",
        ]
        review = review.merge(
            calibrated_df[[col for col in calibrated_cols if col in calibrated_df.columns]],
            on="sample_id",
            how="left",
        )

    for code_col in ["stock_code"]:
        if code_col in review.columns:
            review[code_col] = review[code_col].apply(normalize_code)

    for col in [
        "next_day_up_probability",
        "hit_1pct_probability",
        "hit_2pct_probability",
        "stop_2pct_probability",
        "calibrated_hit_1pct_probability",
        "calibrated_hit_2pct_probability",
        "calibrated_stop_2pct_probability",
        "direction_up_close",
        "hit_1pct_after_touch",
        "hit_2pct_after_touch",
        "stop_2pct_after_touch",
    ]:
        if col in review.columns:
            review[col] = pd.to_numeric(review[col], errors="coerce")

    review["direction_hit"] = (
        (review["next_day_up_probability"] >= 0.5).astype(float)
        == review["direction_up_close"].astype(float)
    ).astype(int)
    review.loc[review["next_day_up_probability"].isna() | review["direction_up_close"].isna(), "direction_hit"] = pd.NA

    review["hit_1pct_bucket"] = review["hit_1pct_probability"].apply(probability_bucket)
    review["hit_2pct_bucket"] = review["hit_2pct_probability"].apply(probability_bucket)
    review["stop_2pct_bucket"] = review["stop_2pct_probability"].apply(probability_bucket)
    review["direction_model_version"] = review.get("direction_model_version", "").fillna(DIRECTION_MODEL_VERSION)
    review["profit_model_version"] = review.get("profit_model_version", "").fillna(PROFIT_MODEL_VERSION)
    review["calibration_model_version"] = review.get("calibration_model_version", "").fillna(CALIBRATION_MODEL_VERSION)
    review["created_at"] = now_text()
    review["review_id"] = review["sample_id"].apply(lambda value: f"{MODEL_VERSION}_{value}")

    columns = [
        "review_id",
        "sample_id",
        "stock_code",
        "stock_name",
        "predict_date",
        "target_date",
        "direction_model_version",
        "profit_model_version",
        "calibration_model_version",
        "next_day_up_probability",
        "hit_1pct_probability",
        "hit_2pct_probability",
        "stop_2pct_probability",
        "calibrated_hit_1pct_probability",
        "calibrated_hit_2pct_probability",
        "calibrated_stop_2pct_probability",
        "direction_up_close",
        "hit_1pct_after_touch",
        "hit_2pct_after_touch",
        "stop_2pct_after_touch",
        "direction_hit",
        "hit_1pct_bucket",
        "hit_2pct_bucket",
        "stop_2pct_bucket",
        "market_regime",
        "sector_name",
        "created_at",
    ]
    return review[[col for col in columns if col in review.columns]].copy()


def mean_binary(df: pd.DataFrame, label_col: str) -> float | None:
    if df.empty or label_col not in df.columns:
        return None

    values = pd.to_numeric(df[label_col], errors="coerce").dropna()
    if values.empty:
        return None

    return round(float(values.mean()), 6)


def brier(df: pd.DataFrame, probability_col: str, label_col: str) -> float | None:
    if df.empty or probability_col not in df.columns or label_col not in df.columns:
        return None

    work = df[[probability_col, label_col]].apply(pd.to_numeric, errors="coerce").dropna()
    if work.empty:
        return None

    return round(float(((work[probability_col] - work[label_col]) ** 2).mean()), 6)


def append_score(rows: list[dict[str, Any]], model_version: str, metric_name: str, segment_type: str, segment_value: str, count: int, score: Any) -> None:
    rows.append({
        "scorecard_id": f"{MODEL_VERSION}_{model_version}_{metric_name}_{segment_type}_{segment_value}".replace(" ", "_"),
        "model_version": model_version,
        "metric_name": metric_name,
        "segment_type": segment_type,
        "segment_value": str(segment_value),
        "sample_count": int(count),
        "score": score,
        "created_at": now_text(),
    })


def build_scorecard(review_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    if review_df.empty:
        return pd.DataFrame()

    append_score(
        rows,
        DIRECTION_MODEL_VERSION,
        "direction_hit_rate",
        "all",
        "all",
        len(review_df),
        mean_binary(review_df, "direction_hit"),
    )

    for probability_col, label_col, version, metric_prefix in [
        ("hit_1pct_probability", "hit_1pct_after_touch", PROFIT_MODEL_VERSION, "hit_1pct"),
        ("hit_2pct_probability", "hit_2pct_after_touch", PROFIT_MODEL_VERSION, "hit_2pct"),
        ("stop_2pct_probability", "stop_2pct_after_touch", PROFIT_MODEL_VERSION, "stop_2pct"),
        ("calibrated_hit_1pct_probability", "hit_1pct_after_touch", CALIBRATION_MODEL_VERSION, "calibrated_hit_1pct"),
        ("calibrated_hit_2pct_probability", "hit_2pct_after_touch", CALIBRATION_MODEL_VERSION, "calibrated_hit_2pct"),
        ("calibrated_stop_2pct_probability", "stop_2pct_after_touch", CALIBRATION_MODEL_VERSION, "calibrated_stop_2pct"),
    ]:
        append_score(
            rows,
            version,
            f"{metric_prefix}_brier",
            "all",
            "all",
            len(review_df),
            brier(review_df, probability_col, label_col),
        )

    for segment_col, segment_type in [("market_regime", "market"), ("sector_name", "sector")]:
        if segment_col not in review_df.columns:
            continue
        for value, group in review_df.groupby(segment_col, dropna=False):
            segment_value = str(value) if str(value).strip() else "未标记"
            append_score(
                rows,
                DIRECTION_MODEL_VERSION,
                "direction_hit_rate",
                segment_type,
                segment_value,
                len(group),
                mean_binary(group, "direction_hit"),
            )
            append_score(
                rows,
                PROFIT_MODEL_VERSION,
                "hit_1pct_actual_rate",
                segment_type,
                segment_value,
                len(group),
                mean_binary(group, "hit_1pct_after_touch"),
            )

    for bucket_col, label_col, metric_name in [
        ("hit_1pct_bucket", "hit_1pct_after_touch", "hit_1pct_actual_rate_by_bucket"),
        ("hit_2pct_bucket", "hit_2pct_after_touch", "hit_2pct_actual_rate_by_bucket"),
        ("stop_2pct_bucket", "stop_2pct_after_touch", "stop_2pct_actual_rate_by_bucket"),
    ]:
        if bucket_col not in review_df.columns:
            continue
        for bucket, group in review_df.groupby(bucket_col, dropna=False):
            append_score(
                rows,
                PROFIT_MODEL_VERSION,
                metric_name,
                "probability_bucket",
                str(bucket),
                len(group),
                mean_binary(group, label_col),
            )

    return pd.DataFrame(rows)


def write_review_report(review_df: pd.DataFrame, scorecard_df: pd.DataFrame) -> None:
    PREDICTION_REVIEW_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# v2.9 预测回顾与模型评分报告",
        "",
        f"生成时间：{now_text()}",
        f"回顾版本：`{MODEL_VERSION}`",
        "",
        "## 一、总体回顾",
        "",
        f"- 回顾样本数：{len(review_df)}",
        f"- 方向命中率：{metric_text(mean_binary(review_df, 'direction_hit'))}",
        f"- +1% 实际发生率：{rate_text(mean_binary(review_df, 'hit_1pct_after_touch'))}",
        f"- +2% 实际发生率：{rate_text(mean_binary(review_df, 'hit_2pct_after_touch'))}",
        f"- 止损实际发生率：{rate_text(mean_binary(review_df, 'stop_2pct_after_touch'))}",
        "",
        "## 二、模型评分",
        "",
        "| 模型版本 | 指标 | 分组 | 分组值 | 样本数 | 分数 |",
        "|---|---|---|---|---:|---:|",
    ]

    for _, row in scorecard_df.head(80).iterrows():
        lines.append(
            f"| {row.get('model_version', '')} | {row.get('metric_name', '')} | "
            f"{row.get('segment_type', '')} | {row.get('segment_value', '')} | "
            f"{int(row.get('sample_count', 0))} | {metric_text(row.get('score'))} |"
        )

    lines.extend([
        "",
        "## 三、说明",
        "",
        "- v2.9 负责回顾和评分，不训练新模型。",
        "- 方向模型用方向命中率评分；概率模型用 Brier Score 和概率桶实际发生率评分。",
        "- 样本少时分行业/分市场指标只做观察，不能作为稳定结论。",
        "- 后续 v3.0 将读取本评分结果，辅助规则评分和模型概率融合。",
    ])

    PREDICTION_REVIEW_REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rate_text(value: Any) -> str:
    if value is None:
        return "-"
    return f"{safe_float(value):.2%}"


def run_prediction_review() -> dict[str, Any]:
    labels_df = read_labels()
    direction_df = read_csv(DIRECTION_PREDICTION_FILE)
    profit_df = read_csv(PROFIT_PREDICTION_FILE)
    calibrated_df = read_csv(CALIBRATED_PREDICTION_FILE)

    review_df = build_review_frame(labels_df, direction_df, profit_df, calibrated_df)
    scorecard_df = build_scorecard(review_df)

    PREDICTION_REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    review_df.to_csv(PREDICTION_REVIEW_FILE, index=False, encoding="utf-8-sig")
    scorecard_df.to_csv(MODEL_SCORECARD_FILE, index=False, encoding="utf-8-sig")
    write_review_report(review_df, scorecard_df)

    with sqlite3.connect(DATABASE_FILE) as conn:
        ensure_review_tables(conn)
        review_df.to_sql("prediction_review_results", conn, if_exists="replace", index=False)
        scorecard_df.to_sql("model_scorecard", conn, if_exists="replace", index=False)

    print("v2.9 预测回顾与模型评分已生成。")
    print(f"回顾明细：{PREDICTION_REVIEW_FILE}")
    print(f"模型评分：{MODEL_SCORECARD_FILE}")
    print(f"回顾报告：{PREDICTION_REVIEW_REPORT_FILE}")

    return {
        "review": str(PREDICTION_REVIEW_FILE),
        "scorecard": str(MODEL_SCORECARD_FILE),
        "report": str(PREDICTION_REVIEW_REPORT_FILE),
        "rows": len(review_df),
    }


if __name__ == "__main__":
    run_prediction_review()
