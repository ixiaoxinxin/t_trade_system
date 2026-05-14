# app.py
# -*- coding: utf-8 -*-

"""
A股隔日T选股系统 v1.9.4 Streamlit 精简版

原则：
1. 只显示最重要信息
2. 减少冗余表格
3. 聚焦实盘执行
"""

from pathlib import Path
import subprocess
import sys

import pandas as pd
import streamlit as st


# =========================
# 文件路径
# =========================

MARKET_ENV_FILE = Path("output/market_environment.csv")
MARKET_ENV_MD_FILE = Path("output/market_environment.md")

FINAL_WATCHLIST_FILE = Path("output/final_watchlist.csv")
PLAN_FILE = Path("output/daily_plan.md")

LUNCH_REVIEW_FILE = Path("output/lunch_review.csv")
LUNCH_REVIEW_MD_FILE = Path("output/lunch_review.md")

NEXT_DAY_REVIEW_FILE = Path("output/next_day_review.csv")
NEXT_DAY_REVIEW_MD_FILE = Path("output/next_day_review.md")

FACTOR_PERFORMANCE_FILE = Path("output/factor_performance.csv")


st.set_page_config(
    page_title="A股隔日T选股系统 v1.9.4",
    layout="wide"
)


# =========================
# 通用函数
# =========================

def run_script(script_name: str) -> bool:
    """
    执行指定 Python 脚本。
    """

    try:
        result = subprocess.run(
            [sys.executable, script_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )

        if result.returncode != 0:
            st.error(f"{script_name} 执行失败")
            if result.stderr:
                st.code(result.stderr[-4000:])
            return False

        st.success(f"{script_name} 执行完成")

        if result.stdout:
            st.code(result.stdout[-2000:])

        return True

    except Exception as e:
        st.error(f"执行 {script_name} 出错：{e}")
        return False


def run_main_pipeline() -> None:
    """
    主流程：
    1. 市场环境
    2. 候选池
    3. 尾盘确认
    4. 交易计划
    """

    steps = [
        "market_environment.py",
        "strategy_overnight_t.py",
        "tail_confirmation.py",
        "report_generator.py",
    ]

    for script in steps:
        ok = run_script(script)

        if not ok:
            st.error(f"主流程中断：{script}")
            return

    st.success("主流程完成")


def load_csv(file_path: Path) -> pd.DataFrame:
    """
    读取 CSV。
    """

    if not file_path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(file_path, dtype={"股票代码": str})

        if "股票代码" in df.columns:
            df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)

        return df

    except Exception as e:
        st.error(f"读取 {file_path} 失败：{e}")
        return pd.DataFrame()


def load_markdown(file_path: Path) -> str:
    """
    读取 Markdown。
    """

    if not file_path.exists():
        return ""

    try:
        return file_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"读取 {file_path} 失败：{e}"


def keep_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """
    只保留核心字段。
    """

    if df.empty:
        return df

    existing = [col for col in columns if col in df.columns]

    return df[existing].copy()


def sort_final_watchlist(df: pd.DataFrame) -> pd.DataFrame:
    """
    尾盘确认排序。
    """

    if df.empty:
        return df

    df = df.copy()

    if "最终评分" in df.columns:
        df["最终评分"] = pd.to_numeric(df["最终评分"], errors="coerce")

    if "隔夜建议等级" in df.columns:
        grade_order = {"A": 1, "B": 2, "C": 3, "D": 4}
        df["_rank"] = df["隔夜建议等级"].map(grade_order).fillna(9)

        if "最终评分" in df.columns:
            df = df.sort_values(["_rank", "最终评分"], ascending=[True, False])
        else:
            df = df.sort_values("_rank")

        df = df.drop(columns=["_rank"])

    return df.reset_index(drop=True)


def show_table(title: str, df: pd.DataFrame) -> None:
    """
    展示表格。
    """

    st.subheader(title)

    if df.empty:
        st.warning("暂无数据")
        return

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
    )


def get_market_summary(market_df: pd.DataFrame) -> dict:
    """
    提取市场环境摘要。
    """

    if market_df.empty:
        return {
            "市场环境": "-",
            "是否允许隔夜": "-",
            "建议仓位": "-",
            "交易建议": "-",
        }

    row = market_df.iloc[0]

    return {
        "市场环境": str(row.get("市场环境", "-")),
        "是否允许隔夜": str(row.get("是否允许隔夜", "-")),
        "建议仓位": str(row.get("建议仓位", "-")),
        "交易建议": str(row.get("交易建议", "-")),
    }


def show_top_metrics(
    market_df: pd.DataFrame,
    final_df: pd.DataFrame,
    lunch_df: pd.DataFrame,
    next_df: pd.DataFrame,
) -> None:
    """
    顶部核心指标。
    """

    market = get_market_summary(market_df)

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("市场环境", market["市场环境"])

    with col2:
        st.metric("是否允许隔夜", market["是否允许隔夜"])

    with col3:
        if not final_df.empty and "隔夜建议等级" in final_df.columns:
            count = final_df[final_df["隔夜建议等级"].isin(["A", "B"])].shape[0]
        else:
            count = 0
        st.metric("A/B 候选", count)

    with col4:
        st.metric("午盘验证", len(lunch_df) if not lunch_df.empty else 0)

    with col5:
        if not next_df.empty and "是否验证成功" in next_df.columns:
            success_rate = next_df["是否验证成功"].astype(str).eq("是").mean() * 100
            st.metric("验证成功率", f"{success_rate:.1f}%")
        else:
            st.metric("验证成功率", "-")


