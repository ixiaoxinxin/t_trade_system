# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from common import PRODUCT_VERSION, load_yaml_config, normalize_code, safe_float
from llm_labeler import build_llm_tables as build_llm_label_tables
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


def ensure_database(conn: sqlite3.Connection) -> None:
    for table_name, schema in TABLE_SCHEMAS.items():
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({schema})")
        conn.execute(f"DELETE FROM {table_name}")

    conn.commit()


def insert_dataframe(conn: sqlite3.Connection, table_name: str, df: pd.DataFrame) -> None:
    if df.empty:
        return

    df.to_sql(table_name, conn, if_exists="append", index=False)


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

        rows.append({
            "sample_id": sample_id(code, generated_at, rule_version),
            "stock_code": code,
            "feature_date": generated_at,
            "ret_1d": safe_float(row.get("今日涨跌幅", 0)),
            "ret_3d": None,
            "ret_5d": safe_float(row.get("最近5日涨幅", 0)),
            "ret_20d": None,
            "ma5_gap": safe_float(row.get("距MA5偏离率", 0)),
            "ma10_gap": None,
            "ma20_gap": None,
            "ma5_slope": None,
            "ma10_slope": None,
            "atr_14": None,
            "hist_vol_20": None,
            "range_5d": safe_float(row.get("最近5日振幅", row.get("今日振幅", 0))),
            "amount": safe_float(row.get("今日成交额", 0)),
            "avg_amount_5d": safe_float(row.get("最近5日平均成交额", 0)),
            "turnover_rate": None,
            "volume_ratio": safe_float(row.get("尾盘放量倍数", 0)),
            "body_pct": None,
            "upper_shadow_pct": None,
            "lower_shadow_pct": None,
            "gap_open_pct": safe_float(row.get("今日开盘", 0)) - safe_float(row.get("昨收", 0)),
            "open_strength": None,
            "first_15m_return": None,
            "first_15m_drawdown": None,
            "vwap_gap": None,
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

    samples_df = build_samples(final_df, manifest, sources)
    feature_df = build_feature_snapshot(final_df, market_env, manifest)
    label_df = build_label_snapshot(next_day_df)
    prediction_df = build_prediction_log(final_df, manifest)
    trade_df = build_trade_record_table()
    llm_df, usage_df = build_llm_label_tables(config, samples_df, label_df)

    with sqlite3.connect(db_path) as conn:
        ensure_database(conn)
        insert_dataframe(conn, "dataset_samples", samples_df)
        insert_dataframe(conn, "feature_snapshot", feature_df)
        insert_dataframe(conn, "label_snapshot", label_df)
        insert_dataframe(conn, "prediction_log", prediction_df)
        insert_dataframe(conn, "trade_records", trade_df)
        insert_dataframe(conn, "llm_label_snapshot", llm_df)
        insert_dataframe(conn, "api_usage_log", usage_df)
        conn.commit()

        table_counts = {
            table_name: int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
            for table_name in TABLE_SCHEMAS
        }
        outputs = []

    split_path = build_split(samples_df, split_dir)
    outputs.append(split_path)
    outputs.append(str(db_path))
    outputs.append(str(QUALITY_REPORT_FILE))

    write_quality_report(
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
