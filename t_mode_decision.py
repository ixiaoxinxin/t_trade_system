# -*- coding: utf-8 -*-

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from common import normalize_code, safe_float


OPENING_LEVELS_FILE = Path("output/opening_levels.csv")
FIXED_HOLDINGS_SIGNAL_FILE = Path("output/fixed_holdings_signals.csv")
MARKET_ENV_FILE = Path("output/market_environment.csv")
SECTOR_FLOW_FILE = Path("output/sector_fund_flow.csv")
TRADE_RECORD_FILE = Path("output/trade_records.csv")
OUTPUT_CSV = Path("output/t_mode_decision.csv")
OUTPUT_MD = Path("output/t_mode_decision.md")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, dtype={"股票代码": str, "stock_code": str})
    for col in ["股票代码", "stock_code"]:
        if col in df.columns:
            df[col] = df[col].apply(normalize_code)
    return df


def parse_price_range(value: Any) -> tuple[float, float]:
    numbers = [safe_float(item, None) for item in re.findall(r"\d+(?:\.\d+)?", str(value))]
    numbers = [item for item in numbers if item is not None and item > 0]
    if not numbers:
        return 0.0, 0.0
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    low, high = sorted(numbers[:2])
    return low, high


def first_text(row: pd.Series, columns: list[str], default: str = "") -> str:
    for col in columns:
        if col in row.index:
            text = str(row.get(col, "")).strip()
            if text and text.lower() not in {"nan", "none"}:
                return text
    return default


def first_float(row: pd.Series, columns: list[str], default: float = 0.0) -> float:
    for col in columns:
        if col in row.index:
            value = safe_float(row.get(col), None)
            if value is not None and value != 0:
                return value
    return default


