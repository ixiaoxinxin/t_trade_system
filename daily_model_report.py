# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from common import now_text, safe_float
from trade_journal import load_trade_records


DIRECTION_EVALUATION_FILE = Path("output/model_evaluation_v2.6.md")
PROFIT_EVALUATION_FILE = Path("output/profit_probability_evaluation_v2.7.md")
CALIBRATION_REPORT_FILE = Path("output/probability_calibration_v2.8.md")
PREDICTION_REVIEW_FILE = Path("output/prediction_review_v2.9.csv")
MODEL_SCORECARD_FILE = Path("output/model_scorecard_v2.9.csv")
DAILY_REPORT_FILE = Path("output/daily_model_report.md")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    return pd.read_csv(path, dtype={"stock_code": str, "股票代码": str})


def metric_value(scorecard_df: pd.DataFrame, metric_name: str, segment_type: str = "all", segment_value: str = "all") -> float | None:
    if scorecard_df.empty:
        return None

    rows = scorecard_df[
        scorecard_df["metric_name"].astype(str).eq(metric_name)
        & scorecard_df["segment_type"].astype(str).eq(segment_type)
        & scorecard_df["segment_value"].astype(str).eq(segment_value)
    ]
    if rows.empty:
        return None

    value = pd.to_numeric(rows.iloc[0].get("score"), errors="coerce")
    return None if pd.isna(value) else float(value)


def percent_text(value: Any) -> str:
    number = safe_float(value, default=float("nan"))
    if pd.isna(number):
        return "-"
    return f"{number:.2%}"


def number_text(value: Any) -> str:
    number = safe_float(value, default=float("nan"))
    if pd.isna(number):
        return "-"
    return f"{number:.4f}"


def detect_model_stage(scorecard_df: pd.DataFrame) -> str:
    direction_hit = metric_value(scorecard_df, "direction_hit_rate")
    hit_1_brier = metric_value(scorecard_df, "hit_1pct_brier")
    calibrated_hit_1_brier = metric_value(scorecard_df, "calibrated_hit_1pct_brier")

    if direction_hit is None and hit_1_brier is None and calibrated_hit_1_brier is None:
        return "模型仍处在样本不足或基准概率阶段，暂时不能用作强排序。"

    return "模型已有可评分结果，但仍需结合样本量和分组稳定性观察。"


def calculate_improvement(scorecard_df: pd.DataFrame) -> tuple[str, str]:
    raw_brier = metric_value(scorecard_df, "hit_1pct_brier")
    calibrated_brier = metric_value(scorecard_df, "calibrated_hit_1pct_brier")

    if raw_brier is None or calibrated_brier is None:
        return "-", "今天没有足够有效标签计算校准前后 Brier，不能证明模型提升。"

    improvement = raw_brier - calibrated_brier
    if improvement > 0:
        return f"{improvement:.4f}", "校准后 Brier 下降，概率质量有提升。"
    if improvement < 0:
        return f"{improvement:.4f}", "校准后 Brier 上升，需要回滚或扩大样本再观察。"
    return "0.0000", "校准前后没有可见提升。"


def summarize_trades() -> list[str]:
    trade_df = load_trade_records()
    if trade_df.empty:
        return ["- 今日交易记录：0 笔。"]

    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    today_df = trade_df[trade_df["交易日期"].astype(str).eq(today)].copy()
    closed_df = today_df[today_df["闭环状态"].astype(str).eq("已闭环")].copy()
    total_profit = pd.to_numeric(closed_df["到手利润"], errors="coerce").fillna(0).sum()
    avg_return = pd.to_numeric(closed_df["收益率"], errors="coerce").dropna()

    return [
        f"- 今日交易记录：{len(today_df)} 笔，其中已闭环 {len(closed_df)} 笔。",
        f"- 今日已实现盈亏：{total_profit:.2f} 元。",
        f"- 今日平均收益率：{avg_return.mean():.2f}%。" if not avg_return.empty else "- 今日平均收益率：-。",
    ]


def build_daily_model_report() -> dict[str, Any]:
    review_df = read_csv(PREDICTION_REVIEW_FILE)
    scorecard_df = read_csv(MODEL_SCORECARD_FILE)

    sample_count = len(review_df)
    buy_range_rate = metric_value(scorecard_df, "buy_range_executable_rate")
    range_coverage = metric_value(scorecard_df, "range_coverage_rate")
    range_overlap = metric_value(scorecard_df, "range_overlap_rate")
    hit_1_actual_rate = metric_value(scorecard_df, "hit_1pct_actual_rate_by_bucket", "probability_bucket", "0-20%")
    hit_2_actual_rate = metric_value(scorecard_df, "hit_2pct_actual_rate_by_bucket", "probability_bucket", "0-20%")
    stop_actual_rate = metric_value(scorecard_df, "stop_2pct_actual_rate_by_bucket", "probability_bucket", "0-20%")
    improvement_value, improvement_note = calculate_improvement(scorecard_df)

    lines = [
        "# 今日模型与预测复盘报告",
        "",
        f"生成时间：{now_text()}",
        "",
        "## 一、今日结论",
        "",
        f"- 回顾样本数：{sample_count}。",
        f"- 模型阶段：{detect_model_stage(scorecard_df)}",
        f"- 低吸区间可成交率：{percent_text(buy_range_rate)}。",
        f"- 平均区间覆盖率：{percent_text(range_coverage)}，平均区间重合度：{percent_text(range_overlap)}。",
        f"- +1% 实际发生率：{percent_text(hit_1_actual_rate)}，+2% 实际发生率：{percent_text(hit_2_actual_rate)}。",
        f"- 止损实际发生率：{percent_text(stop_actual_rate)}。",
        "",
        "## 二、模型提升度",
        "",
        f"- 校准提升值（原始 Brier - 校准后 Brier）：{improvement_value}。",
        f"- 判断：{improvement_note}",
        "- 当前方向模型和收益概率模型若仍显示 `baseline_probability`，说明它们还没有从样本中学出个股区分能力。",
        "",
        "## 三、真实交易反馈",
        "",
        *summarize_trades(),
        "",
        "## 四、今天暴露的问题",
        "",
        "- `calibrate-explain` 在校准样本为空时写 SQLite 失败，需要避免用空字段 DataFrame 覆盖表结构。",
        "- 交易记录股票代码不能强制填写，实盘可以先记录股票名称，代码后续再补。",
        "- 修改交易记录数量变多后，需要按日期、股票名称、交易类型筛选。",
        "",
        "## 五、程序修改建议",
        "",
        "- 校准模块：空校准表只清空旧数据，不重建空表。",
        "- 交易记录：允许股票代码为空，禁止空代码被保存为 `000000`。",
        "- 页面：修改记录区增加日期、股票名称、交易类型筛选。",
        "- 模型：当前概率只作为观察，不参与强排序；下一步优先提高有效标签质量和样本量。",
    ]

    DAILY_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    DAILY_REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"今日模型报告已生成：{DAILY_REPORT_FILE}")
    return {"report": str(DAILY_REPORT_FILE), "rows": sample_count}


if __name__ == "__main__":
    build_daily_model_report()
