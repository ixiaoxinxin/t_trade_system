# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd

from common import normalize_code, safe_float


TRADE_RECORD_FILE = Path("output/trade_records.csv")
TRADE_DATABASE_FILE = Path("data/dataset/trade_dataset.sqlite3")

TRADE_RECORD_COLUMNS = [
    "记录ID",
    "记录时间",
    "交易日期",
    "交易类型",
    "股票代码",
    "股票名称",
    "方向",
    "买入价格",
    "卖出价格",
    "数量",
    "买入手续费",
    "卖出手续费",
    "卖出印花税",
    "手续费合计",
    "到手利润",
    "收益率",
    "闭环状态",
    "策略来源",
    "是否按计划执行",
    "备注",
]

ALLOWED_TRADE_TYPES = {"日内T", "隔日T"}
ALLOWED_DIRECTIONS = {"买入", "卖出", "买入并卖出"}
COMMISSION_RATE = 0.00025
MIN_COMMISSION = 5.0
SELL_STAMP_TAX_RATE = 0.0005

DB_TO_CN_COLUMNS = {
    "record_id": "记录ID",
    "recorded_at": "记录时间",
    "trade_date": "交易日期",
    "trade_type": "交易类型",
    "stock_code": "股票代码",
    "stock_name": "股票名称",
    "direction": "方向",
    "buy_price": "买入价格",
    "sell_price": "卖出价格",
    "quantity": "数量",
    "buy_commission": "买入手续费",
    "sell_commission": "卖出手续费",
    "sell_stamp_tax": "卖出印花税",
    "total_commission": "手续费合计",
    "net_profit": "到手利润",
    "return_rate": "收益率",
    "closed_status": "闭环状态",
    "strategy_source": "策略来源",
    "followed_plan": "是否按计划执行",
    "note": "备注",
}

CN_TO_DB_COLUMNS = {value: key for key, value in DB_TO_CN_COLUMNS.items()}


def calculate_commission(amount: float) -> float:
    if amount <= 0:
        return 0.0

    return round(max(amount * COMMISSION_RATE, MIN_COMMISSION), 2)


def calculate_sell_stamp_tax(amount: float) -> float:
    if amount <= 0:
        return 0.0

    return round(amount * SELL_STAMP_TAX_RATE, 2)


def ensure_trade_record_table() -> None:
    TRADE_DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(TRADE_DATABASE_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_records (
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
                sell_stamp_tax REAL,
                total_commission REAL,
                net_profit REAL,
                return_rate REAL,
                closed_status TEXT,
                strategy_source TEXT,
                followed_plan TEXT,
                note TEXT
            )
        """)
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(trade_records)").fetchall()
        }
        if "sell_stamp_tax" not in existing_columns:
            conn.execute("ALTER TABLE trade_records ADD COLUMN sell_stamp_tax REAL")
        conn.commit()


def default_sqlite_enabled(path: Path) -> bool:
    return Path(path) == TRADE_RECORD_FILE


def load_trade_records_from_sqlite() -> pd.DataFrame:
    if not TRADE_DATABASE_FILE.exists():
        return pd.DataFrame(columns=TRADE_RECORD_COLUMNS)

    ensure_trade_record_table()

    with sqlite3.connect(TRADE_DATABASE_FILE) as conn:
        df = pd.read_sql_query("SELECT * FROM trade_records ORDER BY recorded_at DESC", conn)

    if df.empty:
        return pd.DataFrame(columns=TRADE_RECORD_COLUMNS)

    df = df.rename(columns=DB_TO_CN_COLUMNS)

    for col in TRADE_RECORD_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df["股票代码"] = df["股票代码"].apply(normalize_code)

    return df[TRADE_RECORD_COLUMNS].copy()


def append_trade_record_to_sqlite(record: dict) -> pd.DataFrame:
    ensure_trade_record_table()
    db_record = {db_col: record.get(cn_col, "") for cn_col, db_col in CN_TO_DB_COLUMNS.items()}

    with sqlite3.connect(TRADE_DATABASE_FILE) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO trade_records
            (record_id, recorded_at, trade_date, trade_type, stock_code, stock_name,
             direction, buy_price, sell_price, quantity, buy_commission, sell_commission,
             sell_stamp_tax, total_commission, net_profit, return_rate, closed_status, strategy_source,
             followed_plan, note)
            VALUES
            (:record_id, :recorded_at, :trade_date, :trade_type, :stock_code, :stock_name,
             :direction, :buy_price, :sell_price, :quantity, :buy_commission, :sell_commission,
             :sell_stamp_tax, :total_commission, :net_profit, :return_rate, :closed_status, :strategy_source,
             :followed_plan, :note)
            """,
            db_record,
        )
        conn.commit()

    return load_trade_records_from_sqlite()


def calculate_net_profit(
    buy_price: float,
    sell_price: float,
    quantity: int,
    buy_commission: float = 0.0,
    sell_commission: float = 0.0,
    sell_stamp_tax: float = 0.0,
) -> tuple[float, float]:
    if buy_price <= 0 or sell_price <= 0 or quantity <= 0:
        return 0.0, 0.0

    profit = (sell_price - buy_price) * quantity - buy_commission - sell_commission - sell_stamp_tax
    profit_rate = profit / (buy_price * quantity) * 100

    return round(profit, 2), round(profit_rate, 2)


