# sell_signal_engine.py
# -*- coding: utf-8 -*-

"""
A股隔日T系统 v2.1.0：卖点引擎 + PushPlus 推送

功能：
1. 读取尾盘确认后的 A/B 核心候选
2. 获取分钟数据
3. 计算卖点因子
4. 生成卖出建议
5. 推送到微信
"""

from pathlib import Path
from datetime import datetime
import json
import os
from urllib.request import Request, urlopen

import pandas as pd

from data_provider import get_stock_minute


FINAL_WATCHLIST_FILE = Path("output/final_watchlist.csv")
MARKET_ENV_FILE = Path("output/market_environment.json")

OUTPUT_CSV = Path("output/sell_signal.csv")
OUTPUT_MD = Path("output/sell_signal.md")


CONFIG = {
    "include_grades": ["A", "B"],

    "take_profit_1": 1.0,
    "take_profit_2": 2.0,
    "strong_take_profit": 3.0,
    "stop_loss": -2.0,

    "pullback_warn": 1.5,
    "pullback_sell": 2.0,

    "keep_ratio_strong": 70.0,
    "keep_ratio_normal": 50.0,
    "keep_ratio_weak": 30.0,

    "pushplus": {
        "enabled": True,
        "url": "https://www.pushplus.plus/send",
        # 优先使用环境变量；如果没有环境变量，则使用你提供的 token
        "token": os.getenv("PUSHPLUS_TOKEN", "b75b94a8e3ac44db9237ad16c3a4b170"),
    },
}


def safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def normalize_code(code) -> str:
    return str(code).zfill(6)


def load_market_environment() -> dict:
    default_env = {
        "市场环境": "未知",
        "风险等级": "未知",
        "是否允许隔夜": "未知",
        "建议仓位": "未知",
        "交易建议": "未读取到市场环境。",
    }

    if not MARKET_ENV_FILE.exists():
        return default_env

    try:
        return json.loads(MARKET_ENV_FILE.read_text(encoding="utf-8"))
    except Exception:
        return default_env


def standardize_minute_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()

    rename_map = {
        "时间": "datetime",
        "日期": "datetime",
        "day": "datetime",
        "date": "datetime",
        "成交时间": "datetime",
        "开盘": "open",
        "开盘价": "open",
        "最高": "high",
        "最高价": "high",
        "最低": "low",
        "最低价": "low",
        "收盘": "close",
        "收盘价": "close",
        "最新价": "close",
        "成交量": "volume",
        "成交额": "amount",
    }

    df = df.rename(columns=rename_map)

    if "datetime" not in df.columns:
        return pd.DataFrame()

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")

    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    required = ["datetime", "open", "high", "low", "close"]

    if any(col not in df.columns for col in required):
        return pd.DataFrame()

    df = df.dropna(subset=required)
    df = df.sort_values("datetime").reset_index(drop=True)

    if "amount" not in df.columns:
        df["amount"] = 0.0

    if "volume" not in df.columns:
        df["volume"] = 0.0

    return df


def get_today_minute_data(symbol: str) -> pd.DataFrame:
    minute_df = get_stock_minute(symbol)
    minute_df = standardize_minute_columns(minute_df)

    if minute_df.empty:
        return pd.DataFrame()

    latest_date = minute_df["datetime"].dt.date.max()

    today_df = minute_df[
        minute_df["datetime"].dt.date == latest_date
    ].copy()

    return today_df.sort_values("datetime").reset_index(drop=True)


def get_reference_price(row: pd.Series) -> float:
    for col in ["收盘价", "最新收盘价", "隔夜参考价", "买入参考价"]:
        price = safe_float(row.get(col, 0))
        if price > 0:
            return price

    return 0.0


def calculate_vwap_like_price(df: pd.DataFrame) -> float:
    """
    计算近似分时均价线。
    如果没有成交量，就用 close 均值兜底。
    """

    if df.empty:
        return 0.0

    if "volume" in df.columns and df["volume"].sum() > 0:
        return float((df["close"] * df["volume"]).sum() / df["volume"].sum())

    return float(df["close"].mean())


def classify_ma_status(current_price: float, avg_price: float) -> str:
    if avg_price <= 0:
        return "未知"

    if current_price >= avg_price:
        return "均线上方"

    return "跌破均线"


def classify_keep_ratio(keep_ratio: float, max_pct: float) -> str:
    if max_pct <= 0:
        return "无冲高"

    if keep_ratio >= CONFIG["keep_ratio_strong"]:
        return "强保持"

    if keep_ratio >= CONFIG["keep_ratio_normal"]:
        return "正常保持"

    if keep_ratio >= CONFIG["keep_ratio_weak"]:
        return "弱保持"

    return "假强"


