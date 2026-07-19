# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from common import normalize_code, safe_float
from data_provider import get_stock_daily, get_stock_minute


FIXED_HOLDINGS = [
    {"股票代码": "002192", "股票名称": "融捷股份"},
    {"股票代码": "600096", "股票名称": "云天化"},
    {"股票代码": "002213", "股票名称": "大为股份"},
    {"股票代码": "000933", "股票名称": "神火股份"},
    {"股票代码": "002466", "股票名称": "天齐锂业"},
]

FIXED_REASON = "固定持仓每日跟踪"
FIXED_REFRESH_FILE = Path("output/fixed_holdings_refresh.csv")


def fixed_holding_codes() -> set[str]:
    return {normalize_code(item["股票代码"]) for item in FIXED_HOLDINGS}


def fixed_holding_name_map() -> dict[str, str]:
    return {normalize_code(item["股票代码"]): item["股票名称"] for item in FIXED_HOLDINGS}


def is_fixed_holding(code: Any) -> bool:
    return normalize_code(code) in fixed_holding_codes()


def latest_daily_reference(stock_code: str) -> tuple[float, str]:
    code = normalize_code(stock_code)

    try:
        daily_df = get_stock_daily(code)
    except Exception as exc:
        return 0.0, f"日线刷新失败：{exc}"

    if daily_df is None or daily_df.empty:
        return 0.0, "日线数据为空"

    row = daily_df.iloc[-1]

    for col in ["收盘", "close", "最新价", "收盘价"]:
        price = safe_float(row.get(col, 0))
        if price > 0:
            return price, "日线已刷新"

    return 0.0, "日线缺少收盘价"


def refresh_fixed_holding_market_data() -> pd.DataFrame:
    rows = []

    for item in FIXED_HOLDINGS:
        code = normalize_code(item["股票代码"])
        name = item["股票名称"]
        daily_status = "未刷新"
        minute_status = "未刷新"
        reference_price = 0.0
        minute_rows = 0

        try:
            daily_df = get_stock_daily(code)
            daily_status = "成功" if not daily_df.empty else "日线为空"
            if not daily_df.empty:
                reference_price = latest_daily_reference(code)[0]
        except Exception as exc:
            daily_status = f"失败：{exc}"

        try:
            minute_df = get_stock_minute(code, period="1")
            minute_rows = len(minute_df)
            minute_status = "成功" if not minute_df.empty else "分钟为空"
        except Exception as exc:
            minute_status = f"失败：{exc}"

        rows.append({
            "刷新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "股票代码": code,
            "股票名称": name,
            "参考价": round(reference_price, 3) if reference_price else "",
            "日线状态": daily_status,
            "分钟状态": minute_status,
            "分钟行数": minute_rows,
            "固定持仓": "是",
            "置顶原因": FIXED_REASON,
        })

    df = pd.DataFrame(rows)
    FIXED_REFRESH_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(FIXED_REFRESH_FILE, index=False, encoding="utf-8-sig")
    print(f"固定持仓行情刷新完成：{FIXED_REFRESH_FILE}")
    print(df.to_string(index=False))
    return df


def build_fixed_row(columns: list[str], stock_code: str, stock_name: str) -> dict[str, Any]:
    reference_price, refresh_status = latest_daily_reference(stock_code)
    row = {column: "" for column in columns}
    row.update({
        "股票代码": normalize_code(stock_code),
        "股票名称": stock_name,
        "固定持仓": "是",
        "置顶原因": FIXED_REASON,
        "行情刷新状态": refresh_status,
        "隔夜建议等级": "持仓",
        "隔夜建议说明": "固定持仓，每日置顶观察卖点、午盘结构和次日表现。",
        "分时结构标签": "固定持仓",
        "尾盘抢筹标签": "固定持仓",
        "最终评分": 0,
        "尾盘评分": 0,
        "候选评分": 0,
    })

    if reference_price > 0:
        row["昨收"] = reference_price
        row["收盘价"] = reference_price
        row["最新收盘价"] = reference_price
        row["隔夜参考价"] = reference_price
        row["买入参考价"] = reference_price

    return row


def mark_fixed_holdings(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    result = df.copy()

    if "股票代码" in result.columns:
        result["股票代码"] = result["股票代码"].apply(normalize_code)

    result["固定持仓"] = result.get("固定持仓", "否")
    result["置顶原因"] = result.get("置顶原因", "")
    result["行情刷新状态"] = result.get("行情刷新状态", "")

    fixed_codes = fixed_holding_codes()
    mask = result["股票代码"].isin(fixed_codes) if "股票代码" in result.columns else pd.Series(False, index=result.index)
    result.loc[mask, "固定持仓"] = "是"
    result.loc[mask, "置顶原因"] = FIXED_REASON
    result.loc[mask & result["行情刷新状态"].astype(str).eq(""), "行情刷新状态"] = "来自当前交易池"

    name_map = fixed_holding_name_map()
    for index, row in result.loc[mask].iterrows():
        code = normalize_code(row.get("股票代码", ""))
        if code in name_map and not str(row.get("股票名称", "")).strip():
            result.at[index, "股票名称"] = name_map[code]

    return result


def sort_fixed_holdings_first(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "固定持仓" not in df.columns:
        return df

    result = df.copy()
    result["_fixed_rank"] = result["固定持仓"].astype(str).eq("是").map({True: 0, False: 1})

    sort_cols = ["_fixed_rank"]
    ascending = [True]

    if "隔夜建议等级" in result.columns:
        grade_order = {"A": 1, "B": 2, "C": 3, "持仓": 4, "D": 5}
        result["_grade_rank"] = result["隔夜建议等级"].map(grade_order).fillna(9)
        sort_cols.append("_grade_rank")
        ascending.append(True)

    for col in ["最终评分", "当前涨幅", "最高涨幅"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")
            sort_cols.append(col)
            ascending.append(False)

    result = result.sort_values(sort_cols, ascending=ascending)
    return result.drop(columns=[col for col in ["_fixed_rank", "_grade_rank"] if col in result.columns]).reset_index(drop=True)


def enrich_watchlist_with_fixed_holdings(
    df: pd.DataFrame,
    *,
    include_grades: list[str] | None = None,
    ensure_all: bool = True,
) -> pd.DataFrame:
    result = mark_fixed_holdings(df)

    if include_grades and not result.empty and "隔夜建议等级" in result.columns:
        result = result[
            result["隔夜建议等级"].isin(include_grades)
            | result["固定持仓"].astype(str).eq("是")
        ].copy()

    if ensure_all:
        columns = list(result.columns)
        for required in ["股票代码", "股票名称", "固定持仓", "置顶原因", "行情刷新状态"]:
            if required not in columns:
                columns.append(required)

        existing_codes = set(result["股票代码"].apply(normalize_code)) if not result.empty and "股票代码" in result.columns else set()
        missing_rows = []

        for item in FIXED_HOLDINGS:
            code = normalize_code(item["股票代码"])
            if code not in existing_codes:
                missing_rows.append(build_fixed_row(columns, code, item["股票名称"]))

        if missing_rows:
            result = pd.concat([result, pd.DataFrame(missing_rows)], ignore_index=True)

    return sort_fixed_holdings_first(result)
