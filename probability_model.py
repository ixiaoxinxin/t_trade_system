# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import pickle
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from common import normalize_code, safe_float
from direction_model import (
    BaselineDirectionModel,
    CATEGORICAL_COLUMNS,
    chronological_split,
    metric_text,
    now_text,
    predict_probability,
    table_from_group_metrics,
    trainable_model,
)

try:
    from sklearn.metrics import accuracy_score, average_precision_score, brier_score_loss, roc_auc_score
except Exception:
    accuracy_score = None
    average_precision_score = None
    brier_score_loss = None
    roc_auc_score = None


DATABASE_FILE = Path("data/dataset/trade_dataset.sqlite3")
MODEL_DIR = Path("data/models")
MODEL_FILE = MODEL_DIR / "profit_probability_model_v2.7.pkl"
FEATURE_FILE = MODEL_DIR / "profit_probability_model_v2.7_features.json"
EVALUATION_REPORT_FILE = Path("output/profit_probability_evaluation_v2.7.md")
PREDICTION_FILE = Path("output/profit_probabilities_v2.7.csv")

MODEL_VERSION = "v2.7-profit-probability-001"

TARGETS = {
    "hit_1pct_after_touch": {
        "name": "触达后达到+1%",
        "probability_column": "hit_1pct_probability",
        "direction_column": "hit_1pct_signal",
    },
    "hit_2pct_after_touch": {
        "name": "触达后达到+2%",
        "probability_column": "hit_2pct_probability",
        "direction_column": "hit_2pct_signal",
    },
    "stop_2pct_after_touch": {
        "name": "触达后触发-2%止损",
        "probability_column": "stop_2pct_probability",
        "direction_column": "stop_2pct_signal",
    },
}

IDENTITY_COLUMNS = [
    "sample_id",
    "stock_code",
    "stock_name",
    "predict_date",
    "feature_date",
    "target_date",
    "rule_version",
    *TARGETS.keys(),
]


