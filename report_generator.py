# report_generator.py
# -*- coding: utf-8 -*-

"""
A股隔日T交易计划生成器 v1.3

功能：
1. 读取 output/overnight_t_candidates.csv
2. 生成 output/daily_plan.md
3. 新增主观察池
4. 使用排他分组逻辑
5. 使用动态止损
6. 输出更接近实盘执行的交易计划
"""

from pathlib import Path
from datetime import datetime

import pandas as pd


INPUT_FILE = Path("output/overnight_t_candidates.csv")
OUTPUT_FILE = Path("output/daily_plan.md")


def safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def format_price(value) -> str:
    return f"{safe_float(value):.2f}"


def normalize_code(code) -> str:
    return str(code).zfill(6)


def is_unknown_tag(tag: str) -> bool:
    tag = str(tag).strip()
    return tag in ["", "未归类", "未分类", "未知", "未标记"]


def get_ma5_deviation(row: pd.Series) -> float:
    """
    获取距MA5偏离率。
    优先读取 v1.3 字段，否则自行计算。
    """

    if "距MA5偏离率" in row.index:
        return safe_float(row.get("距MA5偏离率", 0))

    close_price = safe_float(row.get("最新收盘价", 0))
    ma5 = safe_float(row.get("MA5", 0))

    if ma5 <= 0:
        return 999

    return (close_price - ma5) / ma5 * 100


def get_low_buy_range(ma5: float, amplitude_5d: float) -> str:
    """
    动态低吸区间：
    - 普通波动：MA5 ±1%
    - 中高波动：MA5 -1.5% 到 +1%
    - 极高波动：MA5 -2% 到 +0.5%
    """

    if amplitude_5d >= 30:
        low = ma5 * 0.98
        high = ma5 * 1.005
    elif amplitude_5d >= 20:
        low = ma5 * 0.985
        high = ma5 * 1.01
    else:
        low = ma5 * 0.99
        high = ma5 * 1.01

    return f"{low:.2f} - {high:.2f}"


def get_stop_loss(ma5: float, amplitude_5d: float) -> str:
    """
    动态止损：
    - 振幅 <15%：MA5下2%
    - 15%-25%：MA5下3%
    - >25%：MA5下4%
    """

    if amplitude_5d > 25:
        stop_loss = ma5 * 0.96
    elif amplitude_5d >= 15:
        stop_loss = ma5 * 0.97
    else:
        stop_loss = ma5 * 0.98

    return f"{stop_loss:.2f}"


def get_sell_plan(row: pd.Series) -> str:
    close_price = safe_float(row.get("最新收盘价", 0))
    ma5 = safe_float(row.get("MA5", 0))
    rise_5d = safe_float(row.get("最近5日涨幅", 0))
    amplitude_5d = safe_float(row.get("最近5日振幅", 0))
    priority = str(row.get("买入优先级", "C"))
    strategy_type = str(row.get("策略类型", "隔日T"))

    if priority == "A":
        return "只做计划低吸；若次日冲高2%-3%，优先兑现；若跌破止损，不补仓。"

    if amplitude_5d >= 30:
        return "高波动票，只做快进快出；高开3%以上不追，盘中冲高优先走。"

    if rise_5d >= 15:
        return "5日涨幅偏高，次日只看回落承接；冲高先减，不做恋战。"

    if strategy_type == "趋势低吸":
        return "低吸后看分时承接；若站上前高可持有到午后，否则冲高兑现。"

    if close_price > ma5:
        return "围绕MA5做隔日T；高开不追，低开接近MA5再观察。"

    return "只观察，不主动开仓。"