def get_sell_signal(
    grade: str,
    market_env: str,
    current_pct: float,
    max_pct: float,
    pullback_pct: float,
    keep_ratio: float,
    ma_status: str,
    structure: str,
) -> tuple[str, str]:
    """
    返回：
    - 卖出信号
    - 卖出理由
    """

    if current_pct <= CONFIG["stop_loss"]:
        return "止损", "当前跌幅已触发-2%止损线，不补仓，优先退出。"

    if market_env in ["情绪冰点", "系统风险"]:
        if current_pct >= CONFIG["take_profit_1"]:
            return "止盈", "系统风险/情绪冰点环境下，有1%以上利润优先兑现。"
        if pullback_pct >= CONFIG["pullback_warn"]:
            return "清仓", "系统风险环境下冲高回落，优先防守。"

    if market_env == "偏弱":
        if current_pct >= CONFIG["take_profit_2"]:
            return "止盈", "偏弱市场中已达到2%目标，优先兑现。"
        if pullback_pct >= CONFIG["pullback_warn"]:
            return "减仓", "偏弱市场中高点回撤超过1.5%，先减仓锁利润。"

    if pullback_pct >= CONFIG["pullback_sell"]:
        return "清仓", "高点回撤超过2%，按冲高失败处理。"

    if pullback_pct >= CONFIG["pullback_warn"]:
        return "减仓", "高点回撤超过1.5%，进入减仓区。"

    if keep_ratio < CONFIG["keep_ratio_weak"] and max_pct >= CONFIG["take_profit_1"]:
        return "清仓", "冲高保持率低于30%，资金兑现明显。"

    if ma_status == "跌破均线" and current_pct > 0:
        return "减仓", "当前价跌破分时均价线，承接转弱，先减仓。"

    if current_pct >= CONFIG["strong_take_profit"]:
        return "止盈", "当前涨幅达到3%，属于强止盈区，不恋战。"

    if current_pct >= CONFIG["take_profit_2"]:
        if grade == "A" and ("强势横盘" in structure or keep_ratio >= 70):
            return "持有", "A级强结构且冲高保持良好，可继续观察二次冲高。"
        return "止盈", "当前涨幅达到2%，普通结构优先兑现。"

    if current_pct >= CONFIG["take_profit_1"]:
        return "持有", "当前涨幅达到1%，进入止盈观察区，继续看回撤和均线。"

    return "持有", "当前未触发止盈/止损，继续观察。"


def build_sell_signal_row(row: pd.Series, market_env: dict) -> dict | None:
    symbol = normalize_code(row.get("股票代码", ""))
    name = str(row.get("股票名称", ""))

    reference_price = get_reference_price(row)

    if reference_price <= 0:
        print(f"{symbol} {name} 缺少参考价，跳过")
        return None

    minute_df = get_today_minute_data(symbol)

    if minute_df.empty:
        print(f"{symbol} {name} 分钟数据为空，跳过")
        return None

    current_price = safe_float(minute_df["close"].iloc[-1])
    high_price = safe_float(minute_df["high"].max())
    low_price = safe_float(minute_df["low"].min())
    avg_price = calculate_vwap_like_price(minute_df)

    current_pct = (current_price - reference_price) / reference_price * 100
    max_pct = (high_price - reference_price) / reference_price * 100
    min_pct = (low_price - reference_price) / reference_price * 100
    pullback_pct = max_pct - current_pct

    if max_pct > 0:
        keep_ratio = current_pct / max_pct * 100
    else:
        keep_ratio = 0.0

    ma_status = classify_ma_status(current_price, avg_price)
    keep_ratio_tag = classify_keep_ratio(keep_ratio, max_pct)

    grade = str(row.get("隔夜建议等级", ""))
    structure = str(row.get("分时结构标签", ""))
    tail_tag = str(row.get("尾盘抢筹标签", ""))
    env = str(market_env.get("市场环境", "未知"))

    signal, reason = get_sell_signal(
        grade=grade,
        market_env=env,
        current_pct=current_pct,
        max_pct=max_pct,
        pullback_pct=pullback_pct,
        keep_ratio=keep_ratio,
        ma_status=ma_status,
        structure=structure,
    )

    return {
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "股票代码": symbol,
        "股票名称": name,
        "隔夜等级": grade,
        "市场环境": env,
        "参考价": round(reference_price, 2),
        "当前价": round(current_price, 2),
        "盘中最高": round(high_price, 2),
        "盘中最低": round(low_price, 2),
        "分时均价": round(avg_price, 2),
        "当前涨幅": round(current_pct, 2),
        "最高涨幅": round(max_pct, 2),
        "最低涨幅": round(min_pct, 2),
        "高点回撤": round(pullback_pct, 2),
        "冲高保持率": round(keep_ratio, 2),
        "保持率标签": keep_ratio_tag,
        "均线状态": ma_status,
        "卖出信号": signal,
        "卖出理由": reason,
        "最终评分": safe_float(row.get("最终评分", 0)),
        "尾盘评分": safe_float(row.get("尾盘评分", 0)),
        "分时结构标签": structure,
        "尾盘抢筹标签": tail_tag,
    }


