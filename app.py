# app.py
# -*- coding: utf-8 -*-

"""
A股隔日T选股系统 Streamlit 精简版

升级点：
1. 页面继续降噪，删除高低点/最高涨幅/最低涨幅等冗余展示
2. 次日验证拆分为：验证成功 / 验证失败或待优化
3. 已购买股票优先展示
4. 市场环境增加板块资金方向展示
5. 原始 Markdown 报告默认折叠
6. 页面按真实交易工作流重组
7. 人工复盘入口下线，复盘沉淀以真实交易记录为准
8. 页面按工作流拆成独立一级 Tab，固定持仓、交易记录、午盘、模型训练、模型预测分开验收
"""

from pathlib import Path
import subprocess
import sys
import time

import pandas as pd
import streamlit as st

from fixed_holdings import fixed_holding_codes, fixed_holding_name_map, mark_fixed_holdings, sort_fixed_holdings_first
from common import normalize_code, safe_float
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


st.set_page_config(
    page_title="A股隔日T选股系统",
    layout="wide"
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
        "需分时确认": "需确认：日线无法判断先涨还是先跌。",
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


def show_table(title: str, df: pd.DataFrame) -> None:
    st.subheader(title)

    if df.empty:
        st.warning("暂无数据")
        return

    display_df = df.copy()

    for col in display_df.select_dtypes(include=["object"]).columns:
        display_df[col] = display_df[col].fillna("").astype(str)

    st.dataframe(
        display_df,
        width="stretch",
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
    st.caption("融捷股份、云天化、大为股份、神火股份、天齐锂业单独成表。先看买点区间和卖点信号，再看午盘/次日结果。")

    signal_df = load_csv(FIXED_HOLDINGS_SIGNAL_FILE)
    signal_df = add_profit_probability(add_model_probability(signal_df, prediction_df), profit_probability_df)
    signal_df = add_final_decision(signal_df, final_decision_df)

    if signal_df.empty:
        st.info("暂无固定持仓买卖点，请点击【刷新持仓买卖点】。")
    else:
        signal_df = add_short_reason(add_model_signal_status(signal_df))
        show_table(
            "固定持仓买点 / 卖点",
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
                    "买点下限",
                    "买点上限",
                    "当前价",
                    "实时行情时间",
                    "实时状态",
                    "日线状态",
                    "分钟状态",
                    "模型状态",
                ],
            ),
        )

    fixed_codes = fixed_holding_codes()
    frames = []

    for source_name, frame in [
        ("交易池", final_df),
        ("卖点", sell_df),
        ("午盘", lunch_df),
        ("次日", next_df),
    ]:
        if frame.empty or "股票代码" not in frame.columns:
            continue

        temp = mark_fixed_holdings(frame)
        temp = temp[temp["股票代码"].astype(str).str.zfill(6).isin(fixed_codes)].copy()
        if temp.empty:
            continue

        temp["来源"] = source_name
        frames.append(temp)

    if not frames:
        st.info("固定持仓暂无卖点/午盘/次日刷新结果，请点击【更新卖点信号】、【午盘验证】或【次日复盘】。")
        return

    fixed_df = pd.concat(frames, ignore_index=True)
    fixed_df = add_profit_probability(add_model_probability(fixed_df, prediction_df), profit_probability_df)
    fixed_df = add_final_decision(fixed_df, final_decision_df)
    fixed_df = add_short_reason(add_model_signal_status(add_verification_summary(fixed_df)))
    show_table(
        "固定持仓验证状态",
        keep_columns(
            fixed_df,
            [
                "最终操作",
                "股票名称",
                "股票代码",
                "操作短句",
                "来源",
                "卖出信号",
                "卖出理由",
                "午盘涨幅",
                "系统验证结果",
                "复盘结论",
                "上午结构标签",
                "下午操作建议",
                "模型状态",
            ],
        ),
    )


# =========================
# 页面主体
# =========================

st.title("A股隔日T选股系统")

