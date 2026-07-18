# app.py
# -*- coding: utf-8 -*-

"""
A股隔日T选股系统 v2.0 Streamlit 精简版

升级点：
1. 页面继续降噪，删除高低点/最高涨幅/最低涨幅等冗余展示
2. 次日验证拆分为：验证成功 / 验证失败或待优化
3. 已购买股票优先展示
4. 市场环境增加板块资金方向展示
5. 原始 Markdown 报告默认折叠
6. 人工复盘案例库动态读取
7. 卖点信号、午盘验证、次日验证字段进一步精简
"""

from pathlib import Path
import subprocess
import sys
import time
import json

import pandas as pd
import streamlit as st


# =========================
# 文件路径
# =========================

MARKET_ENV_FILE = Path("output/market_environment.csv")
MARKET_ENV_MD_FILE = Path("output/market_environment.md")

SECTOR_FLOW_FILE = Path("output/sector_fund_flow.csv")
SECTOR_FLOW_MD_FILE = Path("output/sector_fund_flow.md")

FINAL_WATCHLIST_FILE = Path("output/final_watchlist.csv")
PLAN_FILE = Path("output/daily_plan.md")

SELL_SIGNAL_FILE = Path("output/sell_signal.csv")
SELL_SIGNAL_MD_FILE = Path("output/sell_signal.md")

LUNCH_REVIEW_FILE = Path("output/lunch_review.csv")
LUNCH_REVIEW_MD_FILE = Path("output/lunch_review.md")

NEXT_DAY_REVIEW_FILE = Path("output/next_day_review.csv")
NEXT_DAY_REVIEW_MD_FILE = Path("output/next_day_review.md")

FACTOR_PERFORMANCE_FILE = Path("output/factor_performance.csv")

REVIEW_CASES_FILE = Path("output/review_cases.jsonl")
REVIEW_CASES_MD_FILE = Path("output/review_cases.md")

TRADE_RECORD_FILE = Path("output/trade_records.csv")


st.set_page_config(
    page_title="A股隔日T选股系统 v2.0",
    layout="wide"
)


# =========================
# 通用函数
# =========================

