# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import pickle
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from common import PRODUCT_VERSION, normalize_code, safe_float


try:
    from lightgbm import LGBMClassifier
except Exception:
    LGBMClassifier = None

try:
    from sklearn.metrics import accuracy_score, average_precision_score, roc_auc_score
    from sklearn.model_selection import train_test_split
except Exception:
    accuracy_score = None
    average_precision_score = None
    roc_auc_score = None
    train_test_split = None


DATABASE_FILE = Path("data/dataset/trade_dataset.sqlite3")
SPLIT_FILE = Path("data/dataset/splits/latest.json")
MODEL_DIR = Path("data/models")
MODEL_FILE = MODEL_DIR / "direction_model_v2.6.joblib"
FEATURE_FILE = MODEL_DIR / "direction_model_v2.6_features.json"
EVALUATION_REPORT_FILE = Path("output/model_evaluation_v2.6.md")
PREDICTION_FILE = Path("output/model_predictions_v2.6.csv")

MODEL_VERSION = "v2.6-direction-001"
LABEL_FIELD = "direction_up_close"

IDENTITY_COLUMNS = [
    "sample_id",
    "stock_code",
    "stock_name",
    "predict_date",
    "feature_date",
    "target_date",
    "rule_version",
    LABEL_FIELD,
]

CATEGORICAL_COLUMNS = [
    "market_regime",
    "market_risk_level",
    "sector_name",
    "sector_status",
    "overnight_grade",
    "risk_level",
]