def latest_by_code(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "股票代码" not in df.columns:
        return pd.DataFrame()
    work = df.copy()
    sort_cols = [col for col in ["刷新时间", "记录时间"] if col in work.columns]
    if sort_cols:
        work = work.sort_values(sort_cols[-1])
    return work.drop_duplicates(subset=["股票代码"], keep="last")


def market_context(market_df: pd.DataFrame, sector_df: pd.DataFrame) -> dict[str, str]:
    if market_df.empty:
        return {"市场环境": "未知", "风险等级": "未知", "资金流入方向": "", "金融预警": "未知"}
    row = market_df.iloc[-1]
    sector_text = str(row.get("资金流入方向", "")).strip()
    financial_alert = "无"
    if not sector_df.empty and "板块名称" in sector_df.columns:
        financial_names = ["证券", "银行", "保险", "多元金融"]
        financial_df = sector_df[
            sector_df["板块名称"].astype(str).apply(lambda name: any(key in name for key in financial_names))
        ].copy()
        if not financial_df.empty:
            inflow = pd.to_numeric(financial_df.get("主力净流入", 0), errors="coerce").fillna(0).sum()
            financial_alert = "金融拉盘" if inflow > 0 else "金融偏弱"
    return {
        "市场环境": str(row.get("市场环境", "未知")),
        "风险等级": str(row.get("风险等级", "未知")),
        "资金流入方向": sector_text,
        "金融预警": financial_alert,
    }


def trade_summary(trade_df: pd.DataFrame, code: str, name: str) -> dict[str, Any]:
    if trade_df.empty:
        return {"历史T次数": 0, "历史T胜率": 0.0, "历史T均收益率": 0.0}
    work = trade_df.copy()
    if "股票代码" in work.columns:
        work["股票代码"] = work["股票代码"].apply(normalize_code)
    name_mask = work.get("股票名称", pd.Series([""] * len(work), index=work.index)).astype(str).str.contains(
        name.replace("A", ""), na=False
    )
    code_mask = work.get("股票代码", pd.Series([""] * len(work), index=work.index)).astype(str).eq(normalize_code(code))
    matched = work[name_mask | code_mask].copy()
    if matched.empty:
        return {"历史T次数": 0, "历史T胜率": 0.0, "历史T均收益率": 0.0}
    profit = pd.to_numeric(matched.get("到手利润", 0), errors="coerce").fillna(0)
    ret = pd.to_numeric(matched.get("收益率", 0), errors="coerce").fillna(0)
    return {
        "历史T次数": int(len(matched)),
        "历史T胜率": round(float((profit > 0).mean()), 4),
        "历史T均收益率": round(float(ret.mean()), 4),
    }


def decision_from_row(row: pd.Series, context: dict[str, str], history: dict[str, Any]) -> dict[str, Any]:
    buy_low, buy_high = parse_price_range(row.get("买进区间", row.get("买点区间", "")))
    sell_low, sell_high = parse_price_range(row.get("卖出区间", row.get("卖点区间", "")))
    current_price = first_float(row, ["当前价", "参考价", "集合竞价价"])
    support = first_float(row, ["支撑位", "买点下限"], buy_low)
    pressure = first_float(row, ["压力位", "买点上限"], sell_low)
    sell_signal = first_text(row, ["卖点信号", "卖出信号"], "观察")
    buy_status = first_text(row, ["买点状态", "操作"], "观察")
    risk_level = context.get("风险等级", "未知")
    market = context.get("市场环境", "未知")

    data_status = "正常"
    if current_price <= 0 or buy_low <= 0 or buy_high <= 0 or sell_low <= 0:
        data_status = "缺少价格区间"
        return {
            "推荐模式": "不做T",
            "推荐强度": "弱",
            "模式短句": "等数据",
            "风险线": round(support, 3) if support else "",
            "触发条件": "先刷新开盘区间和持仓买卖点",
            "一句话理由": "价格或区间不完整，不能给实盘动作。",
            "数据状态": data_status,
        }

    if sell_signal in {"止损", "清仓"}:
        mode, strength = "不做T", "强"
        trigger = "先按卖点纪律退出，不补仓摊低成本"
        reason = f"{sell_signal}信号已触发，今天先控风险。"
    elif current_price >= sell_low or sell_signal in {"止盈", "减仓"} or (pressure > 0 and current_price >= pressure * 0.985):
        mode = "先卖再买"
        strength = "强" if current_price >= sell_low else "中"
        trigger = f"{sell_low:.3f}-{sell_high:.3f} 先卖，回落到 {buy_low:.3f}-{buy_high:.3f} 再接"
        reason = "价格靠近卖出区间，先锁利润，再等回落。"
    elif buy_low <= current_price <= buy_high or current_price <= buy_high:
        mode = "先买再卖"
        strength = "中" if risk_level in {"高", "极高"} else "强"
        trigger = f"{buy_low:.3f}-{buy_high:.3f} 分批低吸，反弹到 {sell_low:.3f}-{sell_high:.3f} 卖出"
        reason = "价格进入买入区间，可按低吸节奏做T。"
    elif market in {"情绪冰点", "系统风险", "偏弱"} and current_price > buy_high:
        mode, strength = "不做T", "中"
        trigger = f"只等回落到 {buy_low:.3f}-{buy_high:.3f}，不追高"
        reason = "市场偏弱且价格不在买区，先等确定性。"
    else:
        mode, strength = "不做T", "弱"
        trigger = f"跌近 {buy_high:.3f} 再看低吸，冲近 {sell_low:.3f} 再看卖出"
        reason = "价格在区间中间，赔率不够清楚。"

    if history.get("历史T次数", 0) >= 3 and history.get("历史T胜率", 0) < 0.45 and strength == "强":
        strength = "中"
        reason += " 该股历史T胜率偏低，强度下调。"

    return {
        "推荐模式": mode,
        "推荐强度": strength,
        "模式短句": f"{mode}：{reason}",
        "风险线": round(support, 3) if support else "",
        "触发条件": trigger,
        "一句话理由": reason,
        "数据状态": data_status,
    }


def build_t_mode_decisions(
    opening_df: pd.DataFrame,
    holding_signal_df: pd.DataFrame,
    market_df: pd.DataFrame,
    sector_df: pd.DataFrame,
    trade_df: pd.DataFrame,
) -> pd.DataFrame:
    opening_latest = latest_by_code(opening_df)
    signal_latest = latest_by_code(holding_signal_df)
    if opening_latest.empty and signal_latest.empty:
        return pd.DataFrame()

    if opening_latest.empty:
        merged = signal_latest.copy()
    elif signal_latest.empty:
        merged = opening_latest.copy()
    else:
        merged = opening_latest.merge(signal_latest, on=["股票代码", "股票名称"], how="outer", suffixes=("", "_信号"))

    context = market_context(market_df, sector_df)
    run_id = f"tmode_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    rows = []
    for _, row in merged.iterrows():
        code = normalize_code(row.get("股票代码", ""))
        name = first_text(row, ["股票名称", "股票名称_信号"], code)
        history = trade_summary(trade_df, code, name)
        decision = decision_from_row(row, context, history)
        rows.append({
            "刷新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "run_id": run_id,
            "股票代码": code,
            "股票名称": name,
            "推荐模式": decision["推荐模式"],
            "推荐强度": decision["推荐强度"],
            "模式短句": decision["模式短句"],
            "买入区间": row.get("买进区间", row.get("买点区间", "")),
            "卖出区间": row.get("卖出区间", ""),
            "风险线": decision["风险线"],
            "触发条件": decision["触发条件"],
            "一句话理由": decision["一句话理由"],
            "当前价": first_float(row, ["当前价", "参考价", "集合竞价价"]),
            "支撑位": first_float(row, ["支撑位", "买点下限"]),
            "压力位": first_float(row, ["压力位", "买点上限"]),
            "买点状态": first_text(row, ["买点状态", "操作"], ""),
            "卖点信号": first_text(row, ["卖点信号", "卖出信号"], ""),
            "市场环境": context["市场环境"],
            "风险等级": context["风险等级"],
            "板块资金方向": context["资金流入方向"],
            "金融预警": context["金融预警"],
            "历史T次数": history["历史T次数"],
            "历史T胜率": history["历史T胜率"],
            "历史T均收益率": history["历史T均收益率"],
            "数据状态": decision["数据状态"],
        })
    return pd.DataFrame(rows)


def write_report(df: pd.DataFrame) -> None:
    lines = [
        "# 做T模式决策",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 用途：固定持仓先判断今天适合先买再卖、先卖再买，还是不做T。",
        "- 口径：开盘T区间 + 固定持仓买卖点 + 市场环境 + 历史真实交易。",
        "",
    ]
    if df.empty:
        lines.append("暂无可计算数据，请先刷新开盘T区间和持仓买卖点。")
    else:
        lines.append(df.to_markdown(index=False))
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")


def run_t_mode_decision() -> pd.DataFrame:
    df = build_t_mode_decisions(
        read_csv(OPENING_LEVELS_FILE),
        read_csv(FIXED_HOLDINGS_SIGNAL_FILE),
        read_csv(MARKET_ENV_FILE),
        read_csv(SECTOR_FLOW_FILE),
        read_csv(TRADE_RECORD_FILE),
    )
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    write_report(df)
    print(f"做T模式决策已生成：{OUTPUT_CSV}")
    if not df.empty:
        print(df.to_string(index=False))
    return df


if __name__ == "__main__":
    run_t_mode_decision()
