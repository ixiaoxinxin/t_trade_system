# factor_ranker.py
# -*- coding: utf-8 -*-

"""
A股隔日T系统 v1.8.0：因子表现排行榜

功能：
1. 读取 output/next_day_review.csv
2. 统计因子实盘验证表现
3. 输出：
   - output/factor_rank.csv
   - output/factor_rank.md

用途：
帮助判断哪些因子有效，哪些因子后续应该降权或淘汰。
"""

from pathlib import Path
from datetime import datetime

import pandas as pd


INPUT_FILE = Path("output/next_day_review.csv")
OUTPUT_CSV = Path("output/factor_rank.csv")
OUTPUT_MD = Path("output/factor_rank.md")


CONFIG = {
    "factor_columns": {
        "分时结构标签": "分时结构因子",
        "尾盘抢筹标签": "尾盘资金因子",
        "隔夜建议等级": "隔夜等级因子",
        "热点标签": "热点题材因子",
    },
    "grade_rules": {
        "S": 75,
        "A": 60,
        "B": 45,
        "C": 30,
    },
}


def safe_float(value, default=0.0) -> float:
    """
    安全转 float。
    """

    try:
        return float(value)
    except Exception:
        return default


def get_factor_grade(success_rate: float) -> str:
    """
    根据成功率给因子评级。
    """

    if success_rate >= CONFIG["grade_rules"]["S"]:
        return "S"
    if success_rate >= CONFIG["grade_rules"]["A"]:
        return "A"
    if success_rate >= CONFIG["grade_rules"]["B"]:
        return "B"
    if success_rate >= CONFIG["grade_rules"]["C"]:
        return "C"

    return "D"


