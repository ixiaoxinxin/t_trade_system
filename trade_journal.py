# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from common import normalize_code, safe_float


TRADE_RECORD_FILE = Path("output/trade_records.csv")

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
    "费用",
    "盈亏金额",
    "收益率",
    "持仓状态",
    "策略来源",
    "是否按计划执行",
    "情绪状态",
    "备注",
]


def calculate_profit(
    buy_price: float,
    sell_price: float,
    quantity: int,
    fee: float = 0.0,
) -> tuple[float, float]:
    if buy_price <= 0 or sell_price <= 0 or quantity <= 0:
        return 0.0, 0.0

    profit = (sell_price - buy_price) * quantity - fee
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
    fee: Any = 0,
    strategy_source: str = "手动记录",
    followed_plan: str = "未记录",
    emotion: str = "",
    note: str = "",
    recorded_at: datetime | None = None,
) -> dict:
    code = normalize_code(stock_code)
    name = str(stock_name).strip()
    buy = safe_float(buy_price)
    sell = safe_float(sell_price)
    shares = int(safe_float(quantity))
    trade_fee = safe_float(fee)
    now = recorded_at or datetime.now()

    if not code:
        raise ValueError("股票代码不能为空")

    if not name:
        raise ValueError("股票名称不能为空")

    if buy <= 0:
        raise ValueError("买入价格必须大于 0")

    if shares <= 0:
        raise ValueError("数量必须大于 0")

    profit, profit_rate = calculate_profit(
        buy_price=buy,
        sell_price=sell,
        quantity=shares,
        fee=trade_fee,
    )

    holding_status = "已卖出" if sell > 0 else "持仓中"

    if hasattr(trade_date, "strftime"):
        trade_date_text = trade_date.strftime("%Y-%m-%d")
    else:
        trade_date_text = str(trade_date).strip()

    record_id = f"{now.strftime('%Y%m%d%H%M%S')}_{code}_{trade_type}_{direction}"

    return {
        "记录ID": record_id,
        "记录时间": now.strftime("%Y-%m-%d %H:%M:%S"),
        "交易日期": trade_date_text,
        "交易类型": str(trade_type).strip(),
        "股票代码": code,
        "股票名称": name,
        "方向": str(direction).strip(),
        "买入价格": round(buy, 3),
        "卖出价格": round(sell, 3) if sell > 0 else "",
        "数量": shares,
        "费用": round(trade_fee, 2),
        "盈亏金额": profit if sell > 0 else "",
        "收益率": profit_rate if sell > 0 else "",
        "持仓状态": holding_status,
        "策略来源": str(strategy_source).strip(),
        "是否按计划执行": str(followed_plan).strip(),
        "情绪状态": str(emotion).strip(),
        "备注": str(note).strip(),
    }


def load_trade_records(path: Path = TRADE_RECORD_FILE) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=TRADE_RECORD_COLUMNS)

    df = pd.read_csv(path, dtype={"股票代码": str})

    for col in TRADE_RECORD_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df["股票代码"] = df["股票代码"].apply(normalize_code)

    return df[TRADE_RECORD_COLUMNS].copy()


def append_trade_record(record: dict, path: Path = TRADE_RECORD_FILE) -> pd.DataFrame:
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
