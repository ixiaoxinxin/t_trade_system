# app.py
# -*- coding: utf-8 -*-

"""A股隔日T选股系统 Streamlit 页面入口。"""

from pathlib import Path
import subprocess
import sys
import time

import pandas as pd
import streamlit as st

try:
    import streamlit_antd_components as sac
except Exception:
    sac = None

from fixed_holdings import fixed_holding_codes, fixed_holding_name_map, mark_fixed_holdings, sort_fixed_holdings_first
from common import normalize_code, safe_float
from scheduled_refresh import read_state as read_scheduled_refresh_state
from sqlite_store import load_dataframe, load_document, migrate_local_files_to_sqlite
from trade_journal import (
    append_trade_record,
    build_trade_record,
    calculate_commission,
    calculate_sell_stamp_tax,
    load_trade_records,
    normalize_optional_code,
    update_trade_record,
)


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

TRADE_RECORD_FILE = Path("output/trade_records.csv")
DATASET_QUALITY_REPORT_FILE = Path("output/dataset_quality_report.md")
DATASET_SAMPLES_FILE = Path("data/dataset/dataset_samples.csv")
FEATURE_SNAPSHOT_FILE = Path("data/dataset/feature_snapshot.csv")
LABEL_SNAPSHOT_FILE = Path("data/dataset/label_snapshot.csv")
PREDICTION_LOG_FILE = Path("data/dataset/prediction_log.csv")
MODEL_PREDICTION_FILE = Path("output/model_predictions_v2.6.csv")
MODEL_EVALUATION_MD_FILE = Path("output/model_evaluation_v2.6.md")
PROFIT_PROBABILITY_FILE = Path("output/profit_probabilities_v2.7.csv")
PROFIT_PROBABILITY_EVALUATION_MD_FILE = Path("output/profit_probability_evaluation_v2.7.md")
CALIBRATED_PROBABILITY_FILE = Path("output/calibrated_probabilities_v2.8.csv")
MODEL_EXPLANATION_FILE = Path("output/model_explanations_v2.8.csv")
CALIBRATION_REPORT_FILE = Path("output/probability_calibration_v2.8.md")
PREDICTION_REVIEW_FILE = Path("output/prediction_review_v2.9.csv")
MODEL_SCORECARD_FILE = Path("output/model_scorecard_v2.9.csv")
PREDICTION_REVIEW_REPORT_FILE = Path("output/prediction_review_v2.9.md")
DAILY_MODEL_REPORT_FILE = Path("output/daily_model_report.md")
FINAL_DECISION_FILE = Path("output/final_decision_v3.0.csv")
FINAL_DECISION_MD_FILE = Path("output/final_decision_v3.0.md")
SINGLE_STOCK_DECISION_FILE = Path("output/single_stock_decision.csv")
SINGLE_STOCK_DECISION_MD_FILE = Path("output/single_stock_decision.md")
FIXED_HOLDINGS_SIGNAL_FILE = Path("output/fixed_holdings_signals.csv")
FIXED_HOLDINGS_REFRESH_FILE = Path("output/fixed_holdings_refresh.csv")
OPENING_LEVELS_FILE = Path("output/opening_levels.csv")
OPENING_LEVELS_MD_FILE = Path("output/opening_levels.md")
T_MODE_DECISION_FILE = Path("output/t_mode_decision.csv")
T_MODE_DECISION_MD_FILE = Path("output/t_mode_decision.md")
METAL_MACRO_FILE = Path("output/metal_macro_snapshot.csv")
METAL_MACRO_MD_FILE = Path("output/metal_macro_report.md")
PREOPEN_PREDICTION_FILE = Path("output/preopen_prediction.csv")
PREOPEN_PREDICTION_MD_FILE = Path("output/preopen_prediction.md")
SECTOR_ROTATION_FILE = Path("output/sector_rotation.csv")
SECTOR_ROTATION_MD_FILE = Path("output/sector_rotation_report.md")
PERFORMANCE_REPORT_FILE = Path("output/performance_report.csv")
PERFORMANCE_REPORT_MD_FILE = Path("output/performance_report.md")


st.set_page_config(
    page_title="A股隔日T选股系统",
    layout="wide"
)

