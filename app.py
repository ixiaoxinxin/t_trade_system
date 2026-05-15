# app.py
# -*- coding: utf-8 -*-

"""
A股隔日T选股系统 v2.0.1 Streamlit 精简版

升级点：
1. 一键主流程完整顺序执行
2. 每个脚本显示执行状态和日志
3. 执行完成后自动刷新页面
4. 页面只保留核心信息
5. 明日交易池中明确展示尾盘确认关键字段
6. 增加人工复盘案例库
"""

from pathlib import Path
import subprocess
import sys
import time

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
    page_title="A股隔日T选股系统 v2.0.1",
    layout="wide"
)


# =========================
# 通用函数
# =========================

def run_script(script_name: str) -> tuple[bool, str, str]:
    """
    执行指定 Python 脚本。

    返回：
    - 是否成功
    - stdout
    - stderr
    """

    try:
        result = subprocess.run(
            [sys.executable, script_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )

        success = result.returncode == 0

        return success, result.stdout or "", result.stderr or ""

    except Exception as e:
        return False, "", str(e)


def show_script_result(script_name: str, success: bool, stdout: str, stderr: str) -> None:
    """
    展示单个脚本执行结果。
    """

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
    """
    执行单个脚本，完成后自动刷新。
    """

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
    """
    一键主流程：
    1. 市场环境
    2. 候选池
    3. 尾盘确认
    4. 交易计划

    全部执行成功后自动刷新页面。
    """

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


def show_manual_review_cases() -> None:
    """
    人工复盘案例库。
    """

    st.subheader("人工复盘案例库")

    st.markdown("""
# 人工复盘案例库 v2.0.1

---

## 案例一：共达电声（002655）

### 交易结果

| 项目 | 内容 |
|---|---|
| 买入时间 | 尾盘 |
| 买入价 | 37.50 |
| 买入数量 | 200股 |
| 卖出价 | 38.10 / 37.70 |
| 平均卖出价 | 37.90 |
| 实际盈利 | 约 68.2 元 |
| 市场环境 | 偏弱，大盘约 -0.88% |
| 系统结构 | B级 + 强势横盘型 |
| 尾盘抢筹 | 尾盘普通 |

---

### 系统判断

这笔交易属于：

**弱市环境下的 B 级强势横盘验证单。**

系统选股有效，次日给出 +2% 以上冲高空间，说明：

| 因子 | 结论 |
|---|---|
| 强势横盘型 | 有效 |
| 弱市强势股 | 有效 |
| B级低仓验证 | 合理 |
| 尾盘普通 | 确定性不如尾盘资金回流 |

---

### 实际问题

这笔交易最大问题不是买点，而是卖点。

具体表现：

| 问题 | 说明 |
|---|---|
| 达到 +2% 后未完全兑现 | 弱市中应优先止盈 |
| 冲高后回落未及时处理 | 利润回吐 |
| 37.70 卖出偏慢 | 第二笔卖点效率较低 |
| 缺少规则化止盈 | 卖出仍带主观情绪 |

---

### 优化后的标准卖法

| 卖点 | 条件 | 动作 |
|---|---|---|
| 第一卖点 | 价格冲到 38.00~38.20，达到约 +2% | 先卖出至少一半 |
| 第二卖点 | 高点回撤超过 1.5% | 清仓或继续减仓 |
| 防守卖点 | 跌破分时均线 | 清仓 |
| 弱市规则 | 大盘弱于 -0.5%，个股达到 2% | 不恋战，优先兑现 |

---

### 本案例沉淀出的卖点因子

| 因子 | 规则 |
|---|---|
| 市场环境 | 偏弱/系统风险时，盈利阈值降低 |
| 达到2% | 弱市中触发主动止盈 |
| 高点回撤 | 回撤超过 1.5% 触发卖出 |
| 分时均线 | 跌破均线视为承接减弱 |
| 冲高保持率 | 低于 40% 视为假强 |
| 尾盘抢筹强度 | 尾盘普通的票，次日更应快进快出 |

---

### 对系统的升级要求

下一版本应新增：

**sell_signal_engine.py**

核心目标：

- 对 A/B 核心候选生成次日止盈计划
- 计算 1%、2%、3% 止盈价
- 根据市场环境调整止盈速度
- 根据分时结构决定持有/兑现
- 用 PushPlus 推送微信提醒
- 后续记录卖出结果，验证卖点系统盈利能力

---

## 案例二：环旭电子

| 项目 | 结论 |
|---|---|
| 结构 | 尾盘资金回流 |
| 次日表现 | 成功 |
| 系统结论 | 尾盘资金回流是高有效性结构 |

---

## 案例三：潍柴动力

| 项目 | 结论 |
|---|---|
| 结构 | 急跌修复 |
| 次日表现 | 失败 |
| 系统结论 | 急跌修复持续性较差，隔夜应降权 |

---

## 当前有效性排序

| 结构 | 当前有效性 |
|---|---|
| 尾盘资金回流 | 高 |
| 强势横盘 | 高 |
| 弱市强势横盘 | 高，但必须快进快出 |
| 急跌修复 | 中低 |
| 冲高回落 | 低 |

---

## 当前系统阶段结论

v1.x 已初步验证：

**选股系统有效。**

v2.x 重点应转向：

**卖点系统。**

当前最重要目标：

不是继续找更多股票，而是提高：

- 止盈效率
- 利润保留率
- 冲高回落处理能力
- 弱市兑现纪律
""")


# =========================
# 页面主体
# =========================

st.title("A股隔日T选股系统 v2.0.1")

st.caption("精简版：市场环境 → 明日交易池 → 午盘验证 → 次日验证 → 因子表现 → 人工复盘")

st.divider()

# =========================
# 操作区
# =========================

st.subheader("操作区")

col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("市场环境", use_container_width=True):
        run_single_script_and_refresh("market_environment.py")

with col2:
    if st.button("一键主流程", use_container_width=True):
        run_main_pipeline_and_refresh()

with col3:
    if st.button("午盘验证", use_container_width=True):
        run_single_script_and_refresh("lunch_validator.py")

with col4:
    if st.button("次日验证", use_container_width=True):
        run_single_script_and_refresh("next_day_validator.py")

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

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "市场环境",
    "明日交易池",
    "午盘验证",
    "次日验证",
    "因子表现",
    "人工复盘",
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

    st.markdown("""
### 尾盘确认关键字段

| 字段 | 含义 | 怎么看 |
|---|---|---|
| 隔夜建议等级 | 最终是否适合隔夜 | 只优先看 A/B |
| 风险等级 | 当前个股风险 | 优先低风险 |
| 尾盘评分 | 只看尾盘资金和分时强度 | 越高越好 |
| 最终评分 | 日线评分 + 尾盘评分 + 风控结果 | 越高越好 |
| 分时结构标签 | 全天/尾盘分时形态 | 优先强势横盘、尾盘资金回流 |
| 尾盘抢筹标签 | 14:30 后资金态度 | 优先尾盘抢筹、尾盘资金回流 |
| 隔夜建议说明 | 系统给出的操作解释 | 用于人工复核 |
""")

    st.divider()

    if daily_plan_md:
        st.markdown(daily_plan_md)
    else:
        st.warning("暂无交易计划，请先点击【一键主流程】。")

    st.divider()

    final_df = sort_final_watchlist(final_df)

    if not final_df.empty and "隔夜建议等级" in final_df.columns:
        trade_df = final_df[
            final_df["隔夜建议等级"].isin(["A", "B"])
        ].copy()
    else:
        trade_df = final_df.copy()

    trade_df = keep_columns(
        trade_df,
        [
            "股票代码",
            "股票名称",
            "热点标签",
            "所属板块",
            "风险等级",
            "隔夜建议等级",
            "候选评分",
            "尾盘评分",
            "最终评分",
            "分时结构标签",
            "尾盘抢筹标签",
            "今日涨跌幅",
            "收盘位置",
            "从低点修复幅度",
            "尾盘放量倍数",
            "隔夜建议说明",
        ],
    )

    show_table("尾盘确认后的 A/B 核心候选", trade_df)

    st.info(
        "实盘优先级：A/B + 低风险 + 尾盘评分高 + 分时结构强 + 尾盘资金回流。"
        " 如果市场环境为系统风险，只看 A 级低风险，且小仓位。"
    )


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


# =========================
# 人工复盘
# =========================

with tab6:
    show_manual_review_cases()