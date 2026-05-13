# app.py
# -*- coding: utf-8 -*-

"""
A股隔日T选股系统 v1.7.1 Streamlit 页面

功能：
1. 展示候选池
2. 展示尾盘确认结果
3. 展示交易计划
4. 展示次日验证
5. 展示因子表现
6. 展示因子登记表
7. 支持一键运行完整流程
"""

from pathlib import Path
import subprocess
import sys

import pandas as pd
import streamlit as st


CANDIDATE_FILE = Path("output/overnight_t_candidates.csv")
FINAL_WATCHLIST_FILE = Path("output/final_watchlist.csv")
PLAN_FILE = Path("output/daily_plan.md")
FACTOR_REGISTRY_FILE = Path("output/factor_registry.md")

NEXT_DAY_REVIEW_FILE = Path("output/next_day_review.csv")
NEXT_DAY_REVIEW_MD_FILE = Path("output/next_day_review.md")
FACTOR_PERFORMANCE_FILE = Path("output/factor_performance.csv")


st.set_page_config(
    page_title="A股隔日T选股系统 v1.7.1",
    layout="wide"
)


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
                st.code(result.stderr[-5000:])
            return False

        st.success(f"{script_name} 执行完成")

        if result.stdout:
            st.code(result.stdout[-3000:])

        return True

    except Exception as e:
        st.error(f"执行 {script_name} 出错：{e}")
        return False


def run_full_pipeline() -> None:
    """
    一键运行完整流程：
    1. 生成候选池
    2. 尾盘确认
    3. 生成交易计划

    注意：
    次日验证需要在次日行情出现后单独运行。
    """

    steps = [
        "strategy_overnight_t.py",
        "tail_confirmation.py",
        "report_generator.py",
    ]

    for script in steps:
        ok = run_script(script)

        if not ok:
            st.error(f"流程中断：{script} 执行失败")
            return

    st.success("完整流程执行完成")


def load_csv(file_path: Path) -> pd.DataFrame:
    """
    读取 CSV 文件。
    """

    if not file_path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(file_path, dtype={"股票代码": str})

        if df.empty:
            return df

        if "股票代码" in df.columns:
            df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)

        return df

    except Exception as e:
        st.error(f"读取 {file_path} 失败：{e}")
        return pd.DataFrame()


def load_markdown(file_path: Path) -> str:
    """
    读取 Markdown 文件。
    """

    if not file_path.exists():
        return ""

    try:
        return file_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"读取 {file_path} 失败：{e}"


