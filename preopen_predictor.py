# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from common import safe_float
from ds_analysis import call_ds_analysis, compact_records


MARKET_ENV_FILE = Path("output/market_environment.csv")
SECTOR_FLOW_FILE = Path("output/sector_fund_flow.csv")
OPENING_LEVELS_FILE = Path("output/opening_levels.csv")
METAL_MACRO_FILE = Path("output/metal_macro_snapshot.csv")
OUTPUT_CSV = Path("output/preopen_prediction.csv")
OUTPUT_MD = Path("output/preopen_prediction.md")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"股票代码": str})


def last_row(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=object)
    return df.iloc[-1]


def classify_opening(market_env: str, sector_df: pd.DataFrame, metal_df: pd.DataFrame, opening_df: pd.DataFrame) -> dict[str, Any]:
    score = 50
    reasons: list[str] = []

    if market_env in {"正常"}:
        score += 12
        reasons.append("大盘环境正常")
    elif market_env in {"偏弱", "系统风险", "情绪冰点"}:
        score -= 15
        reasons.append("大盘环境偏弱")
    else:
        reasons.append("大盘环境未知")

    if not sector_df.empty and "主力净流入" in sector_df.columns:
        top_inflow = pd.to_numeric(sector_df["主力净流入"], errors="coerce").fillna(0).head(10).sum()
        top_pct = pd.to_numeric(sector_df.get("板块涨跌幅", 0), errors="coerce").fillna(0).head(10).mean()
        if top_inflow > 0 and top_pct >= 0:
            score += 12
            reasons.append("强板块资金流入")
        elif top_inflow > 0 and top_pct < 0:
            score += 4
            reasons.append("资金流入但价格承接一般")
        else:
            score -= 10
            reasons.append("板块资金不足")
    else:
        reasons.append("板块资金缺失")

    if not metal_df.empty:
        metal_state = str(last_row(metal_df).get("金属模块状态", ""))
        if metal_state in {"偏强", "风险偏好修复"}:
            score += 6
            reasons.append(f"金属模块{metal_state}")
        elif metal_state == "偏弱":
            score -= 6
            reasons.append("金属模块偏弱")
    else:
        reasons.append("金属数据缺失")

    if not opening_df.empty and {"集合竞价价", "昨收"}.issubset(opening_df.columns):
        auction = pd.to_numeric(opening_df["集合竞价价"], errors="coerce")
        prev_close = pd.to_numeric(opening_df["昨收"], errors="coerce")
        gap = ((auction / prev_close - 1) * 100).replace([float("inf"), -float("inf")], pd.NA).dropna()
        if not gap.empty:
            avg_gap = float(gap.mean())
            if avg_gap > 1.2:
                score += 8
                reasons.append("固定持仓竞价偏强")
            elif avg_gap < -1.2:
                score -= 10
                reasons.append("固定持仓竞价偏弱")
            else:
                reasons.append("固定持仓竞价平稳")

    score = max(0, min(100, int(round(score))))
    if score >= 72:
        opening_type = "强开"
        strategy = "可进攻"
    elif score >= 58:
        opening_type = "震荡偏强"
        strategy = "只低吸"
    elif score >= 43:
        opening_type = "震荡"
        strategy = "先确认"
    elif score >= 30:
        opening_type = "弱开"
        strategy = "先防守"
    else:
        opening_type = "风险开局"
        strategy = "不做"

    financial_alert = "无"
    if not sector_df.empty and "板块名称" in sector_df.columns:
        financial_mask = sector_df["板块名称"].astype(str).str.contains("证券|银行|保险|多元金融", regex=True, na=False)
        financial_inflow = pd.to_numeric(sector_df.loc[financial_mask, "主力净流入"], errors="coerce").fillna(0).sum()
        theme_inflow = pd.to_numeric(sector_df.loc[~financial_mask, "主力净流入"], errors="coerce").fillna(0).head(20).sum()
        if financial_inflow > 0 and theme_inflow <= 0:
            financial_alert = "指数假强"
            reasons.append("金融拉盘但题材资金未跟")
        elif financial_inflow > 0:
            financial_alert = "金融支持"

    return {
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "开盘评分": score,
        "开盘定性": opening_type,
        "金融拉盘预警": financial_alert,
        "固定持仓影响": "有利" if score >= 58 else "不利" if score < 43 else "中性",
        "今日策略": strategy,
        "评分来源": "；".join(reasons),
    }