st.caption("工作流版：今日能不能做 → 明天看哪几只 → 实盘怎么处理 → 结果沉淀到数据集")
st.info("使用主线：先看最终操作，再看单票依据；模型概率只辅助排序和风控，不替代规则。")

st.divider()

# =========================
# 操作区
# =========================

st.subheader("日常操作")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    if st.button("生成明日计划", width="stretch"):
        run_main_pipeline_and_refresh()

with col2:
    if st.button("更新卖点信号", width="stretch"):
        run_single_script_and_refresh("sell_signal_engine.py")

with col3:
    if st.button("午盘验证", width="stretch"):
        run_single_script_and_refresh("lunch_validator.py")

with col4:
    if st.button("次日复盘", width="stretch"):
        run_single_script_and_refresh("next_day_validator.py")

with col5:
    if st.button("保存训练数据", width="stretch"):
        run_single_script_and_refresh("dataset_builder.py")

with st.expander("高级工具", expanded=False):
    tool_col1, tool_col2, tool_col3, tool_col4 = st.columns(4)

    with tool_col1:
        if st.button("单独刷新市场环境", width="stretch"):
            run_single_script_and_refresh("market_environment.py")

    with tool_col2:
        if st.button("刷新固定持仓行情", width="stretch"):
            run_main_command_and_refresh("holdings-refresh")

    with tool_col3:
        if st.button("刷新持仓买卖点", width="stretch"):
            run_main_command_and_refresh("holdings-signals")

    with tool_col4:
        if st.button("迁移数据库", width="stretch"):
            run_single_script_and_refresh("sqlite_store.py")

st.caption("页面数据源：SQLite 优先；脚本产生的本地文件会在执行后自动迁移入库。")

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
model_prediction_df = load_csv(MODEL_PREDICTION_FILE)
profit_probability_df = load_csv(PROFIT_PROBABILITY_FILE)
calibrated_probability_df = load_csv(CALIBRATED_PROBABILITY_FILE)
model_explanation_df = load_csv(MODEL_EXPLANATION_FILE)
prediction_review_df = load_csv(PREDICTION_REVIEW_FILE)
model_scorecard_df = load_csv(MODEL_SCORECARD_FILE)
final_decision_df = load_csv(FINAL_DECISION_FILE)
single_stock_decision_df = load_csv(SINGLE_STOCK_DECISION_FILE)
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
    st.subheader("持仓卖点")

    if sell_signal_md:
        with st.expander("展开卖点信号原始报告", expanded=False):
            st.markdown(sell_signal_md)
    else:
        st.warning("暂无卖点信号，有持仓时点击【更新卖点信号】。")

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
    show_table("卖点核心信号", sell_core_df)


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
            "上午结构标签",
            "午盘涨幅",
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
        "股票名称",
        "股票代码",
        "复盘结论",
        "优化方向",
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


tab_plan, tab_holdings, tab_single_stock, tab_trade_records, tab_lunch, tab_next_day, tab_model_train, tab_model_predict = st.tabs([
    "明日计划",
    "固定持仓",
    "单票决策",
    "交易记录",
    "午盘验证",
    "系统次日验证",
    "模型训练",
    "模型预测",
])


with tab_plan:
    with st.expander("今日市场与高级信息", expanded=False):
        render_market_panel()
        st.divider()
        render_factor_panel()

    render_trade_plan_panel()


with tab_holdings:
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
    st.divider()
    render_sell_signal_panel()


with tab_single_stock:
    render_single_stock_panel()


with tab_trade_records:
    render_trade_record_panel()


with tab_lunch:
    if st.button("刷新午盘验证", key="tab_refresh_lunch", width="stretch"):
        run_single_script_and_refresh("lunch_validator.py")

    render_lunch_panel()


with tab_next_day:
    if st.button("刷新系统次日验证", key="tab_refresh_next_day", width="stretch"):
        run_single_script_and_refresh("next_day_validator.py")

    render_next_day_panel()


with tab_model_train:
    render_model_training_panel()


with tab_model_predict:
    render_model_prediction_panel()