def run_script(script_name: str) -> tuple[bool, str, str]:
    try:
        result = subprocess.run(
            [sys.executable, script_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )

        return result.returncode == 0, result.stdout or "", result.stderr or ""

    except Exception as e:
        return False, "", str(e)


def show_script_result(script_name: str, success: bool, stdout: str, stderr: str) -> None:
    if success:
        st.success(f"{script_name} 执行完成")
    else:
        st.error(f"{script_name} 执行失败")

    if stdout:
        with st.expander(f"{script_name} 运行日志", expanded=False):
            st.code(stdout[-4000:])

    if stderr:
        with st.expander(f"{script_name} 错误日志", expanded=True):
            st.code(stderr[-4000:])


def run_single_script_and_refresh(script_name: str) -> None:
    with st.status(f"正在执行 {script_name} ...", expanded=True) as status:
        success, stdout, stderr = run_script(script_name)

        show_script_result(script_name, success, stdout, stderr)

        if success:
            status.update(
                label=f"{script_name} 执行完成，正在刷新页面...",
                state="complete",
            )
            time.sleep(1)
            st.rerun()
        else:
            status.update(
                label=f"{script_name} 执行失败",
                state="error",
            )


def run_main_pipeline_and_refresh() -> None:
    steps = [
        "market_environment.py",
        "strategy_overnight_t.py",
        "tail_confirmation.py",
        "report_generator.py",
    ]

    all_success = True

    with st.status("正在执行一键主流程...", expanded=True) as status:
        for index, script in enumerate(steps, start=1):
            st.write(f"步骤 {index}/{len(steps)}：{script}")

            success, stdout, stderr = run_script(script)
            show_script_result(script, success, stdout, stderr)

            if not success:
                all_success = False
                status.update(
                    label=f"主流程中断：{script} 执行失败",
                    state="error",
                )
                break

        if all_success:
            status.update(
                label="一键主流程全部执行完成，正在刷新页面...",
                state="complete",
            )
            time.sleep(1)
            st.rerun()


def load_csv(file_path: Path) -> pd.DataFrame:
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


def load_jsonl(file_path: Path) -> pd.DataFrame:
    if not file_path.exists():
        return pd.DataFrame()

    rows = []

    try:
        with file_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                if not line:
                    continue

                rows.append(json.loads(line))

        return pd.DataFrame(rows)

    except Exception as e:
        st.error(f"读取 {file_path} 失败：{e}")
        return pd.DataFrame()


def load_markdown(file_path: Path) -> str:
    if not file_path.exists():
        return ""

    try:
        return file_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"读取 {file_path} 失败：{e}"


def keep_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return df

    existing = [col for col in columns if col in df.columns]
    return df[existing].copy()


def load_bought_codes(
    trade_record_df: pd.DataFrame,
    review_df: pd.DataFrame,
) -> set[str]:
    bought_codes = set()

    if not trade_record_df.empty and "股票代码" in trade_record_df.columns:
        bought_codes.update(
            trade_record_df["股票代码"].astype(str).str.zfill(6).tolist()
        )

    if not review_df.empty and "股票代码" in review_df.columns:
        bought_codes.update(
            review_df["股票代码"].astype(str).str.zfill(6).tolist()
        )

    return bought_codes


def add_bought_flag(df: pd.DataFrame, bought_codes: set[str]) -> pd.DataFrame:
    if df.empty or "股票代码" not in df.columns:
        return df

    df = df.copy()

    if "是否已买入" in df.columns:
        df = df.drop(columns=["是否已买入"])

    df["是否已买入"] = df["股票代码"].astype(str).str.zfill(6).isin(bought_codes)
    df["是否已买入"] = df["是否已买入"].map({True: "是", False: "否"})

    df["_buy_rank"] = df["是否已买入"].map({"是": 0, "否": 1})
    df = df.sort_values("_buy_rank").drop(columns=["_buy_rank"])

    cols = ["是否已买入"] + [col for col in df.columns if col != "是否已买入"]
    return df[cols].reset_index(drop=True)


def sort_final_watchlist(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()

    if "最终评分" in df.columns:
        df["最终评分"] = pd.to_numeric(df["最终评分"], errors="coerce")

    if "尾盘评分" in df.columns:
        df["尾盘评分"] = pd.to_numeric(df["尾盘评分"], errors="coerce")

    if "隔夜建议等级" in df.columns:
        grade_order = {"A": 1, "B": 2, "C": 3, "D": 4}
        df["_rank"] = df["隔夜建议等级"].map(grade_order).fillna(9)

        sort_cols = ["_rank"]
        ascending = [True]

        if "最终评分" in df.columns:
            sort_cols.append("最终评分")
            ascending.append(False)

        if "尾盘评分" in df.columns:
            sort_cols.append("尾盘评分")
            ascending.append(False)

        df = df.sort_values(sort_cols, ascending=ascending)
        df = df.drop(columns=["_rank"])

    return df.reset_index(drop=True)


def show_table(title: str, df: pd.DataFrame) -> None:
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
    if market_df.empty:
        return {
            "市场环境": "-",
            "是否允许隔夜": "-",
            "建议仓位": "-",
            "资金流入方向": "-",
        }

    row = market_df.iloc[0]

    return {
        "市场环境": str(row.get("市场环境", "-")),
        "是否允许隔夜": str(row.get("是否允许隔夜", "-")),
        "建议仓位": str(row.get("建议仓位", "-")),
        "资金流入方向": str(row.get("资金流入方向", "-")),
    }


def show_top_metrics(
    market_df: pd.DataFrame,
    final_df: pd.DataFrame,
    sell_df: pd.DataFrame,
    lunch_df: pd.DataFrame,
    next_df: pd.DataFrame,
    review_df: pd.DataFrame,
) -> None:
    market = get_market_summary(market_df)

    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)

    with col1:
        st.metric("市场环境", market["市场环境"])

    with col2:
        st.metric("是否隔夜", market["是否允许隔夜"])

    with col3:
        if not final_df.empty and "隔夜建议等级" in final_df.columns:
            count = final_df[final_df["隔夜建议等级"].isin(["A", "B"])].shape[0]
        else:
            count = 0
        st.metric("A/B候选", count)

    with col4:
        st.metric("卖点信号", len(sell_df) if not sell_df.empty else 0)

    with col5:
        st.metric("午盘验证", len(lunch_df) if not lunch_df.empty else 0)

    with col6:
        if not next_df.empty and "是否验证成功" in next_df.columns:
            success_rate = next_df["是否验证成功"].astype(str).eq("是").mean() * 100
            st.metric("成功率", f"{success_rate:.1f}%")
        else:
            st.metric("成功率", "-")

    with col7:
        st.metric("复盘案例", len(review_df) if not review_df.empty else 0)

    st.caption(f"资金流入方向：{market['资金流入方向']}")


# =========================
# 页面主体
# =========================

st.title("A股隔日T选股系统 v2.0")

st.caption("精简版：市场环境 → 明日交易池 → 卖点信号 → 午盘验证 → 次日验证 → 复盘")

st.divider()

# =========================
# 操作区
# =========================

st.subheader("操作区")

col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    if st.button("市场环境", use_container_width=True):
        run_single_script_and_refresh("market_environment.py")

with col2:
    if st.button("一键主流程", use_container_width=True):
        run_main_pipeline_and_refresh()

with col3:
    if st.button("卖点信号", use_container_width=True):
        run_single_script_and_refresh("sell_signal_engine.py")

with col4:
    if st.button("午盘验证", use_container_width=True):
        run_single_script_and_refresh("lunch_validator.py")

with col5:
    if st.button("次日验证", use_container_width=True):
        run_single_script_and_refresh("next_day_validator.py")

with col6:
    if st.button("生成复盘库", use_container_width=True):
        run_single_script_and_refresh("review_manager.py")

st.divider()

# =========================
# 读取数据
# =========================

market_df = load_csv(MARKET_ENV_FILE)
sector_flow_df = load_csv(SECTOR_FLOW_FILE)

final_df = load_csv(FINAL_WATCHLIST_FILE)
sell_signal_df = load_csv(SELL_SIGNAL_FILE)
lunch_df = load_csv(LUNCH_REVIEW_FILE)
next_df = load_csv(NEXT_DAY_REVIEW_FILE)
factor_df = load_csv(FACTOR_PERFORMANCE_FILE)
review_cases_df = load_jsonl(REVIEW_CASES_FILE)
trade_record_df = load_csv(TRADE_RECORD_FILE)

daily_plan_md = load_markdown(PLAN_FILE)
market_md = load_markdown(MARKET_ENV_MD_FILE)
sector_flow_md = load_markdown(SECTOR_FLOW_MD_FILE)
sell_signal_md = load_markdown(SELL_SIGNAL_MD_FILE)
lunch_md = load_markdown(LUNCH_REVIEW_MD_FILE)
next_md = load_markdown(NEXT_DAY_REVIEW_MD_FILE)
review_cases_md = load_markdown(REVIEW_CASES_MD_FILE)

bought_codes = load_bought_codes(trade_record_df, review_cases_df)

show_top_metrics(
    market_df=market_df,
    final_df=final_df,
    sell_df=sell_signal_df,
    lunch_df=lunch_df,
    next_df=next_df,
    review_df=review_cases_df,
)

st.divider()

# =========================
# Tab 区
# =========================

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "市场环境",
    "明日交易池",
    "卖点信号",
    "午盘验证",
    "次日验证",
    "因子表现",
    "人工复盘",
])