class BaselineDirectionModel:
    def __init__(self, positive_rate: float):
        self.positive_rate = max(0.0, min(1.0, float(positive_rate)))

    def fit(self, features: pd.DataFrame, target: pd.Series) -> "BaselineDirectionModel":
        if len(target):
            self.positive_rate = max(0.0, min(1.0, float(pd.to_numeric(target, errors="coerce").fillna(0).mean())))
        return self

    def predict_proba(self, features: pd.DataFrame) -> list[list[float]]:
        return [[1 - self.positive_rate, self.positive_rate] for _ in range(len(features))]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_model_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_training_runs (
            model_version TEXT PRIMARY KEY,
            algorithm TEXT,
            label_field TEXT,
            train_start TEXT,
            train_end TEXT,
            validation_start TEXT,
            validation_end TEXT,
            test_start TEXT,
            test_end TEXT,
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
        CREATE TABLE IF NOT EXISTS model_prediction_results (
            prediction_id TEXT PRIMARY KEY,
            sample_id TEXT,
            stock_code TEXT,
            stock_name TEXT,
            predict_date TEXT,
            model_version TEXT,
            next_day_up_probability REAL,
            direction_confidence REAL,
            predicted_direction TEXT,
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
            l.direction_up_close
        FROM dataset_samples s
        JOIN feature_snapshot f ON s.sample_id = f.sample_id
        JOIN label_snapshot l ON s.sample_id = l.sample_id
        WHERE l.direction_up_close IS NOT NULL
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


def load_split_ids(split_file: Path = SPLIT_FILE) -> dict[str, set[str]]:
    if not split_file.exists():
        return {"train": set(), "validation": set(), "test": set()}

    try:
        split = json.loads(split_file.read_text(encoding="utf-8"))
    except Exception:
        return {"train": set(), "validation": set(), "test": set()}

    return {
        "train": set(split.get("train", [])),
        "validation": set(split.get("validation", [])),
        "test": set(split.get("test", [])),
    }


def chronological_split(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if df.empty:
        return {"train": df, "validation": df, "test": df}

    split_ids = load_split_ids()

    if any(split_ids.values()):
        return {
            name: df[df["sample_id"].isin(ids)].copy()
            for name, ids in split_ids.items()
        }

    ordered = df.sort_values(["predict_date", "sample_id"]).reset_index(drop=True)
    n = len(ordered)
    train_end = max(1, int(n * 0.7))
    validation_end = max(train_end, int(n * 0.85))

    return {
        "train": ordered.iloc[:train_end].copy(),
        "validation": ordered.iloc[train_end:validation_end].copy(),
        "test": ordered.iloc[validation_end:].copy(),
    }


def prepare_features(
    df: pd.DataFrame,
    feature_columns: list[str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    if df.empty:
        return pd.DataFrame(), feature_columns or []

    work = df.copy()

    drop_cols = [col for col in IDENTITY_COLUMNS if col in work.columns]
    work = work.drop(columns=drop_cols, errors="ignore")
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


def trainable_model(y_train: pd.Series):
    positive_rate = float(y_train.mean()) if len(y_train) else 0.5

    if len(y_train) < 8 or y_train.nunique(dropna=True) < 2 or LGBMClassifier is None:
        return BaselineDirectionModel(positive_rate), "baseline_probability"

    return LGBMClassifier(
        objective="binary",
        n_estimators=80,
        learning_rate=0.05,
        num_leaves=15,
        min_child_samples=5,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1,
    ), "lightgbm"


def predict_probability(model: Any, features: pd.DataFrame) -> list[float]:
    if features.empty:
        return []

    probabilities = model.predict_proba(features)
    return [float(row[1]) for row in probabilities]


def evaluate_split(name: str, frame: pd.DataFrame, model: Any, feature_columns: list[str]) -> dict[str, Any]:
    if frame.empty:
        return {"split": name, "count": 0}

    x, _ = prepare_features(frame, feature_columns)
    y = pd.to_numeric(frame[LABEL_FIELD], errors="coerce").fillna(0).astype(int)
    prob = predict_probability(model, x)
    pred = [1 if value >= 0.5 else 0 for value in prob]

    metrics: dict[str, Any] = {
        "split": name,
        "count": len(frame),
        "positive_rate": round(float(y.mean()), 4) if len(y) else 0,
    }

    if accuracy_score is not None:
        metrics["accuracy"] = round(float(accuracy_score(y, pred)), 4)

    if y.nunique(dropna=True) >= 2:
        if roc_auc_score is not None:
            metrics["auc"] = round(float(roc_auc_score(y, prob)), 4)
        if average_precision_score is not None:
            metrics["pr_auc"] = round(float(average_precision_score(y, prob)), 4)
    else:
        metrics["auc"] = None
        metrics["pr_auc"] = None

    detail = frame[["market_regime", "sector_name"]].copy() if "market_regime" in frame.columns else pd.DataFrame(index=frame.index)
    detail["label"] = y.values
    detail["pred"] = pred

    if "market_regime" in detail.columns:
        metrics["by_market_regime"] = group_hit_rate(detail, "market_regime")

    if "sector_name" in detail.columns:
        metrics["by_sector"] = group_hit_rate(detail, "sector_name")

    return metrics


def group_hit_rate(df: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    if df.empty or column not in df.columns:
        return []

    rows = []
    for value, group in df.groupby(column, dropna=False):
        if len(group) == 0:
            continue
        rows.append({
            column: str(value) if str(value).strip() else "未标记",
            "count": int(len(group)),
            "accuracy": round(float((group["label"] == group["pred"]).mean()), 4),
        })

    return sorted(rows, key=lambda item: item["count"], reverse=True)


def date_range(frame: pd.DataFrame) -> tuple[str, str]:
    if frame.empty or "predict_date" not in frame.columns:
        return "", ""

    dates = pd.to_datetime(frame["predict_date"], errors="coerce").dropna()
    if dates.empty:
        return "", ""

    return str(dates.min().date()), str(dates.max().date())


def write_evaluation_report(
    metrics: dict[str, dict[str, Any]],
    *,
    algorithm: str,
    feature_columns: list[str],
    model_path: Path,
) -> None:
    EVALUATION_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# v2.6 次日涨跌方向模型评估报告",
        "",
        f"生成时间：{now_text()}",
        f"模型版本：`{MODEL_VERSION}`",
        f"算法：`{algorithm}`",
        f"标签：`{LABEL_FIELD}`",
        f"模型文件：`{model_path}`",
        "",
        "## 一、总体指标",
        "",
        "| 数据集 | 样本数 | 正样本率 | AUC | PR-AUC | 准确率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    for split_name in ["train", "validation", "test"]:
        item = metrics.get(split_name, {})
        lines.append(
            f"| {split_name} | {item.get('count', 0)} | "
            f"{safe_float(item.get('positive_rate', 0)):.2%} | "
            f"{metric_text(item.get('auc'))} | "
            f"{metric_text(item.get('pr_auc'))} | "
            f"{metric_text(item.get('accuracy'))} |"
        )

    lines.extend([
        "",
        "## 二、分市场环境命中率",
        "",
        table_from_group_metrics(metrics.get("test", {}).get("by_market_regime", []), "market_regime"),
        "",
        "## 三、分行业命中率",
        "",
        table_from_group_metrics(metrics.get("test", {}).get("by_sector", []), "sector_name"),
        "",
        "## 四、说明",
        "",
        "- v2.6 模型只输出次日上涨概率和方向置信度，不直接替代规则等级。",
        "- 样本不足、标签单一或 LightGBM 不可用时，系统会使用正样本率基准概率，保证页面和数据链路不断。",
        f"- 特征数量：{len(feature_columns)}。",
    ])

    EVALUATION_REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def metric_text(value: Any) -> str:
    if value is None or value == "":
        return "-"
    try:
        return f"{float(value):.4f}"
    except Exception:
        return "-"


def table_from_group_metrics(rows: list[dict[str, Any]], column: str) -> str:
    if not rows:
        return "暂无可统计数据。"

    header_name = "市场环境" if column == "market_regime" else "行业/板块"
    lines = [
        f"| {header_name} | 样本数 | 命中率 |",
        "|---|---:|---:|",
    ]

    for row in rows[:20]:
        lines.append(f"| {row.get(column, '未标记')} | {row.get('count', 0)} | {safe_float(row.get('accuracy', 0)):.2%} |")

    return "\n".join(lines)


def save_training_run(
    conn: sqlite3.Connection,
    *,
    algorithm: str,
    split_frames: dict[str, pd.DataFrame],
    metrics: dict[str, dict[str, Any]],
    feature_columns: list[str],
) -> None:
    train_start, train_end = date_range(split_frames.get("train", pd.DataFrame()))
    validation_start, validation_end = date_range(split_frames.get("validation", pd.DataFrame()))
    test_start, test_end = date_range(split_frames.get("test", pd.DataFrame()))

    conn.execute(
        """
        INSERT OR REPLACE INTO model_training_runs
        (model_version, algorithm, label_field, train_start, train_end, validation_start, validation_end,
         test_start, test_end, train_count, validation_count, test_count, metrics_json, feature_columns_json,
         model_path, report_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            MODEL_VERSION,
            algorithm,
            LABEL_FIELD,
            train_start,
            train_end,
            validation_start,
            validation_end,
            test_start,
            test_end,
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


def train_direction_model() -> dict[str, Any]:
    df = read_training_frame(DATABASE_FILE)

    if df.empty:
        raise RuntimeError("训练数据为空，请先运行 `python main.py dataset` 并完成次日复盘标签。")

    df[LABEL_FIELD] = pd.to_numeric(df[LABEL_FIELD], errors="coerce")
    df = df.dropna(subset=[LABEL_FIELD]).copy()
    df[LABEL_FIELD] = df[LABEL_FIELD].astype(int)

    split_frames = chronological_split(df)
    train_df = split_frames["train"]

    if train_df.empty:
        train_df = df.copy()
        split_frames["train"] = train_df

    x_train, feature_columns = prepare_features(train_df)
    y_train = train_df[LABEL_FIELD].astype(int)
    model, algorithm = trainable_model(y_train)
    model.fit(x_train, y_train)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_FILE.write_bytes(pickle.dumps(model))
    FEATURE_FILE.write_text(json.dumps(feature_columns, ensure_ascii=False, indent=2), encoding="utf-8")

    metrics = {
        split_name: evaluate_split(split_name, frame, model, feature_columns)
        for split_name, frame in split_frames.items()
    }

    write_evaluation_report(
        metrics=metrics,
        algorithm=algorithm,
        feature_columns=feature_columns,
        model_path=MODEL_FILE,
    )

    with sqlite3.connect(DATABASE_FILE) as conn:
        ensure_model_tables(conn)
        save_training_run(
            conn,
            algorithm=algorithm,
            split_frames=split_frames,
            metrics=metrics,
            feature_columns=feature_columns,
        )

    print("v2.6 次日方向模型训练完成。")
    print(f"模型文件：{MODEL_FILE}")
    print(f"评估报告：{EVALUATION_REPORT_FILE}")

    return {
        "model_version": MODEL_VERSION,
        "algorithm": algorithm,
        "model_file": str(MODEL_FILE),
        "report": str(EVALUATION_REPORT_FILE),
        "metrics": metrics,
    }


def load_model_and_features() -> tuple[Any, list[str]]:
    if not MODEL_FILE.exists() or not FEATURE_FILE.exists():
        raise RuntimeError("模型文件不存在，请先运行 `python main.py model-train`。")

    model = pickle.loads(MODEL_FILE.read_bytes())
    feature_columns = json.loads(FEATURE_FILE.read_text(encoding="utf-8"))
    return model, feature_columns


def build_prediction_rows(df: pd.DataFrame, probabilities: list[float]) -> pd.DataFrame:
    rows = []
    created_at = now_text()

    for (_, row), probability in zip(df.iterrows(), probabilities):
        code = normalize_code(row.get("stock_code", ""))
        prediction_id = f"{MODEL_VERSION}_{row.get('sample_id', code)}"
        confidence = abs(probability - 0.5) * 2
        rows.append({
            "prediction_id": prediction_id,
            "sample_id": str(row.get("sample_id", "")),
            "stock_code": code,
            "stock_name": str(row.get("stock_name", "")),
            "predict_date": str(row.get("predict_date", ""))[:10],
            "model_version": MODEL_VERSION,
            "next_day_up_probability": round(probability, 6),
            "direction_confidence": round(confidence, 6),
            "predicted_direction": "上涨" if probability >= 0.5 else "下跌或震荡",
            "rule_version": str(row.get("rule_version", "")),
            "market_regime": str(row.get("market_regime", "")),
            "sector_name": str(row.get("sector_name", "")),
            "created_at": created_at,
        })

    return pd.DataFrame(rows)


def predict_direction(stock_code: str | None = None) -> pd.DataFrame:
    model, feature_columns = load_model_and_features()
    df = read_prediction_frame(DATABASE_FILE)

    if df.empty:
        raise RuntimeError("预测样本为空，请先运行 `python main.py dataset`。")

    if stock_code:
        code = normalize_code(stock_code)
        df = df[df["stock_code"].apply(normalize_code).eq(code)].copy()

    if df.empty:
        raise RuntimeError(f"没有找到可预测样本：{stock_code}")

    df = df.sort_values(["predict_date", "sample_id"]).drop_duplicates("stock_code", keep="last")
    features, _ = prepare_features(df, feature_columns)
    probabilities = predict_probability(model, features)
    prediction_df = build_prediction_rows(df, probabilities)
    prediction_df = prediction_df.sort_values("next_day_up_probability", ascending=False).reset_index(drop=True)

    PREDICTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    prediction_df.to_csv(PREDICTION_FILE, index=False, encoding="utf-8-sig")

    with sqlite3.connect(DATABASE_FILE) as conn:
        ensure_model_tables(conn)
        prediction_df.to_sql("model_prediction_results", conn, if_exists="replace", index=False)

    print("v2.6 次日方向预测已生成。")
    print(f"预测文件：{PREDICTION_FILE}")
    print(f"预测数量：{len(prediction_df)}")

    return prediction_df


def run_model_train() -> dict[str, Any]:
    return train_direction_model()


def run_model_predict(stock_code: str | None = None) -> dict[str, Any]:
    df = predict_direction(stock_code=stock_code)
    return {"rows": len(df), "output": str(PREDICTION_FILE)}


if __name__ == "__main__":
    train_direction_model()
    predict_direction()
