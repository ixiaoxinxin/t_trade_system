# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


DATABASE_FILE = Path("data/dataset/trade_dataset.sqlite3")
QUALITY_REPORT_FILE = Path("output/dataset_quality_report.md")
LABEL_REVIEW_QUEUE_FILE = Path("output/label_review_queue.md")

REQUIRED_LABEL_FIELDS = [
    "direction_up_close",
    "touch_buy_range",
    "hit_1pct_after_touch",
    "hit_2pct_after_touch",
    "stop_2pct_after_touch",
    "first_event",
    "execution_quality",
]


def read_table(conn: sqlite3.Connection, table_name: str) -> pd.DataFrame:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()

    if not row:
        return pd.DataFrame()

    return pd.read_sql_query(f"SELECT * FROM {table_name}", conn)


def missing_count(df: pd.DataFrame, field: str) -> int:
    if field not in df.columns:
        return len(df)

    values = df[field]
    return int(values.isna().sum() + values.astype(str).str.strip().isin(["", "None", "nan"]).sum())


def build_label_review_queue(label_df: pd.DataFrame, llm_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    if not label_df.empty:
        for _, row in label_df.iterrows():
            reasons = []
            touch = row.get("touch_buy_range")
            hit_1 = row.get("hit_1pct_after_touch")
            hit_2 = row.get("hit_2pct_after_touch")
            stop = row.get("stop_2pct_after_touch")

            for field in REQUIRED_LABEL_FIELDS:
                if field not in label_df.columns or pd.isna(row.get(field)) or str(row.get(field)).strip() == "":
                    reasons.append(f"missing:{field}")

            if touch == 0 and any(value == 1 for value in [hit_1, hit_2, stop]):
                reasons.append("conflict:no_touch_but_has_event")

            if hit_2 == 1 and hit_1 == 0:
                reasons.append("conflict:hit_2pct_without_hit_1pct")

            if stop == 1 and (hit_1 == 1 or hit_2 == 1):
                reasons.append("needs_minute_path:hit_and_stop_in_same_ohlc")

            if reasons:
                rows.append({
                    "sample_id": row.get("sample_id", ""),
                    "stock_code": row.get("stock_code", ""),
                    "review_type": "rule_label",
                    "severity": "high" if any(reason.startswith("conflict") for reason in reasons) else "medium",
                    "reason": ";".join(reasons),
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })

    if not llm_df.empty:
        for _, row in llm_df.iterrows():
            needs_review = int(row.get("needs_manual_review", 0) or 0) == 1
            confidence = row.get("label_confidence")
            low_confidence = pd.notna(confidence) and float(confidence) < 0.7
            conflict_fields = str(row.get("conflict_fields", "")).strip()

            if needs_review or low_confidence or conflict_fields not in ["", "[]", "nan"]:
                rows.append({
                    "sample_id": row.get("sample_id", ""),
                    "stock_code": "",
                    "review_type": "llm_label",
                    "severity": "medium",
                    "reason": f"needs_manual_review={needs_review}; low_confidence={low_confidence}; conflict_fields={conflict_fields}",
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })

    return pd.DataFrame(rows, columns=["sample_id", "stock_code", "review_type", "severity", "reason", "created_at"])


def write_label_review_queue_markdown(queue_df: pd.DataFrame) -> None:
    LABEL_REVIEW_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# v2.5 标签人工复核队列",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"待复核数量：{len(queue_df)}",
        "",
    ]

    if queue_df.empty:
        lines.append("当前没有规则冲突或低置信辅助标签。")
    else:
        lines.extend(["| sample_id | stock_code | 类型 | 严重度 | 原因 |", "|---|---|---|---|---|"])

        for _, row in queue_df.iterrows():
            lines.append(
                f"| {row.get('sample_id', '')} | {row.get('stock_code', '')} | "
                f"{row.get('review_type', '')} | {row.get('severity', '')} | {row.get('reason', '')} |"
            )

    LABEL_REVIEW_QUEUE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_quality_metrics(
    conn: sqlite3.Connection,
    split_path: str,
    outputs: list[str],
    llm_enabled: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    table_names = [
        "dataset_samples",
        "feature_snapshot",
        "label_snapshot",
        "prediction_log",
        "trade_records",
        "llm_label_snapshot",
        "api_usage_log",
        "label_review_queue",
    ]
    tables = {table_name: read_table(conn, table_name) for table_name in table_names}
    label_df = tables["label_snapshot"]
    llm_df = tables["llm_label_snapshot"]
    usage_df = tables["api_usage_log"]
    queue_df = build_label_review_queue(label_df, llm_df)

    total_samples = len(tables["dataset_samples"])
    label_count = len(label_df)
    labeled_sample_ids = set(label_df.get("sample_id", pd.Series(dtype=str)).dropna().astype(str))
    sample_ids = set(tables["dataset_samples"].get("sample_id", pd.Series(dtype=str)).dropna().astype(str))
    matched_label_sample_count = len(sample_ids & labeled_sample_ids)
    missing_label_sample_count = len(sample_ids - labeled_sample_ids)
    required_missing = {field: missing_count(label_df, field) for field in REQUIRED_LABEL_FIELDS}
    llm_cost = float(pd.to_numeric(usage_df.get("cost_estimate_cny", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())

    metrics = {
        "table_counts": {table_name: len(df) for table_name, df in tables.items()},
        "sample_count": total_samples,
        "label_count": label_count,
        "matched_label_sample_count": matched_label_sample_count,
        "label_coverage_pct": round(matched_label_sample_count / total_samples * 100, 2) if total_samples else 0.0,
        "missing_label_sample_count": missing_label_sample_count,
        "required_label_missing": required_missing,
        "review_queue_count": len(queue_df),
        "llm_enabled": llm_enabled,
        "llm_cost_estimate_cny": round(llm_cost, 6),
        "split_path": split_path,
        "outputs": outputs,
    }

    return metrics, queue_df


def write_quality_report(
    table_counts: dict[str, int],
    db_path: Path,
    split_path: str,
    outputs: list[str],
    llm_enabled: bool,
) -> dict[str, Any]:
    QUALITY_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        metrics, queue_df = build_quality_metrics(conn, split_path, outputs, llm_enabled)
        queue_df.to_sql("label_review_queue", conn, if_exists="replace", index=False)
        metrics["table_counts"].update({"label_review_queue": len(queue_df)})

    write_label_review_queue_markdown(queue_df)

    lines = [
        "# v2.5 数据集质量报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 一、数据库",
        "",
        "- 数据库类型：SQLite",
        f"- 数据库文件：`{db_path}`",
        "",
        "## 二、表记录数",
        "",
        "| 表 | 记录数 |",
        "|---|---:|",
    ]

    for table_name, count in metrics["table_counts"].items():
        lines.append(f"| `{table_name}` | {count} |")

    lines.extend([
        "",
        "## 三、标签质量",
        "",
        f"- 样本数：{metrics['sample_count']}",
        f"- 标签数：{metrics['label_count']}",
        f"- 样本标签匹配数：{metrics['matched_label_sample_count']}",
        f"- 标签覆盖率：{metrics['label_coverage_pct']}%",
        f"- 缺标签样本数：{metrics['missing_label_sample_count']}",
        "",
        "| 字段 | 缺失数 |",
        "|---|---:|",
    ])

    for field, count in metrics["required_label_missing"].items():
        lines.append(f"| `{field}` | {count} |")

    lines.extend([
        "",
        "## 四、人工复核队列",
        "",
        f"- 待复核数量：{metrics['review_queue_count']}",
        f"- 队列表：`label_review_queue`",
        f"- 队列报告：`{LABEL_REVIEW_QUEUE_FILE}`",
        "",
        "## 五、LLM 辅助标签",
        "",
        f"- 当前开关：{'开启' if metrics['llm_enabled'] else '关闭'}",
        f"- 估算成本：{metrics['llm_cost_estimate_cny']} CNY",
        "- 未配置或关闭时，不阻断样本、特征、标签、交易记录生成。",
        "",
        "## 六、时间序列切分",
        "",
        f"- 切分文件：`{split_path}`",
        "",
        "## 七、导出文件",
        "",
    ])

    for output in outputs:
        lines.append(f"- `{output}`")

    QUALITY_REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return metrics


def run_dataset_quality_report() -> dict:
    outputs = [
        str(Path("data/dataset/splits/latest.json")),
        str(DATABASE_FILE),
        str(QUALITY_REPORT_FILE),
        str(LABEL_REVIEW_QUEUE_FILE),
    ]
    metrics = write_quality_report(
        table_counts={},
        db_path=DATABASE_FILE,
        split_path=str(Path("data/dataset/splits/latest.json")),
        outputs=outputs,
        llm_enabled=False,
    )
    print(f"质量报告已生成：{QUALITY_REPORT_FILE}")
    print(f"待复核样本：{metrics['review_queue_count']}")

    return {"success": True, "quality_report": str(QUALITY_REPORT_FILE), "review_queue_count": metrics["review_queue_count"]}


if __name__ == "__main__":
    run_dataset_quality_report()
