# report_generator.py
# -*- coding: utf-8 -*-

"""
A股隔日T交易计划生成器 v1.9.2

升级点：
1. 优先读取 output/final_watchlist.csv
2. 接入 output/market_environment.json
3. 根据市场环境调整交易池和仓位
4. 系统风险日自动降仓
5. 情绪冰点日自动空仓
"""

from pathlib import Path
from datetime import datetime
import json

import pandas as pd
import yaml


CONFIG_FILE = Path("config.yaml")

FINAL_WATCHLIST_FILE = Path("output/final_watchlist.csv")
CANDIDATES_FILE = Path("output/overnight_t_candidates.csv")
MARKET_ENV_FILE = Path("output/market_environment.json")
OUTPUT_FILE = Path("output/daily_plan.md")


def load_config() -> dict:
    default_config = {
        "capital": {
            "single_stock_min": 3000,
            "single_stock_max": 5000,
            "max_trade_count": 2,
        }
    }

    if not CONFIG_FILE.exists():
        return default_config

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}

        for section, values in default_config.items():
            if section not in user_config:
                user_config[section] = values
            else:
                for key, value in values.items():
                    user_config[section].setdefault(key, value)

        return user_config

    except Exception:
        return default_config


CONFIG = load_config()

SINGLE_STOCK_MIN = float(CONFIG["capital"]["single_stock_min"])
SINGLE_STOCK_MAX = float(CONFIG["capital"]["single_stock_max"])
MAX_TRADE_COUNT = int(CONFIG["capital"]["max_trade_count"])


def load_market_environment() -> dict:
    """
    读取市场环境判断。
    如果文件不存在，则默认市场环境正常。
    """

    default_env = {
        "市场环境": "未知",
        "风险等级": "未知",
        "是否允许隔夜": "是",
        "建议仓位": "按原计划",
        "交易建议": "未读取到市场环境文件，按原计划执行，但需人工确认。",
    }

    if not MARKET_ENV_FILE.exists():
        return default_env

    try:
        return json.loads(MARKET_ENV_FILE.read_text(encoding="utf-8"))
    except Exception:
        return default_env


MARKET_ENV = load_market_environment()


def safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def normalize_code(code) -> str:
    return str(code).zfill(6)


