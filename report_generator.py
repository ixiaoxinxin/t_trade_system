# report_generator.py
# -*- coding: utf-8 -*-

"""
v1.2 交易计划生成器

功能：
1. 读取 output/overnight_t_candidates.csv
2. 取综合评分前20只
3. 生成：
   - 重点观察
   - 低吸候选
   - 放弃名单
4. 输出 output/daily_plan.md
"""

from pathlib import Path
from datetime import datetime

import pandas as pd


INPUT_FILE = Path("output/overnight_t_candidates.csv")
OUTPUT_FILE = Path("output/daily_plan.md")


def safe_float(value, default=0.0) -> float:
    """
    安全转 float
    """

    try:
        return float(value)
    except Exception:
        return default


def format_price(value) -> str:
    """
    格式化价格
    """

    return f"{safe_float(value):.2f}"


def get_low_buy_range(ma5: float) -> str:
    """
    低吸区间：MA5 附近 ±1%
    """

    low = ma5 * 0.99
    high = ma5 * 1.01

    return f"{low:.2f} - {high:.2f}"


def get_stop_loss(ma5: float) -> str:
    """
    止损价：MA5 下方 2%
    """

    stop_loss = ma5 * 0.98

    return f"{stop_loss:.2f}"


def get_sell_plan(close_price: float, ma5: float, rise_5d: float, amplitude_5d: float) -> str:
    """
    次日卖出计划
    """

    if rise_5d >= 15:
        return "次日冲高优先减仓，若高开不追，回落跌破分时均线放弃。"

    if amplitude_5d >= 25:
        return "波动较大，只做快进快出；高开3%以上优先卖，不做恋战。"

    if close_price > ma5:
        return "若次日高开或冲高1.5%-3%，分批止盈；若低开靠近MA5再观察承接。"

    return "只低吸不追高，未回到MA5附近不主动开仓。"


def get_position_advice(close_price: float) -> str:
    """
    仓位建议：单票不超过3000-5000元
    """

    shares_3000 = int(3000 // close_price // 100 * 100)
    shares_5000 = int(5000 // close_price // 100 * 100)

    if shares_3000 <= 0:
        return "价格偏高，单票最多100股观察仓。"

    if shares_5000 <= shares_3000:
        return f"建议 {shares_3000} 股，控制在约3000元附近。"

    return f"建议 {shares_3000}-{shares_5000} 股，单票控制在3000-5000元。"


def build_stock_plan(row: pd.Series) -> dict:
    """
    为单只股票生成交易计划字段
    """

    code = str(row.get("股票代码", "")).zfill(6)
    name = str(row.get("股票名称", ""))
    tag = str(row.get("热点标签", "未归类"))

    close_price = safe_float(row.get("最新收盘价", 0))
    ma5 = safe_float(row.get("MA5", 0))
    rise_5d = safe_float(row.get("最近5日涨幅", 0))
    amplitude_5d = safe_float(row.get("最近5日振幅", 0))

    return {
        "股票代码": code,
        "股票名称": name,
        "热点标签": tag,
        "最新收盘价": format_price(close_price),
        "MA5": format_price(ma5),
        "参考低吸区间": get_low_buy_range(ma5),
        "止损价": get_stop_loss(ma5),
        "次日卖出计划": get_sell_plan(close_price, ma5, rise_5d, amplitude_5d),
        "仓位建议": get_position_advice(close_price),
    }


def make_markdown_table(rows: list[dict]) -> str:
    """
    生成 Markdown 表格
    """

    if not rows:
        return "无。\n"

    headers = [
        "股票代码",
        "股票名称",
        "热点标签",
        "最新收盘价",
        "MA5",
        "参考低吸区间",
        "止损价",
        "次日卖出计划",
        "仓位建议",
    ]

    lines = []

    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")

    return "\n".join(lines) + "\n"


def generate_daily_plan():
    """
    生成每日交易计划
    """

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"找不到候选池文件：{INPUT_FILE}")

    df = pd.read_csv(INPUT_FILE, dtype={"股票代码": str})

    if df.empty:
        raise ValueError("候选池为空，无法生成交易计划")

    required_cols = [
        "股票代码",
        "股票名称",
        "热点标签",
        "最新收盘价",
        "MA5",
        "最近5日振幅",
        "最近5日涨幅",
        "综合评分",
    ]

    missing_cols = [col for col in required_cols if col not in df.columns]

    if missing_cols:
        raise ValueError(f"候选池缺少字段：{missing_cols}")

    df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)

    numeric_cols = [
        "最新收盘价",
        "MA5",
        "最近5日振幅",
        "最近5日涨幅",
        "综合评分",
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=numeric_cols)

    # 按综合评分排序，只取前20
    top20 = df.sort_values("综合评分", ascending=False).head(20).copy()

    # 重点观察：综合评分前5
    focus_df = top20.head(5).copy()

    # 低吸候选：最新收盘价接近MA5，且最近5日涨幅不超过15%
    top20["距离MA5百分比"] = (top20["最新收盘价"] - top20["MA5"]) / top20["MA5"] * 100

    low_buy_df = top20[
        (top20["距离MA5百分比"].abs() <= 3)
        & (top20["最近5日涨幅"] <= 15)
    ].copy()

    # 最多观察2只
    low_buy_df = low_buy_df.head(2)

    # 放弃名单：涨幅过高、振幅过高、热点标签未归类/未分类
    abandon_df = top20[
        (top20["最近5日涨幅"] > 15)
        | (top20["最近5日振幅"] > 25)
        | (top20["热点标签"].isin(["未归类", "未分类", ""]))
    ].copy()

    focus_rows = [build_stock_plan(row) for _, row in focus_df.iterrows()]
    low_buy_rows = [build_stock_plan(row) for _, row in low_buy_df.iterrows()]
    abandon_rows = [build_stock_plan(row) for _, row in abandon_df.iterrows()]

    today = datetime.now().strftime("%Y-%m-%d")

    md = f"""# A股隔日T交易计划

生成日期：{today}

数据来源：`output/overnight_t_candidates.csv`

---

## 一、执行原则

- 单票仓位控制在 `3000-5000 元`
- 最多实际观察 `2 只`
- 不追高，只看 MA5 附近低吸机会
- 跌破止损价，不补仓，先退出
- 高开冲高优先兑现，不恋战

---

## 二、重点观察：综合评分前5

{make_markdown_table(focus_rows)}

---

## 三、低吸候选：接近 MA5 且5日涨幅不超过15%

{make_markdown_table(low_buy_rows)}

---

## 四、放弃名单：涨幅过高 / 振幅过高 / 热点未归类

{make_markdown_table(abandon_rows)}

---

## 五、明日操作限制

1. 最多只做 `2 只`
2. 每只只开 `3000-5000 元`
3. 低吸区间不到，不开仓
4. 涨幅已经过高的，只观察，不追
5. 当天亏损达到计划止损，停止交易

"""

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    OUTPUT_FILE.write_text(md, encoding="utf-8")

    print(f"交易计划已生成：{OUTPUT_FILE}")


if __name__ == "__main__":
    generate_daily_plan()