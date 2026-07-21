# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import pickle
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from common import normalize_code, safe_float
from direction_model import metric_text, now_text
from probability_model import (
    DATABASE_FILE,
    MODEL_FILE as PROFIT_MODEL_FILE,
    MODEL_VERSION as PROFIT_MODEL_VERSION,
    PREDICTION_FILE as PROFIT_PREDICTION_FILE,
    TARGETS,
    prepare_features,
    read_prediction_frame,
)

try:
    from sklearn.metrics import brier_score_loss
except Exception:
    brier_score_loss = None


CALIBRATION_REPORT_FILE = Path("output/probability_calibration_v2.8.md")
CALIBRATED_PREDICTION_FILE = Path("output/calibrated_probabilities_v2.8.csv")
EXPLANATION_FILE = Path("output/model_explanations_v2.8.csv")
CALIBRATION_FILE = Path("data/models/probability_calibration_v2.8.json")

MODEL_VERSION = "v2.8-calibration-explain-001"


def ensure_calibration_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS probability_calibration_curves (
            calibration_id TEXT PRIMARY KEY,
            model_version TEXT,
            source_model_version TEXT,
            target_field TEXT,
            bucket TEXT,
            sample_count INTEGER,
            predicted_mean REAL,
            observed_rate REAL,
            calibrated_probability REAL,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_explanations (
            explanation_id TEXT PRIMARY KEY,
            sample_id TEXT,
            stock_code TEXT,
            stock_name TEXT,
            predict_date TEXT,
            model_version TEXT,
            source_model_version TEXT,
            top_positive_factors TEXT,
            top_negative_factors TEXT,
            explanation_method TEXT,
            created_at TEXT
        )
    """)
    conn.commit()


def read_probability_predictions(path: Path = PROFIT_PREDICTION_FILE) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    return pd.read_csv(path, dtype={"stock_code": str})


def read_probability_labels(db_path: Path = DATABASE_FILE) -> pd.DataFrame:
    if not db_path.exists():
        return pd.DataFrame()

    query = """
        SELECT
            sample_id,
            hit_1pct_after_touch,
            hit_2pct_after_touch,
            stop_2pct_after_touch
        FROM label_snapshot
    """

    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(query, conn)


def calibration_bucket(probability: float) -> str:
    p = max(0.0, min(1.0, safe_float(probability, 0.0)))
    lower = min(int(p * 5) * 20, 80)
    upper = lower + 20
    return f"{lower}-{upper}%"


def build_calibration_table(prediction_df: pd.DataFrame, label_df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    if prediction_df.empty or label_df.empty:
        return pd.DataFrame(), {}

    merged = prediction_df.merge(label_df, on="sample_id", how="inner")
    rows = []
    summary: dict[str, Any] = {}
    created_at = now_text()

    for target, spec in TARGETS.items():
        prob_col = spec["probability_column"]
        if target not in merged.columns or prob_col not in merged.columns:
            continue

        work = merged[["sample_id", prob_col, target]].copy()
        work[prob_col] = pd.to_numeric(work[prob_col], errors="coerce")
        work[target] = pd.to_numeric(work[target], errors="coerce")
        work = work.dropna(subset=[prob_col, target])

        if work.empty:
            continue

        work["bucket"] = work[prob_col].apply(calibration_bucket)
        target_summary: dict[str, Any] = {
            "count": int(len(work)),
            "raw_brier": calculate_brier(work[target], work[prob_col]),
            "global_observed_rate": round(float(work[target].mean()), 6),
            "buckets": {},
        }

        for bucket, group in work.groupby("bucket", sort=True):
            predicted_mean = round(float(group[prob_col].mean()), 6)
            observed_rate = round(float(group[target].mean()), 6)
            rows.append({
                "calibration_id": f"{MODEL_VERSION}_{target}_{bucket}",
                "model_version": MODEL_VERSION,
                "source_model_version": PROFIT_MODEL_VERSION,
                "target_field": target,
                "bucket": bucket,
                "sample_count": int(len(group)),
                "predicted_mean": predicted_mean,
                "observed_rate": observed_rate,
                "calibrated_probability": observed_rate,
                "created_at": created_at,
            })
            target_summary["buckets"][bucket] = observed_rate

        calibrated = work["bucket"].map(target_summary["buckets"]).fillna(target_summary["global_observed_rate"])
        target_summary["calibrated_brier"] = calculate_brier(work[target], calibrated)
        summary[target] = target_summary

    return pd.DataFrame(rows), summary


def calculate_brier(labels: pd.Series, probabilities: pd.Series) -> float | None:
    y = pd.to_numeric(labels, errors="coerce")
    p = pd.to_numeric(probabilities, errors="coerce")
    valid = pd.DataFrame({"y": y, "p": p}).dropna()

    if valid.empty:
        return None

    if brier_score_loss is not None:
        return round(float(brier_score_loss(valid["y"], valid["p"])), 6)

    return round(float(((valid["p"] - valid["y"]) ** 2).mean()), 6)


def apply_calibration(prediction_df: pd.DataFrame, summary: dict[str, Any]) -> pd.DataFrame:
    if prediction_df.empty:
        return prediction_df

    calibrated = prediction_df.copy()

    for target, spec in TARGETS.items():
        prob_col = spec["probability_column"]
        output_col = f"calibrated_{prob_col}"
        target_summary = summary.get(target, {})

        if prob_col not in calibrated.columns:
            continue

        buckets = target_summary.get("buckets", {})
        global_rate = safe_float(target_summary.get("global_observed_rate", 0.5), 0.5)
        calibrated[output_col] = calibrated[prob_col].apply(
            lambda value: buckets.get(calibration_bucket(value), global_rate)
        )

    if "calibrated_hit_1pct_probability" in calibrated.columns and "calibrated_stop_2pct_probability" in calibrated.columns:
        calibrated["calibrated_risk_adjusted_1pct"] = (
            pd.to_numeric(calibrated["calibrated_hit_1pct_probability"], errors="coerce")
            - pd.to_numeric(calibrated["calibrated_stop_2pct_probability"], errors="coerce")
        ).round(6)

    if "calibrated_hit_2pct_probability" in calibrated.columns and "calibrated_stop_2pct_probability" in calibrated.columns:
        calibrated["calibrated_risk_adjusted_2pct"] = (
            pd.to_numeric(calibrated["calibrated_hit_2pct_probability"], errors="coerce")
            - pd.to_numeric(calibrated["calibrated_stop_2pct_probability"], errors="coerce")
        ).round(6)

    calibrated["calibration_model_version"] = MODEL_VERSION
    calibrated["calibrated_at"] = now_text()
    return calibrated


def load_profit_model_artifact() -> dict[str, Any]:
    if not PROFIT_MODEL_FILE.exists():
        return {}

    return pickle.loads(PROFIT_MODEL_FILE.read_bytes())


def feature_importance_for_target(model: Any, feature_columns: list[str]) -> dict[str, float]:
    if not feature_columns:
        return {}

    values = getattr(model, "feature_importances_", None)
    if values is None:
        return {}

    total = sum(abs(float(value)) for value in values) or 1.0
    return {
        feature: round(abs(float(value)) / total, 8)
        for feature, value in zip(feature_columns, values)
        if abs(float(value)) > 0
    }


def explain_prediction_rows(prediction_df: pd.DataFrame, artifact: dict[str, Any]) -> pd.DataFrame:
    if prediction_df.empty:
        return pd.DataFrame()

    source_df = read_prediction_frame(DATABASE_FILE)
    if source_df.empty:
        return pd.DataFrame()

    latest_source = source_df.sort_values(["predict_date", "sample_id"]).drop_duplicates("stock_code", keep="last")
    merged = prediction_df.merge(
        latest_source,
        on=["sample_id", "stock_code"],
        how="left",
        suffixes=("", "_feature"),
    )
    created_at = now_text()
    rows = []

    target = "hit_1pct_after_touch"
    model = artifact.get("models", {}).get(target)
    feature_columns = artifact.get("feature_columns", {}).get(target, [])
    importance = feature_importance_for_target(model, feature_columns)

    if importance:
        features, _ = prepare_features(merged, feature_columns)
        medians = features.median(numeric_only=True).fillna(0)
        method = "feature_importance_deviation"
    else:
        features = pd.DataFrame(index=merged.index)
        medians = pd.Series(dtype=float)
        method = "baseline_summary"

    for idx, row in merged.iterrows():
        if importance and idx in features.index:
            contributions = {}
            for feature, weight in importance.items():
                value = safe_float(features.loc[idx, feature], 0)
                baseline = safe_float(medians.get(feature, 0), 0)
                contributions[feature] = (value - baseline) * weight
            positive = top_factor_text(contributions, reverse=True)
            negative = top_factor_text(contributions, reverse=False)
        else:
            positive = "样本不足或基准模型：暂无稳定正贡献因子"
            negative = "样本不足或基准模型：暂无稳定负贡献因子"

        rows.append({
            "explanation_id": f"{MODEL_VERSION}_{row.get('sample_id', idx)}",
            "sample_id": str(row.get("sample_id", "")),
            "stock_code": normalize_code(row.get("stock_code", "")),
            "stock_name": str(row.get("stock_name", "")),
            "predict_date": str(row.get("predict_date", ""))[:10],
            "model_version": MODEL_VERSION,
            "source_model_version": str(row.get("model_version", PROFIT_MODEL_VERSION)),
            "top_positive_factors": positive,
            "top_negative_factors": negative,
            "explanation_method": method,
            "created_at": created_at,
        })

    return pd.DataFrame(rows)


def top_factor_text(contributions: dict[str, float], *, reverse: bool) -> str:
    filtered = {
        key: value
        for key, value in contributions.items()
        if (value > 0 if reverse else value < 0)
    }

    if not filtered:
        return "暂无明显因子"

    ordered = sorted(filtered.items(), key=lambda item: item[1], reverse=reverse)[:5]
    return "；".join([f"{name}:{value:.4f}" for name, value in ordered])


def write_calibration_report(calibration_df: pd.DataFrame, summary: dict[str, Any], explanation_df: pd.DataFrame) -> None:
    CALIBRATION_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# v2.8 概率校准与模型解释报告",
        "",
        f"生成时间：{now_text()}",
        f"校准版本：`{MODEL_VERSION}`",
        f"来源模型：`{PROFIT_MODEL_VERSION}`",
        "",
        "## 一、校准前后 Brier Score",
        "",
        "| 目标 | 样本数 | 原始 Brier | 校准后 Brier | 样本实际正例率 |",
        "|---|---:|---:|---:|---:|",
    ]

    for target, item in summary.items():
        lines.append(
            f"| {TARGETS[target]['name']} | {item.get('count', 0)} | "
            f"{metric_text(item.get('raw_brier'))} | "
            f"{metric_text(item.get('calibrated_brier'))} | "
            f"{safe_float(item.get('global_observed_rate', 0)):.2%} |"
        )

    lines.extend([
        "",
        "## 二、校准曲线",
        "",
        "| 目标 | 概率桶 | 样本数 | 平均预测概率 | 实际发生率 | 校准概率 |",
        "|---|---|---:|---:|---:|---:|",
    ])

    for _, row in calibration_df.iterrows():
        lines.append(
            f"| {TARGETS.get(row['target_field'], {}).get('name', row['target_field'])} | "
            f"{row['bucket']} | {int(row['sample_count'])} | "
            f"{safe_float(row['predicted_mean']):.2%} | "
            f"{safe_float(row['observed_rate']):.2%} | "
            f"{safe_float(row['calibrated_probability']):.2%} |"
        )

    lines.extend([
        "",
        "## 三、解释输出",
        "",
        f"- 解释样本数：{len(explanation_df)}",
        "- 当前优先使用模型特征重要性 + 单样本特征偏离生成多空摘要。",
        "- 如果模型退回基准概率，解释会明确标记为样本不足，不伪造 SHAP。",
        "- 后续样本量充足并引入 `shap` 依赖后，可替换为 TreeExplainer。",
    ])

    CALIBRATION_REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_calibration_tables(conn: sqlite3.Connection, calibration_df: pd.DataFrame, explanation_df: pd.DataFrame) -> None:
    ensure_calibration_tables(conn)
    if calibration_df.empty:
        conn.execute("DELETE FROM probability_calibration_curves")
    else:
        calibration_df.to_sql("probability_calibration_curves", conn, if_exists="replace", index=False)

    if explanation_df.empty:
        conn.execute("DELETE FROM model_explanations")
    else:
        explanation_df.to_sql("model_explanations", conn, if_exists="replace", index=False)

    conn.commit()


def run_calibration_and_explain() -> dict[str, Any]:
    prediction_df = read_probability_predictions()
    label_df = read_probability_labels()

    if prediction_df.empty:
        raise RuntimeError("v2.7 概率预测为空，请先运行 `python main.py probability-predict`。")

    calibration_df, summary = build_calibration_table(prediction_df, label_df)
    calibrated_df = apply_calibration(prediction_df, summary)
    artifact = load_profit_model_artifact()
    explanation_df = explain_prediction_rows(prediction_df, artifact)

    CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    calibrated_df.to_csv(CALIBRATED_PREDICTION_FILE, index=False, encoding="utf-8-sig")
    explanation_df.to_csv(EXPLANATION_FILE, index=False, encoding="utf-8-sig")
    write_calibration_report(calibration_df, summary, explanation_df)

    with sqlite3.connect(DATABASE_FILE) as conn:
        write_calibration_tables(conn, calibration_df, explanation_df)

    print("v2.8 概率校准与模型解释已生成。")
    print(f"校准报告：{CALIBRATION_REPORT_FILE}")
    print(f"校准预测：{CALIBRATED_PREDICTION_FILE}")
    print(f"解释输出：{EXPLANATION_FILE}")

    return {
        "report": str(CALIBRATION_REPORT_FILE),
        "calibrated_predictions": str(CALIBRATED_PREDICTION_FILE),
        "explanations": str(EXPLANATION_FILE),
        "rows": len(calibrated_df),
    }


if __name__ == "__main__":
    run_calibration_and_explain()
