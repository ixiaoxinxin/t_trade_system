# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from common import normalize_code, safe_float
from data_provider import get_stock_daily, get_stock_minute, get_stock_realtime_quote
from ds_analysis import call_ds_analysis, compact_records


FIXED_HOLDINGS = [
    {"股票代码": "002192", "股票名称": "融捷股份"},
    {"股票代码": "603799", "股票名称": "华友钴业"},
    {"股票代码": "002497", "股票名称": "雅化集团"},
    {"股票代码": "002466", "股票名称": "天齐锂业"},
]

FIXED_REASON = "固定持仓每日跟踪"
FIXED_REFRESH_FILE = Path("output/fixed_holdings_refresh.csv")
FIXED_SIGNAL_FILE = Path("output/fixed_holdings_signals.csv")
MODEL_PREDICTION_FILE = Path("output/model_predictions_v2.6.csv")
PROFIT_PROBABILITY_FILE = Path("output/profit_probabilities_v2.7.csv")


def read_model_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"stock_code": str, "股票代码": str})


def enrich_fixed_signals_with_model(signal_df: pd.DataFrame) -> pd.DataFrame:
    if signal_df.empty or "股票代码" not in signal_df.columns:
        return signal_df
    result = signal_df.copy()
    result["股票代码"] = result["股票代码"].apply(normalize_code)

    prediction_df = read_model_csv(MODEL_PREDICTION_FILE)
    if not prediction_df.empty and "stock_code" in prediction_df.columns:
        pred = prediction_df.copy()
        pred["股票代码"] = pred["stock_code"].apply(normalize_code)
        sort_col = "predict_date" if "predict_date" in pred.columns else pred.columns[0]
        pred = pred.sort_values(sort_col).drop_duplicates("股票代码", keep="last")
        pred = pred.rename(columns={
            "next_day_up_probability": "次日上涨概率",
            "direction_confidence": "方向置信度",
            "predicted_direction": "模型方向",
        })
        keep = [col for col in ["股票代码", "次日上涨概率", "方向置信度", "模型方向"] if col in pred.columns]
        result = result.merge(pred[keep], on="股票代码", how="left")

    probability_df = read_model_csv(PROFIT_PROBABILITY_FILE)
    if not probability_df.empty and "stock_code" in probability_df.columns:
        prob = probability_df.copy()
        prob["股票代码"] = prob["stock_code"].apply(normalize_code)
        sort_col = "predict_date" if "predict_date" in prob.columns else prob.columns[0]
        prob = prob.sort_values(sort_col).drop_duplicates("股票代码", keep="last")
        prob = prob.rename(columns={
            "hit_1pct_probability": "达到1%概率",
            "hit_2pct_probability": "达到2%概率",
            "stop_2pct_probability": "止损概率",
            "final_probability_signal": "概率信号",
        })
        keep = [col for col in ["股票代码", "达到1%概率", "达到2%概率", "止损概率", "概率信号"] if col in prob.columns]
        result = result.merge(prob[keep], on="股票代码", how="left")

    return result


def fallback_fixed_signal_ds(signal_df: pd.DataFrame) -> dict[str, str]:
    if signal_df.empty:
        return {
            "DS固定持仓判断": "固定持仓数据不足，先刷新行情。",
            "DS固定持仓动作": "不加仓，等买卖点刷新。",
            "DS固定持仓风险": "实时价缺失时不做判断。",
        }
    risk_rows = signal_df[signal_df.get("卖点信号", pd.Series(dtype=str)).astype(str).isin(["止损", "清仓", "减仓"])]
    if not risk_rows.empty:
        names = "、".join(risk_rows["股票名称"].astype(str).head(3).tolist())
        action = f"{names} 先按卖点纪律处理。"
    else:
        action = "暂无强卖点，先看回落到买点区。"
    return {
        "DS固定持仓判断": "固定持仓先看卖点纪律，再看买点回补。",
        "DS固定持仓动作": action,
        "DS固定持仓风险": "跌破回补区不补仓，等止跌。",
    }