def normalize_review_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    统一字段类型。
    """

    df = df.copy()

    numeric_cols = [
        "次日最高涨幅",
        "次日收盘涨幅",
        "次日最低涨幅",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    flag_cols = [
        "是否验证成功",
        "是否达到1%",
        "是否达到2%",
        "是否触发-2%止损",
    ]

    for col in flag_cols:
        if col not in df.columns:
            df[col] = "否"

        df[col] = df[col].astype(str)

    return df


def build_factor_summary(df: pd.DataFrame, factor_col: str, factor_type: str) -> pd.DataFrame:
    """
    按单个因子字段统计表现。
    """

    if factor_col not in df.columns:
        return pd.DataFrame()

    temp = df.copy()

    temp[factor_col] = temp[factor_col].astype(str).fillna("未知")

    temp["验证成功数"] = temp["是否验证成功"].eq("是").astype(int)
    temp["达到1数"] = temp["是否达到1%"].eq("是").astype(int)
    temp["达到2数"] = temp["是否达到2%"].eq("是").astype(int)
    temp["止损数"] = temp["是否触发-2%止损"].eq("是").astype(int)

    summary = temp.groupby(factor_col).agg(
        使用次数=("股票代码", "count"),
        验证成功次数=("验证成功数", "sum"),
        达到1次数=("达到1数", "sum"),
        达到2次数=("达到2数", "sum"),
        止损次数=("止损数", "sum"),
        平均次日最高涨幅=("次日最高涨幅", "mean"),
        平均次日收盘涨幅=("次日收盘涨幅", "mean"),
        平均最大回撤=("次日最低涨幅", "mean"),
    ).reset_index()

    summary = summary.rename(columns={factor_col: "因子名称"})
    summary.insert(0, "因子类型", factor_type)

    summary["成功率"] = summary["验证成功次数"] / summary["使用次数"] * 100
    summary["达到1%率"] = summary["达到1次数"] / summary["使用次数"] * 100
    summary["达到2%率"] = summary["达到2次数"] / summary["使用次数"] * 100
    summary["止损率"] = summary["止损次数"] / summary["使用次数"] * 100

    round_cols = [
        "成功率",
        "达到1%率",
        "达到2%率",
        "止损率",
        "平均次日最高涨幅",
        "平均次日收盘涨幅",
        "平均最大回撤",
    ]

    for col in round_cols:
        summary[col] = summary[col].round(2)

    summary["因子等级"] = summary["成功率"].apply(get_factor_grade)

    return summary


def build_factor_rank() -> pd.DataFrame:
    """
    生成所有因子的排行榜。
    """

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"找不到次日验证文件：{INPUT_FILE}")

    df = pd.read_csv(INPUT_FILE, dtype={"股票代码": str})

    if df.empty:
        raise ValueError("next_day_review.csv 为空，无法生成因子排行榜")

    df = normalize_review_df(df)

    summaries = []

    for factor_col, factor_type in CONFIG["factor_columns"].items():
        summary = build_factor_summary(df, factor_col, factor_type)

        if not summary.empty:
            summaries.append(summary)

    if not summaries:
        return pd.DataFrame()

    rank_df = pd.concat(summaries, ignore_index=True)

    grade_order = {"S": 1, "A": 2, "B": 3, "C": 4, "D": 5}
    rank_df["_grade_rank"] = rank_df["因子等级"].map(grade_order).fillna(9)

    rank_df = rank_df.sort_values(
        by=["_grade_rank", "成功率", "平均次日最高涨幅", "使用次数"],
        ascending=[True, False, False, False],
    ).drop(columns=["_grade_rank"]).reset_index(drop=True)

    return rank_df


def build_markdown(rank_df: pd.DataFrame) -> str:
    """
    生成 Markdown 报告。
    """

    today = datetime.now().strftime("%Y-%m-%d")

    md_lines = [
        "# 因子表现排行榜 v1.8.0",
        "",
        f"生成日期：{today}",
        "",
        "数据来源：`output/next_day_review.csv`",
        "",
        "## 一、评级规则",
        "",
        "| 成功率 | 因子等级 |",
        "| --- | --- |",
        "| >= 75% | S |",
        "| >= 60% | A |",
        "| >= 45% | B |",
        "| >= 30% | C |",
        "| < 30% | D |",
        "",
        "## 二、因子总榜",
        "",
    ]

    if rank_df.empty:
        md_lines.append("无数据。")
        return "\n".join(md_lines)

    display_cols = [
        "因子类型",
        "因子名称",
        "因子等级",
        "使用次数",
        "验证成功次数",
        "成功率",
        "达到1%率",
        "达到2%率",
        "止损率",
        "平均次日最高涨幅",
        "平均次日收盘涨幅",
        "平均最大回撤",
    ]

    md_lines.append(rank_df[display_cols].to_markdown(index=False))
    md_lines.append("")

    for factor_type, group in rank_df.groupby("因子类型", sort=False):
        md_lines.append(f"## 三、{factor_type}")
        md_lines.append("")
        md_lines.append(group[display_cols].to_markdown(index=False))
        md_lines.append("")

    md_lines.extend([
        "## 四、使用建议",
        "",
        "- S/A 级因子：后续版本可以考虑加权。",
        "- B 级因子：继续观察，样本量不足时不急于调整。",
        "- C/D 级因子：后续需要降权、过滤或重新定义。",
        "- 使用次数过少的因子，不要过早下结论。",
    ])

    return "\n".join(md_lines)


def export_factor_rank() -> None:
    """
    主流程：生成并导出因子排行榜。
    """

    rank_df = build_factor_rank()

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    rank_df.to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    md = build_markdown(rank_df)
    OUTPUT_MD.write_text(md, encoding="utf-8")

    print("因子排行榜生成完成。")
    print(f"CSV：{OUTPUT_CSV}")
    print(f"Markdown：{OUTPUT_MD}")
    print(f"因子数量：{len(rank_df)}")

    if not rank_df.empty:
        print("\n因子等级统计：")
        print(rank_df["因子等级"].value_counts().sort_index())


if __name__ == "__main__":
    export_factor_rank()