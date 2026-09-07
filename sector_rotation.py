# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from common import normalize_code, safe_float
from ds_analysis import call_ds_analysis, compact_records
from fixed_holdings import FIXED_HOLDINGS
from sector_mapper import build_sector_profile, load_sector_mapping


OUTPUT_CSV = Path("output/sector_rotation.csv")
OUTPUT_MD = Path("output/sector_rotation_report.md")


def classify_rotation(row: pd.Series) -> str:
    inflow = safe_float(row.get("主力净流入", 0))
    pct = safe_float(row.get("板块涨跌幅", 0))
    breadth = safe_float(row.get("板块广度", 0))
    rank_5d = safe_float(row.get("板块近5日排名", 999))

    if inflow > 0 and pct > 0 and breadth >= 55 and rank_5d <= 10:
        return "主线延续"
    if inflow > 0 and pct <= 0:
        return "低位轮动"
    if inflow <= 0 and pct > 0:
        return "冲高分歧"
    if inflow <= 0 and pct <= 0:
        return "资金流出"
    return "观察"


def classify_action(row: pd.Series) -> str:
    status = str(row.get("板块轮动状态", ""))
    if status == "主线延续":
        return "可跟踪强势股"
    if status == "低位轮动":
        return "只等回踩确认"
    if status == "冲高分歧":
        return "追高谨慎"
    if status == "资金流出":
        return "降权回避"
    return "观察"


def holding_sector_table(rotation_df: pd.DataFrame) -> pd.DataFrame:
    mapping = load_sector_mapping()
    if mapping.empty or rotation_df.empty:
        return pd.DataFrame()
    holding_df = pd.DataFrame(FIXED_HOLDINGS)
    holding_df["股票代码"] = holding_df["股票代码"].apply(normalize_code)
    holding_df = holding_df.merge(mapping, on="股票代码", how="left")
    result = holding_df.merge(
        rotation_df[["所属板块", "板块轮动状态", "板块操作建议", "板块资金标签", "板块广度", "主力净流入"]],
        on="所属板块",
        how="left",
    )
    return result


def fallback_sector_ds_analysis(rotation_df: pd.DataFrame, holding_df: pd.DataFrame) -> dict[str, str]:
    if rotation_df.empty:
        return {
            "DS盘面判断": "板块资金数据不足，先不做方向判断。",
            "DS操作指引": "等待资金流向刷新后再看。",
            "DS风险提示": "缺少板块资金，不能用来追涨。",
            "DS固定持仓提示": "固定持仓先按原纪律执行。",
        }
    top_rows = rotation_df.head(3)
    top_names = "、".join(top_rows.get("所属板块", pd.Series(dtype=str)).astype(str).tolist())
    outflow_count = int((pd.to_numeric(rotation_df.get("主力净流入", 0), errors="coerce").fillna(0) < 0).sum())
    holding_hit = ""
    if not holding_df.empty and "板块轮动状态" in holding_df.columns:
        supported = holding_df[holding_df["板块轮动状态"].astype(str).isin(["主线延续", "低位轮动"])]
        if not supported.empty:
            names = "、".join(supported.get("股票名称", pd.Series(dtype=str)).astype(str).head(4).tolist())
            holding_hit = f"固定持仓中 {names} 有板块支持。"
    return {
        "DS盘面判断": f"资金优先看{top_names}，流出板块{outflow_count}个。",
        "DS操作指引": "只做有资金支持的低吸，冲高分歧不追。",
        "DS风险提示": "若金融拉指数但题材不跟，降低仓位。",
        "DS固定持仓提示": holding_hit or "固定持仓暂无明确板块加分，按个股纪律处理。",
    }


def build_sector_ds_analysis(rotation_df: pd.DataFrame, holding_df: pd.DataFrame) -> tuple[dict[str, str], str]:
    fallback = fallback_sector_ds_analysis(rotation_df, holding_df)
    payload = {
        "任务": "根据板块资金流向给出盘中可操作判断",
        "强板块": compact_records(
            rotation_df,
            ["所属板块", "板块轮动状态", "板块操作建议", "板块涨跌幅", "主力净流入", "板块广度", "板块近5日排名"],
            limit=8,
        ),
        "固定持仓板块": compact_records(
            holding_df,
            ["股票名称", "股票代码", "所属板块", "板块轮动状态", "板块操作建议", "主力净流入", "板块广度"],
            limit=8,
        ),
    }
    system_prompt = (
        "你是A股盘中辅助分析员。只根据用户提供的数据输出严格JSON，字段为："
        "DS盘面判断、DS操作指引、DS风险提示、DS固定持仓提示。"
        "每个字段不超过50个中文字符；不要编造数据；不要展示计算过程；语言要像实盘提示。"
    )
    return call_ds_analysis(
        prompt_version="v4.01_sector_rotation_ds",
        system_prompt=system_prompt,
        payload=payload,
        fallback=fallback,
    )


def build_sector_rotation() -> tuple[pd.DataFrame, pd.DataFrame]:
    profile = build_sector_profile()
    if profile.empty:
        return pd.DataFrame(), pd.DataFrame()
    df = profile.copy()
    df["生成时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df["板块轮动状态"] = df.apply(classify_rotation, axis=1)
    df["板块操作建议"] = df.apply(classify_action, axis=1)
    sort_cols = [col for col in ["资金排名", "板块近5日排名"] if col in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, na_position="last")
    return df.reset_index(drop=True), holding_sector_table(df)


def write_report(
    rotation_df: pd.DataFrame,
    holding_df: pd.DataFrame,
    ds_result: dict[str, str] | None = None,
    ds_status: str = "",
) -> None:
    lines = [
        "# 大资金板块轮动",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 用途：判断今天资金去哪、固定持仓有没有板块支持。",
        "",
    ]
    if rotation_df.empty:
        lines.append("暂无板块轮动数据，请先运行市场环境模块。")
    else:
        if ds_result:
            lines.extend([
                "## DS盘面结论",
                "",
                f"- 盘面判断：{ds_result.get('DS盘面判断', '')}",
                f"- 操作指引：{ds_result.get('DS操作指引', '')}",
                f"- 风险提示：{ds_result.get('DS风险提示', '')}",
                f"- 固定持仓：{ds_result.get('DS固定持仓提示', '')}",
                f"- DS状态：{ds_status}",
                "",
            ])
        lines.extend([
            "## 今日强弱板块",
            "",
            rotation_df.head(20).to_markdown(index=False),
        ])
    if not holding_df.empty:
        lines.extend(["", "## 固定持仓板块状态", "", holding_df.to_markdown(index=False)])
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")


def run_sector_rotation() -> pd.DataFrame:
    rotation_df, holding_df = build_sector_rotation()
    ds_result, ds_status = build_sector_ds_analysis(rotation_df, holding_df)
    for key, value in ds_result.items():
        rotation_df[key] = value
    rotation_df["DS状态"] = ds_status
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    rotation_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    write_report(rotation_df, holding_df, ds_result, ds_status)
    print(f"板块轮动报告已生成：{OUTPUT_CSV}")
    if not rotation_df.empty:
        print(rotation_df.head(10)[["所属板块", "板块轮动状态", "板块操作建议", "DS状态"]].to_string(index=False))
    return rotation_df


if __name__ == "__main__":
    run_sector_rotation()