def fallback_preopen_ds_analysis(row: dict[str, Any], sector_df: pd.DataFrame, metal_df: pd.DataFrame) -> dict[str, str]:
    strategy = str(row.get("今日策略", "先确认"))
    opening_type = str(row.get("开盘定性", "未知"))
    financial_alert = str(row.get("金融拉盘预警", "无"))
    if strategy == "可进攻":
        action = "先看强板块承接，符合再小仓试。"
    elif strategy == "只低吸":
        action = "只等支撑区低吸，不追开盘冲高。"
    elif strategy == "先防守":
        action = "先防守，等跌不动再处理持仓。"
    elif strategy == "不做":
        action = "开盘不新开，先处理风险。"
    else:
        action = "先看十五分钟确认，再决定是否动手。"
    metal_state = ""
    if not metal_df.empty:
        metal_state = str(metal_df.iloc[-1].get("金属模块状态", ""))
    return {
        "DS操作建议": action,
        "DS重点模块": f"开盘{opening_type}，重点看资金流向和固定持仓。",
        "DS防守条件": "若指数假强或固定持仓跌破支撑，先减风险。",
        "DS补充观察": f"金融预警{financial_alert}；金属{metal_state or '暂无'}。",
    }


def build_preopen_ds_analysis(
    row: dict[str, Any],
    sector_df: pd.DataFrame,
    metal_df: pd.DataFrame,
    opening_df: pd.DataFrame,
) -> tuple[dict[str, str], str]:
    fallback = fallback_preopen_ds_analysis(row, sector_df, metal_df)
    payload = {
        "任务": "根据开盘前数据给出今天开盘的实盘操作建议",
        "规则结论": row,
        "资金流向": compact_records(
            sector_df,
            ["板块名称", "所属板块", "板块轮动状态", "板块操作建议", "板块涨跌幅", "主力净流入", "板块广度"],
            limit=10,
        ),
        "金属宏观": compact_records(metal_df, ["金属模块状态", "金银比", "金油比", "金美指", "生成时间"], limit=3),
        "开盘区间": compact_records(
            opening_df,
            ["股票名称", "股票代码", "支撑位", "压力位", "买进区间", "卖出区间", "集合竞价价", "昨收"],
            limit=8,
        ),
    }
    system_prompt = (
        "你是A股开盘前辅助决策员。只根据用户提供的数据输出严格JSON，字段为："
        "DS操作建议、DS重点模块、DS防守条件、DS补充观察。"
        "每个字段不超过55个中文字符；不要编造行情；不要输出计算过程；必须给出实盘可执行语言。"
    )
    return call_ds_analysis(
        prompt_version="v4.01_preopen_prediction_ds",
        system_prompt=system_prompt,
        payload=payload,
        fallback=fallback,
    )


def build_preopen_prediction() -> pd.DataFrame:
    market_df = read_csv(MARKET_ENV_FILE)
    sector_df = read_csv(SECTOR_FLOW_FILE)
    opening_df = read_csv(OPENING_LEVELS_FILE)
    metal_df = read_csv(METAL_MACRO_FILE)
    market_env = str(last_row(market_df).get("市场环境", "未知"))
    row = classify_opening(market_env, sector_df, metal_df, opening_df)
    ds_result, ds_status = build_preopen_ds_analysis(row, sector_df, metal_df, opening_df)
    row.update(ds_result)
    row["DS状态"] = ds_status
    return pd.DataFrame([row])


def write_report(df: pd.DataFrame) -> None:
    lines = [
        "# 开盘前综合预测",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 用途：9:25 后给出当天开盘定性，辅助决定先防守还是只低吸。",
        "",
    ]
    lines.append(df.to_markdown(index=False) if not df.empty else "暂无开盘前预测。")
    if not df.empty:
        row = df.iloc[-1]
        lines.extend([
            "",
            "## DS开盘操作建议",
            "",
            f"- 操作建议：{row.get('DS操作建议', '')}",
            f"- 重点模块：{row.get('DS重点模块', '')}",
            f"- 防守条件：{row.get('DS防守条件', '')}",
            f"- 补充观察：{row.get('DS补充观察', '')}",
            f"- DS状态：{row.get('DS状态', '')}",
        ])
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")


def run_preopen_prediction() -> pd.DataFrame:
    df = build_preopen_prediction()
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    write_report(df)
    print(f"开盘前综合预测已生成：{OUTPUT_CSV}")
    print(df.to_string(index=False))
    return df


if __name__ == "__main__":
    run_preopen_prediction()
