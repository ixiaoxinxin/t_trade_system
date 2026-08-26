# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from common import load_yaml_config, normalize_code, safe_float
from data_provider import get_all_stocks, get_stock_daily, get_stock_minute, get_stock_realtime_quote
from fixed_holdings import FIXED_HOLDINGS
from llm_labeler import load_local_env


OUTPUT_CSV = Path("output/opening_levels.csv")
OUTPUT_MD = Path("output/opening_levels.md")
API_USAGE_CSV = Path("output/opening_levels_api_usage.csv")

DEFAULT_CONFIG = {
    "llm_labeling": {
        "enabled": False,
        "provider_priority": ["deepseek"],
        "request_timeout_seconds": 20,
        "providers": {
            "deepseek": {
                "api_key_env": "DEEPSEEK_API_KEY",
                "base_url": "https://api.deepseek.com/chat/completions",
                "model": "deepseek-chat",
                "input_price_cny_per_million": 1.95,
                "output_price_cny_per_million": 7.95,
            }
        },
    },
    "opening_levels": {
        "ai_enabled": True,
        "provider": "deepseek",
        "prompt_version": "opening-levels-v1.1",
        "max_ai_stocks": 4,
    },
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"股票代码": str, "stock_code": str})


def standardize_daily(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.rename(columns={
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
    }).copy()
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")
    if "date" in result.columns:
        result["date"] = pd.to_datetime(result["date"], errors="coerce")
    return result.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)


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
        "成交量": "volume",
        "成交额": "amount",
    }).copy()
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")
    if "datetime" in result.columns:
        result["datetime"] = pd.to_datetime(result["datetime"], errors="coerce")
    return result.dropna(subset=["datetime", "close"]).sort_values("datetime").reset_index(drop=True)


def latest_completed_daily(daily_df: pd.DataFrame, quote_date: str = "") -> pd.Series | None:
    if daily_df.empty:
        return None
    if quote_date:
        current_date = pd.to_datetime(quote_date, errors="coerce")
        if pd.notna(current_date):
            prior = daily_df[daily_df["date"].dt.date < current_date.date()].copy()
            if not prior.empty:
                return prior.iloc[-1]
    return daily_df.iloc[-1]


def calculate_atr(daily_df: pd.DataFrame, window: int = 14) -> float:
    if daily_df.empty:
        return 0.0
    df = daily_df.copy()
    df["prev_close"] = df["close"].shift(1)
    ranges = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["prev_close"]).abs(),
        (df["low"] - df["prev_close"]).abs(),
    ], axis=1).max(axis=1)
    value = ranges.tail(window).mean()
    return safe_float(value)


def first_minute_open(minute_df: pd.DataFrame) -> float:
    if minute_df.empty:
        return 0.0
    latest_date = minute_df["datetime"].dt.date.max()
    today_df = minute_df[minute_df["datetime"].dt.date.eq(latest_date)].copy()
    if today_df.empty:
        return 0.0
    return safe_float(today_df.iloc[0].get("open", today_df.iloc[0].get("close", 0)))


def today_minute_stats(minute_df: pd.DataFrame) -> dict[str, Any]:
    if minute_df.empty:
        return {"morning_high": 0.0, "morning_low": 0.0, "latest_minute": "", "minute_rows": 0}
    latest_date = minute_df["datetime"].dt.date.max()
    today_df = minute_df[minute_df["datetime"].dt.date.eq(latest_date)].copy()
    if today_df.empty:
        return {"morning_high": 0.0, "morning_low": 0.0, "latest_minute": "", "minute_rows": 0}
    first_15 = today_df.head(15)
    return {
        "morning_high": safe_float(first_15["high"].max() if "high" in first_15.columns else first_15["close"].max()),
        "morning_low": safe_float(first_15["low"].min() if "low" in first_15.columns else first_15["close"].min()),
        "latest_minute": str(today_df["datetime"].max()),
        "minute_rows": len(today_df),
    }


def historical_trade_summary(code: str, name: str) -> dict[str, Any]:
    df = read_csv(Path("output/trade_records.csv"))
    if df.empty:
        return {"trade_count": 0, "win_rate": 0.0, "avg_return_pct": 0.0, "avg_profit": 0.0}

    if "股票代码" in df.columns:
        df["股票代码"] = df["股票代码"].apply(normalize_code)
    name_mask = df.get("股票名称", pd.Series([""] * len(df))).astype(str).str.contains(name.replace("A", ""), na=False)
    code_mask = df.get("股票代码", pd.Series([""] * len(df))).astype(str).eq(normalize_code(code))
    matched = df[name_mask | code_mask].copy()
    if matched.empty:
        return {"trade_count": 0, "win_rate": 0.0, "avg_return_pct": 0.0, "avg_profit": 0.0}

    profit = pd.to_numeric(matched.get("到手利润", 0), errors="coerce").fillna(0)
    ret = pd.to_numeric(matched.get("收益率", 0), errors="coerce").fillna(0)
    return {
        "trade_count": len(matched),
        "win_rate": round(float((profit > 0).mean()), 4),
        "avg_return_pct": round(float(ret.mean()), 4),
        "avg_profit": round(float(profit.mean()), 2),
    }