def sort_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    根据已有评分字段排序。
    """

    if df.empty:
        return df

    df = df.copy()

    for col in [
        "最终评分",
        "尾盘评分",
        "候选评分",
        "综合评分",
        "次日最高涨幅",
        "次日收盘涨幅",
        "成功率",
        "平均最高涨幅",
        "平均收盘涨幅",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "隔夜建议等级" in df.columns:
        grade_order = {"A": 1, "B": 2, "C": 3, "D": 4}
        df["_grade_rank"] = df["隔夜建议等级"].map(grade_order).fillna(9)

        score_col = "最终评分" if "最终评分" in df.columns else None

        if score_col:
            df = df.sort_values(
                by=["_grade_rank", score_col],
                ascending=[True, False],
            )
        else:
            df = df.sort_values("_grade_rank")

        df = df.drop(columns=["_grade_rank"])

        return df.reset_index(drop=True)

    if "买入优先级" in df.columns:
        priority_order = {"A": 1, "B": 2, "C": 3, "D": 4}
        df["_priority_rank"] = df["买入优先级"].map(priority_order).fillna(9)

        score_col = "候选评分" if "候选评分" in df.columns else "综合评分"

        if score_col in df.columns:
            df = df.sort_values(
                by=["_priority_rank", score_col],
                ascending=[True, False],
            )
        else:
            df = df.sort_values("_priority_rank")

        df = df.drop(columns=["_priority_rank"])

        return df.reset_index(drop=True)

    if "成功率" in df.columns:
        df = df.sort_values("成功率", ascending=False)

    elif "次日最高涨幅" in df.columns:
        df = df.sort_values("次日最高涨幅", ascending=False)

    elif "综合评分" in df.columns:
        df = df.sort_values("综合评分", ascending=False)

    return df.reset_index(drop=True)


def filter_dataframe(df: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    """
    根据页面筛选条件过滤 DataFrame。
    """

    if df.empty:
        return df

    filtered = df.copy()

    filter_cols = []

    for col in [
        "隔夜建议等级",
        "买入优先级",
        "风险等级",
        "是否验证成功",
        "是否达到1%",
        "是否达到2%",
        "是否触发-2%止损",
        "分时结构标签",
        "尾盘抢筹标签",
    ]:
        if col in filtered.columns:
            filter_cols.append(col)

    for col in filter_cols:
        values = sorted([v for v in filtered[col].dropna().astype(str).unique().tolist() if v])

        selected = st.multiselect(
            f"{col}筛选",
            options=values,
            default=values,
            key=f"{key_prefix}_{col}",
        )

        if selected:
            filtered = filtered[filtered[col].astype(str).isin(selected)]

    return filtered


def show_metrics(candidate_df: pd.DataFrame, final_df: pd.DataFrame, review_df: pd.DataFrame) -> None:
    """
    顶部核心指标。
    """

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("候选池数量", len(candidate_df) if not candidate_df.empty else 0)

    with col2:
        st.metric("尾盘确认数量", len(final_df) if not final_df.empty else 0)

    with col3:
        if not final_df.empty and "隔夜建议等级" in final_df.columns:
            trade_count = final_df[final_df["隔夜建议等级"].isin(["A", "B"])].shape[0]
        else:
            trade_count = 0
        st.metric("A/B交易候选", trade_count)

    with col4:
        if not final_df.empty and "最终评分" in final_df.columns:
            max_score = pd.to_numeric(final_df["最终评分"], errors="coerce").max()
            st.metric("最高最终评分", f"{max_score:.2f}" if pd.notna(max_score) else "-")
        else:
            st.metric("最高最终评分", "-")

    with col5:
        if not review_df.empty and "是否验证成功" in review_df.columns:
            success_rate = review_df["是否验证成功"].astype(str).eq("是").mean() * 100
            st.metric("验证成功率", f"{success_rate:.2f}%")
        else:
            st.metric("验证成功率", "-")


def show_dataframe_section(title: str, df: pd.DataFrame, key_prefix: str) -> None:
    """
    展示表格区块。
    """

    st.subheader(title)

    if df.empty:
        st.warning(f"暂无数据：{title}")
        return

    filtered_df = filter_dataframe(df, key_prefix)
    filtered_df = sort_dataframe(filtered_df)

    st.caption(f"显示数量：{len(filtered_df)} / 原始数量：{len(df)}")

    st.dataframe(
        filtered_df,
        use_container_width=True,
        hide_index=True,
    )


st.title("A股隔日T选股系统 v1.7.1")

st.caption("流程：候选池 → 尾盘确认 → 交易计划 → 次日验证 → 因子表现")

st.divider()

# =========================
# 操作按钮
# =========================

st.subheader("操作区")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    if st.button("重新生成候选池", use_container_width=True):
        run_script("strategy_overnight_t.py")
        st.rerun()

with col2:
    if st.button("重新生成尾盘确认", use_container_width=True):
        run_script("tail_confirmation.py")
        st.rerun()

with col3:
    if st.button("重新生成交易计划", use_container_width=True):
        run_script("report_generator.py")
        st.rerun()

with col4:
    if st.button("次日验证", use_container_width=True):
        run_script("next_day_validator.py")
        st.rerun()

with col5:
    if st.button("一键全流程", use_container_width=True):
        run_full_pipeline()
        st.rerun()

st.divider()

# =========================
# 读取数据
# =========================

candidate_df = load_csv(CANDIDATE_FILE)
final_df = load_csv(FINAL_WATCHLIST_FILE)
next_day_review_df = load_csv(NEXT_DAY_REVIEW_FILE)
factor_performance_df = load_csv(FACTOR_PERFORMANCE_FILE)

daily_plan = load_markdown(PLAN_FILE)
factor_registry_md = load_markdown(FACTOR_REGISTRY_FILE)
next_day_review_md = load_markdown(NEXT_DAY_REVIEW_MD_FILE)

show_metrics(candidate_df, final_df, next_day_review_df)

st.divider()

# =========================
# 页面 Tab
# =========================

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "候选池",
    "尾盘确认",
    "交易计划",
    "次日验证",
    "因子表现",
    "因子登记",
])

with tab1:
    show_dataframe_section(
        title="候选池：overnight_t_candidates.csv",
        df=candidate_df,
        key_prefix="candidate",
    )

with tab2:
    show_dataframe_section(
        title="尾盘确认：final_watchlist.csv",
        df=final_df,
        key_prefix="final",
    )

with tab3:
    st.subheader("每日交易计划：daily_plan.md")

    if not daily_plan:
        st.warning("暂未找到交易计划文件：output/daily_plan.md")
    else:
        st.markdown(daily_plan)

with tab4:
    st.subheader("次日验证报告：next_day_review.md")

    if not next_day_review_md:
        st.warning("暂未找到次日验证报告：output/next_day_review.md")
    else:
        st.markdown(next_day_review_md)

    show_dataframe_section(
        title="次日验证明细：next_day_review.csv",
        df=next_day_review_df,
        key_prefix="next_day_review",
    )

with tab5:
    show_dataframe_section(
        title="因子表现：factor_performance.csv",
        df=factor_performance_df,
        key_prefix="factor_performance",
    )

with tab6:
    st.subheader("因子登记表：factor_registry.md")

    if not factor_registry_md:
        st.warning("暂未找到因子登记文件：output/factor_registry.md")
    else:
        st.markdown(factor_registry_md)