with tab1:
    st.subheader("市场环境")

    if market_md:
        with st.expander("展开市场环境原始报告", expanded=False):
            st.markdown(market_md)
    else:
        st.warning("暂无市场环境报告，请先点击【市场环境】按钮。")


with tab2:
    st.subheader("明日交易池")

    st.markdown("""
### 核心字段说明

| 字段 | 怎么看 |
|---|---|
| 隔夜建议等级 | 只优先看 A/B |
| 风险等级 | 优先低风险 |
| 最终评分 | 越高越优先 |
| 分时结构标签 | 优先强势横盘、尾盘资金回流 |
| 尾盘抢筹标签 | 优先尾盘抢筹、资金回流 |
""")

    if daily_plan_md:
        with st.expander("展开交易计划原始报告", expanded=False):
            st.markdown(daily_plan_md)
    else:
        st.warning("暂无交易计划，请先点击【一键主流程】。")

    st.divider()

    final_df = sort_final_watchlist(final_df)

    if not final_df.empty and "隔夜建议等级" in final_df.columns:
        trade_df = final_df[final_df["隔夜建议等级"].isin(["A", "B"])].copy()
    else:
        trade_df = final_df.copy()

    trade_df = keep_columns(
        trade_df,
        [
            "股票代码",
            "股票名称",
            "风险等级",
            "隔夜建议等级",
            "最终评分",
            "分时结构标签",
            "尾盘抢筹标签",
            "隔夜建议说明",
        ],
    )

    trade_df = add_bought_flag(trade_df, bought_codes)

    show_table("尾盘确认后的 A/B 核心候选", trade_df)