def latest_model_row(code: str) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for path in [Path("output/model_predictions_v2.6.csv"), Path("output/profit_probabilities_v2.7.csv")]:
        df = read_csv(path)
        if df.empty:
            continue
        code_col = "股票代码" if "股票代码" in df.columns else "stock_code"
        if code_col not in df.columns:
            continue
        df[code_col] = df[code_col].apply(normalize_code)
        matched = df[df[code_col].eq(normalize_code(code))]
        if matched.empty:
            continue
        rows.update(matched.iloc[-1].to_dict())
    return rows


def build_levels(
    *,
    previous_close: float,
    previous_high: float,
    previous_low: float,
    auction_price: float,
    current_price: float,
    atr: float,
    personal_avg_return_pct: float = 0.0,
) -> dict[str, float]:
    if previous_close <= 0:
        return {key: 0.0 for key in ["support", "pressure", "buy_low", "buy_high", "sell_low", "sell_high"]}

    active_price = current_price if current_price > 0 else auction_price if auction_price > 0 else previous_close
    base_range = max(previous_high - previous_low, atr, previous_close * 0.012)
    pivot = (previous_high + previous_low + previous_close) / 3
    gap_pct = (auction_price / previous_close - 1) if auction_price > 0 else 0
    personal_adjust = -0.002 if personal_avg_return_pct < 0 else 0.0

    support = min(pivot, previous_low + base_range * 0.18, active_price * 0.985)
    pressure = max(pivot, previous_high - base_range * 0.08, active_price * 1.012)

    if gap_pct > 0.018:
        support = min(support, previous_close * 1.005)
        pressure = max(pressure, auction_price + base_range * 0.35)
    elif gap_pct < -0.018:
        support = min(support, auction_price - base_range * 0.18)
        pressure = min(max(pressure, previous_close), previous_close + base_range * 0.45)

    buy_high = min(support + base_range * 0.22, active_price * (0.997 + personal_adjust))
    buy_low = buy_high - base_range * 0.22
    sell_low = max(pressure - base_range * 0.12, previous_close * 1.008)
    sell_high = sell_low + base_range * 0.25

    return {
        "support": round(max(support, previous_close * 0.9), 3),
        "pressure": round(min(pressure, previous_close * 1.12), 3),
        "buy_low": round(max(buy_low, previous_close * 0.9), 3),
        "buy_high": round(max(buy_high, previous_close * 0.9), 3),
        "sell_low": round(min(sell_low, previous_close * 1.12), 3),
        "sell_high": round(min(sell_high, previous_close * 1.14), 3),
    }


def action_text(current_price: float, levels: dict[str, float]) -> str:
    if current_price <= 0:
        return "等行情"
    if levels["buy_low"] <= current_price <= levels["buy_high"]:
        return "可低吸"
    if current_price < levels["buy_low"]:
        return "等止跌"
    if current_price >= levels["sell_low"]:
        return "看卖出"
    return "先观察"


def reason_text(row: dict[str, Any]) -> str:
    return (
        f"昨收{row['昨收']}，竞价/开盘{row['集合竞价价']}，当前{row['当前价']}；"
        f"买区{row['买进区间']}，卖区{row['卖出区间']}。"
    )


def provider_config(config: dict) -> tuple[str, dict[str, Any]]:
    opening_config = config.get("opening_levels", {})
    llm_config = config.get("llm_labeling", {})
    provider = str(opening_config.get("provider") or "deepseek")
    providers = llm_config.get("providers", {})
    return provider, providers.get(provider, DEFAULT_CONFIG["llm_labeling"]["providers"]["deepseek"])


