# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from common import normalize_code, safe_float
from ds_analysis import call_ds_analysis, compact_records


TRADE_RECORD_FILE = Path("output/trade_records.csv")
T_MODE_FILE = Path("output/t_mode_decision.csv")
NEXT_DAY_FILE = Path("output/next_day_review.csv")
OPENING_LEVELS_FILE = Path("output/opening_levels.csv")
OUTPUT_CSV = Path("output/performance_report.csv")
OUTPUT_MD = Path("output/performance_report.md")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"股票代码": str})


def period_start(series: pd.Series, period: str) -> pd.Series:
    dates = pd.to_datetime(series, errors="coerce")
    if period == "周":
        return dates.dt.to_period("W").astype(str)
    if period == "月":
        return dates.dt.to_period("M").astype(str)
    if period == "半年":
        return dates.dt.year.astype(str) + "H" + dates.dt.month.apply(lambda m: "1" if m <= 6 else "2")
    return dates.dt.year.astype(str)


def summarize_trades(trade_df: pd.DataFrame, period: str) -> pd.DataFrame:
    if trade_df.empty or "交易日期" not in trade_df.columns:
        return pd.DataFrame()
    df = trade_df.copy()
    df["统计周期"] = period_start(df["交易日期"], period)
    df["到手利润"] = pd.to_numeric(df.get("到手利润", 0), errors="coerce").fillna(0)
    df["收益率"] = pd.to_numeric(df.get("收益率", 0), errors="coerce").fillna(0)
    df["是否盈利"] = df["到手利润"] > 0
    if "做T模式" in df.columns:
        df["做T模式"] = df["做T模式"].astype(str)
    elif "方向" in df.columns:
        df["做T模式"] = df["方向"].astype(str)
    else:
        df["做T模式"] = ""
    grouped = df.groupby("统计周期").agg(
        交易笔数=("记录ID", "count"),
        盈利笔数=("是否盈利", "sum"),
        到手利润=("到手利润", "sum"),
        平均收益率=("收益率", "mean"),
    ).reset_index()
    grouped["胜率"] = grouped["盈利笔数"] / grouped["交易笔数"] * 100
    grouped["报表类型"] = f"{period}度交易"
    return grouped


def summarize_by_stock(trade_df: pd.DataFrame) -> pd.DataFrame:
    if trade_df.empty:
        return pd.DataFrame()
    df = trade_df.copy()
    df["股票代码"] = df.get("股票代码", "").apply(normalize_code)
    df["到手利润"] = pd.to_numeric(df.get("到手利润", 0), errors="coerce").fillna(0)
    df["收益率"] = pd.to_numeric(df.get("收益率", 0), errors="coerce").fillna(0)
    result = df.groupby(["股票名称", "股票代码"]).agg(
        交易笔数=("记录ID", "count"),
        到手利润=("到手利润", "sum"),
        平均收益率=("收益率", "mean"),
    ).reset_index()
    result["报表类型"] = "个股交易"
    return result.sort_values("到手利润", ascending=False)


def summarize_system(next_df: pd.DataFrame) -> pd.DataFrame:
    if next_df.empty:
        return pd.DataFrame()
    df = next_df.copy()
    rows = []
    total = len(df)
    metrics = {
        "买点触达率": df.get("是否触达低吸区间", pd.Series(dtype=str)).astype(str).eq("是").mean() * 100,
        "目标达到率": df.get("是否达到1%", pd.Series(dtype=str)).astype(str).eq("是").mean() * 100,
        "止损触发率": df.get("是否触发-2%止损", pd.Series(dtype=str)).astype(str).eq("是").mean() * 100,
    }
    for name, value in metrics.items():
        rows.append({"报表类型": "系统验证", "指标": name, "样本数": total, "数值": round(safe_float(value), 2)})
    return pd.DataFrame(rows)


def build_optimization_notes(trade_df: pd.DataFrame, next_df: pd.DataFrame, t_mode_df: pd.DataFrame) -> list[str]:
    notes = []
    if trade_df.empty:
        notes.append("真实交易样本不足，先继续沉淀手动做T记录。")
    else:
        profit = pd.to_numeric(trade_df.get("到手利润", 0), errors="coerce").fillna(0)
        win_rate = float((profit > 0).mean()) if len(profit) else 0.0
        if win_rate < 0.5:
            notes.append("真实交易胜率低于50%，优先复核买入区间和卖出纪律。")
        else:
            notes.append("真实交易胜率可用，后续可按股票和模式分层训练。")
    if not next_df.empty:
        stop_rate = next_df.get("是否触发-2%止损", pd.Series(dtype=str)).astype(str).eq("是").mean()
        if stop_rate >= 0.25:
            notes.append("系统验证止损触发偏高，支撑位和买点上沿需要下移或增加分时确认。")
    if not t_mode_df.empty and "推荐模式" in t_mode_df.columns:
        no_t_count = int(t_mode_df["推荐模式"].astype(str).eq("不做T").sum())
        if no_t_count:
            notes.append(f"当前有 {no_t_count} 只固定持仓不适合做T，页面应继续前置风险提示。")
    return notes