def ensure_probability_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profit_probability_training_runs (
            model_version TEXT PRIMARY KEY,
            algorithm_json TEXT,
            target_fields_json TEXT,
            train_count INTEGER,
            validation_count INTEGER,
            test_count INTEGER,
            metrics_json TEXT,
            feature_columns_json TEXT,
            model_path TEXT,
            report_path TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profit_probability_predictions (
            prediction_id TEXT PRIMARY KEY,
            sample_id TEXT,
            stock_code TEXT,
            stock_name TEXT,
            predict_date TEXT,
            model_version TEXT,
            hit_1pct_probability REAL,
            hit_2pct_probability REAL,
            stop_2pct_probability REAL,
            risk_adjusted_1pct REAL,
            risk_adjusted_2pct REAL,
            probability_risk_reward REAL,
            final_probability_signal TEXT,
            rule_version TEXT,
            market_regime TEXT,
            sector_name TEXT,
            created_at TEXT
        )
    """)
    conn.commit()


def read_training_frame(db_path: Path = DATABASE_FILE) -> pd.DataFrame:
    if not db_path.exists():
        return pd.DataFrame()

    query = """
        SELECT
            s.sample_id,
            s.stock_code,
            s.stock_name,
            s.predict_date,
            s.feature_date,
            s.target_date,
            s.rule_version,
            f.*,
            l.hit_1pct_after_touch,
            l.hit_2pct_after_touch,
            l.stop_2pct_after_touch
        FROM dataset_samples s
        JOIN feature_snapshot f ON s.sample_id = f.sample_id
        JOIN label_snapshot l ON s.sample_id = l.sample_id
    """

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(query, conn)

    return df.loc[:, ~df.columns.duplicated()].copy()


def read_prediction_frame(db_path: Path = DATABASE_FILE) -> pd.DataFrame:
    if not db_path.exists():
        return pd.DataFrame()

    query = """
        SELECT
            s.sample_id,
            s.stock_code,
            s.stock_name,
            s.predict_date,
            s.feature_date,
            s.target_date,
            s.rule_version,
            f.*
        FROM dataset_samples s
        JOIN feature_snapshot f ON s.sample_id = f.sample_id
    """

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(query, conn)

    return df.loc[:, ~df.columns.duplicated()].copy()


def prepare_features(df: pd.DataFrame, feature_columns: list[str] | None = None) -> tuple[pd.DataFrame, list[str]]:
    if df.empty:
        return pd.DataFrame(), feature_columns or []

    work = df.copy()
    work = work.drop(columns=[col for col in IDENTITY_COLUMNS if col in work.columns], errors="ignore")
    work = work.loc[:, ~work.columns.duplicated()]

    categorical = [col for col in CATEGORICAL_COLUMNS if col in work.columns]
    numeric = [col for col in work.columns if col not in categorical]

    for col in numeric:
        work[col] = pd.to_numeric(work[col], errors="coerce")

    encoded = pd.get_dummies(work, columns=categorical, dummy_na=True)
    encoded = encoded.apply(pd.to_numeric, errors="coerce")

    if feature_columns is None:
        feature_columns = list(encoded.columns)
    else:
        for col in feature_columns:
            if col not in encoded.columns:
                encoded[col] = 0
        encoded = encoded[feature_columns]

    encoded = encoded.fillna(encoded.median(numeric_only=True)).fillna(0)
    return encoded, feature_columns


def evaluate_target(
    target: str,
    split_name: str,
    frame: pd.DataFrame,
    model: Any,
    feature_columns: list[str],
) -> dict[str, Any]:
    if frame.empty or target not in frame.columns:
        return {"target": target, "split": split_name, "count": 0}

    work = frame.dropna(subset=[target]).copy()
    if work.empty:
        return {"target": target, "split": split_name, "count": 0}

    x, _ = prepare_features(work, feature_columns)
    y = pd.to_numeric(work[target], errors="coerce").fillna(0).astype(int)
    prob = predict_probability(model, x)
    pred = [1 if value >= 0.5 else 0 for value in prob]

    metrics: dict[str, Any] = {
        "target": target,
        "split": split_name,
        "count": len(work),
        "positive_rate": round(float(y.mean()), 4) if len(y) else 0,
    }

    if accuracy_score is not None:
        metrics["accuracy"] = round(float(accuracy_score(y, pred)), 4)

    if brier_score_loss is not None:
        metrics["brier_score"] = round(float(brier_score_loss(y, prob)), 4)

    if y.nunique(dropna=True) >= 2:
        if roc_auc_score is not None:
            metrics["auc"] = round(float(roc_auc_score(y, prob)), 4)
        if average_precision_score is not None:
            metrics["pr_auc"] = round(float(average_precision_score(y, prob)), 4)
    else:
        metrics["auc"] = None
        metrics["pr_auc"] = None

    detail = work[["market_regime", "sector_name"]].copy() if "market_regime" in work.columns else pd.DataFrame(index=work.index)
    detail["label"] = y.values
    detail["pred"] = pred

    if "market_regime" in detail.columns:
        metrics["by_market_regime"] = table_from_group_metrics_for_rows(detail, "market_regime")

    if "sector_name" in detail.columns:
        metrics["by_sector"] = table_from_group_metrics_for_rows(detail, "sector_name")

    return metrics


def table_from_group_metrics_for_rows(df: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    rows = []

    if df.empty or column not in df.columns:
        return rows

    for value, group in df.groupby(column, dropna=False):
        rows.append({
            column: str(value) if str(value).strip() else "未标记",
            "count": int(len(group)),
            "accuracy": round(float((group["label"] == group["pred"]).mean()), 4),
        })

    return sorted(rows, key=lambda item: item["count"], reverse=True)


def train_one_target(target: str, split_frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    train_df = split_frames.get("train", pd.DataFrame()).dropna(subset=[target]).copy()

    if train_df.empty:
        all_frames = pd.concat([frame for frame in split_frames.values() if not frame.empty], ignore_index=True)
        train_df = all_frames.dropna(subset=[target]).copy()

    if train_df.empty:
        model = BaselineDirectionModel(0.5)
        return {
            "model": model,
            "algorithm": "baseline_probability_empty",
            "feature_columns": [],
            "metrics": {name: {"target": target, "split": name, "count": 0} for name in split_frames},
        }

    x_train, feature_columns = prepare_features(train_df)
    y_train = pd.to_numeric(train_df[target], errors="coerce").fillna(0).astype(int)
    model, algorithm = trainable_model(y_train)
    model.fit(x_train, y_train)

    metrics = {
        split_name: evaluate_target(target, split_name, frame, model, feature_columns)
        for split_name, frame in split_frames.items()
    }

    return {
        "model": model,
        "algorithm": algorithm,
        "feature_columns": feature_columns,
        "metrics": metrics,
    }


def probability_signal(p1: float, p2: float, p_stop: float) -> str:
    if p_stop >= 0.55 and p_stop > p1:
        return "风险优先"
    if p2 >= 0.55 and p_stop <= 0.35:
        return "进攻"
    if p1 >= 0.55 and p_stop <= 0.45:
        return "偏多"
    if p1 < 0.45 and p_stop >= 0.45:
        return "放弃"
    return "观察"


def probability_risk_reward(p1: float, p2: float, p_stop: float) -> float:
    expected_gain = p1 * 0.01 + p2 * 0.01
    expected_loss = max(p_stop * 0.02, 0.0001)
    return expected_gain / expected_loss


def build_prediction_rows(df: pd.DataFrame, probabilities: dict[str, list[float]]) -> pd.DataFrame:
    rows = []
    created_at = now_text()

    for idx, row in df.reset_index(drop=True).iterrows():
        code = normalize_code(row.get("stock_code", ""))
        p1 = safe_float(probabilities.get("hit_1pct_after_touch", [0.5] * len(df))[idx], 0.5)
        p2 = safe_float(probabilities.get("hit_2pct_after_touch", [0.5] * len(df))[idx], 0.5)
        p_stop = safe_float(probabilities.get("stop_2pct_after_touch", [0.5] * len(df))[idx], 0.5)

        rows.append({
            "prediction_id": f"{MODEL_VERSION}_{row.get('sample_id', code)}",
            "sample_id": str(row.get("sample_id", "")),
            "stock_code": code,
            "stock_name": str(row.get("stock_name", "")),
            "predict_date": str(row.get("predict_date", ""))[:10],
            "model_version": MODEL_VERSION,
            "hit_1pct_probability": round(p1, 6),
            "hit_2pct_probability": round(p2, 6),
            "stop_2pct_probability": round(p_stop, 6),
            "risk_adjusted_1pct": round(p1 - p_stop, 6),
            "risk_adjusted_2pct": round(p2 - p_stop, 6),
            "probability_risk_reward": round(probability_risk_reward(p1, p2, p_stop), 6),
            "final_probability_signal": probability_signal(p1, p2, p_stop),
            "rule_version": str(row.get("rule_version", "")),
            "market_regime": str(row.get("market_regime", "")),
            "sector_name": str(row.get("sector_name", "")),
            "created_at": created_at,
        })

    return pd.DataFrame(rows)


def write_evaluation_report(results: dict[str, dict[str, Any]]) -> None:
    EVALUATION_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# v2.7 +1%/+2% 概率模型评估报告",
        "",
        f"生成时间：{now_text()}",
        f"模型版本：`{MODEL_VERSION}`",
        f"模型文件：`{MODEL_FILE}`",
        "",
        "## 一、总体指标",
        "",
        "| 目标 | 数据集 | 样本数 | 正样本率 | AUC | PR-AUC | Brier | 准确率 | 算法 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]

    for target, result in results.items():
        for split_name in ["train", "validation", "test"]:
            item = result["metrics"].get(split_name, {})
            lines.append(
                f"| {TARGETS[target]['name']} | {split_name} | {item.get('count', 0)} | "
                f"{safe_float(item.get('positive_rate', 0)):.2%} | "
                f"{metric_text(item.get('auc'))} | "
                f"{metric_text(item.get('pr_auc'))} | "
                f"{metric_text(item.get('brier_score'))} | "
                f"{metric_text(item.get('accuracy'))} | "
                f"`{result.get('algorithm', '')}` |"
            )

    lines.extend([
        "",
        "## 二、测试集分市场表现",
        "",
    ])

    for target, result in results.items():
        lines.extend([
            f"### {TARGETS[target]['name']}",
            "",
            table_from_group_metrics(result["metrics"].get("test", {}).get("by_market_regime", []), "market_regime"),
            "",
        ])

    lines.extend([
        "## 三、使用说明",
        "",
        "- v2.7 概率只辅助隔日T收益目标判断，不自动替代规则等级。",
        "- `risk_adjusted_1pct = 达到+1%概率 - 触发止损概率`。",
        "- `probability_risk_reward` 用概率期望收益除以概率期望亏损，数值越高代表概率收益风险比越好。",
        "- 样本不足或标签单一时自动退回基准概率模型，保证预测链路不断。",
    ])

    EVALUATION_REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_training_run(conn: sqlite3.Connection, results: dict[str, dict[str, Any]], split_frames: dict[str, pd.DataFrame]) -> None:
    algorithms = {target: result.get("algorithm", "") for target, result in results.items()}
    feature_columns = {target: result.get("feature_columns", []) for target, result in results.items()}
    metrics = {target: result.get("metrics", {}) for target, result in results.items()}

    conn.execute(
        """
        INSERT OR REPLACE INTO profit_probability_training_runs
        (model_version, algorithm_json, target_fields_json, train_count, validation_count, test_count,
         metrics_json, feature_columns_json, model_path, report_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            MODEL_VERSION,
            json.dumps(algorithms, ensure_ascii=False),
            json.dumps(list(TARGETS.keys()), ensure_ascii=False),
            len(split_frames.get("train", pd.DataFrame())),
            len(split_frames.get("validation", pd.DataFrame())),
            len(split_frames.get("test", pd.DataFrame())),
            json.dumps(metrics, ensure_ascii=False),
            json.dumps(feature_columns, ensure_ascii=False),
            str(MODEL_FILE),
            str(EVALUATION_REPORT_FILE),
            now_text(),
        ),
    )
    conn.commit()