st.markdown(
    """
    <style>
    #MainMenu, footer {
        visibility: hidden;
    }
    section[data-testid="stSidebar"] {
        min-width: 260px !important;
        width: 260px !important;
    }
    .block-container {
        padding-top: 2rem;
        max-width: 100%;
    }
    div[data-testid="stDataFrame"] {
        border-radius: 8px;
        max-width: 100%;
        overflow-x: auto;
    }
    div[data-testid="stMetric"] {
        min-width: 120px;
    }
    .stButton button {
        min-height: 44px;
        white-space: normal;
    }
    @media (max-width: 900px) {
        section[data-testid="stSidebar"] {
            min-width: 224px !important;
            width: 224px !important;
        }
        .block-container {
            padding: 1rem 0.75rem 2rem;
        }
        h1 {
            font-size: 2rem !important;
            line-height: 1.2 !important;
        }
        h2 {
            font-size: 1.55rem !important;
            line-height: 1.25 !important;
        }
        h3 {
            font-size: 1.25rem !important;
            line-height: 1.3 !important;
        }
        p, li, label, [data-testid="stMarkdownContainer"] {
            font-size: 0.95rem;
        }
        [data-testid="column"] {
            min-width: 0;
        }
        div[data-testid="stDataFrame"] {
            border-radius: 6px;
        }
        div[data-testid="stMetric"] {
            padding-bottom: 0.5rem;
        }
    }
    @media (max-width: 640px) {
        .block-container {
            padding-left: 0.55rem;
            padding-right: 0.55rem;
        }
        h1 {
            font-size: 1.7rem !important;
        }
        .stButton button {
            width: 100%;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================
# 通用函数
# =========================

def run_script(script_name: str) -> tuple[bool, str, str]:
    return run_command([script_name])


def run_command(command_args: list[str]) -> tuple[bool, str, str]:
    try:
        result = subprocess.run(
            [sys.executable, *command_args],
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
            migrate_local_files_to_sqlite()
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


def run_main_command_and_refresh(command_name: str) -> None:
    with st.status(f"正在执行 {command_name} ...", expanded=True) as status:
        success, stdout, stderr = run_command(["main.py", command_name])

        show_script_result(command_name, success, stdout, stderr)

        if success:
            migrate_local_files_to_sqlite()
            status.update(
                label=f"{command_name} 执行完成，正在刷新页面...",
                state="complete",
            )
            time.sleep(1)
            st.rerun()
        else:
            status.update(
                label=f"{command_name} 执行失败",
                state="error",
            )


def run_main_command_with_stock_and_refresh(command_name: str, stock_text: str) -> None:
    with st.status(f"正在执行 {command_name} ...", expanded=True) as status:
        args = ["main.py", command_name]
        if stock_text.strip():
            args.extend(["--stock-code", stock_text.strip()])
        success, stdout, stderr = run_command(args)

        show_script_result(command_name, success, stdout, stderr)

        if success:
            migrate_local_files_to_sqlite()
            status.update(
                label=f"{command_name} 执行完成，正在刷新页面...",
                state="complete",
            )
            time.sleep(1)
            st.rerun()
        else:
            status.update(
                label=f"{command_name} 执行失败",
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

    with st.status("正在生成明日计划...", expanded=True) as status:
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
            migrate_local_files_to_sqlite()
            status.update(
                label="明日计划生成完成，正在刷新页面...",
                state="complete",
            )
            time.sleep(1)
            st.rerun()


def load_csv(file_path: Path) -> pd.DataFrame:
    db_df = load_dataframe(file_path)

    if not db_df.empty:
        return db_df

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
    db_content = load_document(file_path)

    if db_content:
        return db_content

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


def render_scheduled_refresh_status() -> None:
    state = read_scheduled_refresh_state()
    schedule_text = "；".join(
        f"{item.get('time')} {item.get('name')}"
        for item in state.get("schedule", [])
    )
    last_success = state.get("last_success")
    if state.get("running"):
        status_text = f"运行中：{state.get('last_job', '')}，开始于 {state.get('last_started_at', '')}"
    elif last_success is True:
        status_text = f"最近完成：{state.get('last_job', '')}，{state.get('last_finished_at', '')}"
    elif last_success is False:
        status_text = f"最近失败：{state.get('last_job', '')}，失败命令：{state.get('last_error', '')}"
    else:
        status_text = "等待首次自动刷新"

    st.caption(f"后台自动刷新：{schedule_text}")
    st.caption(status_text)


def parse_price_input(value: str) -> float:
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    return float(text)


def build_stock_name_code_map(*frames: pd.DataFrame) -> dict[str, str]:
    mapping = {name: code for code, name in fixed_holding_name_map().items()}

    for frame in frames:
        if frame.empty:
            continue

        code_col = "股票代码" if "股票代码" in frame.columns else "stock_code" if "stock_code" in frame.columns else ""
        name_col = "股票名称" if "股票名称" in frame.columns else "stock_name" if "stock_name" in frame.columns else ""
        if not code_col or not name_col:
            continue

        for _, row in frame.iterrows():
            name = str(row.get(name_col, "")).strip()
            code = normalize_optional_code(row.get(code_col, ""))
            if name and code:
                mapping.setdefault(name, code)

    return mapping


def resolve_trade_stock_code(stock_name: str, stock_code: str, name_code_map: dict[str, str]) -> str:
    raw_code = str(stock_code).strip()
    if raw_code:
        return normalize_optional_code(raw_code)

    return name_code_map.get(str(stock_name).strip(), "")


def model_has_variation(df: pd.DataFrame, columns: list[str]) -> bool:
    for col in columns:
        if col not in df.columns:
            continue
        unique_count = pd.to_numeric(df[col], errors="coerce").dropna().round(6).nunique()
        if unique_count > 1:
            return True
    return False


def add_model_signal_status(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    result = df.copy()
    columns = [
        "次日上涨概率",
        "方向置信度",
        "达到1%概率",
        "达到2%概率",
        "止损概率",
    ]
    result["模型状态"] = "有区分" if model_has_variation(result, columns) else "仅观察"
    return result


def short_action_text(action: str, *, fixed: bool = False) -> str:
    action = str(action).strip()
    fixed_text = {
        "继续持有": "继续持有：暂未触发卖点。",
        "减仓": "减仓：风险升高，先降仓位。",
        "止盈": "止盈：收益已到，先落袋。",
        "清仓": "清仓：卖点触发，先退出。",
        "止损": "止损：跌破风控，立即退出。",
    }
    candidate_text = {
        "优先低吸": "优先低吸：只等计划买点。",
        "小仓观察": "小仓观察：可看，不追。",
        "只观察": "只观察：条件不够，先不买。",
        "放弃": "放弃：风险不划算。",
    }

    if fixed and action in fixed_text:
        return fixed_text[action]
    if action in candidate_text:
        return candidate_text[action]
    if action in fixed_text:
        return fixed_text[action]
    return action or "暂无操作。"


def add_short_reason(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "最终操作" not in df.columns:
        return df

    result = df.copy()
    fixed_series = result.get("固定持仓", pd.Series(["否"] * len(result), index=result.index))
    result["操作短句"] = [
        short_action_text(action, fixed=str(fixed).lower() in ["true", "1", "是"])
        for action, fixed in zip(result["最终操作"], fixed_series)
    ]
    return result


def add_verification_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    result = df.copy()

    def row_status(row: pd.Series) -> str:
        execution = str(row.get("执行验证结果", "")).strip()
        success = str(row.get("是否验证成功", "")).strip()
        touched = str(row.get("是否触达低吸区间", "")).strip()
        hit_1 = str(row.get("是否达到1%", "")).strip()
        stop = str(row.get("是否触发-2%止损", "")).strip()

        if "数据" in execution or "不足" in execution:
            return "数据不足"
        if touched == "否":
            return "未给买点"
        if execution == "需分时确认":
            return "需分时确认"
        if execution == "给买点且成功":
            return "计划有效"
        if execution == "风险触发":
            return "计划待优化"
        if execution == "未给买点":
            return "未给买点"
        if stop == "是" and hit_1 == "是":
            return "需分时确认"
        if success == "是" or hit_1 == "是":
            return "计划有效"
        if stop == "是" or touched == "是":
            return "计划待优化"
        return "数据不足"

    text_map = {
        "计划有效": "计划有效：给了买点，达到目标。",
        "计划待优化": "待优化：给了买点，但收益不足或风险先到。",
        "需分时确认": "需确认：分钟线仍不能判定先止盈还是先止损。",
        "未给买点": "未给买点：计划没有成交机会。",
        "数据不足": "数据不足：今天不参与判断。",
    }

    def row_optimization(row: pd.Series) -> str:
        status = str(row.get("系统验证结果", "")).strip()
        touched = str(row.get("是否触达低吸区间", "")).strip()
        hit_1 = str(row.get("是否达到1%", "")).strip()
        stop = str(row.get("是否触发-2%止损", "")).strip()

        if status == "计划有效":
            return "保留：规则有效"
        if status == "需分时确认":
            return "补分时：确认先止盈还是先止损"
        if status == "未给买点" or touched == "否":
            return "观察：未成交，不评价胜负"
        if status == "数据不足":
            return "补数据：先刷新行情"
        if stop == "是":
            return "降风险：买点下移，弱市少做"
        if hit_1 != "是":
            return "提质量：过滤弱结构和弱板块"
        return "复核：检查规则和数据"

    result["系统验证结果"] = result.apply(row_status, axis=1)
    result["复盘结论"] = result["系统验证结果"].map(text_map).fillna(result["系统验证结果"])
    result["优化方向"] = result.apply(row_optimization, axis=1)
    return result


def pct_text(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value * 100:.1f}%"


def scorecard_metric(metric_name: str) -> float | None:
    if model_scorecard_df.empty or "metric_name" not in model_scorecard_df.columns:
        return None

    metric_df = model_scorecard_df[
        model_scorecard_df["metric_name"].astype(str).eq(metric_name)
        & model_scorecard_df.get("segment_type", pd.Series(index=model_scorecard_df.index, dtype=str)).astype(str).eq("all")
        & model_scorecard_df.get("segment_value", pd.Series(index=model_scorecard_df.index, dtype=str)).astype(str).eq("all")
    ]
    if metric_df.empty or "score" not in metric_df.columns:
        return None

    value = pd.to_numeric(metric_df["score"], errors="coerce").dropna()
    return float(value.iloc[0]) if not value.empty else None


MODEL_DECISION_METRICS = {"direction_hit_rate", "hit_1pct_brier", "hit_2pct_brier", "stop_2pct_brier"}


def model_scorecard_has_valid_scores() -> bool:
    if model_scorecard_df.empty or {"metric_name", "score"}.difference(model_scorecard_df.columns):
        return False

    metric_rows = model_scorecard_df[model_scorecard_df["metric_name"].isin(MODEL_DECISION_METRICS)]
    if metric_rows.empty:
        return False

    return not pd.to_numeric(metric_rows["score"], errors="coerce").dropna().empty


def probability_has_variation(df: pd.DataFrame, columns: list[str]) -> bool:
    if df.empty:
        return False

    valid_counts = []
    for col in columns:
        if col not in df.columns:
            continue
        count = pd.to_numeric(df[col], errors="coerce").dropna().round(6).nunique()
        valid_counts.append(count)

    return bool(valid_counts) and any(count > 1 for count in valid_counts)


def build_model_sorting_guard(
    model_predictions_df: pd.DataFrame,
    profit_probability_df: pd.DataFrame,
) -> pd.DataFrame:
    score_valid = model_scorecard_has_valid_scores()
    direction_varied = probability_has_variation(
        model_predictions_df,
        ["next_day_up_probability", "direction_confidence"],
    )
    profit_varied = probability_has_variation(
        profit_probability_df,
        ["hit_1pct_probability", "hit_2pct_probability", "stop_2pct_probability"],
    )
    allow_sorting = score_valid and (direction_varied or profit_varied)

    return pd.DataFrame(
        [
            {
                "检查项": "模型评分",
                "状态": "有效" if score_valid else "为空/不可用",
                "页面动作": "可参考评分" if score_valid else "不参与强排序",
                "原因": "评分卡存在有效指标" if score_valid else "AUC、Brier 等关键指标为空或缺失",
            },
            {
                "检查项": "方向概率",
                "状态": "有区分" if direction_varied else "无区分",
                "页面动作": "可辅助观察" if direction_varied else "只显示，不排序",
                "原因": "不同股票概率存在差异" if direction_varied else "概率相同、为空或回退到基准概率",
            },
            {
                "检查项": "收益概率",
                "状态": "有区分" if profit_varied else "无区分",
                "页面动作": "可辅助观察" if profit_varied else "只显示，不排序",
                "原因": "收益/止损概率存在差异" if profit_varied else "收益目标概率相同或为空",
            },
            {
                "检查项": "排序保护",
                "状态": "允许辅助排序" if allow_sorting else "禁止强排序",
                "页面动作": "可以参与候选辅助排序" if allow_sorting else "最终操作只看规则、卖点和单票决策",
                "原因": "评分有效且概率有区分" if allow_sorting else "模型还没有证明可用于个股强弱排序",
            },
        ]
    )


def build_next_day_review_summary(next_core_df: pd.DataFrame) -> pd.DataFrame:
    if next_core_df.empty:
        return pd.DataFrame()

    total_count = len(next_core_df)
    touch_rate = next_core_df["是否触达低吸区间"].astype(str).eq("是").mean()
    hit_1_rate = next_core_df["是否达到1%"].astype(str).eq("是").mean()
    stop_rate = next_core_df["是否触发-2%止损"].astype(str).eq("是").mean()
    needs_intraday_count = int(next_core_df["系统验证结果"].astype(str).eq("需分时确认").sum())
    scorecard_touch_rate = scorecard_metric("buy_range_executable_rate")

    has_model_score = model_scorecard_has_valid_scores()

    rows = [
        {
            "复盘项": "低吸可成交",
            "今日数据": f"{pct_text(touch_rate)}（{int(round(touch_rate * total_count))}/{total_count}）",
            "结论": "买点给得到" if touch_rate >= 0.6 else "买点偏低或机会不足",
            "系统优化方向": "成交率不低时优先看风险；成交率低时复核买点区间。",
        },
        {
            "复盘项": "止损风险",
            "今日数据": pct_text(stop_rate),
            "结论": "风险偏高" if stop_rate >= 0.4 else "风险可控",
            "系统优化方向": "止损率高时下调买点上沿，弱结构候选降权。",
        },
        {
            "复盘项": "+1%机会",
            "今日数据": pct_text(hit_1_rate),
            "结论": "有波动空间" if hit_1_rate >= 0.4 else "收益空间不足",
            "系统优化方向": "保留能到 +1% 的形态，过滤冲高后易回撤样本。",
        },
        {
            "复盘项": "分时确认",
            "今日数据": f"{needs_intraday_count} 只",
            "结论": "需要补分时" if needs_intraday_count > 0 else "日线可判断",
            "系统优化方向": "同时出现止盈和止损时，不进入干净标签，先补分时先后顺序。",
        },
        {
            "复盘项": "模型可用性",
            "今日数据": "已有有效评分" if has_model_score else "评分为空",
            "结论": "可辅助观察" if has_model_score else "暂不强排序",
            "系统优化方向": "继续沉淀真实交易和有效标签，模型概率不替代最终操作。",
        },
    ]

    if scorecard_touch_rate is not None and abs(scorecard_touch_rate - touch_rate) >= 0.1:
        rows.append(
            {
                "复盘项": "报告口径",
                "今日数据": f"验证表 {pct_text(touch_rate)} / 评分卡 {pct_text(scorecard_touch_rate)}",
                "结论": "口径不一致",
                "系统优化方向": "报告需标记数据来源和生成批次，避免混用不同运行结果。",
            }
        )

    return pd.DataFrame(rows)


def split_fixed_candidate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty or "固定持仓" not in df.columns:
        return pd.DataFrame(), df.copy()

    fixed_mask = df["固定持仓"].astype(str).str.lower().isin(["true", "1", "是"])
    return df[fixed_mask].copy(), df[~fixed_mask].copy()


def load_bought_codes(trade_record_df: pd.DataFrame) -> set[str]:
    bought_codes = set()

    if not trade_record_df.empty and "股票代码" in trade_record_df.columns:
        bought_codes.update(
            trade_record_df["股票代码"].astype(str).str.zfill(6).tolist()
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


def add_model_probability(df: pd.DataFrame, prediction_df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or prediction_df.empty or "股票代码" not in df.columns:
        return df

    if "stock_code" not in prediction_df.columns:
        return df

    pred = prediction_df.copy()
    pred["股票代码"] = pred["stock_code"].astype(str).str.zfill(6)
    pred = pred.sort_values("predict_date").drop_duplicates("股票代码", keep="last")
    pred = pred.rename(columns={
        "next_day_up_probability": "次日上涨概率",
        "direction_confidence": "方向置信度",
        "predicted_direction": "模型方向",
        "model_version": "模型版本",
    })

    merged = df.merge(
        pred[["股票代码", "次日上涨概率", "方向置信度", "模型方向", "模型版本"]],
        on="股票代码",
        how="left",
    )

    for col in ["次日上涨概率", "方向置信度"]:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")

    return merged


def add_profit_probability(df: pd.DataFrame, probability_df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or probability_df.empty or "股票代码" not in df.columns:
        return df

    if "stock_code" not in probability_df.columns:
        return df

    prob = probability_df.copy()
    prob["股票代码"] = prob["stock_code"].astype(str).str.zfill(6)
    prob = prob.sort_values("predict_date").drop_duplicates("股票代码", keep="last")
    prob = prob.rename(columns={
        "hit_1pct_probability": "达到1%概率",
        "hit_2pct_probability": "达到2%概率",
        "stop_2pct_probability": "止损概率",
        "risk_adjusted_1pct": "1%风险差",
        "risk_adjusted_2pct": "2%风险差",
        "probability_risk_reward": "概率收益风险比",
        "final_probability_signal": "概率信号",
    })

    merged = df.merge(
        prob[
            [
                "股票代码",
                "达到1%概率",
                "达到2%概率",
                "止损概率",
                "1%风险差",
                "2%风险差",
                "概率收益风险比",
                "概率信号",
            ]
        ],
        on="股票代码",
        how="left",
    )

    for col in ["达到1%概率", "达到2%概率", "止损概率", "1%风险差", "2%风险差", "概率收益风险比"]:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")

    return merged


def add_final_decision(df: pd.DataFrame, decision_df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or decision_df.empty or "股票代码" not in df.columns:
        return df

    if "stock_code" not in decision_df.columns:
        return df

    decision = decision_df.copy()
    decision["股票代码"] = decision["stock_code"].astype(str).str.zfill(6)
    decision = decision.sort_values("created_at").drop_duplicates("股票代码", keep="last")
    decision = decision.rename(columns={
        "final_action": "最终操作",
        "fusion_score": "融合评分",
        "decision_reason": "操作解释",
        "risk_reward_ratio": "风险收益比",
        "model_quality_score": "模型可信度",
    })

    columns = [
        "股票代码",
        "最终操作",
        "融合评分",
        "操作解释",
        "风险收益比",
        "模型可信度",
    ]
    existing = [col for col in columns if col in decision.columns]

    merged = df.merge(decision[existing], on="股票代码", how="left")
    for col in ["融合评分", "模型可信度"]:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")

    return merged


def sort_final_watchlist(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = sort_fixed_holdings_first(mark_fixed_holdings(df.copy()))

    if "最终评分" in df.columns:
        df["最终评分"] = pd.to_numeric(df["最终评分"], errors="coerce")

    if "尾盘评分" in df.columns:
        df["尾盘评分"] = pd.to_numeric(df["尾盘评分"], errors="coerce")

    if "隔夜建议等级" in df.columns:
        grade_order = {"A": 1, "B": 2, "C": 3, "持仓": 4, "D": 5}
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


def show_table(title: str, df: pd.DataFrame, height: int | None = None) -> None:
    st.subheader(title)

    if df.empty:
        st.warning("暂无数据")
        return

    display_df = df.copy()

    for col in display_df.select_dtypes(include=["object"]).columns:
        display_df[col] = display_df[col].fillna("").astype(str)

    dataframe_kwargs = {
        "width": "stretch",
        "hide_index": True,
    }
    if height is not None:
        dataframe_kwargs["height"] = height

    st.dataframe(display_df, **dataframe_kwargs)


def add_billion_columns(df: pd.DataFrame, source_col: str = "主力净流入") -> pd.DataFrame:
    if df.empty or source_col not in df.columns:
        return df

    result = df.copy()
    values = pd.to_numeric(result[source_col], errors="coerce")
    result[f"{source_col}亿元"] = values.apply(lambda value: "" if pd.isna(value) else f"{value / 100000000:.2f}")
    return result


def keep_recent_dates(df: pd.DataFrame, date_col: str, limit: int = 3) -> pd.DataFrame:
    if df.empty or date_col not in df.columns:
        return df

    result = df.copy()
    dates = pd.to_datetime(result[date_col], errors="coerce")
    result["_sort_date"] = dates
    recent_dates = (
        result.dropna(subset=["_sort_date"])["_sort_date"]
        .dt.date
        .drop_duplicates()
        .sort_values(ascending=False)
        .head(limit)
        .tolist()
    )
    if not recent_dates:
        return result.drop(columns=["_sort_date"])
    result = result[result["_sort_date"].dt.date.isin(recent_dates)]
    return result.drop(columns=["_sort_date"])


def render_action_hint(title: str, text: str) -> None:
    st.info(f"{title}：{text}")


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
    trade_record_df: pd.DataFrame,
) -> None:
    market = get_market_summary(market_df)
    closed_trade_count = 0

    if not trade_record_df.empty and "闭环状态" in trade_record_df.columns:
        closed_trade_count = int(trade_record_df["闭环状态"].astype(str).eq("已闭环").sum())

    col1, col2, col3, col4, col5, col6, col7, col8 = st.columns(8)

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
        st.metric("交易记录", len(trade_record_df) if not trade_record_df.empty else 0)

    with col8:
        st.metric("已闭环", closed_trade_count)

    st.caption(f"资金流入方向：{market['资金流入方向']}")


def build_personal_trade_feedback(trade_record_df: pd.DataFrame) -> pd.DataFrame:
    if trade_record_df.empty:
        return pd.DataFrame(
            [
                {
                    "反馈项": "真实交易样本",
                    "当前数据": "0 笔",
                    "结论": "样本不足",
                    "系统用途": "先记录日内T/隔日T闭环交易，暂不参与个性化校准。",
                }
            ]
        )

    df = trade_record_df.copy()
    status_series = df.get("闭环状态", pd.Series(index=df.index, dtype=str)).astype(str)
    closed_df = df[status_series.eq("已闭环")].copy()
    closed_count = len(closed_df)
    total_count = len(df)
    open_count = total_count - closed_count

    profit_series = pd.to_numeric(closed_df.get("到手利润", pd.Series(dtype=float)), errors="coerce").fillna(0)
    return_series = pd.to_numeric(closed_df.get("收益率", pd.Series(dtype=float)), errors="coerce").dropna()
    total_profit = float(profit_series.sum()) if not profit_series.empty else 0.0
    win_rate = float((profit_series > 0).mean() * 100) if not profit_series.empty else 0.0
    avg_return = float(return_series.mean()) if not return_series.empty else 0.0

    followed_series = df.get("是否按计划执行", pd.Series(index=df.index, dtype=str)).astype(str)
    planned_count = int(followed_series.eq("是").sum())
    planned_rate = planned_count / total_count * 100 if total_count else 0.0

    trade_type_series = df.get("交易类型", pd.Series(index=df.index, dtype=str)).astype(str)
    intraday_count = int(trade_type_series.eq("日内T").sum())
    overnight_count = int(trade_type_series.eq("隔日T").sum())

    if closed_count < 10:
        sample_status = "只做记录"
        sample_usage = "闭环样本少，先用于复盘，不参与模型校准。"
    elif closed_count < 30:
        sample_status = "可做轻量校准"
        sample_usage = "可观察哪些系统候选在你的实盘里更容易赚钱。"
    elif win_rate >= 55 and total_profit > 0:
        sample_status = "可做正向校准"
        sample_usage = "优先提炼盈利交易特征，给同类候选加参考权重。"
    else:
        sample_status = "优先做风险校准"
        sample_usage = "优先提炼亏损交易共性，降低同类候选追买强度。"

    return pd.DataFrame(
        [
            {
                "反馈项": "闭环交易",
                "当前数据": f"{closed_count}/{total_count} 笔，未闭环 {open_count} 笔",
                "结论": sample_status,
                "系统用途": sample_usage,
            },
            {
                "反馈项": "实盘结果",
                "当前数据": f"胜率 {win_rate:.1f}%，已实现 {total_profit:.2f} 元，均值 {avg_return:.2f}%",
                "结论": "赚钱样本" if total_profit > 0 else "风险样本",
                "系统用途": "后续用于校准系统候选的真实可执行收益，而不是只看理论命中。",
            },
            {
                "反馈项": "执行纪律",
                "当前数据": f"按计划 {planned_count}/{total_count} 笔，比例 {planned_rate:.1f}%",
                "结论": "纪律可评估" if planned_count else "缺少计划标记",
                "系统用途": "区分系统问题和执行偏差，避免把人为追高误算成策略失败。",
            },
            {
                "反馈项": "交易类型",
                "当前数据": f"日内T {intraday_count} 笔，隔日T {overnight_count} 笔",
                "结论": "样本分层",
                "系统用途": "后续分别校准日内T和隔日T，不混用两种交易节奏。",
            },
        ]
    )


def render_fixed_holding_snapshot(
    final_df: pd.DataFrame,
    sell_df: pd.DataFrame,
    lunch_df: pd.DataFrame,
    next_df: pd.DataFrame,
    prediction_df: pd.DataFrame,
) -> None:
    st.subheader("固定持仓监控")
    st.caption("这里只看当前持仓怎么处理。午盘/次日验证已移到模型构建的数据复盘页。")

    signal_df = load_csv(FIXED_HOLDINGS_SIGNAL_FILE)
    signal_df = add_profit_probability(add_model_probability(signal_df, prediction_df), profit_probability_df)
    signal_df = add_final_decision(signal_df, final_decision_df)

    if signal_df.empty:
        st.info("暂无固定持仓买卖点，请点击【刷新持仓买卖点】。")
    else:
        signal_df = add_short_reason(add_model_signal_status(signal_df))
        show_table(
            "固定持仓重点数据",
            keep_columns(
                signal_df,
                [
                    "股票名称",
                    "股票代码",
                    "当前价",
                    "当前涨幅",
                    "买点下限",
                    "买点上限",
                    "买点状态",
                    "卖点信号",
                    "实时行情时间",
                    "实时状态",
                    "分钟状态",
                ],
            ),
            height=260,
        )
        show_table(
            "固定持仓操作建议",
            keep_columns(
                signal_df,
                [
                    "最终操作",
                    "股票名称",
                    "股票代码",
                    "操作短句",
                    "卖点信号",
                    "卖点理由",
                    "买点状态",
                    "买点依据",
                    "模型状态",
                ],
            ),
            height=260,
        )


# =========================
# 页面主体
# =========================

st.title("A股隔日T选股系统")
st.caption("按实盘操作顺序重组：数据前瞻 → 准备工作 → 日内交易 → 隔日持仓 → 交易记录 → 模型构建。")
render_scheduled_refresh_status()

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
model_prediction_df = load_csv(MODEL_PREDICTION_FILE)
profit_probability_df = load_csv(PROFIT_PROBABILITY_FILE)
calibrated_probability_df = load_csv(CALIBRATED_PROBABILITY_FILE)
model_explanation_df = load_csv(MODEL_EXPLANATION_FILE)
prediction_review_df = load_csv(PREDICTION_REVIEW_FILE)
model_scorecard_df = load_csv(MODEL_SCORECARD_FILE)
final_decision_df = load_csv(FINAL_DECISION_FILE)
single_stock_decision_df = load_csv(SINGLE_STOCK_DECISION_FILE)
opening_levels_df = load_csv(OPENING_LEVELS_FILE)
t_mode_decision_df = load_csv(T_MODE_DECISION_FILE)
metal_macro_df = load_csv(METAL_MACRO_FILE)
preopen_prediction_df = load_csv(PREOPEN_PREDICTION_FILE)
sector_rotation_df = load_csv(SECTOR_ROTATION_FILE)
performance_report_df = load_csv(PERFORMANCE_REPORT_FILE)
trade_record_df = load_trade_records(TRADE_RECORD_FILE)

daily_plan_md = load_markdown(PLAN_FILE)
market_md = load_markdown(MARKET_ENV_MD_FILE)
sector_flow_md = load_markdown(SECTOR_FLOW_MD_FILE)
sell_signal_md = load_markdown(SELL_SIGNAL_MD_FILE)
lunch_md = load_markdown(LUNCH_REVIEW_MD_FILE)
next_md = load_markdown(NEXT_DAY_REVIEW_MD_FILE)
dataset_quality_md = load_markdown(DATASET_QUALITY_REPORT_FILE)
model_evaluation_md = load_markdown(MODEL_EVALUATION_MD_FILE)
profit_probability_evaluation_md = load_markdown(PROFIT_PROBABILITY_EVALUATION_MD_FILE)
calibration_report_md = load_markdown(CALIBRATION_REPORT_FILE)
prediction_review_report_md = load_markdown(PREDICTION_REVIEW_REPORT_FILE)
daily_model_report_md = load_markdown(DAILY_MODEL_REPORT_FILE)
final_decision_md = load_markdown(FINAL_DECISION_MD_FILE)
single_stock_decision_md = load_markdown(SINGLE_STOCK_DECISION_MD_FILE)
opening_levels_md = load_markdown(OPENING_LEVELS_MD_FILE)
t_mode_decision_md = load_markdown(T_MODE_DECISION_MD_FILE)
metal_macro_md = load_markdown(METAL_MACRO_MD_FILE)
preopen_prediction_md = load_markdown(PREOPEN_PREDICTION_MD_FILE)
sector_rotation_md = load_markdown(SECTOR_ROTATION_MD_FILE)
performance_report_md = load_markdown(PERFORMANCE_REPORT_MD_FILE)

final_df = mark_fixed_holdings(final_df)
sell_signal_df = sort_fixed_holdings_first(mark_fixed_holdings(sell_signal_df))
lunch_df = sort_fixed_holdings_first(mark_fixed_holdings(lunch_df))
next_df = sort_fixed_holdings_first(mark_fixed_holdings(next_df))

bought_codes = load_bought_codes(trade_record_df)

show_top_metrics(
    market_df=market_df,
    final_df=final_df,
    sell_df=sell_signal_df,
    lunch_df=lunch_df,
    next_df=next_df,
    trade_record_df=trade_record_df,
)

st.divider()

# =========================
# Tab 区
# =========================

def render_trade_record_panel() -> None:
    st.subheader("交易记录")
    st.caption("只记录日内T / 隔日T。佣金按招行证券万2.5、单笔最低5元；卖出另扣印花税。")

    name_code_map = build_stock_name_code_map(
        final_df,
        final_decision_df,
        sell_signal_df,
        lunch_df,
        next_df,
        model_prediction_df,
        profit_probability_df,
    )

    with st.form("trade_record_form", clear_on_submit=True):
        row1_col1, row1_col2, row1_col3, row1_col4 = st.columns([1, 1, 1, 1])

        with row1_col1:
            trade_date = st.date_input("交易日期")

        with row1_col2:
            trade_type = st.selectbox("交易类型", ["隔日T", "日内T"])

        with row1_col3:
            stock_name = st.text_input("股票名称", placeholder="例如 天齐锂业")

        with row1_col4:
            stock_code = st.text_input("股票代码（可选）", placeholder="留空时按股票名称匹配")

        row2_col1, row2_col2, row2_col3, row2_col4 = st.columns([1, 1, 1, 1])

        with row2_col1:
            direction = st.selectbox("方向", ["买入并卖出", "买入", "卖出"])

        with row2_col2:
            buy_price_text = st.text_input("买入价格/成本价", placeholder="例如 46.99")

        with row2_col3:
            sell_price_text = st.text_input("卖出价格", placeholder="例如 48.20；未卖出可空")

        with row2_col4:
            quantity = st.number_input("数量", min_value=0, value=100, step=100)

        try:
            buy_price = parse_price_input(buy_price_text)
            sell_price = parse_price_input(sell_price_text)
            preview_buy_amount = buy_price * quantity
            preview_sell_amount = sell_price * quantity
            preview_buy_fee = calculate_commission(preview_buy_amount)
            preview_sell_fee = calculate_commission(preview_sell_amount) if preview_sell_amount > 0 else 0
            preview_stamp_tax = calculate_sell_stamp_tax(preview_sell_amount) if preview_sell_amount > 0 else 0
            preview_total_fee = preview_buy_fee + preview_sell_fee + preview_stamp_tax
        except ValueError:
            buy_price = 0.0
            sell_price = 0.0
            preview_buy_fee = 0.0
            preview_sell_fee = 0.0
            preview_stamp_tax = 0.0
            preview_total_fee = 0.0
            st.warning("价格只能输入数字，例如 46.99。")

        if sell_price > 0 and buy_price > 0 and quantity > 0:
            preview_profit = (sell_price - buy_price) * quantity - preview_total_fee
            preview_return = preview_profit / preview_buy_amount * 100 if preview_buy_amount > 0 else 0
            st.caption(
                f"预估费用：{preview_total_fee:.2f} 元"
                f"（买佣 {preview_buy_fee:.2f}，卖佣 {preview_sell_fee:.2f}，印花税 {preview_stamp_tax:.2f}）；"
                f"预估到手利润：{preview_profit:.2f} 元；"
                f"收益率：{preview_return:.2f}%"
            )
        elif buy_price > 0 and quantity > 0:
            st.caption(f"预估买入手续费：{preview_buy_fee:.2f} 元；卖出后将自动计算到手利润。")

        row3_col1, row3_col2 = st.columns([1, 1])

        with row3_col1:
            strategy_source = st.selectbox("策略来源", ["系统候选", "手动观察", "盘中机会", "复盘补录"])

        with row3_col2:
            followed_plan = st.selectbox("是否按计划执行", ["是", "否", "部分执行", "未记录"])

        note = st.text_area("备注", placeholder="记录买入理由、卖出理由、错过点、执行偏差等", height=90)
        submitted = st.form_submit_button("保存交易记录", width="stretch")

        if submitted:
            try:
                resolved_code = resolve_trade_stock_code(stock_name, stock_code, name_code_map)

                record = build_trade_record(
                    stock_code=resolved_code,
                    stock_name=stock_name,
                    trade_date=trade_date,
                    trade_type=trade_type,
                    direction=direction,
                    buy_price=buy_price,
                    sell_price=sell_price,
                    quantity=quantity,
                    strategy_source=strategy_source,
                    followed_plan=followed_plan,
                    note=note,
                )
                append_trade_record(record, TRADE_RECORD_FILE)
                st.success("交易记录已保存")
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"保存失败：{e}")

    st.divider()
    render_trade_record_summary()


def render_trade_record_summary() -> None:
    current_trade_df = load_trade_records(TRADE_RECORD_FILE)

    if current_trade_df.empty:
        st.info("暂无交易记录，先保存一笔日内T或隔日T。")
        return

    open_position_count = int(current_trade_df["闭环状态"].astype(str).eq("未闭环").sum())
    sold_df = current_trade_df[current_trade_df["闭环状态"].astype(str).eq("已闭环")].copy()
    total_profit = pd.to_numeric(sold_df["到手利润"], errors="coerce").fillna(0).sum()
    avg_return = pd.to_numeric(sold_df["收益率"], errors="coerce").dropna()
    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)

    with metric_col1:
        st.metric("交易记录", len(current_trade_df))

    with metric_col2:
        st.metric("未闭环", open_position_count)

    with metric_col3:
        st.metric("已实现盈亏", f"{total_profit:.2f}")

    with metric_col4:
        st.metric("平均收益率", f"{avg_return.mean():.2f}%" if not avg_return.empty else "-")

    show_table("真实交易个性化反馈", build_personal_trade_feedback(current_trade_df))

    render_trade_record_editor(current_trade_df)

    recent_trade_df = current_trade_df.sort_values("记录时间", ascending=False).head(30)
    show_table(
        "最近交易记录",
        keep_columns(
            recent_trade_df,
            [
                "闭环状态",
                "股票名称",
                "股票代码",
                "交易类型",
                "方向",
                "买入价格",
                "卖出价格",
                "数量",
                "到手利润",
                "收益率",
                "买入手续费",
                "卖出手续费",
                "卖出印花税",
                "手续费合计",
                "交易日期",
                "策略来源",
                "是否按计划执行",
                "备注",
            ],
        ),
    )


def render_trade_record_editor(current_trade_df: pd.DataFrame) -> None:
    name_code_map = build_stock_name_code_map(
        final_df,
        final_decision_df,
        sell_signal_df,
        lunch_df,
        next_df,
        model_prediction_df,
        profit_probability_df,
        current_trade_df,
    )
    editable_df = current_trade_df.copy()
    editable_df["记录ID"] = editable_df["记录ID"].astype(str)
    editable_df = editable_df[editable_df["记录ID"].str.strip().ne("")]

    if editable_df.empty:
        return

    editable_df = editable_df.sort_values("记录时间", ascending=False).reset_index(drop=True)

    with st.expander("修改已保存记录", expanded=False):
        filter_col1, filter_col2, filter_col3 = st.columns([1, 1, 1])

        date_options = ["全部"] + sorted(
            [str(value) for value in editable_df["交易日期"].dropna().unique() if str(value).strip()],
            reverse=True,
        )
        type_options = ["全部", "日内T", "隔日T"]

        with filter_col1:
            selected_date_filter = st.selectbox("按日期筛选", date_options, key="edit_filter_date")

        with filter_col2:
            stock_name_filter = st.text_input("按股票名称筛选", placeholder="例如 华友", key="edit_filter_stock_name")

        with filter_col3:
            selected_type_filter = st.selectbox("按交易类型筛选", type_options, key="edit_filter_trade_type")

        filtered_df = editable_df.copy()
        if selected_date_filter != "全部":
            filtered_df = filtered_df[filtered_df["交易日期"].astype(str).eq(selected_date_filter)]

        if stock_name_filter.strip():
            filtered_df = filtered_df[
                filtered_df["股票名称"].astype(str).str.contains(stock_name_filter.strip(), case=False, na=False)
            ]

        if selected_type_filter != "全部":
            filtered_df = filtered_df[filtered_df["交易类型"].astype(str).eq(selected_type_filter)]

        if filtered_df.empty:
            st.info("没有匹配的交易记录，放宽筛选条件再试。")
            return

        record_options = filtered_df["记录ID"].tolist()
        label_map = {
            row["记录ID"]: (
                f"{row.get('交易日期', '')} | {row.get('股票名称', '')} | "
                f"{row.get('买入价格', '')}->{row.get('卖出价格', '')} | "
                f"{row.get('数量', '')}股 | {row.get('闭环状态', '')}"
            )
            for _, row in filtered_df.iterrows()
        }

        selected_id = st.selectbox(
            "选择要修改的记录",
            record_options,
            format_func=lambda record_id: label_map.get(record_id, record_id),
        )
        edit_key_prefix = f"trade_record_edit_{selected_id}"
        selected_row = filtered_df[filtered_df["记录ID"].eq(selected_id)].iloc[0]

        trade_date_value = pd.to_datetime(selected_row.get("交易日期", ""), errors="coerce")
        if pd.isna(trade_date_value):
            trade_date_value = pd.Timestamp.today()

        recorded_at_value = pd.to_datetime(selected_row.get("记录时间", ""), errors="coerce")
        recorded_at = recorded_at_value.to_pydatetime() if not pd.isna(recorded_at_value) else None

        trade_type_options = ["隔日T", "日内T"]
        direction_options = ["买入并卖出", "买入", "卖出"]
        strategy_options = ["系统候选", "手动观察", "盘中机会", "复盘补录"]
        followed_options = ["是", "否", "部分执行", "未记录"]

        with st.form("trade_record_edit_form"):
            row1_col1, row1_col2, row1_col3, row1_col4 = st.columns([1, 1, 1, 1])

            with row1_col1:
                edit_trade_date = st.date_input(
                    "交易日期",
                    value=trade_date_value.date(),
                    key=f"{edit_key_prefix}_trade_date",
                )

            with row1_col2:
                current_trade_type = str(selected_row.get("交易类型", "隔日T"))
                edit_trade_type = st.selectbox(
                    "交易类型",
                    trade_type_options,
                    index=trade_type_options.index(current_trade_type) if current_trade_type in trade_type_options else 0,
                    key=f"{edit_key_prefix}_trade_type",
                )

            with row1_col3:
                edit_stock_name = st.text_input(
                    "股票名称",
                    value=str(selected_row.get("股票名称", "")),
                    key=f"{edit_key_prefix}_stock_name",
                )

            with row1_col4:
                stored_code = normalize_optional_code(selected_row.get("股票代码", ""))
                edit_stock_code = st.text_input(
                    "股票代码（可选）",
                    value=stored_code,
                    key=f"{edit_key_prefix}_stock_code",
                )

            row2_col1, row2_col2, row2_col3, row2_col4 = st.columns([1, 1, 1, 1])

            with row2_col1:
                current_direction = str(selected_row.get("方向", "买入并卖出"))
                edit_direction = st.selectbox(
                    "方向",
                    direction_options,
                    index=direction_options.index(current_direction) if current_direction in direction_options else 0,
                    key=f"{edit_key_prefix}_direction",
                )

            with row2_col2:
                edit_buy_price_text = st.text_input(
                    "买入价格/成本价",
                    value=str(selected_row.get("买入价格", "")).strip(),
                    key=f"{edit_key_prefix}_buy_price",
                )

            with row2_col3:
                edit_sell_price_text = st.text_input(
                    "卖出价格",
                    value=str(selected_row.get("卖出价格", "")).strip(),
                    key=f"{edit_key_prefix}_sell_price",
                )

            with row2_col4:
                edit_quantity = st.number_input(
                    "数量",
                    min_value=0,
                    value=int(safe_float(selected_row.get("数量", 0))),
                    step=100,
                    key=f"{edit_key_prefix}_quantity",
                )

            row3_col1, row3_col2 = st.columns([1, 1])

            with row3_col1:
                current_strategy = str(selected_row.get("策略来源", "手动观察"))
                edit_strategy_source = st.selectbox(
                    "策略来源",
                    strategy_options,
                    index=strategy_options.index(current_strategy) if current_strategy in strategy_options else 1,
                    key=f"{edit_key_prefix}_strategy_source",
                )

            with row3_col2:
                current_followed = str(selected_row.get("是否按计划执行", "未记录"))
                edit_followed_plan = st.selectbox(
                    "是否按计划执行",
                    followed_options,
                    index=followed_options.index(current_followed) if current_followed in followed_options else 3,
                    key=f"{edit_key_prefix}_followed_plan",
                )

            edit_note = st.text_area(
                "备注",
                value=str(selected_row.get("备注", "")),
                height=90,
                key=f"{edit_key_prefix}_note",
            )
            update_submitted = st.form_submit_button("保存修改", width="stretch")

            if update_submitted:
                try:
                    edit_buy_price = parse_price_input(edit_buy_price_text)
                    edit_sell_price = parse_price_input(edit_sell_price_text)
                    resolved_code = resolve_trade_stock_code(edit_stock_name, edit_stock_code, name_code_map)
                    record = build_trade_record(
                        record_id=selected_id,
                        stock_code=resolved_code,
                        stock_name=edit_stock_name,
                        trade_date=edit_trade_date,
                        trade_type=edit_trade_type,
                        direction=edit_direction,
                        buy_price=edit_buy_price,
                        sell_price=edit_sell_price,
                        quantity=edit_quantity,
                        strategy_source=edit_strategy_source,
                        followed_plan=edit_followed_plan,
                        note=edit_note,
                        recorded_at=recorded_at,
                    )
                    update_trade_record(record, TRADE_RECORD_FILE)
                    st.success("交易记录已修改，费用和利润已重新计算")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"修改失败：{e}")


def render_market_panel() -> None:
    st.subheader("今日市场")

    if market_md:
        with st.expander("展开市场环境原始报告", expanded=False):
            st.markdown(market_md)
    else:
        st.warning("暂无市场环境报告，请点击【生成明日计划】或【单独刷新市场环境】。")

    sector_core_df = keep_columns(
        sector_flow_df,
        [
            "资金排名",
            "板块名称",
            "板块涨跌幅",
            "主力净流入",
            "主力净流入占比",
            "板块资金标签",
            "隔夜建议",
        ],
    )
    show_table("板块资金方向", sector_core_df.head(15))


def render_trade_plan_panel() -> None:
    st.subheader("明日计划")
    st.caption("这里只看明天怎么做。固定持仓看处理动作，候选池看是否值得关注。")

    plan_col1, plan_col2 = st.columns(2)
    with plan_col1:
        if st.button("生成明日计划", key="generate_daily_plan", width="stretch"):
            run_main_pipeline_and_refresh()
    with plan_col2:
        if st.button("刷新最终决策", key="refresh_final_decision", width="stretch"):
            run_main_command_and_refresh("decision-fusion")

    if not final_decision_df.empty:
        final_show_df = final_decision_df.copy()
        final_show_df["股票代码"] = final_show_df["stock_code"].astype(str).str.zfill(6)
        final_show_df = final_show_df.rename(columns={
            "stock_name": "股票名称",
            "is_fixed_holding": "固定持仓",
            "rule_grade": "规则等级",
            "fusion_score": "融合评分",
            "next_day_up_probability": "次日上涨概率",
            "hit_1pct_probability": "达到1%概率",
            "hit_2pct_probability": "达到2%概率",
            "stop_2pct_probability": "止损概率",
            "final_action": "最终操作",
            "decision_reason": "操作解释",
            "risk_reward_ratio": "风险收益比",
        })
        final_show_df["固定持仓"] = final_show_df["固定持仓"].map({True: "是", False: "否", "True": "是", "False": "否"}).fillna(final_show_df["固定持仓"])
        final_show_df = add_short_reason(add_model_signal_status(final_show_df))
        fixed_decision_df, candidate_decision_df = split_fixed_candidate(final_show_df)

        show_table(
            "固定持仓处理",
            keep_columns(
                fixed_decision_df,
                [
                    "最终操作",
                    "股票名称",
                    "股票代码",
                    "操作短句",
                    "规则等级",
                    "模型状态",
                ],
            ),
        )
        show_table(
            "明日候选池",
            keep_columns(
                candidate_decision_df,
                [
                    "最终操作",
                    "股票名称",
                    "股票代码",
                    "操作短句",
                    "规则等级",
                    "融合评分",
                    "模型状态",
                ],
            ).head(12),
        )
        with st.expander("展开模型依据明细", expanded=False):
            show_table(
                "模型依据明细",
                keep_columns(
                    final_show_df,
                    [
                        "股票名称",
                        "股票代码",
                        "次日上涨概率",
                        "达到1%概率",
                        "达到2%概率",
                        "止损概率",
                        "风险收益比",
                        "模型状态",
                    ],
                ).head(30),
            )
    else:
        st.info("暂无最终决策，请先运行模型预测后点击【刷新最终决策】。")

    if final_decision_md:
        with st.expander("展开最终决策报告", expanded=False):
            st.markdown(final_decision_md)

    if daily_plan_md:
        with st.expander("展开交易计划原始报告", expanded=False):
            st.markdown(daily_plan_md)
    else:
        st.warning("暂无交易计划，请点击【生成明日计划】。")

    st.divider()
    sorted_final_df = sort_final_watchlist(final_df)

    if not sorted_final_df.empty and "隔夜建议等级" in sorted_final_df.columns:
        trade_df = sorted_final_df[sorted_final_df["隔夜建议等级"].isin(["A", "B"])].copy()
    else:
        trade_df = sorted_final_df.copy()

    trade_df = keep_columns(
        add_final_decision(
            add_profit_probability(add_model_probability(trade_df, model_prediction_df), profit_probability_df),
            final_decision_df,
        ),
        [
            "最终操作",
            "股票名称",
            "股票代码",
            "操作解释",
            "隔夜建议等级",
            "融合评分",
            "是否已买入",
            "固定持仓",
            "所属板块",
            "风险等级",
            "模型状态",
            "分时结构标签",
            "尾盘抢筹标签",
            "板块过滤原因",
            "隔夜建议说明",
        ],
    )
    trade_df = add_bought_flag(trade_df, bought_codes)
    trade_df = add_short_reason(add_model_signal_status(trade_df))
    trade_df = keep_columns(
        trade_df,
        [
            "最终操作",
            "股票名称",
            "股票代码",
            "操作短句",
            "隔夜建议等级",
            "融合评分",
            "是否已买入",
            "固定持仓",
            "模型状态",
            "所属板块",
            "风险等级",
        ],
    )
    show_table("A/B 核心候选", trade_df)


def render_sell_signal_panel() -> None:
    st.subheader("候选卖点信号")
    st.caption("这里更新明日计划 A/B 候选股票的盘中卖点，固定持仓卖点在【准备工作 > 固定持仓】下方。")

    if st.button("更新卖点信号", key="refresh_sell_signal_page", width="stretch"):
        run_single_script_and_refresh("sell_signal_engine.py")

    if sell_signal_md:
        with st.expander("展开卖点信号原始报告", expanded=False):
            st.markdown(sell_signal_md)
    else:
        st.warning("暂无候选卖点信号，请先生成明日计划，再点击【更新卖点信号】。")

    sell_core_df = keep_columns(
        add_profit_probability(add_model_probability(sell_signal_df, model_prediction_df), profit_probability_df),
        [
            "卖出信号",
            "股票名称",
            "股票代码",
            "卖出理由",
            "参考价",
            "分时均价",
            "盘中最高",
            "市场环境",
            "固定持仓",
        ],
    )
    sell_core_df = add_bought_flag(sell_core_df, bought_codes)
    show_table("候选卖点核心信号", sell_core_df)


def render_lunch_panel() -> None:
    st.subheader("午盘验证")

    if lunch_md:
        with st.expander("展开午盘验证原始报告", expanded=False):
            st.markdown(lunch_md)
    else:
        st.warning("暂无午盘验证报告，请在 11:20 后点击【午盘验证】。")

    lunch_core_df = keep_columns(
        add_profit_probability(add_model_probability(lunch_df, model_prediction_df), profit_probability_df),
        [
            "下午操作建议",
            "股票名称",
            "股票代码",
            "当前价",
            "当前涨幅",
            "数据时效",
            "实时行情时间",
            "分钟最新时间",
            "午盘价",
            "上午结构标签",
            "午盘涨幅",
            "是否触发-2%止损",
            "隔夜建议等级",
            "固定持仓",
        ],
    )
    lunch_core_df = add_bought_flag(lunch_core_df, bought_codes)
    show_table("午盘核心结果", lunch_core_df)


def render_next_day_panel() -> None:
    st.subheader("系统次日验证")
    st.caption("这里只看昨天计划准不准，用于复盘和训练数据，不直接指导今天买卖。")

    if next_md:
        with st.expander("展开次日验证原始报告", expanded=False):
            st.markdown(next_md)
    else:
        st.warning("暂无次日验证报告，请次日收盘后点击【次日复盘】。")

    next_core_df = keep_columns(
        add_profit_probability(add_model_probability(next_df, model_prediction_df), profit_probability_df),
        [
            "固定持仓",
            "股票名称",
            "股票代码",
            "是否触达低吸区间",
            "是否达到1%",
            "是否触发-2%止损",
            "执行验证结果",
            "分时确认状态",
            "分时首事件",
            "分时首事件时间",
            "时序判断",
            "是否验证成功",
            "次日收盘涨幅",
            "隔夜建议等级",
            "分时结构标签",
            "尾盘抢筹标签",
            "买入参考价",
            "计划低吸下限",
            "计划低吸上限",
        ],
    )
    next_core_df = add_bought_flag(next_core_df, bought_codes)
    next_core_df = add_verification_summary(next_core_df)

    if next_core_df.empty:
        st.info("暂无系统次日验证结果。")
        return

    metric_col1, metric_col2, metric_col3, metric_col4, metric_col5 = st.columns(5)
    with metric_col1:
        st.metric("计划有效", int(next_core_df["系统验证结果"].eq("计划有效").sum()))
    with metric_col2:
        st.metric("待优化", int(next_core_df["系统验证结果"].eq("计划待优化").sum()))
    with metric_col3:
        st.metric("需分时确认", int(next_core_df["系统验证结果"].eq("需分时确认").sum()))
    with metric_col4:
        st.metric("未给买点", int(next_core_df["系统验证结果"].eq("未给买点").sum()))
    with metric_col5:
        st.metric("固定持仓", int(next_core_df["固定持仓"].astype(str).isin(["是", "True", "true", "1"]).sum()))

    review_summary_df = build_next_day_review_summary(next_core_df)
    show_table("今日复盘摘要", review_summary_df)

    optimization_df = (
        next_core_df[next_core_df["系统验证结果"].isin(["计划待优化", "需分时确认"])]["优化方向"]
        .value_counts()
        .rename_axis("待优化原因")
        .reset_index(name="数量")
    )
    if not optimization_df.empty:
        show_table("待优化原因", optimization_df)

    fixed_review_df, candidate_review_df = split_fixed_candidate(next_core_df)
    core_columns = [
        "系统验证结果",
        "系统闭环结果",
        "系统模拟利润",
        "系统模拟买入价",
        "系统模拟卖出价",
        "系统模拟股数",
        "股票名称",
        "股票代码",
        "复盘结论",
        "优化方向",
        "分时确认状态",
        "分时首事件",
        "是否触达低吸区间",
        "是否达到1%",
        "是否触发-2%止损",
    ]

    show_table("固定持仓验证", keep_columns(fixed_review_df, core_columns))
    show_table("候选池验证", keep_columns(candidate_review_df, core_columns))

    with st.expander("展开验证明细", expanded=False):
        show_table(
            "验证明细",
            keep_columns(
                next_core_df,
                core_columns
                + [
                    "隔夜建议等级",
                    "分时结构标签",
                    "尾盘抢筹标签",
                    "买入参考价",
                    "计划低吸下限",
                    "计划低吸上限",
                    "次日收盘涨幅",
                    "执行验证结果",
                    "分时首事件时间",
                    "时序判断",
                ],
            ),
        )


def render_factor_panel() -> None:
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


def load_dataset_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dataset_samples_df = load_csv(DATASET_SAMPLES_FILE)
    feature_snapshot_df = load_csv(FEATURE_SNAPSHOT_FILE)
    label_snapshot_df = load_csv(LABEL_SNAPSHOT_FILE)
    prediction_log_df = load_csv(PREDICTION_LOG_FILE)
    model_predictions_df = load_csv(MODEL_PREDICTION_FILE)

    return (
        dataset_samples_df,
        feature_snapshot_df,
        label_snapshot_df,
        prediction_log_df,
        model_predictions_df,
    )


def render_dataset_metrics(
    dataset_samples_df: pd.DataFrame,
    feature_snapshot_df: pd.DataFrame,
    label_snapshot_df: pd.DataFrame,
    prediction_log_df: pd.DataFrame,
    model_predictions_df: pd.DataFrame,
) -> None:
    metric_col1, metric_col2, metric_col3, metric_col4, metric_col5 = st.columns(5)

    with metric_col1:
        st.metric("样本", len(dataset_samples_df) if not dataset_samples_df.empty else 0)

    with metric_col2:
        st.metric("特征快照", len(feature_snapshot_df) if not feature_snapshot_df.empty else 0)

    with metric_col3:
        st.metric("标签", len(label_snapshot_df) if not label_snapshot_df.empty else 0)

    with metric_col4:
        st.metric("预测日志", len(prediction_log_df) if not prediction_log_df.empty else 0)

    with metric_col5:
        st.metric("模型预测", len(model_predictions_df) if not model_predictions_df.empty else 0)


def render_model_training_panel() -> None:
    st.subheader("模型训练")
    st.caption("先保存训练数据，再训练方向模型和收益目标模型。这里主要看样本量、标签覆盖和评估报告。")
    st.markdown(
        "操作顺序：保存训练数据 → 训练方向模型 → 训练收益目标概率 → 生成校准与解释 → 生成预测回顾。"
    )

    train_col1, train_col2, train_col3, train_col4, train_col5 = st.columns(5)

    with train_col1:
        if st.button("训练方向模型", width="stretch"):
            run_main_command_and_refresh("model-train")

    with train_col2:
        if st.button("训练收益目标概率模型", width="stretch"):
            run_main_command_and_refresh("probability-train")

    with train_col3:
        if st.button("生成校准与解释", width="stretch"):
            run_main_command_and_refresh("calibrate-explain")

    with train_col4:
        if st.button("生成预测回顾", width="stretch"):
            run_main_command_and_refresh("prediction-review")

    with train_col5:
        if st.button("生成今日报告", width="stretch"):
            run_main_command_and_refresh("daily-report")

    (
        dataset_samples_df,
        feature_snapshot_df,
        label_snapshot_df,
        prediction_log_df,
        model_predictions_df,
    ) = load_dataset_frames()

    render_dataset_metrics(
        dataset_samples_df,
        feature_snapshot_df,
        label_snapshot_df,
        prediction_log_df,
        model_predictions_df,
    )
    show_table(
        "模型排序保护",
        build_model_sorting_guard(model_predictions_df, profit_probability_df),
    )

    if dataset_quality_md:
        with st.expander("展开数据集质量报告", expanded=False):
            st.markdown(dataset_quality_md)
    else:
        st.warning("暂无数据集质量报告，请点击【保存训练数据】。")

    if model_evaluation_md:
        with st.expander("展开方向模型评估报告", expanded=False):
            st.markdown(model_evaluation_md)
    else:
        st.info("暂无方向模型评估报告，请先点击【训练方向模型】。")

    if profit_probability_evaluation_md:
        with st.expander("展开收益目标概率评估报告", expanded=False):
            st.markdown(profit_probability_evaluation_md)
    else:
        st.info("暂无收益目标概率评估报告，请先点击【训练收益目标概率模型】。")

    if calibration_report_md:
        with st.expander("展开概率校准与解释报告", expanded=False):
            st.markdown(calibration_report_md)
    else:
        st.info("暂无概率校准与解释报告，请先点击【生成校准与解释】。")

    if prediction_review_report_md:
        with st.expander("展开预测回顾与模型评分报告", expanded=False):
            st.markdown(prediction_review_report_md)
    else:
        st.info("暂无预测回顾报告，请先点击【生成预测回顾】。")

    if daily_model_report_md:
        with st.expander("展开今日模型与预测复盘报告", expanded=True):
            st.markdown(daily_model_report_md)
    else:
        st.info("暂无今日模型报告，请先点击【生成今日报告】。")

    show_table("样本主表预览", dataset_samples_df.head(20))


def render_model_prediction_panel() -> None:
    st.subheader("模型预测")
    st.caption("生成候选股票的上涨概率、收益目标概率和止损概率。这里只做辅助排序，最终操作仍看明日计划和单票决策。")

    predict_col1, predict_col2 = st.columns(2)

    with predict_col1:
        if st.button("生成方向预测", width="stretch"):
            run_main_command_and_refresh("model-predict")

    with predict_col2:
        if st.button("生成收益目标概率", width="stretch"):
            run_main_command_and_refresh("probability-predict")

    (
        dataset_samples_df,
        feature_snapshot_df,
        label_snapshot_df,
        prediction_log_df,
        model_predictions_df,
    ) = load_dataset_frames()

    render_dataset_metrics(
        dataset_samples_df,
        feature_snapshot_df,
        label_snapshot_df,
        prediction_log_df,
        model_predictions_df,
    )
    sorting_guard_df = build_model_sorting_guard(model_predictions_df, profit_probability_df)
    show_table("模型排序保护", sorting_guard_df)

    model_show_df = model_predictions_df.rename(columns={
        "stock_code": "股票代码",
        "stock_name": "股票名称",
        "next_day_up_probability": "次日上涨概率",
        "direction_confidence": "方向置信度",
        "predicted_direction": "模型方向",
        "model_version": "模型版本",
        "predict_date": "预测日期",
        "market_regime": "市场环境",
        "sector_name": "所属板块",
    })

    if not model_show_df.empty and "次日上涨概率" in model_show_df.columns:
        probability_count = pd.to_numeric(
            model_show_df["次日上涨概率"],
            errors="coerce",
        ).dropna().round(6).nunique()
        confidence_count = 0
        if "方向置信度" in model_show_df.columns:
            confidence_count = pd.to_numeric(
                model_show_df["方向置信度"],
                errors="coerce",
            ).dropna().round(6).nunique()

        if probability_count <= 1 or confidence_count <= 1:
            st.warning(
                "当前方向概率或方向置信度基本一致，说明方向模型暂时没有学出个股差异。"
                "常见原因是样本太少、标签分布单一，或模型回退到整体基准概率。"
                "这种情况下先把它当作风险提示，最终仍以规则评分、卖点信号和单票决策为准。"
            )
            model_show_df["模型状态"] = "仅观察"
        else:
            model_show_df["模型状态"] = "有区分"

    show_table(
        "次日上涨概率排序",
        keep_columns(
            model_show_df,
            [
                "预测日期",
                "股票名称",
                "股票代码",
                "模型状态",
                "次日上涨概率",
                "方向置信度",
                "模型方向",
                "市场环境",
                "所属板块",
            ],
        ),
    )

    profit_show_df = profit_probability_df.rename(columns={
        "stock_code": "股票代码",
        "stock_name": "股票名称",
        "hit_1pct_probability": "达到1%概率",
        "hit_2pct_probability": "达到2%概率",
        "stop_2pct_probability": "止损概率",
        "risk_adjusted_1pct": "1%风险差",
        "risk_adjusted_2pct": "2%风险差",
        "probability_risk_reward": "概率收益风险比",
        "final_probability_signal": "概率信号",
        "model_version": "模型版本",
        "predict_date": "预测日期",
    })
    if not profit_show_df.empty:
        profit_show_df["模型状态"] = "有区分" if model_has_variation(
            profit_show_df,
            ["达到1%概率", "达到2%概率", "止损概率"],
        ) else "仅观察"
        if profit_show_df["模型状态"].eq("仅观察").all():
            st.warning("收益目标概率当前也没有形成有效区分，不适合作为候选排序依据。")

    show_table(
        "收益目标概率排序",
        keep_columns(
            profit_show_df,
            [
                "预测日期",
                "股票名称",
                "股票代码",
                "模型状态",
                "达到1%概率",
                "达到2%概率",
                "止损概率",
                "1%风险差",
                "2%风险差",
                "概率收益风险比",
                "概率信号",
            ],
        ),
    )

    calibrated_show_df = calibrated_probability_df.rename(columns={
        "stock_code": "股票代码",
        "stock_name": "股票名称",
        "calibrated_hit_1pct_probability": "校准后1%概率",
        "calibrated_hit_2pct_probability": "校准后2%概率",
        "calibrated_stop_2pct_probability": "校准后止损概率",
        "calibrated_risk_adjusted_1pct": "校准后1%风险差",
        "calibrated_risk_adjusted_2pct": "校准后2%风险差",
        "final_probability_signal": "概率信号",
        "calibration_model_version": "校准版本",
        "predict_date": "预测日期",
    })
    show_table(
        "校准后概率",
        keep_columns(
            calibrated_show_df,
            [
                "预测日期",
                "股票代码",
                "股票名称",
                "校准后1%概率",
                "校准后2%概率",
                "校准后止损概率",
                "校准后1%风险差",
                "校准后2%风险差",
                "概率信号",
            ],
        ),
    )

    explanation_show_df = model_explanation_df.rename(columns={
        "stock_code": "股票代码",
        "stock_name": "股票名称",
        "predict_date": "预测日期",
        "top_positive_factors": "偏多因素",
        "top_negative_factors": "偏空因素",
        "explanation_method": "解释方法",
    })
    show_table(
        "单票多空因素",
        keep_columns(
            explanation_show_df,
            [
                "预测日期",
                "股票代码",
                "股票名称",
                "偏多因素",
                "偏空因素",
                "解释方法",
            ],
        ),
    )

    scorecard_show_df = model_scorecard_df.rename(columns={
        "model_version": "模型版本",
        "metric_name": "指标",
        "segment_type": "分组类型",
        "segment_value": "分组",
        "sample_count": "样本数",
        "score": "分数",
        "created_at": "生成时间",
    })
    show_table(
        "模型评分卡",
        keep_columns(
            scorecard_show_df,
            [
                "指标",
                "分组类型",
                "分组",
                "样本数",
                "分数",
            ],
        ),
    )


def run_single_stock_and_refresh(stock_code: str) -> None:
    with st.status(f"正在生成 {stock_code} 单票决策 ...", expanded=True) as status:
        success, stdout, stderr = run_command(["main.py", "single-stock", "--stock-code", stock_code])
        show_script_result("single-stock", success, stdout, stderr)

        if success:
            migrate_local_files_to_sqlite()
            status.update(
                label="单票决策生成完成，正在刷新页面...",
                state="complete",
            )
            time.sleep(1)
            st.rerun()
        else:
            status.update(
                label="单票决策生成失败",
                state="error",
            )


def render_single_stock_panel() -> None:
    st.subheader("单票决策")
    st.caption("快速查看一只股票的最终操作、模型概率、买卖点和验证信息；不会覆盖全市场预测结果。")

    holding_options = [f"{code} {name}" for code, name in fixed_holding_name_map().items()]
    selected = st.selectbox("固定持仓快捷选择", holding_options, index=0)
    manual_code = st.text_input("股票代码", value=selected.split()[0] if selected else "002466")

    if st.button("生成单票决策", key="generate_single_stock_decision", width="stretch"):
        run_single_stock_and_refresh(manual_code)

    if single_stock_decision_df.empty:
        st.info("暂无单票决策，请输入股票代码后生成。")
    else:
        show_df = single_stock_decision_df.rename(columns={
            "stock_code": "股票代码",
            "stock_name": "股票名称",
            "is_fixed_holding": "固定持仓",
            "final_action": "最终操作",
            "fusion_score": "融合评分",
            "decision_reason": "操作解释",
            "rule_grade": "规则等级",
            "rule_score": "规则评分",
            "next_day_up_probability": "次日上涨概率",
            "hit_1pct_probability": "达到1%概率",
            "hit_2pct_probability": "达到2%概率",
            "stop_2pct_probability": "止损概率",
            "buy_status": "买点状态",
            "buy_range": "买点区间",
            "sell_signal": "卖点信号",
            "sell_reason": "卖点理由",
        })
        show_df = add_short_reason(add_model_signal_status(show_df))
        show_table(
            "单票核心结论",
            keep_columns(
                show_df,
                [
                    "最终操作",
                    "股票名称",
                    "股票代码",
                    "操作短句",
                    "买点状态",
                    "买点区间",
                    "卖点信号",
                    "卖点理由",
                    "规则等级",
                    "模型状态",
                ],
            ),
        )
        with st.expander("展开单票模型明细", expanded=False):
            show_table(
                "单票模型明细",
                keep_columns(
                    show_df,
                    [
                        "股票名称",
                        "股票代码",
                        "融合评分",
                        "次日上涨概率",
                        "达到1%概率",
                        "达到2%概率",
                        "止损概率",
                    ],
                ),
            )

    if single_stock_decision_md:
        with st.expander("展开单票决策报告", expanded=False):
            st.markdown(single_stock_decision_md)


def render_opening_levels_panel() -> None:
    st.subheader("支撑压力")
    st.caption("固定持仓的支撑位、压力位、买进区间、卖出区间；只展示可执行信息，计算过程折叠。")

    col1, col2, col3 = st.columns([1.1, 2.2, 1.1], vertical_alignment="bottom")
    with col1:
        if st.button("刷新固定持仓开盘区间", key="refresh_opening_levels", width="stretch"):
            run_main_command_and_refresh("opening-levels")
    with col2:
        stock_text = st.text_input(
            "单票计算",
            placeholder="输入股票名称或代码，例如 融捷股份 / 002192",
            label_visibility="collapsed",
        )
    with col3:
        if st.button("计算单票开盘区间", key="refresh_single_opening_levels", width="stretch"):
            run_main_command_with_stock_and_refresh("opening-levels", stock_text)

    if opening_levels_df.empty:
        st.info("暂无开盘区间，请点击刷新固定持仓开盘区间。")
        return

    show_table(
        "支撑压力数据",
        keep_columns(
            opening_levels_df,
            [
                "操作",
                "股票名称",
                "股票代码",
                "支撑位",
                "压力位",
                "买进区间",
                "卖出区间",
                "集合竞价价",
                "当前价",
                "AI辅助",
                "历史T次数",
                "历史T胜率",
                "实时行情时间",
                "状态",
            ],
        ),
        height=320,
    )

    if opening_levels_md:
        with st.expander("展开计算报告", expanded=False):
            st.markdown(opening_levels_md)


def render_t_mode_panel(page_title: str = "做T判断") -> None:
    st.subheader(page_title)
    st.caption("固定持仓先看这里：先判断今天做不做T，再看支撑压力和买卖区间。")
    st.markdown(
        """
        <style>
        div[data-testid="stDataFrame"] div[role="gridcell"],
        div[data-testid="stDataFrame"] div[role="columnheader"] {
            font-size: 18px !important;
            line-height: 1.45 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    refresh_col1, refresh_col2 = st.columns(2)
    with refresh_col1:
        if st.button("刷新做T判断", key="refresh_t_mode_decision", width="stretch"):
            run_main_command_and_refresh("t-mode")
    with refresh_col2:
        if st.button("刷新支撑压力", key="refresh_t_mode_opening_levels", width="stretch"):
            run_main_command_and_refresh("opening-levels")

    if t_mode_decision_df.empty:
        st.info("暂无做T模式，请先刷新开盘T区间和持仓买卖点。")
    else:
        show_table(
            "做T模式列表",
            keep_columns(
                t_mode_decision_df,
                [
                    "推荐模式",
                    "股票名称",
                    "股票代码",
                    "推荐强度",
                    "模式短句",
                    "买入区间",
                    "卖出区间",
                    "风险线",
                    "触发条件",
                    "一句话理由",
                    "当前价",
                    "金融预警",
                    "历史T胜率",
                    "数据状态",
                ],
            ),
            height=300,
        )

    if not opening_levels_df.empty:
        show_table(
            "支撑压力参考",
            keep_columns(
                opening_levels_df,
                [
                    "操作",
                    "股票名称",
                    "股票代码",
                    "支撑位",
                    "压力位",
                    "买进区间",
                    "卖出区间",
                    "当前价",
                    "AI辅助",
                    "实时行情时间",
                ],
            ),
            height=260,
        )

    if t_mode_decision_md:
        with st.expander("展开做T模式报告", expanded=False):
            st.markdown(t_mode_decision_md)


def render_metal_macro_panel() -> None:
    st.subheader("金属宏观")
    st.caption("这里看黄金、白银、美元和利率压力，只做资源股和贵金属方向的辅助判断。")

    if st.button("刷新金属宏观", key="refresh_metal_macro", width="stretch"):
        run_main_command_and_refresh("metal-macro")

    show_table(
        "金属与利率联动",
        keep_columns(
            metal_macro_df,
            [
                "金属模块状态",
                "黄金策略",
                "利率压力",
                "指标",
                "数值",
                "解释",
                "一句话建议",
                "数据状态",
                "生成时间",
            ],
        ),
    )

    if metal_macro_md:
        with st.expander("展开金属宏观报告", expanded=False):
            st.markdown(metal_macro_md)


def render_preopen_prediction_panel() -> None:
    st.subheader("开盘前预测")
    st.caption("9:25 后看开盘评分和定性，判断今天先防守、只低吸，还是可进攻。")

    if st.button("刷新开盘前预测", key="refresh_preopen_prediction", width="stretch"):
        run_main_command_and_refresh("preopen-predict")

    if preopen_prediction_df.empty:
        st.info("暂无开盘前预测，请先刷新市场、开盘T区间和金属宏观。")
        return

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    row = preopen_prediction_df.iloc[-1]
    with metric_col1:
        st.metric("开盘评分", row.get("开盘评分", "-"))
    with metric_col2:
        st.metric("开盘定性", row.get("开盘定性", "-"))
    with metric_col3:
        st.metric("今日策略", row.get("今日策略", "-"))
    with metric_col4:
        st.metric("金融预警", row.get("金融拉盘预警", "-"))

    render_action_hint(
        "怎么用",
        "先看今日策略和金融预警；弱势就降仓位，只低吸不追高；强势再结合固定持仓和支撑压力执行。",
    )
    if any(col in preopen_prediction_df.columns for col in ["DS操作建议", "DS重点模块", "DS防守条件"]):
        ds_row = preopen_prediction_df.iloc[-1]
        render_action_hint("DS操作建议", str(ds_row.get("DS操作建议", "暂无")))
        ds_col1, ds_col2 = st.columns(2)
        with ds_col1:
            render_action_hint("重点模块", str(ds_row.get("DS重点模块", "暂无")))
        with ds_col2:
            render_action_hint("防守条件", str(ds_row.get("DS防守条件", "暂无")))

    show_table(
        "开盘预测来源",
        keep_columns(
            preopen_prediction_df,
            [
                "开盘评分",
                "开盘定性",
                "金融拉盘预警",
                "固定持仓影响",
                "今日策略",
                "DS补充观察",
                "DS状态",
                "评分来源",
                "生成时间",
            ],
        ),
    )

    if preopen_prediction_md:
        with st.expander("展开开盘前预测报告", expanded=False):
            st.markdown(preopen_prediction_md)


def render_sector_rotation_panel() -> None:
    st.subheader("资金流向")
    st.caption("只看最近板块资金强弱和固定持仓有没有资金支持；详细报告默认折叠。")

    if st.button("刷新板块轮动", key="refresh_sector_rotation", width="stretch"):
        run_main_command_and_refresh("sector-rotation")

    display_df = add_billion_columns(sector_rotation_df)
    if not display_df.empty:
        inflow_df = display_df[pd.to_numeric(display_df.get("主力净流入", 0), errors="coerce").fillna(0) > 0].copy()
        outflow_df = display_df[pd.to_numeric(display_df.get("主力净流入", 0), errors="coerce").fillna(0) < 0].copy()
        metric_col1, metric_col2, metric_col3 = st.columns(3)
        with metric_col1:
            st.metric("流入板块", len(inflow_df))
        with metric_col2:
            st.metric("流出板块", len(outflow_df))
        with metric_col3:
            top_sector = str(display_df.iloc[0].get("所属板块", "-"))
            st.metric("资金第一", top_sector)

        ds_cols = ["DS盘面判断", "DS操作指引", "DS风险提示", "DS固定持仓提示"]
        if any(col in display_df.columns for col in ds_cols):
            ds_row = display_df.iloc[0]
            render_action_hint("DS盘面判断", str(ds_row.get("DS盘面判断", "暂无")))
            hint_col1, hint_col2, hint_col3 = st.columns(3)
            with hint_col1:
                render_action_hint("操作指引", str(ds_row.get("DS操作指引", "暂无")))
            with hint_col2:
                render_action_hint("风险提示", str(ds_row.get("DS风险提示", "暂无")))
            with hint_col3:
                render_action_hint("持仓提示", str(ds_row.get("DS固定持仓提示", "暂无")))

        render_action_hint(
            "怎么用",
            "优先看资金前三名和固定持仓所属板块；若固定持仓板块没有资金支持，盘中只按纪律低吸或减仓。",
        )

    core_cols = [
        "板块轮动状态",
        "板块操作建议",
        "所属板块",
        "板块资金标签",
        "资金排名",
        "板块涨跌幅",
        "主力净流入亿元",
        "主力净流入占比",
        "板块广度",
        "板块近5日排名",
        "DS状态",
        "生成时间",
    ]
    ranked_df = keep_columns(display_df, core_cols)
    if not ranked_df.empty:
        show_table("板块轮动前三名", ranked_df.head(3), height=180)
        tail_df = ranked_df.sort_values("资金排名", ascending=False, na_position="last").head(3)
        show_table("板块轮动后三名", tail_df, height=180)
    else:
        show_table("板块轮动前三名", ranked_df)


def render_performance_report_panel() -> None:
    st.subheader("账面复盘")
    st.caption("按日期筛选真实交易，生成复盘报表：赚了多少、收益率多少、买卖点还能怎么提高。")

    if st.button("生成复盘报表", key="refresh_performance_report", width="stretch"):
        run_main_command_and_refresh("performance-report")

    current_trade_df = load_trade_records(TRADE_RECORD_FILE)
    if current_trade_df.empty:
        st.info("暂无交易记录，请先到【交易记录 > 日常记账】录入真实交易。")
    else:
        show_df = current_trade_df.copy()
        show_df["_交易日期_dt"] = pd.to_datetime(show_df.get("交易日期", ""), errors="coerce").dt.date
        valid_dates = show_df["_交易日期_dt"].dropna()
        default_start = valid_dates.min() if not valid_dates.empty else None
        default_end = valid_dates.max() if not valid_dates.empty else None

        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            start_date = st.date_input("开始日期", value=default_start, key="performance_start_date")
        with filter_col2:
            end_date = st.date_input("结束日期", value=default_end, key="performance_end_date")

        if start_date:
            show_df = show_df[show_df["_交易日期_dt"] >= start_date]
        if end_date:
            show_df = show_df[show_df["_交易日期_dt"] <= end_date]

        closed_df = show_df[show_df.get("闭环状态", pd.Series(dtype=str)).astype(str).eq("已闭环")].copy()
        total_profit = pd.to_numeric(closed_df.get("到手利润", 0), errors="coerce").fillna(0).sum()
        buy_amount = (
            pd.to_numeric(closed_df.get("买入价格", 0), errors="coerce").fillna(0)
            * pd.to_numeric(closed_df.get("数量", 0), errors="coerce").fillna(0)
        ).sum()
        return_rate = total_profit / buy_amount * 100 if buy_amount > 0 else 0

        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
        with metric_col1:
            st.metric("交易笔数", len(show_df))
        with metric_col2:
            st.metric("已闭环", len(closed_df))
        with metric_col3:
            st.metric("到手利润", f"{total_profit:.2f}")
        with metric_col4:
            st.metric("收益率", f"{return_rate:.2f}%")

        detail_tab, ds_tab = st.tabs(["复盘交易明细", "交易复盘结果"])
        with detail_tab:
            show_table(
                "复盘交易明细",
                keep_columns(
                    show_df.sort_values("交易日期", ascending=False).drop(columns=["_交易日期_dt"], errors="ignore"),
                    [
                        "闭环状态",
                        "股票名称",
                        "股票代码",
                        "交易类型",
                        "方向",
                        "买入价格",
                        "卖出价格",
                        "数量",
                        "到手利润",
                        "收益率",
                        "买入手续费",
                        "卖出手续费",
                        "卖出印花税",
                        "手续费合计",
                        "交易日期",
                        "策略来源",
                        "是否按计划执行",
                        "备注",
                    ],
                ),
                height=420,
            )

        with ds_tab:
            ds_df = performance_report_df[
                performance_report_df.get("报表类型", pd.Series(dtype=str)).astype(str).eq("DS分析")
            ].copy()
            if ds_df.empty:
                st.info("暂无 DS 交易复盘结果，请点击【生成复盘报表】。")
            else:
                for _, row in ds_df.iterrows():
                    render_action_hint(str(row.get("指标", "DS分析")), str(row.get("数值", "")))

    if performance_report_md:
        with st.expander("展开周期复盘报告", expanded=False):
            st.markdown(performance_report_md)


def render_fixed_holding_panel() -> None:
    holding_col1, holding_col2, holding_col3 = st.columns(3)

    with holding_col1:
        if st.button("刷新固定持仓行情", key="tab_refresh_holding_market", width="stretch"):
            run_main_command_and_refresh("holdings-refresh")

    with holding_col2:
        if st.button("刷新持仓买卖点", key="tab_refresh_holding_signals", width="stretch"):
            run_main_command_and_refresh("holdings-signals")

    with holding_col3:
        if st.button("更新全部卖点信号", key="tab_refresh_all_sell_signals", width="stretch"):
            run_single_script_and_refresh("sell_signal_engine.py")

    render_fixed_holding_snapshot(
        final_df=final_df,
        sell_df=sell_signal_df,
        lunch_df=lunch_df,
        next_df=next_df,
        prediction_df=model_prediction_df,
    )
    signal_df = load_csv(FIXED_HOLDINGS_SIGNAL_FILE)
    if not signal_df.empty:
        st.divider()
        st.subheader("持仓买点卖点分析")
        ds_cols = ["DS固定持仓判断", "DS固定持仓动作", "DS固定持仓风险"]
        if any(col in signal_df.columns for col in ds_cols):
            ds_row = signal_df.iloc[0]
            render_action_hint("DS固定持仓判断", str(ds_row.get("DS固定持仓判断", "暂无")))
            ds_col1, ds_col2 = st.columns(2)
            with ds_col1:
                render_action_hint("操作动作", str(ds_row.get("DS固定持仓动作", "暂无")))
            with ds_col2:
                render_action_hint("风险条件", str(ds_row.get("DS固定持仓风险", "暂无")))
        show_table(
            "买卖点明细",
            keep_columns(
                signal_df,
                [
                    "股票名称",
                    "股票代码",
                    "当前价",
                    "当前涨幅",
                    "买点状态",
                    "买点下限",
                    "买点上限",
                    "卖点信号",
                    "卖点理由",
                    "次日上涨概率",
                    "达到1%概率",
                    "止损概率",
                    "实时行情时间",
                    "DS状态",
                ],
            ),
            height=300,
        )


def render_lunch_workspace() -> None:
    if st.button("刷新午盘验证", key="tab_refresh_lunch", width="stretch"):
        run_single_script_and_refresh("lunch_validator.py")

    render_lunch_panel()


def render_next_day_workspace() -> None:
    if st.button("刷新系统次日验证", key="tab_refresh_next_day", width="stretch"):
        run_single_script_and_refresh("next_day_validator.py")

    render_next_day_panel()


def render_dataset_quality_panel() -> None:
    st.subheader("数据集与质量")
    if st.button("保存训练数据并刷新质量报告", key="refresh_dataset_quality", width="stretch"):
        run_main_command_and_refresh("dataset")

    (
        dataset_samples_df,
        feature_snapshot_df,
        label_snapshot_df,
        prediction_log_df,
        model_predictions_df,
    ) = load_dataset_frames()
    render_dataset_metrics(
        dataset_samples_df,
        feature_snapshot_df,
        label_snapshot_df,
        prediction_log_df,
        model_predictions_df,
    )
    if dataset_quality_md:
        with st.expander("展开数据集质量报告", expanded=True):
            st.markdown(dataset_quality_md)
    show_table("样本主表预览", dataset_samples_df.head(30))


def build_validation_review_frame() -> pd.DataFrame:
    fixed_codes = fixed_holding_codes()
    frames = []

    for source_name, frame in [
        ("明日计划", final_df),
        ("卖点信号", sell_signal_df),
        ("午盘验证", lunch_df),
        ("次日复盘", next_df),
    ]:
        if frame.empty or "股票代码" not in frame.columns:
            continue

        temp = mark_fixed_holdings(frame)
        temp = temp[temp["股票代码"].astype(str).str.zfill(6).isin(fixed_codes)].copy()
        if temp.empty:
            continue

        temp["数据来源"] = source_name
        if "实时行情时间" in temp.columns:
            temp["验证时间"] = temp["实时行情时间"]
        elif "刷新时间" in temp.columns:
            temp["验证时间"] = temp["刷新时间"]
        elif "验证日期" in temp.columns:
            temp["验证时间"] = temp["验证日期"]
        else:
            temp["验证时间"] = ""
        frames.append(temp)

    if not frames:
        return pd.DataFrame()

    review_df = pd.concat(frames, ignore_index=True)
    review_df = add_profit_probability(add_model_probability(review_df, model_prediction_df), profit_probability_df)
    review_df = add_final_decision(review_df, final_decision_df)
    return add_short_reason(add_model_signal_status(add_verification_summary(review_df)))


def render_validation_review_panel() -> None:
    review_df = build_validation_review_frame()
    if review_df.empty:
        st.info("暂无固定持仓验证数据。")
        return

    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    with filter_col1:
        source_options = ["全部"] + sorted(review_df["数据来源"].dropna().astype(str).unique().tolist())
        source_filter = st.selectbox("数据来源", source_options, key="validation_source_filter")
    with filter_col2:
        stock_filter = st.text_input("股票名称", placeholder="例如 大为", key="validation_stock_filter")
    with filter_col3:
        result_options = ["全部"] + sorted(
            review_df.get("系统验证结果", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()
        )
        result_filter = st.selectbox("验证结果", result_options, key="validation_result_filter")
    with filter_col4:
        date_filter = st.text_input("验证时间", placeholder="例如 2026-09-03", key="validation_time_filter")

    show_df = review_df.copy()
    if source_filter != "全部":
        show_df = show_df[show_df["数据来源"].astype(str).eq(source_filter)]
    if stock_filter.strip():
        show_df = show_df[show_df["股票名称"].astype(str).str.contains(stock_filter.strip(), case=False, na=False)]
    if result_filter != "全部":
        show_df = show_df[show_df["系统验证结果"].astype(str).eq(result_filter)]
    if date_filter.strip():
        show_df = show_df[show_df["验证时间"].astype(str).str.contains(date_filter.strip(), na=False)]

    show_table(
        "固定持仓验证数据",
        keep_columns(
            show_df,
            [
                "数据来源",
                "验证时间",
                "系统验证结果",
                "最终操作",
                "股票名称",
                "股票代码",
                "操作短句",
                "卖出信号",
                "卖出理由",
                "午盘涨幅",
                "复盘结论",
                "分时确认状态",
                "模型状态",
            ],
        ),
        height=360,
    )


PAGE_CATALOG = [
    {"一级菜单": "数据前瞻", "二级菜单": "隔日外盘", "状态": "待开发", "旧页面": "无", "功能": "隔夜外盘、美元、美债、商品期货等开盘前参考。"},
    {"一级菜单": "数据前瞻", "二级菜单": "金银纵横", "状态": "已接入", "旧页面": "无", "功能": "金银比、金油比、美元和利率压力的资源方向辅助判断。"},
    {"一级菜单": "数据前瞻", "二级菜单": "资金流向", "状态": "已接入", "旧页面": "今日市场 / 板块资金方向", "功能": "查看板块资金流入流出、主线延续和低位轮动。"},
    {"一级菜单": "准备工作", "二级菜单": "盘前预测", "状态": "已接入", "旧页面": "无", "功能": "9:25 后给开盘评分、开盘定性和今日策略。"},
    {"一级菜单": "准备工作", "二级菜单": "固定持仓", "状态": "已接入", "旧页面": "固定持仓", "功能": "集中查看固定持仓行情、买卖点、午盘和次日验证状态。"},
    {"一级菜单": "准备工作", "二级菜单": "单票决策", "状态": "已接入", "旧页面": "单票决策", "功能": "临时输入一只股票，生成单票操作结论和模型依据。"},
    {"一级菜单": "日内交易", "二级菜单": "做T判断", "状态": "已接入", "旧页面": "无", "功能": "判断固定持仓适合先买再卖、先卖再买，还是不做T。"},
    {"一级菜单": "日内交易", "二级菜单": "支撑压力", "状态": "已接入", "旧页面": "开盘T区间", "功能": "计算固定持仓和单票的支撑、压力、买进区间、卖出区间。"},
    {"一级菜单": "隔日持仓", "二级菜单": "明日计划", "状态": "已接入", "旧页面": "明日计划", "功能": "生成明日计划，分开展示固定持仓处理和 A/B 候选。"},
    {"一级菜单": "隔日持仓", "二级菜单": "卖点信号", "状态": "已接入", "旧页面": "卖点信号 / 固定持仓", "功能": "查看和刷新持仓卖点，输出简短卖出理由。"},
    {"一级菜单": "隔日持仓", "二级菜单": "午盘验证", "状态": "已接入", "旧页面": "午盘验证", "功能": "14:00 前后验证上午结构和下午处理建议。"},
    {"一级菜单": "隔日持仓", "二级菜单": "次日复盘", "状态": "已接入", "旧页面": "系统次日验证", "功能": "复盘昨天计划是否有效，沉淀训练标签。"},
    {"一级菜单": "交易记录", "二级菜单": "日常记账", "状态": "已接入", "旧页面": "交易记录", "功能": "记录和修改日内T / 隔日T交易，自动计算费用、印花税和收益。"},
    {"一级菜单": "交易记录", "二级菜单": "账面复盘", "状态": "已接入", "旧页面": "无", "功能": "按周期统计真实做T收益、胜率和系统有效性。"},
    {"一级菜单": "模型构建", "二级菜单": "数据获取-盘前预测", "状态": "已接入", "旧页面": "资金流向 / 盘前预测", "功能": "把资金流向和盘前预测结构化为模型输入标签。"},
    {"一级菜单": "模型构建", "二级菜单": "数据获取-日内交易", "状态": "半接入", "旧页面": "交易记录", "功能": "目前复用真实交易记录，后续接入分钟级行情和做T路径标签。"},
    {"一级菜单": "模型构建", "二级菜单": "数据获取-隔日持仓", "状态": "已接入", "旧页面": "保存训练数据 / 数据集质量", "功能": "保存隔日持仓训练数据并查看数据质量。"},
    {"一级菜单": "模型构建", "二级菜单": "模型训练", "状态": "已接入", "旧页面": "模型训练", "功能": "训练方向、收益率、校准和解释相关模型。"},
    {"一级菜单": "模型构建", "二级菜单": "模型预测", "状态": "已接入", "旧页面": "模型预测", "功能": "运行模型预测、概率校准、解释和预测回顾。"},
    {"一级菜单": "模型构建", "二级菜单": "数据复盘", "状态": "已接入", "旧页面": "数据复盘 / 因子表现", "功能": "集中看今日模型报告、预测回顾、因子表现。"},
]


def build_menu_structure() -> dict[str, list[str]]:
    menu: dict[str, list[str]] = {}
    for page in PAGE_CATALOG:
        menu.setdefault(page["一级菜单"], []).append(page["二级菜单"])
    return menu


MENU_STRUCTURE = build_menu_structure()
PAGE_META = {page["二级菜单"]: page for page in PAGE_CATALOG}


def render_missing_page(page_name: str, module_hint: str = "") -> None:
    st.subheader(page_name)
    st.warning(f"{page_name} 页面没有，待开发。")
    if module_hint:
        st.caption(module_hint)


def render_preopen_data_page() -> None:
    st.subheader("数据获取-盘前预测")
    st.caption("这里不改数据，只把资金流向和盘前预测整理成模型可用标签。")
    rows = []
    if not preopen_prediction_df.empty:
        row = preopen_prediction_df.iloc[-1]
        rows.extend([
            {"标签来源": "盘前预测", "标签名": "开盘定性", "标签值": row.get("开盘定性", ""), "用途": "判断日内仓位和做T强度"},
            {"标签来源": "盘前预测", "标签名": "今日策略", "标签值": row.get("今日策略", ""), "用途": "指导做T或买卖点输入"},
            {"标签来源": "盘前预测", "标签名": "金融拉盘预警", "标签值": row.get("金融拉盘预警", ""), "用途": "识别指数假强风险"},
            {"标签来源": "盘前预测", "标签名": "DS操作建议", "标签值": row.get("DS操作建议", ""), "用途": "给模型保留自然语言决策摘要"},
        ])
    if not sector_rotation_df.empty:
        sector_show = add_billion_columns(sector_rotation_df).head(5)
        for _, row in sector_show.iterrows():
            rows.append({
                "标签来源": "资金流向",
                "标签名": str(row.get("所属板块", "")),
                "标签值": f"{row.get('板块轮动状态', '')}/{row.get('板块操作建议', '')}",
                "用途": f"主力净流入{row.get('主力净流入亿元', '')}亿，校正板块权重",
            })
    label_df = pd.DataFrame(rows)
    show_table("盘前模型输入标签", label_df, height=360)
    if preopen_prediction_md:
        with st.expander("展开盘前预测报告", expanded=False):
            st.markdown(preopen_prediction_md)


def render_intraday_data_page() -> None:
    st.subheader("数据获取-日内交易")
    st.caption("这里只看日内交易样本来源和质量，不在模型构建页修改交易记录。")
    current_trade_df = load_trade_records(TRADE_RECORD_FILE)
    if current_trade_df.empty:
        st.info("暂无日内交易样本，请先到【交易记录 > 日常记账】录入真实交易。")
        return

    intraday_df = current_trade_df[current_trade_df["交易类型"].astype(str).eq("日内T")].copy()
    closed_df = intraday_df[intraday_df["闭环状态"].astype(str).eq("已闭环")].copy()
    profit_series = pd.to_numeric(closed_df.get("到手利润", pd.Series(dtype=float)), errors="coerce").fillna(0)
    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    with metric_col1:
        st.metric("日内T样本", len(intraday_df))
    with metric_col2:
        st.metric("闭环样本", len(closed_df))
    with metric_col3:
        st.metric("盈利样本", int((profit_series > 0).sum()))
    with metric_col4:
        st.metric("到手利润", f"{profit_series.sum():.2f}")

    show_table(
        "日内交易样本",
        keep_columns(
            intraday_df.sort_values("交易日期", ascending=False),
            [
                "交易日期",
                "股票名称",
                "股票代码",
                "方向",
                "买入价格",
                "卖出价格",
                "数量",
                "到手利润",
                "收益率",
                "策略来源",
                "是否按计划执行",
                "闭环状态",
            ],
        ).head(40),
        height=420,
    )


def render_overnight_data_page() -> None:
    st.subheader("数据获取-隔日持仓")
    st.caption("隔日持仓数据相当于系统模拟盘：系统给买点卖点，你的真实交易用于校准执行效果。")
    if st.button("保存隔日持仓训练数据", key="save_overnight_dataset", width="stretch"):
        run_main_command_and_refresh("dataset")
    if dataset_quality_md:
        with st.expander("展开数据集质量报告", expanded=True):
            st.markdown(dataset_quality_md)
    else:
        st.info("暂无数据集质量报告，请先保存训练数据。")


def render_data_review_page() -> None:
    st.subheader("数据复盘")
    st.caption("这里集中查看验证数据、预测回顾、今日模型报告、因子表现和数据集质量。")
    if st.button("刷新数据复盘", key="refresh_data_review", width="stretch"):
        run_main_command_and_refresh("prediction-review")
    render_validation_review_panel()
    if daily_model_report_md:
        with st.expander("展开今日模型与预测复盘报告", expanded=True):
            st.markdown(daily_model_report_md)
    if prediction_review_report_md:
        with st.expander("展开预测回顾报告", expanded=False):
            st.markdown(prediction_review_report_md)
    render_factor_panel()


PAGE_RENDERERS = {
    "隔日外盘": lambda: render_missing_page("隔日外盘", "需要后续接入美股、日韩指数、美元、美债、商品期货等隔夜数据。"),
    "金银纵横": render_metal_macro_panel,
    "资金流向": render_sector_rotation_panel,
    "盘前预测": render_preopen_prediction_panel,
    "固定持仓": render_fixed_holding_panel,
    "单票决策": render_single_stock_panel,
    "做T判断": render_t_mode_panel,
    "支撑压力": lambda: render_t_mode_panel("支撑压力"),
    "明日计划": render_trade_plan_panel,
    "卖点信号": render_sell_signal_panel,
    "午盘验证": render_lunch_workspace,
    "次日复盘": render_next_day_workspace,
    "日常记账": render_trade_record_panel,
    "账面复盘": render_performance_report_panel,
    "数据获取-盘前预测": render_preopen_data_page,
    "数据获取-日内交易": render_intraday_data_page,
    "数据获取-隔日持仓": render_overnight_data_page,
    "模型训练": render_model_training_panel,
    "模型预测": render_model_prediction_panel,
    "数据复盘": render_data_review_page,
}


def flatten_menu_pages() -> list[str]:
    pages = []
    for children in MENU_STRUCTURE.values():
        pages.extend(children)
    return pages


def render_sidebar_menu() -> str:
    with st.sidebar:
        st.title("实盘工作台")
        st.caption("按操作顺序展开一级菜单，点击二级菜单进入页面。")

        if sac is not None:
            items = []
            for primary, children in MENU_STRUCTURE.items():
                items.append(
                    sac.MenuItem(
                        primary,
                        children=[sac.MenuItem(child) for child in children],
                    )
                )
            selected = sac.menu(
                items,
                open_all=False,
                open_index=[0],
                index=0,
                size="md",
                variant="left-bar",
                color="red",
                key="main_operation_menu",
            )
            if selected in PAGE_RENDERERS:
                return selected
            return MENU_STRUCTURE["数据前瞻"][0]

        st.info("未安装 streamlit-antd-components，当前使用原生菜单降级显示。")
        primary_page = st.radio("一级菜单", list(MENU_STRUCTURE.keys()))
        return st.radio("二级菜单", MENU_STRUCTURE[primary_page])


debug_page = st.query_params.get("page", "")
selected_page = debug_page if debug_page in PAGE_RENDERERS else render_sidebar_menu()
selected_meta = PAGE_META.get(selected_page, {})
if selected_meta:
    st.caption(f"{selected_meta['一级菜单']} > {selected_meta['二级菜单']} · {selected_meta['状态']}")
    st.divider()
PAGE_RENDERERS.get(selected_page, lambda: render_missing_page(selected_page))()
