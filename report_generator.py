# report_generator.py
# -*- coding: utf-8 -*-

"""
A股隔日T交易计划生成器 v1.6.3

目标：
1. 优先读取尾盘确认结果 final_watchlist.csv
2. 只允许 A/B 进入交易池
3. C 进入观察池
4. D 进入放弃池
5. 如果没有 A/B，明确提示空仓
"""

from pathlib import Path
from datetime import datetime

import pandas as pd
import yaml


CONFIG_FILE = Path("config.yaml")

FINAL_WATCHLIST_FILE = Path("output/final_watchlist.csv")
CANDIDATES_FILE = Path("output/overnight_t_candidates.csv")
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


def safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def normalize_code(code) -> str:
    return str(code).zfill(6)


def format_price(value) -> str:
    return f"{safe_float(value):.2f}"


def read_source_data() -> tuple[pd.DataFrame, str]:
    """
    优先读取 final_watchlist.csv。
    如果不存在，则回退 overnight_t_candidates.csv。
    """

    if FINAL_WATCHLIST_FILE.exists():
        df = pd.read_csv(FINAL_WATCHLIST_FILE, dtype={"股票代码": str})
        return df, str(FINAL_WATCHLIST_FILE)

    if CANDIDATES_FILE.exists():
        df = pd.read_csv(CANDIDATES_FILE, dtype={"股票代码": str})
        return df, str(CANDIDATES_FILE)

    raise FileNotFoundError("找不到 final_watchlist.csv 或 overnight_t_candidates.csv")


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    兼容不同版本字段。
    """

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
    """
    用于生成低吸区间的参考价。
    优先 MA5，其次收盘价，其次最新收盘价。
    """

    ma5 = safe_float(row.get("MA5", 0))
    close_price = safe_float(row.get("收盘价", 0))
    latest_close = safe_float(row.get("最新收盘价", 0))

    if ma5 > 0:
        return ma5

    if close_price > 0:
        return close_price

    return latest_close


def get_low_buy_range(row: pd.Series) -> str:
    """
    低吸区间：
    - 有 MA5：MA5 附近 -1% 到 +1%
    - 没 MA5：收盘价下方 1%-2%
    """

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
    """
    动态止损：
    - 振幅小：参考价下2%
    - 振幅中：参考价下3%
    - 振幅大：参考价下4%
    """

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


def get_position_advice(row: pd.Series) -> str:
    """
    仓位建议。
    """

    close_price = safe_float(row.get("收盘价", 0))
    latest_close = safe_float(row.get("最新收盘价", 0))

    price = close_price if close_price > 0 else latest_close

    if price <= 0:
        return "价格异常，不操作。"

    min_shares = int(SINGLE_STOCK_MIN // price // 100 * 100)
    max_shares = int(SINGLE_STOCK_MAX // price // 100 * 100)

    if min_shares <= 0:
        return "价格偏高，不适合当前小资金试盘。"

    if max_shares <= min_shares:
        return f"建议 {min_shares} 股，控制在约 {SINGLE_STOCK_MIN:.0f} 元附近。"

    return f"建议 {min_shares}-{max_shares} 股，单票控制在 {SINGLE_STOCK_MIN:.0f}-{SINGLE_STOCK_MAX:.0f} 元。"


def build_plan_row(row: pd.Series) -> dict:
    return {
        "股票代码": normalize_code(row.get("股票代码", "")),
        "股票名称": str(row.get("股票名称", "")),
        "热点标签": str(row.get("热点标签", "")),
        "候选评分": f"{safe_float(row.get('候选评分', 0)):.2f}",
        "尾盘评分": f"{safe_float(row.get('尾盘评分', 0)):.2f}",
        "最终评分": f"{safe_float(row.get('最终评分', 0)):.2f}",
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


def generate_daily_plan() -> None:
    df, source_name = read_source_data()

    if df.empty:
        raise ValueError("输入数据为空，无法生成交易计划")

    df = ensure_columns(df)

    df = df.sort_values(
        by=["隔夜建议等级", "最终评分"],
        ascending=[True, False]
    ).reset_index(drop=True)

    trade_df = df[df["隔夜建议等级"].isin(["A", "B"])].copy()
    watch_df = df[df["隔夜建议等级"] == "C"].copy()
    abandon_df = df[df["隔夜建议等级"] == "D"].copy()

    trade_df = trade_df.sort_values("最终评分", ascending=False).head(MAX_TRADE_COUNT)

    trade_rows = [build_plan_row(row) for _, row in trade_df.iterrows()]
    watch_rows = [build_plan_row(row) for _, row in watch_df.iterrows()]
    abandon_rows = [build_plan_row(row) for _, row in abandon_df.iterrows()]

    today = datetime.now().strftime("%Y-%m-%d")

    if trade_df.empty:
        trade_summary = "明日交易池为空：没有 A/B 级标的，原则上空仓，不主动交易。"
    else:
        trade_summary = f"明日交易池共 {len(trade_df)} 只，最多只做 {MAX_TRADE_COUNT} 只。"

    md = f"""# A股隔日T交易计划 v1.6.3

生成日期：{today}

数据来源：`{source_name}`

---

## 一、执行原则

- 只允许 `A/B` 级进入交易池
- `C` 级只观察，不主动买入
- `D` 级放弃
- 单票仓位控制在 `{SINGLE_STOCK_MIN:.0f}-{SINGLE_STOCK_MAX:.0f} 元`
- 最多实际操作 `{MAX_TRADE_COUNT} 只`
- 低吸区间不到，不开仓
- 跌破止损价，不补仓，先退出
- 高开冲高优先兑现，不恋战

---

## 二、明日交易池

{trade_summary}

{make_markdown_table(trade_rows)}

---

## 三、观察池

{make_markdown_table(watch_rows)}

---

## 四、放弃池

{make_markdown_table(abandon_rows)}

---

## 五、盘后复盘字段

| 股票代码 | 是否买入 | 买入价 | 卖出价 | 盈亏 | 是否按计划执行 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |

"""

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(md, encoding="utf-8")

    print(f"交易计划已生成：{OUTPUT_FILE}")
    print(f"数据来源：{source_name}")
    print(f"交易池数量：{len(trade_rows)}")
    print(f"观察池数量：{len(watch_rows)}")
    print(f"放弃池数量：{len(abandon_rows)}")


if __name__ == "__main__":
    generate_daily_plan()