def get_position_advice(close_price: float, priority: str) -> str:
    """
    仓位建议：
    - A：3000-5000
    - B：3000附近
    - C：观察仓
    - D：不做
    """

    if close_price <= 0:
        return "价格异常，不操作。"

    shares_3000 = int(3000 // close_price // 100 * 100)
    shares_5000 = int(5000 // close_price // 100 * 100)

    if shares_3000 <= 0:
        return "价格偏高，不适合3W小资金试盘。"

    if priority == "A":
        if shares_5000 > shares_3000:
            return f"建议 {shares_3000}-{shares_5000} 股，单票3000-5000元。"
        return f"建议 {shares_3000} 股，控制在3000元附近。"

    if priority == "B":
        return f"建议 {shares_3000} 股，观察仓。"

    if priority == "C":
        return "仅观察，暂不开仓。"

    return "放弃。"


def get_abandon_reason(row: pd.Series) -> str:
    """
    判断放弃原因。
    """

    reasons = []

    tag = str(row.get("热点标签", ""))
    rise_5d = safe_float(row.get("最近5日涨幅", 0))
    amplitude_5d = safe_float(row.get("最近5日振幅", 0))
    score = safe_float(row.get("综合评分", 0))
    ma5_deviation = get_ma5_deviation(row)
    risk_level = str(row.get("风险等级", ""))

    if rise_5d > 18:
        reasons.append("5日涨幅过热")
    if amplitude_5d > 35:
        reasons.append("5日振幅极端")
    if ma5_deviation > 8:
        reasons.append("距离MA5过远")
    if is_unknown_tag(tag):
        reasons.append("热点标签未识别")
    if risk_level == "高":
        reasons.append("风险等级高")
    if score < 60:
        reasons.append("综合评分低")

    return "；".join(reasons)


def should_abandon(row: pd.Series) -> bool:
    """
    放弃条件，优先级最高。
    """

    reason = get_abandon_reason(row)
    return bool(reason)


def build_stock_plan(row: pd.Series, include_reason: bool = False) -> dict:
    code = normalize_code(row.get("股票代码", ""))
    name = str(row.get("股票名称", ""))
    tag = str(row.get("热点标签", "未归类"))

    close_price = safe_float(row.get("最新收盘价", 0))
    ma5 = safe_float(row.get("MA5", 0))
    amplitude_5d = safe_float(row.get("最近5日振幅", 0))

    priority = str(row.get("买入优先级", "C"))
    risk_level = str(row.get("风险等级", "中"))
    strategy_type = str(row.get("策略类型", "隔日T"))
    score = safe_float(row.get("综合评分", 0))

    result = {
        "股票代码": code,
        "股票名称": name,
        "热点标签": tag,
        "综合评分": f"{score:.2f}",
        "风险等级": risk_level,
        "策略类型": strategy_type,
        "买入优先级": priority,
        "最新收盘价": format_price(close_price),
        "MA5": format_price(ma5),
        "参考低吸区间": get_low_buy_range(ma5, amplitude_5d),
        "止损价": get_stop_loss(ma5, amplitude_5d),
        "次日卖出计划": get_sell_plan(row),
        "仓位建议": get_position_advice(close_price, priority),
    }

    if include_reason:
        result["放弃原因"] = get_abandon_reason(row)

    return result


def make_markdown_table(rows: list[dict], include_reason: bool = False) -> str:
    if not rows:
        return "无。\n"

    headers = [
        "股票代码",
        "股票名称",
        "热点标签",
        "综合评分",
        "风险等级",
        "策略类型",
        "买入优先级",
        "最新收盘价",
        "MA5",
        "参考低吸区间",
        "止损价",
        "次日卖出计划",
        "仓位建议",
    ]

    if include_reason:
        headers.append("放弃原因")

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")

    return "\n".join(lines) + "\n"


def generate_daily_plan():
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

    if "距MA5偏离率" in df.columns:
        numeric_cols.append("距MA5偏离率")

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["最新收盘价", "MA5", "最近5日振幅", "最近5日涨幅", "综合评分"])

    if "买入优先级" not in df.columns:
        df["买入优先级"] = "C"

    if "风险等级" not in df.columns:
        df["风险等级"] = "中"

    if "策略类型" not in df.columns:
        df["策略类型"] = "隔日T"

    if "距MA5偏离率" not in df.columns:
        df["距MA5偏离率"] = (df["最新收盘价"] - df["MA5"]) / df["MA5"] * 100

    priority_order = {"A": 1, "B": 2, "C": 3, "D": 4}
    df["priority_rank"] = df["买入优先级"].map(priority_order).fillna(9)

    top20 = df.sort_values(
        by=["priority_rank", "综合评分"],
        ascending=[True, False]
    ).head(20).copy()

    # 排他逻辑：先识别放弃
    top20["是否放弃"] = top20.apply(should_abandon, axis=1)

    tradable_df = top20[~top20["是否放弃"]].copy()
    abandon_df = top20[top20["是否放弃"]].copy()

    # 主观察池：真正可看的2只
    main_watch_df = tradable_df[
        (tradable_df["距MA5偏离率"] <= 5)
        & (tradable_df["最近5日涨幅"] <= 18)
        & (tradable_df["风险等级"] != "高")
    ].head(2)

    main_codes = set(main_watch_df["股票代码"].tolist())

    # 重点观察：排除主观察池后的前5
    focus_df = tradable_df[
        ~tradable_df["股票代码"].isin(main_codes)
    ].head(5)

    focus_codes = set(focus_df["股票代码"].tolist())

    # 低吸候选：排除主观察和重点观察
    low_buy_df = tradable_df[
        (~tradable_df["股票代码"].isin(main_codes))
        & (~tradable_df["股票代码"].isin(focus_codes))
        & (tradable_df["距MA5偏离率"].between(-1, 3))
        & (tradable_df["最近5日涨幅"] <= 15)
    ].head(3)

    main_watch_rows = [build_stock_plan(row) for _, row in main_watch_df.iterrows()]
    focus_rows = [build_stock_plan(row) for _, row in focus_df.iterrows()]
    low_buy_rows = [build_stock_plan(row) for _, row in low_buy_df.iterrows()]
    abandon_rows = [build_stock_plan(row, include_reason=True) for _, row in abandon_df.iterrows()]

    today = datetime.now().strftime("%Y-%m-%d")

    md = f"""# A股隔日T交易计划 v1.3

生成日期：{today}

数据来源：`output/overnight_t_candidates.csv`

---

## 一、执行原则

- 单票仓位控制在 `3000-5000 元`
- 最多实际操作 `2 只`
- 只做计划内股票，不临盘追陌生票
- 不追高，只看 MA5 附近低吸机会
- 跌破止损价，不补仓，先退出
- 高开冲高优先兑现，不恋战
- 主观察池优先级高于重点观察池
- 放弃名单不参与交易

---

## 二、主观察池：明日最多只看2只

{make_markdown_table(main_watch_rows)}

---

## 三、重点观察：备选跟踪

{make_markdown_table(focus_rows)}

---

## 四、低吸候选：只等 MA5 附近

{make_markdown_table(low_buy_rows)}

---

## 五、放弃名单：不参与交易

{make_markdown_table(abandon_rows, include_reason=True)}

---

## 六、明日操作限制

1. 最多只做 `2 只`
2. 每只只开 `3000-5000 元`
3. 买点不到，不开仓
4. 涨幅已经过热的，只观察，不追
5. 放弃名单不买
6. 当天亏损达到计划止损，停止交易

---

## 七、盘后复盘字段

明日收盘后请记录：

| 股票代码 | 是否买入 | 买入价 | 卖出价 | 盈亏 | 是否按计划执行 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |

"""

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(md, encoding="utf-8")

    print(f"交易计划已生成：{OUTPUT_FILE}")
    print(f"主观察池数量：{len(main_watch_rows)}")
    print(f"重点观察数量：{len(focus_rows)}")
    print(f"低吸候选数量：{len(low_buy_rows)}")
    print(f"放弃名单数量：{len(abandon_rows)}")


if __name__ == "__main__":
    generate_daily_plan()