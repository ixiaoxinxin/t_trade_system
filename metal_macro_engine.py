# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from common import safe_float


MACRO_INPUT_FILES = [Path("output/macro_market_quotes.csv"), Path("data/macro_market_quotes.csv")]
OUTPUT_CSV = Path("output/metal_macro_snapshot.csv")
OUTPUT_MD = Path("output/metal_macro_report.md")

REQUIRED_SYMBOLS = {
    "XAU": "黄金",
    "XAG": "白银",
    "WTI": "原油",
    "XPT": "铂金",
    "DXY": "美元指数",
    "US02Y": "2年美债",
    "US05Y": "5年美债",
    "US10Y": "10年美债",
    "US30Y": "30年美债",
}


def load_macro_quotes() -> pd.DataFrame:
    for path in MACRO_INPUT_FILES:
        if not path.exists():
            continue
        df = pd.read_csv(path)
        if df.empty:
            continue
        df = df.rename(columns={
            "代码": "symbol",
            "品种": "symbol",
            "名称": "name",
            "价格": "price",
            "最新价": "price",
            "涨跌幅": "pct_change",
            "日期": "quote_time",
            "更新时间": "quote_time",
        })
        if "symbol" not in df.columns or "price" not in df.columns:
            continue
        df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
        if "pct_change" in df.columns:
            df["pct_change"] = pd.to_numeric(df["pct_change"], errors="coerce")
        else:
            df["pct_change"] = 0.0
        if "quote_time" not in df.columns:
            df["quote_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if "name" not in df.columns:
            df["name"] = df["symbol"].map(REQUIRED_SYMBOLS).fillna(df["symbol"])
        return df.dropna(subset=["price"])
    return pd.DataFrame(columns=["symbol", "name", "price", "pct_change", "quote_time"])


def quote_map(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if df.empty:
        return {}
    latest = df.drop_duplicates(subset=["symbol"], keep="last")
    return {str(row["symbol"]): row.to_dict() for _, row in latest.iterrows()}


def ratio(price_map: dict[str, dict[str, Any]], left: str, right: str) -> float:
    left_value = safe_float(price_map.get(left, {}).get("price"), 0.0)
    right_value = safe_float(price_map.get(right, {}).get("price"), 0.0)
    if left_value <= 0 or right_value <= 0:
        return 0.0
    return round(left_value / right_value, 4)


def classify_metal_state(price_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    gold_pct = safe_float(price_map.get("XAU", {}).get("pct_change"), 0.0)
    silver_pct = safe_float(price_map.get("XAG", {}).get("pct_change"), 0.0)
    dxy_pct = safe_float(price_map.get("DXY", {}).get("pct_change"), 0.0)
    us10y_pct = safe_float(price_map.get("US10Y", {}).get("pct_change"), 0.0)
    gold_silver = ratio(price_map, "XAU", "XAG")

    if not price_map:
        return {
            "金属模块状态": "数据缺失",
            "利率压力": "未知",
            "黄金策略": "不参与判断",
            "一句话建议": "缺少宏观行情输入，先补充 output/macro_market_quotes.csv。",
        }

    rate_pressure = "高" if us10y_pct > 0.4 or dxy_pct > 0.4 else "低" if us10y_pct < -0.2 and dxy_pct < 0.2 else "中"

    if gold_pct > 0 and rate_pressure != "高":
        state = "偏强"
        advice = "黄金强且利率压力不高，资源和贵金属方向可关注回踩机会。"
    elif gold_pct < 0 and rate_pressure == "高":
        state = "偏弱"
        advice = "黄金弱且利率/美元有压力，贵金属仓位偏防守。"
    elif gold_pct > 0 and silver_pct > gold_pct and gold_silver > 0:
        state = "风险偏好修复"
        advice = "白银相对更强，说明工业属性在修复，资源链可观察。"
    else:
        state = "震荡"
        advice = "宏观信号不一致，等价格和板块资金确认。"

    return {
        "金属模块状态": state,
        "利率压力": rate_pressure,
        "黄金策略": "只低吸" if state in {"偏强", "风险偏好修复"} else "先观察",
        "一句话建议": advice,
    }


def build_metal_macro_snapshot(quotes_df: pd.DataFrame) -> pd.DataFrame:
    prices = quote_map(quotes_df)
    state = classify_metal_state(prices)
    rows = [
        {"指标": "金银比", "数值": ratio(prices, "XAU", "XAG"), "解释": "升高偏避险，下降偏白银/工业修复"},
        {"指标": "金油比", "数值": ratio(prices, "XAU", "WTI"), "解释": "升高偏避险，下降偏通胀和风险偏好修复"},
        {"指标": "金铂比", "数值": ratio(prices, "XAU", "XPT"), "解释": "升高说明黄金相对工业贵金属更强"},
        {"指标": "金美指比", "数值": ratio(prices, "XAU", "DXY"), "解释": "升高说明黄金抵抗美元压力"},
    ]
    for row in rows:
        row.update({
            "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "金属模块状态": state["金属模块状态"],
            "利率压力": state["利率压力"],
            "黄金策略": state["黄金策略"],
            "一句话建议": state["一句话建议"],
            "数据状态": "正常" if row["数值"] > 0 else "缺少价格",
        })
    return pd.DataFrame(rows)


def write_report(df: pd.DataFrame, quotes_df: pd.DataFrame) -> None:
    lines = [
        "# 金属与利率联动预测",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 用途：给 A 股资源股、黄金和贵金属方向提供宏观辅助。",
        "- 数据规则：缺少价格时明确标注，不用旧数据冒充实时结论。",
        "",
    ]
    if df.empty:
        lines.append("暂无金属宏观数据。")
    else:
        lines.append(df.to_markdown(index=False))
    if not quotes_df.empty:
        lines.extend(["", "## 输入行情", "", quotes_df.to_markdown(index=False)])
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")


def run_metal_macro() -> pd.DataFrame:
    quotes = load_macro_quotes()
    df = build_metal_macro_snapshot(quotes)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    write_report(df, quotes)
    print(f"金属宏观报告已生成：{OUTPUT_CSV}")
    print(df.to_string(index=False))
    return df


if __name__ == "__main__":
    run_metal_macro()