def build_sell_signal() -> pd.DataFrame:
    if not FINAL_WATCHLIST_FILE.exists():
        raise FileNotFoundError(f"找不到文件：{FINAL_WATCHLIST_FILE}")

    df = pd.read_csv(FINAL_WATCHLIST_FILE, dtype={"股票代码": str})

    if df.empty:
        raise ValueError("final_watchlist.csv 为空，无法生成卖点信号")

    df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)

    if "隔夜建议等级" in df.columns:
        df = df[df["隔夜建议等级"].isin(CONFIG["include_grades"])].copy()

    market_env = load_market_environment()

    rows = []

    for _, row in df.iterrows():
        result = build_sell_signal_row(row, market_env)

        if result is not None:
            rows.append(result)

    signal_df = pd.DataFrame(rows)

    if signal_df.empty:
        return signal_df

    signal_order = {
        "止损": 1,
        "清仓": 2,
        "止盈": 3,
        "减仓": 4,
        "持有": 5,
    }

    signal_df["_rank"] = signal_df["卖出信号"].map(signal_order).fillna(9)

    signal_df = signal_df.sort_values(
        by=["_rank", "当前涨幅", "最高涨幅"],
        ascending=[True, False, False],
    ).drop(columns=["_rank"]).reset_index(drop=True)

    return signal_df


def build_markdown(signal_df: pd.DataFrame) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if signal_df.empty:
        return f"""# 卖点信号 v2.1.0

生成时间：{now}

暂无 A/B 核心候选卖点信号。
"""

    core_cols = [
        "股票代码",
        "股票名称",
        "隔夜等级",
        "市场环境",
        "参考价",
        "当前价",
        "当前涨幅",
        "最高涨幅",
        "高点回撤",
        "冲高保持率",
        "保持率标签",
        "均线状态",
        "卖出信号",
        "卖出理由",
    ]

    md = f"""# 卖点信号 v2.1.0

生成时间：{now}

---

## 一、卖点规则

| 条件 | 动作 |
|---|---|
| 当前涨幅 <= -2% | 止损 |
| 系统风险/情绪冰点 + 盈利1%以上 | 止盈 |
| 偏弱市场 + 盈利2%以上 | 止盈 |
| 高点回撤 > 2% | 清仓 |
| 高点回撤 > 1.5% | 减仓 |
| 冲高保持率 < 30% | 清仓 |
| 跌破分时均线 | 减仓 |
| A级强结构 + 保持率高 | 可继续持有 |

---

## 二、当前卖点信号

{signal_df[core_cols].to_markdown(index=False)}

---

## 三、完整明细

{signal_df.to_markdown(index=False)}
"""

    return md


def send_pushplus_message(title: str, content: str) -> bool:
    if not CONFIG["pushplus"]["enabled"]:
        print("PushPlus 未启用。")
        return False

    token = CONFIG["pushplus"]["token"]

    if not token:
        print("PushPlus token 为空，跳过推送。")
        return False

    payload = {
        "token": token,
        "title": title,
        "content": content,
        "template": "markdown",
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = Request(
        CONFIG["pushplus"]["url"],
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=10) as response:
            raw = response.read().decode("utf-8", errors="ignore")
            print(f"PushPlus 返回：{raw}")
            return True

    except Exception as e:
        print(f"PushPlus 推送失败：{e}")
        return False


def run_sell_signal_engine() -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    signal_df = build_sell_signal()

    signal_df.to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    md = build_markdown(signal_df)

    OUTPUT_MD.write_text(md, encoding="utf-8")

    print("卖点信号生成完成。")
    print(f"CSV：{OUTPUT_CSV}")
    print(f"Markdown：{OUTPUT_MD}")
    print(f"信号数量：{len(signal_df)}")

    send_pushplus_message(
        title="A股隔日T卖点信号",
        content=md,
    )


if __name__ == "__main__":
    run_sell_signal_engine()