def build_trade_record(
    *,
    stock_code: Any,
    stock_name: str,
    trade_date,
    trade_type: str,
    direction: str,
    buy_price: Any,
    sell_price: Any = 0,
    quantity: Any = 0,
    strategy_source: str = "手动记录",
    followed_plan: str = "未记录",
    note: str = "",
    recorded_at: datetime | None = None,
    record_id: str | None = None,
) -> dict:
    raw_code = str(stock_code).strip()
    code = normalize_code(raw_code) if raw_code else ""
    name = str(stock_name).strip()
    buy = safe_float(buy_price)
    sell = safe_float(sell_price)
    shares = int(safe_float(quantity))
    trade_type_text = str(trade_type).strip()
    direction_text = str(direction).strip()
    now = recorded_at or datetime.now()

    if not code:
        raise ValueError("股票代码不能为空")

    if not name:
        raise ValueError("股票名称不能为空")

    if trade_type_text not in ALLOWED_TRADE_TYPES:
        raise ValueError("交易类型只能是日内T或隔日T")

    if direction_text not in ALLOWED_DIRECTIONS:
        raise ValueError("方向只能是买入、卖出或买入并卖出")

    if buy <= 0:
        raise ValueError("买入价格/成本价必须大于 0")

    if direction_text in ["卖出", "买入并卖出"] and sell <= 0:
        raise ValueError("卖出或买入并卖出时，卖出价格必须大于 0")

    if shares <= 0:
        raise ValueError("数量必须大于 0")

    buy_commission = calculate_commission(buy * shares)
    sell_commission = calculate_commission(sell * shares) if sell > 0 else 0.0
    sell_stamp_tax = calculate_sell_stamp_tax(sell * shares) if sell > 0 else 0.0
    total_commission = round(buy_commission + sell_commission + sell_stamp_tax, 2)

    profit = ""
    profit_rate = ""
    closed_status = "未闭环"

    if sell > 0:
        profit, profit_rate = calculate_net_profit(
            buy_price=buy,
            sell_price=sell,
            quantity=shares,
            buy_commission=buy_commission,
            sell_commission=sell_commission,
            sell_stamp_tax=sell_stamp_tax,
        )
        closed_status = "已闭环"

    if hasattr(trade_date, "strftime"):
        trade_date_text = trade_date.strftime("%Y-%m-%d")
    else:
        trade_date_text = str(trade_date).strip()

    next_record_id = str(record_id).strip() if record_id else f"{now.strftime('%Y%m%d%H%M%S')}_{code}_{trade_type_text}_{direction_text}"

    return {
        "记录ID": next_record_id,
        "记录时间": now.strftime("%Y-%m-%d %H:%M:%S"),
        "交易日期": trade_date_text,
        "交易类型": trade_type_text,
        "股票代码": code,
        "股票名称": name,
        "方向": direction_text,
        "买入价格": round(buy, 3),
        "卖出价格": round(sell, 3) if sell > 0 else "",
        "数量": shares,
        "买入手续费": buy_commission,
        "卖出手续费": sell_commission if sell > 0 else "",
        "卖出印花税": sell_stamp_tax if sell > 0 else "",
        "手续费合计": total_commission,
        "到手利润": profit,
        "收益率": profit_rate,
        "闭环状态": closed_status,
        "策略来源": str(strategy_source).strip(),
        "是否按计划执行": str(followed_plan).strip(),
        "备注": str(note).strip(),
    }


def load_trade_records(path: Path = TRADE_RECORD_FILE) -> pd.DataFrame:
    if default_sqlite_enabled(path):
        sqlite_df = load_trade_records_from_sqlite()

        if not sqlite_df.empty:
            return sqlite_df

    if not path.exists():
        return pd.DataFrame(columns=TRADE_RECORD_COLUMNS)

    df = pd.read_csv(path, dtype={"股票代码": str})

    for col in TRADE_RECORD_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df["股票代码"] = df["股票代码"].apply(normalize_code)

    return df[TRADE_RECORD_COLUMNS].copy()


def append_trade_record(record: dict, path: Path = TRADE_RECORD_FILE) -> pd.DataFrame:
    if default_sqlite_enabled(path):
        return append_trade_record_to_sqlite(record)

    path.parent.mkdir(parents=True, exist_ok=True)

    existing = load_trade_records(path)
    record_df = pd.DataFrame([record])

    if existing.empty:
        next_df = record_df.copy()
    else:
        next_df = pd.concat([existing, record_df], ignore_index=True)

    next_df = next_df[TRADE_RECORD_COLUMNS]
    next_df.to_csv(path, index=False, encoding="utf-8-sig")

    return next_df


def update_trade_record(record: dict, path: Path = TRADE_RECORD_FILE) -> pd.DataFrame:
    record_id = str(record.get("记录ID", "")).strip()
    if not record_id:
        raise ValueError("记录ID不能为空")

    if default_sqlite_enabled(path):
        return append_trade_record_to_sqlite(record)

    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_trade_records(path)
    record_df = pd.DataFrame([record])

    if existing.empty:
        next_df = record_df.copy()
    else:
        next_df = existing[existing["记录ID"].astype(str) != record_id].copy()
        next_df = pd.concat([next_df, record_df], ignore_index=True)

    next_df = next_df[TRADE_RECORD_COLUMNS]
    next_df.to_csv(path, index=False, encoding="utf-8-sig")

    return next_df