def read_source_data() -> tuple[pd.DataFrame, str]:
    if FINAL_WATCHLIST_FILE.exists():
        df = pd.read_csv(FINAL_WATCHLIST_FILE, dtype={"股票代码": str})
        return df, str(FINAL_WATCHLIST_FILE)

    if CANDIDATES_FILE.exists():
        df = pd.read_csv(CANDIDATES_FILE, dtype={"股票代码": str})
        return df, str(CANDIDATES_FILE)

    raise FileNotFoundError("找不到 final_watchlist.csv 或 overnight_t_candidates.csv")


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)

    default_cols = {
        "热点标签": "未归类",
        "候选评分": 0,
        "尾盘评分": 0,
        "最终评分": df["综合评分"] if "综合评分" in df.columns else 0,
        "隔夜建议等级": "C",
        "隔夜建议说明": "无尾盘确认，仅观察。",
        "MA5": 0,
        "收盘价": df["最新收盘价"] if "最新收盘价" in df.columns else 0,
        "最新收盘价": df["收盘价"] if "收盘价" in df.columns else 0,
        "今日振幅": df["最近5日振幅"] if "最近5日振幅" in df.columns else 0,
        "风险等级": "中",
    }

    for col, default_value in default_cols.items():
        if col not in df.columns:
            df[col] = default_value

    numeric_cols = [
        "候选评分",
        "尾盘评分",
        "最终评分",
        "MA5",
        "收盘价",
        "最新收盘价",
        "今日振幅",
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    return df


def get_base_price(row: pd.Series) -> float:
    ma5 = safe_float(row.get("MA5", 0))
    close_price = safe_float(row.get("收盘价", 0))
    latest_close = safe_float(row.get("最新收盘价", 0))

    if ma5 > 0:
        return ma5

    if close_price > 0:
        return close_price

    return latest_close


def get_low_buy_range(row: pd.Series) -> str:
    ma5 = safe_float(row.get("MA5", 0))
    base_price = get_base_price(row)

    if base_price <= 0:
        return "-"

    if ma5 > 0:
        low = ma5 * 0.99
        high = ma5 * 1.01
    else:
        low = base_price * 0.98
        high = base_price * 0.99

    return f"{low:.2f} - {high:.2f}"


def get_stop_loss(row: pd.Series) -> str:
    base_price = get_base_price(row)
    amplitude = safe_float(row.get("今日振幅", 0))

    if base_price <= 0:
        return "-"

    if amplitude >= 6:
        stop_loss = base_price * 0.96
    elif amplitude >= 4:
        stop_loss = base_price * 0.97
    else:
        stop_loss = base_price * 0.98

    return f"{stop_loss:.2f}"


def get_position_range_by_market(row: pd.Series) -> tuple[float, float, str]:
    """
    根据市场环境返回仓位区间。
    """

    env = MARKET_ENV.get("市场环境", "未知")
    grade = str(row.get("隔夜建议等级", "C"))
    risk_level = str(row.get("风险等级", "中"))

    min_capital = SINGLE_STOCK_MIN
    max_capital = SINGLE_STOCK_MAX
    reason = "按原计划。"

    if env == "正常":
        reason = "市场正常，按原仓位计划。"

    elif env == "偏弱":
        min_capital = max(1000, SINGLE_STOCK_MIN * 0.5)
        max_capital = max(1500, SINGLE_STOCK_MAX * 0.5)
        reason = "市场偏弱，仓位减半。"

    elif env == "系统风险":
        if grade == "A" and risk_level in ["低", "未知"]:
            min_capital = 1000
            max_capital = 2000
            reason = "系统风险日，只允许A级低风险，小仓位。"
        else:
            min_capital = 0
            max_capital = 0
            reason = "系统风险日，非A级低风险不交易。"

    elif env == "情绪冰点":
        min_capital = 0
        max_capital = 0
        reason = "情绪冰点，不隔夜。"

    return min_capital, max_capital, reason


def get_position_advice(row: pd.Series) -> str:
    close_price = safe_float(row.get("收盘价", 0))
    latest_close = safe_float(row.get("最新收盘价", 0))
    price = close_price if close_price > 0 else latest_close

    if price <= 0:
        return "价格异常，不操作。"

    min_capital, max_capital, reason = get_position_range_by_market(row)

    if max_capital <= 0:
        return f"不操作。{reason}"

    min_shares = int(min_capital // price // 100 * 100)
    max_shares = int(max_capital // price // 100 * 100)

    if min_shares <= 0:
        return f"价格偏高，最多100股观察。{reason}"

    if max_shares <= min_shares:
        return f"建议 {min_shares} 股。{reason}"

    return f"建议 {min_shares}-{max_shares} 股。{reason}"


def build_plan_row(row: pd.Series) -> dict:
    return {
        "股票代码": normalize_code(row.get("股票代码", "")),
        "股票名称": str(row.get("股票名称", "")),
        "热点标签": str(row.get("热点标签", "")),
        "候选评分": f"{safe_float(row.get('候选评分', 0)):.2f}",
        "尾盘评分": f"{safe_float(row.get('尾盘评分', 0)):.2f}",
        "最终评分": f"{safe_float(row.get('最终评分', 0)):.2f}",
        "风险等级": str(row.get("风险等级", "")),
        "隔夜等级": str(row.get("隔夜建议等级", "")),
        "参考低吸区间": get_low_buy_range(row),
        "止损价": get_stop_loss(row),
        "仓位建议": get_position_advice(row),
        "隔夜建议说明": str(row.get("隔夜建议说明", "")),
    }


def make_markdown_table(rows: list[dict]) -> str:
    if not rows:
        return "无。\n"

    headers = [
        "股票代码",
        "股票名称",
        "热点标签",
        "候选评分",
        "尾盘评分",
        "最终评分",
        "风险等级",
        "隔夜等级",
        "参考低吸区间",
        "止损价",
        "仓位建议",
        "隔夜建议说明",
    ]

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")

    return "\n".join(lines) + "\n"


def filter_trade_pool_by_market(df: pd.DataFrame) -> pd.DataFrame:
    """
    根据市场环境过滤交易池。
    """

    env = MARKET_ENV.get("市场环境", "未知")

    if env == "情绪冰点":
        return df.iloc[0:0].copy()

    if env == "系统风险":
        return df[
            (df["隔夜建议等级"] == "A")
            & (df["风险等级"].astype(str).isin(["低", "未知"]))
        ].copy()

    return df[df["隔夜建议等级"].isin(["A", "B"])].copy()


def generate_daily_plan() -> None:
    df, source_name = read_source_data()

    if df.empty:
        raise ValueError("输入数据为空，无法生成交易计划")

    df = ensure_columns(df)

    df = df.sort_values(
        by=["隔夜建议等级", "最终评分"],
        ascending=[True, False]
    ).reset_index(drop=True)

    trade_df = filter_trade_pool_by_market(df)
    watch_df = df[df["隔夜建议等级"] == "C"].copy()
    abandon_df = df[df["隔夜建议等级"] == "D"].copy()

    trade_df = trade_df.sort_values("最终评分", ascending=False).head(MAX_TRADE_COUNT)

    trade_rows = [build_plan_row(row) for _, row in trade_df.iterrows()]
    watch_rows = [build_plan_row(row) for _, row in watch_df.iterrows()]
    abandon_rows = [build_plan_row(row) for _, row in abandon_df.iterrows()]

    today = datetime.now().strftime("%Y-%m-%d")

    env = MARKET_ENV.get("市场环境", "未知")
    env_risk = MARKET_ENV.get("风险等级", "未知")
    env_allow = MARKET_ENV.get("是否允许隔夜", "未知")
    env_position = MARKET_ENV.get("建议仓位", "未知")
    env_advice = MARKET_ENV.get("交易建议", "未读取到交易建议。")

    if trade_df.empty:
        trade_summary = "明日交易池为空：当前市场环境或个股等级不满足隔夜条件，原则上空仓。"
    else:
        trade_summary = f"明日交易池共 {len(trade_df)} 只，最多只做 {MAX_TRADE_COUNT} 只。"

    md = f"""# A股隔日T交易计划 v1.9.2

生成日期：{today}

数据来源：`{source_name}`

---

## 一、市场环境判断

| 项目 | 结果 |
|---|---|
| 市场环境 | {env} |
| 风险等级 | {env_risk} |
| 是否允许隔夜 | {env_allow} |
| 建议仓位 | {env_position} |
| 交易建议 | {env_advice} |

---

## 二、执行原则

- 正常：允许 `A/B` 低风险票隔夜
- 偏弱：只做 `A/B` 低风险，仓位减半
- 系统风险：只允许 `A` 级低风险，单票不超过 `2000 元`
- 情绪冰点：不隔夜
- `C` 级只观察，不主动买入
- `D` 级放弃
- 低吸区间不到，不开仓
- 跌破止损价，不补仓，先退出
- 高开冲高优先兑现，不恋战

---

## 三、明日交易池

{trade_summary}

{make_markdown_table(trade_rows)}

---

## 四、观察池

{make_markdown_table(watch_rows)}

---

## 五、放弃池

{make_markdown_table(abandon_rows)}

---

## 六、盘后复盘字段

| 股票代码 | 是否买入 | 买入价 | 卖出价 | 盈亏 | 是否按计划执行 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |

"""

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(md, encoding="utf-8")

    print(f"交易计划已生成：{OUTPUT_FILE}")
    print(f"数据来源：{source_name}")
    print(f"市场环境：{env}")
    print(f"交易建议：{env_advice}")
    print(f"交易池数量：{len(trade_rows)}")
    print(f"观察池数量：{len(watch_rows)}")
    print(f"放弃池数量：{len(abandon_rows)}")


if __name__ == "__main__":
    generate_daily_plan()