with tab3:
    st.subheader("卖点信号")

    if sell_signal_md:
        with st.expander("展开卖点信号原始报告", expanded=False):
            st.markdown(sell_signal_md)
    else:
        st.warning("暂无卖点信号，请点击【卖点信号】按钮。")

    st.divider()

    sell_core_df = keep_columns(
        sell_signal_df,
        [
            "股票代码",
            "股票名称",
            "市场环境",
            "参考价",
            "分时均价",
            "盘中最高",
            "卖出信号",
            "卖出理由",
        ],
    )

    sell_core_df = add_bought_flag(sell_core_df, bought_codes)

    show_table("卖点核心信号", sell_core_df)


with tab4:
    st.subheader("午盘验证")

    if lunch_md:
        with st.expander("展开午盘验证原始报告", expanded=False):
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
            "午盘涨幅",
            "上午结构标签",
            "下午操作建议",
        ],
    )

    lunch_core_df = add_bought_flag(lunch_core_df, bought_codes)

    show_table("午盘核心结果", lunch_core_df)


with tab5:
    st.subheader("次日验证")

    if next_md:
        with st.expander("展开次日验证原始报告", expanded=False):
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
            "计划低吸下限",
            "计划低吸上限",
            "次日收盘涨幅",
            "是否触达低吸区间",
            "执行验证结果",
            "是否达到1%",
            "是否达到2%",
            "是否触发-2%止损",
            "是否验证成功",
        ],
    )

    next_core_df = add_bought_flag(next_core_df, bought_codes)

    if not next_core_df.empty and "是否验证成功" in next_core_df.columns:
        success_df = next_core_df[next_core_df["是否验证成功"].astype(str).eq("是")].copy()
        failed_df = next_core_df[~next_core_df["是否验证成功"].astype(str).eq("是")].copy()
    else:
        success_df = pd.DataFrame()
        failed_df = next_core_df.copy()

    show_table("验证成功", success_df)
    show_table("验证失败 / 待优化", failed_df)


with tab6:
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
            "平均收盘涨幅",
        ],
    )

    show_table("因子表现统计", factor_core_df)


with tab7:
    st.subheader("人工复盘案例库")

    if review_cases_md:
        with st.expander("展开复盘原始报告", expanded=False):
            st.markdown(review_cases_md)
    else:
        st.warning("暂无复盘案例库，请点击【生成复盘库】按钮。")

    st.divider()

    review_core_df = keep_columns(
        review_cases_df,
        [
            "日期",
            "股票代码",
            "股票名称",
            "交易类型",
            "实际盈亏",
            "市场环境",
            "系统结构",
            "系统结论",
        ],
    )

    show_table("复盘案例明细", review_core_df)