def build_fixed_signal_ds(signal_df: pd.DataFrame) -> tuple[dict[str, str], str]:
    fallback = fallback_fixed_signal_ds(signal_df)
    payload = {
        "任务": "结合固定持仓买卖点和模型概率输出实盘短指令",
        "固定持仓": compact_records(
            signal_df,
            [
                "股票名称",
                "股票代码",
                "当前价",
                "当前涨幅",
                "买点状态",
                "买点下限",
                "买点上限",
                "卖点信号",
                "卖点理由",
                "次日上涨概率",
                "达到1%概率",
                "止损概率",
                "概率信号",
                "实时行情时间",
            ],
            limit=6,
        ),
    }
    system_prompt = (
        "你是A股固定持仓盘中辅助员。只根据提供数据输出严格JSON，字段为："
        "DS固定持仓判断、DS固定持仓动作、DS固定持仓风险。"
        "每个字段不超过48个中文字符；不编造价格；不展示计算过程；必须适合盘中快速执行。"
    )
    return call_ds_analysis(
        prompt_version="v4.02_fixed_holding_signal_ds",
        system_prompt=system_prompt,
        payload=payload,
        fallback=fallback,
    )


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


def standardize_daily(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    result = df.rename(columns={
        "日期": "date",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "开盘": "open",
        "成交额": "amount",
    }).copy()

    for col in ["open", "high", "low", "close", "amount"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")

    if "date" in result.columns:
        result["date"] = pd.to_datetime(result["date"], errors="coerce")

    return result.dropna(subset=["close"]).reset_index(drop=True)


def standardize_minute(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    result = df.rename(columns={
        "时间": "datetime",
        "日期": "datetime",
        "收盘": "close",
        "最新价": "close",
        "最高": "high",
        "最低": "low",
        "开盘": "open",
        "成交额": "amount",
        "成交量": "volume",
    }).copy()

    for col in ["open", "high", "low", "close", "amount", "volume"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")

    if "datetime" in result.columns:
        result["datetime"] = pd.to_datetime(result["datetime"], errors="coerce")
        result = result.sort_values("datetime")

    return result.dropna(subset=["close"]).reset_index(drop=True)


def calculate_buy_zone(daily_df: pd.DataFrame, reference_price: float) -> tuple[float, float, str]:
    if reference_price > 0:
        return reference_price * 0.98, reference_price * 0.99, "昨收回撤1%-2%"

    return 0.0, 0.0, "数据不足"


def classify_buy_status(current_price: float, buy_low: float, buy_high: float, reference_price: float) -> str:
    if current_price <= 0 or buy_low <= 0 or buy_high <= 0:
        return "待刷新"

    if buy_low <= current_price <= buy_high:
        return "进入回补区"

    if current_price < buy_low:
        return "跌破回补区，先等止跌"

    if reference_price > 0 and current_price >= reference_price * 1.01:
        return "高于回补区，不追"

    return "高于回补区，等回落"


def build_signal_watchlist_row(stock_code: str, stock_name: str, reference_price: float) -> pd.Series:
    row = build_fixed_row(
        [
            "股票代码",
            "股票名称",
            "固定持仓",
            "置顶原因",
            "行情刷新状态",
            "隔夜建议等级",
            "隔夜建议说明",
            "分时结构标签",
            "尾盘抢筹标签",
            "最终评分",
            "尾盘评分",
            "候选评分",
            "收盘价",
            "最新收盘价",
            "昨收",
        ],
        stock_code,
        stock_name,
    )

    if reference_price > 0:
        row["收盘价"] = reference_price
        row["最新收盘价"] = reference_price
        row["昨收"] = reference_price

    return pd.Series(row)


def run_fixed_holding_trade_signals() -> pd.DataFrame:
    from sell_signal_engine import build_sell_signal_row, load_market_environment

    market_env = load_market_environment()
    rows = []

    for item in FIXED_HOLDINGS:
        code = normalize_code(item["股票代码"])
        name = item["股票名称"]
        daily_status = "未刷新"
        minute_status = "未刷新"
        reference_price = 0.0
        current_price = 0.0
        day_high = 0.0
        day_low = 0.0
        quote_status = "实时未刷新"
        quote_time = ""

        try:
            daily_df = standardize_daily(get_stock_daily(code))
            daily_status = "成功" if not daily_df.empty else "日线为空"
            if not daily_df.empty:
                reference_price = safe_float(daily_df["close"].iloc[-1])
        except Exception as exc:
            daily_df = pd.DataFrame()
            daily_status = f"失败：{exc}"

        quote = get_stock_realtime_quote(code)
        if quote:
            quote_status = str(quote.get("数据源", "实时已刷新"))
            quote_time = " ".join(
                part
                for part in [str(quote.get("行情日期", "")).strip(), str(quote.get("行情时间", "")).strip()]
                if part
            )
            current_price = safe_float(quote.get("最新价", 0))
            day_high = safe_float(quote.get("最高", 0)) or current_price
            day_low = safe_float(quote.get("最低", 0)) or current_price
            quote_previous_close = safe_float(quote.get("昨收", 0))
            if quote_previous_close > 0:
                reference_price = quote_previous_close

        try:
            minute_df = standardize_minute(get_stock_minute(code, period="1"))
            minute_status = "成功" if not minute_df.empty else "分钟为空"
            if not minute_df.empty and current_price <= 0:
                latest_date = minute_df["datetime"].dt.date.max() if "datetime" in minute_df.columns else None
                today_minute = minute_df[minute_df["datetime"].dt.date.eq(latest_date)].copy() if latest_date else minute_df
                current_price = safe_float(today_minute["close"].iloc[-1])
                day_high = safe_float(today_minute["high"].max()) if "high" in today_minute.columns else current_price
                day_low = safe_float(today_minute["low"].min()) if "low" in today_minute.columns else current_price
        except Exception as exc:
            minute_status = f"失败：{exc}"

        buy_low, buy_high, buy_basis = calculate_buy_zone(daily_df, reference_price)
        buy_status = classify_buy_status(current_price, buy_low, buy_high, reference_price)

        sell_row = build_sell_signal_row(build_signal_watchlist_row(code, name, reference_price), market_env)
        sell_signal = sell_row.get("卖出信号", "待刷新") if sell_row else "待刷新"
        sell_reason = sell_row.get("卖出理由", "固定持仓卖点数据不足，请刷新行情。") if sell_row else "固定持仓卖点数据不足，请刷新行情。"
        current_pct = sell_row.get("当前涨幅", 0) if sell_row else 0
        pullback_pct = sell_row.get("高点回撤", 0) if sell_row else 0

        rows.append({
            "刷新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "股票代码": code,
            "股票名称": name,
            "固定持仓": "是",
            "参考价": round(reference_price, 3) if reference_price else "",
            "当前价": round(current_price, 3) if current_price else "",
            "实时行情时间": quote_time,
            "日内最高": round(day_high, 3) if day_high else "",
            "日内最低": round(day_low, 3) if day_low else "",
            "买点下限": round(buy_low, 3) if buy_low else "",
            "买点上限": round(buy_high, 3) if buy_high else "",
            "买点依据": buy_basis,
            "买点状态": buy_status,
            "卖点信号": sell_signal,
            "卖点理由": sell_reason,
            "当前涨幅": current_pct,
            "高点回撤": pullback_pct,
            "日线状态": daily_status,
            "实时状态": quote_status,
            "分钟状态": minute_status,
        })

    df = enrich_fixed_signals_with_model(pd.DataFrame(rows))
    ds_result, ds_status = build_fixed_signal_ds(df)
    for key, value in ds_result.items():
        df[key] = value
    df["DS状态"] = ds_status
    FIXED_SIGNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(FIXED_SIGNAL_FILE, index=False, encoding="utf-8-sig")
    print(f"固定持仓买卖点刷新完成：{FIXED_SIGNAL_FILE}")
    print(df[["股票名称", "当前价", "买点状态", "卖点信号", "DS状态"]].to_string(index=False))
    return df


def refresh_fixed_holding_market_data() -> pd.DataFrame:
    rows = []

    for item in FIXED_HOLDINGS:
        code = normalize_code(item["股票代码"])
        name = item["股票名称"]
        daily_status = "未刷新"
        minute_status = "未刷新"
        reference_price = 0.0
        current_price = 0.0
        day_high = 0.0
        day_low = 0.0
        quote_status = "实时未刷新"
        quote_time = ""
        minute_rows = 0

        try:
            daily_df = get_stock_daily(code)
            daily_status = "成功" if not daily_df.empty else "日线为空"
            if not daily_df.empty:
                reference_price = latest_daily_reference(code)[0]
        except Exception as exc:
            daily_status = f"失败：{exc}"

        quote = get_stock_realtime_quote(code)
        if quote:
            quote_status = str(quote.get("数据源", "实时已刷新"))
            quote_time = " ".join(
                part
                for part in [str(quote.get("行情日期", "")).strip(), str(quote.get("行情时间", "")).strip()]
                if part
            )
            current_price = safe_float(quote.get("最新价", 0))
            day_high = safe_float(quote.get("最高", 0)) or current_price
            day_low = safe_float(quote.get("最低", 0)) or current_price
            quote_previous_close = safe_float(quote.get("昨收", 0))
            if quote_previous_close > 0:
                reference_price = quote_previous_close

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
            "当前价": round(current_price, 3) if current_price else "",
            "日内最高": round(day_high, 3) if day_high else "",
            "日内最低": round(day_low, 3) if day_low else "",
            "实时行情时间": quote_time,
            "日线状态": daily_status,
            "实时状态": quote_status,
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