def train_profit_probability_model() -> dict[str, Any]:
    df = read_training_frame(DATABASE_FILE)

    if df.empty:
        raise RuntimeError("训练数据为空，请先运行 `python main.py dataset`。")

    for target in TARGETS:
        df[target] = pd.to_numeric(df[target], errors="coerce")

    trainable_df = df.dropna(subset=list(TARGETS.keys()), how="all").copy()
    if trainable_df.empty:
        raise RuntimeError("v2.7 标签为空，请先生成次日验证和标签。")

    split_frames = chronological_split(trainable_df)
    results = {
        target: train_one_target(target, split_frames)
        for target in TARGETS
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    artifact = {
        "model_version": MODEL_VERSION,
        "targets": list(TARGETS.keys()),
        "models": {target: result["model"] for target, result in results.items()},
        "feature_columns": {target: result["feature_columns"] for target, result in results.items()},
        "created_at": now_text(),
    }
    MODEL_FILE.write_bytes(pickle.dumps(artifact))
    FEATURE_FILE.write_text(
        json.dumps(artifact["feature_columns"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    write_evaluation_report(results)

    with sqlite3.connect(DATABASE_FILE) as conn:
        ensure_probability_tables(conn)
        save_training_run(conn, results, split_frames)

    print("v2.7 +1%/+2% 概率模型训练完成。")
    print(f"模型文件：{MODEL_FILE}")
    print(f"评估报告：{EVALUATION_REPORT_FILE}")

    return {
        "model_version": MODEL_VERSION,
        "model_file": str(MODEL_FILE),
        "report": str(EVALUATION_REPORT_FILE),
        "targets": list(TARGETS.keys()),
    }


def load_model_artifact() -> dict[str, Any]:
    if not MODEL_FILE.exists():
        raise RuntimeError("v2.7 模型文件不存在，请先运行 `python main.py probability-train`。")

    return pickle.loads(MODEL_FILE.read_bytes())


def predict_profit_probabilities(stock_code: str | None = None) -> pd.DataFrame:
    artifact = load_model_artifact()
    df = read_prediction_frame(DATABASE_FILE)

    if df.empty:
        raise RuntimeError("预测样本为空，请先运行 `python main.py dataset`。")

    if stock_code:
        code = normalize_code(stock_code)
        df = df[df["stock_code"].apply(normalize_code).eq(code)].copy()

    if df.empty:
        raise RuntimeError(f"没有找到可预测样本：{stock_code}")

    df = df.sort_values(["predict_date", "sample_id"]).drop_duplicates("stock_code", keep="last")
    probabilities: dict[str, list[float]] = {}

    for target in TARGETS:
        model = artifact["models"].get(target)
        feature_columns = artifact["feature_columns"].get(target, [])
        features, _ = prepare_features(df, feature_columns)
        probabilities[target] = predict_probability(model, features) if model is not None else [0.5] * len(df)

    prediction_df = build_prediction_rows(df, probabilities)
    prediction_df = prediction_df.sort_values(
        ["risk_adjusted_1pct", "hit_1pct_probability"],
        ascending=[False, False],
    ).reset_index(drop=True)

    PREDICTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    prediction_df.to_csv(PREDICTION_FILE, index=False, encoding="utf-8-sig")

    with sqlite3.connect(DATABASE_FILE) as conn:
        ensure_probability_tables(conn)
        prediction_df.to_sql("profit_probability_predictions", conn, if_exists="replace", index=False)

    print("v2.7 收益目标概率预测已生成。")
    print(f"预测文件：{PREDICTION_FILE}")
    print(f"预测数量：{len(prediction_df)}")

    return prediction_df


def run_probability_train() -> dict[str, Any]:
    return train_profit_probability_model()


def run_probability_predict(stock_code: str | None = None) -> dict[str, Any]:
    df = predict_profit_probabilities(stock_code=stock_code)
    return {"rows": len(df), "output": str(PREDICTION_FILE)}


if __name__ == "__main__":
    train_profit_probability_model()
    predict_profit_probabilities()