# =========================
# 页面主体
# =========================

st.title("A股隔日T选股系统 v1.9.4")

st.caption("精简版：只看市场环境、交易池、午盘验证、次日验证、因子表现。")

st.divider()

# =========================
# 操作区
# =========================

st.subheader("操作区")

col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("市场环境", use_container_width=True):
        run_script("market_environment.py")
        st.rerun()

with col2:
    if st.button("一键主流程", use_container_width=True):
        run_main_pipeline()
        st.rerun()

with col3:
    if st.button("午盘验证", use_container_width=True):
        run_script("lunch_validator.py")
        st.rerun()

with col4:
    if st.button("次日验证", use_container_width=True):
        run_script("next_day_validator.py")
        st.rerun()

st.divider()

# =========================
# 读取数据
# =========================

market_df = load_csv(MARKET_ENV_FILE)
final_df = load_csv(FINAL_WATCHLIST_FILE)
lunch_df = load_csv(LUNCH_REVIEW_FILE)
next_df = load_csv(NEXT_DAY_REVIEW_FILE)
factor_df = load_csv(FACTOR_PERFORMANCE_FILE)

daily_plan_md = load_markdown(PLAN_FILE)
market_md = load_markdown(MARKET_ENV_MD_FILE)
lunch_md = load_markdown(LUNCH_REVIEW_MD_FILE)
next_md = load_markdown(NEXT_DAY_REVIEW_MD_FILE)

show_top_metrics(
    market_df=market_df,
    final_df=final_df,
    lunch_df=lunch_df,
    next_df=next_df,
)

st.divider()

# =========================
# Tab 区
# =========================

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "市场环境",
    "明日交易池",
    "午盘验证",
    "次日验证",
    "因子表现",
])


# =========================
# 市场环境
# =========================

with tab1:
    st.subheader("市场环境判断")

    if market_md:
        st.markdown(market_md)
    else:
        st.warning("暂无市场环境报告，请先点击【市场环境】按钮。")


# =========================
# 明日交易池
# =========================

with tab2:
    st.subheader("明日交易池")

    if daily_plan_md:
        st.markdown(daily_plan_md)
    else:
        st.warning("暂无交易计划，请先点击【一键主流程】。")

    st.divider()

    final_df = sort_final_watchlist(final_df)

    if not final_df.empty:
        trade_df = final_df[
            final_df["隔夜建议等级"].isin(["A", "B"])
        ].copy() if "隔夜建议等级" in final_df.columns else final_df.copy()

        trade_df = keep_columns(
            trade_df,
            [
                "股票代码",
                "股票名称",
                "热点标签",
                "风险等级",
                "隔夜建议等级",
                "候选评分",
                "尾盘评分",
                "最终评分",
                "分时结构标签",
                "尾盘抢筹标签",
                "隔夜建议说明",
            ],
        )

        show_table("A/B 核心候选", trade_df)
    else:
        st.warning("暂无尾盘确认结果。")


# =========================
# 午盘验证
# =========================

with tab3:
    st.subheader("午盘验证")

    if lunch_md:
        st.markdown(lunch_md)
    else:
        st.warning("暂无午盘验证报告，请在 11:20 后点击【午盘验证】。")

    st.divider()

    lunch_core_df = keep_columns(
        lunch_df,
        [
            "股票代码",
            "股票名称",
            "隔夜建议等级",
            "最终评分",
            "上午最高涨幅",
            "午盘涨幅",
            "上午最大回撤",
            "冲高保持率",
            "回撤风险等级",
            "冲高质量标签",
            "上午结构标签",
            "下午操作建议",
        ],
    )

    show_table("午盘核心结果", lunch_core_df)


# =========================
# 次日验证
# =========================

with tab4:
    st.subheader("次日验证")

    if next_md:
        st.markdown(next_md)
    else:
        st.warning("暂无次日验证报告，请次日收盘后运行。")

    st.divider()

    next_core_df = keep_columns(
        next_df,
        [
            "股票代码",
            "股票名称",
            "隔夜建议等级",
            "分时结构标签",
            "尾盘抢筹标签",
            "买入参考价",
            "次日最高涨幅",
            "次日收盘涨幅",
            "是否达到1%",
            "是否达到2%",
            "是否触发-2%止损",
            "是否验证成功",
        ],
    )

    show_table("次日验证明细", next_core_df)


# =========================
# 因子表现
# =========================

with tab5:
    st.subheader("因子表现")

    factor_core_df = keep_columns(
        factor_df,
        [
            "因子类型",
            "因子值",
            "数量",
            "成功数",
            "成功率",
            "达到1%率",
            "达到2%率",
            "止损率",
            "平均最高涨幅",
            "平均收盘涨幅",
        ],
    )

    show_table("因子表现统计", factor_core_df)