def fallback_performance_ds_analysis(
    trade_df: pd.DataFrame,
    next_df: pd.DataFrame,
    t_mode_df: pd.DataFrame,
    notes: list[str],
) -> dict[str, str]:
    trade_count = len(trade_df)
    profit_sum = safe_float(pd.to_numeric(trade_df.get("到手利润", 0), errors="coerce").fillna(0).sum()) if not trade_df.empty else 0
    stop_rate = 0.0
    if not next_df.empty:
        stop_rate = next_df.get("是否触发-2%止损", pd.Series(dtype=str)).astype(str).eq("是").mean() * 100
    return {
        "DS账面结论": f"交易{trade_count}笔，到手利润{profit_sum:.2f}，先看稳定性。",
        "DS问题定位": notes[0] if notes else "样本不足，先继续沉淀真实交易。",
        "DS下次动作": "把亏损样本和低胜率模式优先复盘。",
        "DS理论提升": "补充最佳买卖点后估算可多赚空间。",
        "DS风险提醒": f"系统止损触发率约{stop_rate:.1f}%，高时降低开仓。",
    }


def build_performance_ds_analysis(
    trade_df: pd.DataFrame,
    next_df: pd.DataFrame,
    t_mode_df: pd.DataFrame,
    report_df: pd.DataFrame,
    notes: list[str],
) -> tuple[dict[str, str], str]:
    fallback = fallback_performance_ds_analysis(trade_df, next_df, t_mode_df, notes)
    payload = {
        "任务": "根据真实交易和系统验证生成账面复盘结论",
        "周期报表": compact_records(
            report_df,
            ["报表类型", "统计周期", "交易笔数", "盈利笔数", "胜率", "到手利润", "平均收益率", "指标", "样本数", "数值"],
            limit=16,
        ),
        "最近交易": compact_records(
            trade_df.sort_values("交易日期", ascending=False) if "交易日期" in trade_df.columns else trade_df,
            ["交易日期", "股票名称", "股票代码", "交易类型", "方向", "买入价格", "卖出价格", "数量", "到手利润", "收益率", "策略来源"],
            limit=12,
        ),
        "系统验证": compact_records(
            next_df,
            ["股票名称", "股票代码", "是否触达低吸区间", "是否达到1%", "是否触发-2%止损", "最终操作", "验证结论"],
            limit=12,
        ),
        "做T判断": compact_records(
            t_mode_df,
            ["股票名称", "股票代码", "推荐模式", "T机会等级", "操作建议", "风险提示"],
            limit=8,
        ),
        "规则建议": notes,
    }
    system_prompt = (
        "你是A股交易复盘助手。只根据用户数据输出严格JSON，字段为："
        "DS账面结论、DS问题定位、DS下次动作、DS理论提升、DS风险提醒。"
        "每个字段不超过60个中文字符；不要编造交易；不要展示计算过程；必须落到下一次怎么改。"
    )
    return call_ds_analysis(
        prompt_version="v4.01_performance_report_ds",
        system_prompt=system_prompt,
        payload=payload,
        fallback=fallback,
    )


def append_ds_rows(df: pd.DataFrame, ds_result: dict[str, str], ds_status: str) -> pd.DataFrame:
    rows = [
        {"报表类型": "DS分析", "指标": key, "数值": value, "DS状态": ds_status}
        for key, value in ds_result.items()
    ]
    if not rows:
        return df
    ds_df = pd.DataFrame(rows)
    return pd.concat([df, ds_df], ignore_index=True, sort=False) if not df.empty else ds_df


def build_performance_report() -> tuple[pd.DataFrame, list[str], dict[str, str], str]:
    trade_df = read_csv(TRADE_RECORD_FILE)
    t_mode_df = read_csv(T_MODE_FILE)
    next_df = read_csv(NEXT_DAY_FILE)
    frames = []
    for period in ["周", "月", "半年", "年"]:
        summary = summarize_trades(trade_df, period)
        if not summary.empty:
            frames.append(summary)
    stock_summary = summarize_by_stock(trade_df)
    if not stock_summary.empty:
        frames.append(stock_summary)
    system_summary = summarize_system(next_df)
    if not system_summary.empty:
        frames.append(system_summary)
    df = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    notes = build_optimization_notes(trade_df, next_df, t_mode_df)
    ds_result, ds_status = build_performance_ds_analysis(trade_df, next_df, t_mode_df, df, notes)
    return append_ds_rows(df, ds_result, ds_status), notes, ds_result, ds_status


def write_report(df: pd.DataFrame, notes: list[str], ds_result: dict[str, str], ds_status: str) -> None:
    lines = [
        "# 周期复盘报表",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 用途：按周、月、半年、年度统计真实做T收益和系统验证表现。",
        "",
    ]
    if df.empty:
        lines.append("暂无可统计数据。")
    else:
        lines.append(df.to_markdown(index=False))
    if notes:
        lines.extend(["", "## 下一步系统优化建议", ""])
        lines.extend([f"- {note}" for note in notes])
    if ds_result:
        lines.extend([
            "",
            "## DS账面复盘",
            "",
            f"- 账面结论：{ds_result.get('DS账面结论', '')}",
            f"- 问题定位：{ds_result.get('DS问题定位', '')}",
            f"- 下次动作：{ds_result.get('DS下次动作', '')}",
            f"- 理论提升：{ds_result.get('DS理论提升', '')}",
            f"- 风险提醒：{ds_result.get('DS风险提醒', '')}",
            f"- DS状态：{ds_status}",
        ])
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")


def run_performance_report() -> pd.DataFrame:
    df, notes, ds_result, ds_status = build_performance_report()
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    write_report(df, notes, ds_result, ds_status)
    print(f"周期复盘报表已生成：{OUTPUT_CSV}")
    if not df.empty:
        print(df.head(30).to_string(index=False))
    return df


if __name__ == "__main__":
    run_performance_report()