def call_ai(config: dict, rows: list[dict[str, Any]]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    opening_config = config.get("opening_levels", {})
    if not opening_config.get("ai_enabled", True):
        return {}, []

    load_local_env()
    provider, current_provider_config = provider_config(config)
    api_key_env = str(current_provider_config.get("api_key_env", "DEEPSEEK_API_KEY"))
    api_key = os.environ.get(api_key_env, "").strip()
    model = str(current_provider_config.get("model", "deepseek-chat"))
    prompt_version = str(opening_config.get("prompt_version", "opening-levels-v1.1"))
    if not api_key:
        return {}, [usage_row(provider, model, prompt_version, 0, 0, 0.0, f"missing_api_key:{api_key_env}")]

    messages = [
        {
            "role": "system",
            "content": (
                "你是A股日内T辅助风控助手。只基于给定JSON做简短校验，输出JSON对象，"
                "key为股票代码，value为不超过28个汉字的操作提示。不要编造行情。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(rows, ensure_ascii=False),
        },
    ]
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        str(current_provider_config.get("base_url", "https://api.deepseek.com/chat/completions")),
        data=data,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=int(config.get("llm_labeling", {}).get("request_timeout_seconds", 20))) as response:
            payload = json.loads(response.read().decode("utf-8"))
        parsed = json.loads(payload["choices"][0]["message"]["content"])
        usage = payload.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        cost = estimate_cost(current_provider_config, prompt_tokens, completion_tokens)
        return {normalize_code(k): str(v) for k, v in parsed.items()}, [
            usage_row(provider, model, prompt_version, prompt_tokens, completion_tokens, cost, "success")
        ]
    except Exception as exc:
        return {}, [usage_row(provider, model, prompt_version, 0, 0, 0.0, f"failed:{type(exc).__name__}")]
    finally:
        _ = started


def estimate_cost(config: dict[str, Any], input_tokens: int, output_tokens: int) -> float:
    input_price = safe_float(config.get("input_price_cny_per_million", 0))
    output_price = safe_float(config.get("output_price_cny_per_million", 0))
    return round(input_tokens / 1_000_000 * input_price + output_tokens / 1_000_000 * output_price, 6)


def usage_row(provider: str, model: str, prompt_version: str, input_tokens: int, output_tokens: int, cost: float, status: str) -> dict[str, Any]:
    return {
        "usage_id": f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}",
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_estimate_cny": cost,
        "status": status,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def resolve_stock(stock_text: str) -> tuple[str, str]:
    text = str(stock_text).strip()
    if not text:
        return "", ""
    fixed_by_name = {item["股票名称"].replace("A", ""): item for item in FIXED_HOLDINGS}
    fixed_by_code = {normalize_code(item["股票代码"]): item for item in FIXED_HOLDINGS}
    code_match = re.search(r"\d{6}", text)
    if code_match:
        code = normalize_code(code_match.group(0))
        return code, fixed_by_code.get(code, {}).get("股票名称", text.replace(code, "").strip() or code)
    for name, item in fixed_by_name.items():
        if name in text:
            return normalize_code(item["股票代码"]), item["股票名称"]

    for path in [
        Path("output/final_watchlist.csv"),
        Path("output/final_decision_v3.0.csv"),
        Path("output/trade_records.csv"),
        Path("output/sell_signal.csv"),
    ]:
        df = read_csv(path)
        if df.empty or "股票名称" not in df.columns or "股票代码" not in df.columns:
            continue
        matched = df[df["股票名称"].astype(str).str.contains(text.replace("A", ""), na=False)].copy()
        if not matched.empty:
            row = matched.iloc[-1]
            return normalize_code(row.get("股票代码", "")), str(row.get("股票名称", text))

    try:
        stock_df = get_all_stocks()
        if not stock_df.empty and "名称" in stock_df.columns and "代码" in stock_df.columns:
            matched = stock_df[stock_df["名称"].astype(str).str.contains(text.replace("A", ""), na=False)].copy()
            if not matched.empty:
                row = matched.iloc[0]
                return normalize_code(row.get("代码", "")), str(row.get("名称", text))
    except Exception:
        pass

    return "", text


def build_stock_rows(stock_code: str = "", stock_name: str = "") -> list[dict[str, Any]]:
    targets = []
    if stock_code or stock_name:
        code, name = resolve_stock(stock_code or stock_name)
        targets.append({"股票代码": code, "股票名称": name or stock_name or code})
    else:
        targets = FIXED_HOLDINGS

    rows = []
    for item in targets:
        code = normalize_code(item.get("股票代码", ""))
        name = str(item.get("股票名称", ""))
        if not code:
            rows.append({"股票代码": "", "股票名称": name, "状态": "未匹配代码"})
            continue

        quote = get_stock_realtime_quote(code)
        quote_date = str(quote.get("行情日期", "")).strip()
        daily_df = standardize_daily(get_stock_daily(code))
        minute_df = standardize_minute(get_stock_minute(code, period="1"))
        prev = latest_completed_daily(daily_df, quote_date)
        if prev is None:
            rows.append({"股票代码": code, "股票名称": name, "状态": "日线不足"})
            continue

        trade = historical_trade_summary(code, name)
        model = latest_model_row(code)
        prev_close = safe_float(prev.get("close", 0))
        prev_high = safe_float(prev.get("high", 0))
        prev_low = safe_float(prev.get("low", 0))
        auction_price = safe_float(quote.get("今开", 0)) or first_minute_open(minute_df)
        current_price = safe_float(quote.get("最新价", 0)) or auction_price
        atr = calculate_atr(daily_df)
        levels = build_levels(
            previous_close=prev_close,
            previous_high=prev_high,
            previous_low=prev_low,
            auction_price=auction_price,
            current_price=current_price,
            atr=atr,
            personal_avg_return_pct=safe_float(trade["avg_return_pct"]),
        )
        minute_stats = today_minute_stats(minute_df)
        row = {
            "刷新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "股票代码": code,
            "股票名称": name,
            "状态": "成功",
            "操作": action_text(current_price, levels),
            "支撑位": levels["support"],
            "压力位": levels["pressure"],
            "买进区间": f"{levels['buy_low']}-{levels['buy_high']}",
            "卖出区间": f"{levels['sell_low']}-{levels['sell_high']}",
            "昨收": round(prev_close, 3),
            "昨高": round(prev_high, 3),
            "昨低": round(prev_low, 3),
            "集合竞价价": round(auction_price, 3) if auction_price else "",
            "当前价": round(current_price, 3) if current_price else "",
            "实时行情时间": " ".join(part for part in [quote_date, str(quote.get("行情时间", "")).strip()] if part),
            "ATR": round(atr, 3) if atr else "",
            "前15分钟高": round(minute_stats["morning_high"], 3) if minute_stats["morning_high"] else "",
            "前15分钟低": round(minute_stats["morning_low"], 3) if minute_stats["morning_low"] else "",
            "历史T次数": trade["trade_count"],
            "历史T胜率": trade["win_rate"],
            "历史T均收益率": trade["avg_return_pct"],
            "历史T均利润": trade["avg_profit"],
            "次日上涨概率": safe_float(model.get("next_day_up_probability", model.get("次日上涨概率", 0))),
            "达到1%概率": safe_float(model.get("hit_1pct_probability", model.get("达到1%概率", 0))),
            "达到2%概率": safe_float(model.get("hit_2pct_probability", model.get("达到2%概率", 0))),
            "止损概率": safe_float(model.get("stop_2pct_probability", model.get("止损概率", 0))),
        }
        row["算法依据"] = reason_text(row)
        row["AI辅助"] = "待生成"
        rows.append(row)

    return rows


def write_report(df: pd.DataFrame, api_usage: list[dict[str, Any]]) -> None:
    lines = [
        "# 开盘支撑压力与T区间",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 用途：开盘后先看支撑/压力，再决定是否低吸、止盈或等待。",
        "- 口径：前一交易日日线 + 当日集合竞价/开盘价 + 分钟线 + 历史T交易 + 模型概率；AI只做辅助解释。",
        "",
    ]
    if not df.empty:
        lines.append(df.to_markdown(index=False))
    if api_usage:
        lines.extend(["", "## AI调用", "", pd.DataFrame(api_usage).to_markdown(index=False)])
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")


def run_opening_levels(stock_code: str | None = None, stock_name: str | None = None, use_ai: bool = True) -> pd.DataFrame:
    config = load_yaml_config("config.yaml", DEFAULT_CONFIG)
    rows = build_stock_rows(stock_code or "", stock_name or "")
    ok_rows = [row for row in rows if row.get("状态") == "成功"]
    api_usage: list[dict[str, Any]] = []
    if use_ai and ok_rows:
        max_ai = int(config.get("opening_levels", {}).get("max_ai_stocks", 4) or 4)
        ai_result, api_usage = call_ai(config, ok_rows[:max_ai])
        for row in rows:
            code = normalize_code(row.get("股票代码", ""))
            if code in ai_result:
                row["AI辅助"] = ai_result[code]
            elif row.get("状态") == "成功":
                row["AI辅助"] = "AI未返回，按算法区间"

    df = pd.DataFrame(rows)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    if api_usage:
        pd.DataFrame(api_usage).to_csv(API_USAGE_CSV, index=False, encoding="utf-8-sig")
    write_report(df, api_usage)
    print(f"开盘支撑压力已生成：{OUTPUT_CSV}")
    print(df.to_string(index=False))
    return df


if __name__ == "__main__":
    run_opening_levels()
