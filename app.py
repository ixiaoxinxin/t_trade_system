# app.py
# -*- coding: utf-8 -*-

"""
A股隔日T选股系统 v1.2 Streamlit 页面

功能：
1. 展示 output/overnight_t_candidates.csv
2. 展示 output/daily_plan.md
3. 支持重新生成候选池
4. 支持重新生成交易计划
"""

from pathlib import Path
import subprocess
import sys

import pandas as pd
import streamlit as st


CANDIDATE_FILE = Path("output/overnight_t_candidates.csv")
PLAN_FILE = Path("output/daily_plan.md")


st.set_page_config(
    page_title="A股隔日T选股系统 v1.2",
    layout="wide"
)


def run_script(script_name: str) -> bool:
    """
    执行指定 Python 脚本
    """

    try:
        result = subprocess.run(
            [sys.executable, script_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )

        if result.returncode != 0:
            st.error(f"{script_name} 执行失败")
            st.code(result.stderr)
            return False

        st.success(f"{script_name} 执行完成")
        if result.stdout:
            st.code(result.stdout[-3000:])

        return True

    except Exception as e:
        st.error(f"执行 {script_name} 出错：{e}")
        return False


def load_candidates() -> pd.DataFrame:
    """
    读取候选池 CSV
    """

    if not CANDIDATE_FILE.exists():
        return pd.DataFrame()

    df = pd.read_csv(CANDIDATE_FILE, dtype={"股票代码": str})

    if df.empty:
        return df

    df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)

    if "综合评分" in df.columns:
        df["综合评分"] = pd.to_numeric(df["综合评分"], errors="coerce")
        df = df.sort_values("综合评分", ascending=False).reset_index(drop=True)

    return df


def load_daily_plan() -> str:
    """
    读取每日交易计划 Markdown
    """

    if not PLAN_FILE.exists():
        return ""

    return PLAN_FILE.read_text(encoding="utf-8")


st.title("A股隔日T选股系统 v1.2")

st.divider()

col1, col2 = st.columns(2)

with col1:
    if st.button("重新生成候选池", use_container_width=True):
        run_script("strategy_overnight_t.py")
        st.rerun()

with col2:
    if st.button("重新生成交易计划", use_container_width=True):
        run_script("report_generator.py")
        st.rerun()

st.divider()

st.subheader("候选池")

candidate_df = load_candidates()

if candidate_df.empty:
    st.warning("暂未找到候选池文件：output/overnight_t_candidates.csv")
else:
    st.caption(f"候选股票数量：{len(candidate_df)}")
    st.dataframe(
        candidate_df,
        use_container_width=True,
        hide_index=True
    )

st.divider()

st.subheader("每日交易计划")

daily_plan = load_daily_plan()

if not daily_plan:
    st.warning("暂未找到交易计划文件：output/daily_plan.md")
else:
    st.markdown(daily_plan)