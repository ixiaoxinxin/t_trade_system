# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from common import normalize_code, now_text, safe_float
from fixed_holdings import fixed_holding_name_map


FINAL_DECISION_FILE = Path("output/final_decision_v3.0.csv")
FINAL_WATCHLIST_FILE = Path("output/final_watchlist.csv")
FIXED_HOLDINGS_SIGNAL_FILE = Path("output/fixed_holdings_signals.csv")
SELL_SIGNAL_FILE = Path("output/sell_signal.csv")
LUNCH_REVIEW_FILE = Path("output/lunch_review.csv")
NEXT_DAY_REVIEW_FILE = Path("output/next_day_review.csv")
MODEL_PREDICTION_FILE = Path("output/model_predictions_v2.6.csv")
PROFIT_PROBABILITY_FILE = Path("output/profit_probabilities_v2.7.csv")
CALIBRATED_PROBABILITY_FILE = Path("output/calibrated_probabilities_v2.8.csv")
MODEL_EXPLANATION_FILE = Path("output/model_explanations_v2.8.csv")
PREDICTION_REVIEW_FILE = Path("output/prediction_review_v2.9.csv")

SINGLE_STOCK_DECISION_FILE = Path("output/single_stock_decision.csv")
SINGLE_STOCK_DECISION_REPORT_FILE = Path("output/single_stock_decision.md")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    return pd.read_csv(path, dtype={"股票代码": str, "stock_code": str}, encoding="utf-8-sig")


def stock_code_column(df: pd.DataFrame) -> str:
    if "股票代码" in df.columns:
        return "股票代码"
    if "stock_code" in df.columns:
        return "stock_code"
    return ""


def latest_row(df: pd.DataFrame, stock_code: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=object)

    col = stock_code_column(df)
    if not col:
        return pd.Series(dtype=object)

    work = df.copy()
    work["_code"] = work[col].apply(normalize_code)
    work = work[work["_code"].eq(normalize_code(stock_code))].copy()
    if work.empty:
        return pd.Series(dtype=object)

    sort_cols = [
        col
        for col in ["created_at", "calibrated_at", "predict_date", "确认日期", "刷新时间", "日期"]
        if col in work.columns
    ]
    if sort_cols:
        work = work.sort_values(sort_cols)

    return work.iloc[-1]


def first_text(*values: Any) -> str:
    for value in values:
        if pd.isna(value):
            continue
        text = str(value).strip()
        if text and text.lower() not in ["nan", "none", "null"]:
            return text
    return ""


def pct_text(value: Any) -> str:
    return f"{safe_float(value, 0):.1%}"


def build_single_stock_summary(stock_code: str) -> dict[str, Any]:
    code = normalize_code(stock_code)
    name_map = fixed_holding_name_map()

    final_row = latest_row(read_csv(FINAL_DECISION_FILE), code)
    watch_row = latest_row(read_csv(FINAL_WATCHLIST_FILE), code)
    fixed_signal_row = latest_row(read_csv(FIXED_HOLDINGS_SIGNAL_FILE), code)
    sell_row = latest_row(read_csv(SELL_SIGNAL_FILE), code)
    lunch_row = latest_row(read_csv(LUNCH_REVIEW_FILE), code)
    next_row = latest_row(read_csv(NEXT_DAY_REVIEW_FILE), code)
    direction_row = latest_row(read_csv(MODEL_PREDICTION_FILE), code)
    profit_row = latest_row(read_csv(PROFIT_PROBABILITY_FILE), code)
    calibrated_row = latest_row(read_csv(CALIBRATED_PROBABILITY_FILE), code)
    explanation_row = latest_row(read_csv(MODEL_EXPLANATION_FILE), code)
    review_row = latest_row(read_csv(PREDICTION_REVIEW_FILE), code)

    p1 = first_text(
        calibrated_row.get("calibrated_hit_1pct_probability", ""),
        profit_row.get("hit_1pct_probability", ""),
    )
    p2 = first_text(
        calibrated_row.get("calibrated_hit_2pct_probability", ""),
        profit_row.get("hit_2pct_probability", ""),
    )
    p_stop = first_text(
        calibrated_row.get("calibrated_stop_2pct_probability", ""),
        profit_row.get("stop_2pct_probability", ""),
    )

    return {
        "stock_code": code,
        "stock_name": first_text(
            final_row.get("stock_name", ""),
            watch_row.get("股票名称", ""),
            fixed_signal_row.get("股票名称", ""),
            direction_row.get("stock_name", ""),
            name_map.get(code, ""),
        ),
        "is_fixed_holding": code in name_map,
        "final_action": first_text(final_row.get("final_action", "")),
        "fusion_score": safe_float(final_row.get("fusion_score", 0), 0),
        "decision_reason": first_text(final_row.get("decision_reason", "")),
        "rule_grade": first_text(final_row.get("rule_grade", ""), watch_row.get("隔夜建议等级", "")),
        "rule_score": safe_float(final_row.get("rule_score", watch_row.get("最终评分", 0)), 0),
        "next_day_up_probability": safe_float(direction_row.get("next_day_up_probability", final_row.get("next_day_up_probability", 0)), 0),
        "hit_1pct_probability": safe_float(p1, 0),
        "hit_2pct_probability": safe_float(p2, 0),
        "stop_2pct_probability": safe_float(p_stop, 0),
        "sector_name": first_text(final_row.get("sector_name", ""), watch_row.get("所属板块", "")),
        "sector_status": first_text(final_row.get("sector_status", ""), watch_row.get("板块数据状态", "")),
        "market_regime": first_text(final_row.get("market_regime", ""), direction_row.get("market_regime", "")),
        "buy_status": first_text(fixed_signal_row.get("买点状态", "")),
        "buy_range": first_text(
            format_buy_range(fixed_signal_row),
            "",
        ),
        "sell_signal": first_text(fixed_signal_row.get("卖点信号", ""), sell_row.get("卖出信号", "")),
        "sell_reason": first_text(fixed_signal_row.get("卖点理由", ""), sell_row.get("卖出理由", "")),
        "lunch_status": first_text(lunch_row.get("下午操作建议", ""), lunch_row.get("午盘结论", "")),
        "next_day_result": first_text(next_row.get("执行验证结果", ""), next_row.get("是否验证成功", "")),
        "review_result": first_text(review_row.get("direction_hit", ""), review_row.get("hit_1pct_after_touch", "")),
        "positive_factors": first_text(explanation_row.get("top_positive_factors", "")),
        "negative_factors": first_text(explanation_row.get("top_negative_factors", "")),
        "generated_at": now_text(),
    }


def format_buy_range(row: pd.Series) -> str:
    low = safe_float(row.get("买点下限", 0), 0)
    high = safe_float(row.get("买点上限", 0), 0)
    if low <= 0 or high <= 0:
        return ""
    return f"{low:.2f} - {high:.2f}"


def write_single_stock_report(summary: dict[str, Any]) -> None:
    SINGLE_STOCK_DECISION_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# 单票决策工作台",
        "",
        f"生成时间：{summary['generated_at']}",
        f"股票：`{summary['stock_code']} {summary['stock_name']}`",
        "",
        "## 一、最终结论",
        "",
        f"- 最终操作：{summary['final_action'] or '暂无'}",
        f"- 融合评分：{summary['fusion_score']:.1f}",
        f"- 决策解释：{summary['decision_reason'] or '暂无'}",
        "",
        "## 二、模型与规则依据",
        "",
        "| 项目 | 数值 |",
        "|---|---|",
        f"| 规则等级 | {summary['rule_grade'] or '暂无'} |",
        f"| 规则评分 | {summary['rule_score']:.1f} |",
        f"| 次日上涨概率 | {pct_text(summary['next_day_up_probability'])} |",
        f"| 达到 +1% 概率 | {pct_text(summary['hit_1pct_probability'])} |",
        f"| 达到 +2% 概率 | {pct_text(summary['hit_2pct_probability'])} |",
        f"| 先止损概率 | {pct_text(summary['stop_2pct_probability'])} |",
        f"| 市场环境 | {summary['market_regime'] or '暂无'} |",
        f"| 板块 | {summary['sector_name'] or '暂无'} |",
        f"| 板块状态 | {summary['sector_status'] or '暂无'} |",
        "",
        "## 三、实盘处理",
        "",
        f"- 买点状态：{summary['buy_status'] or '暂无'}",
        f"- 买点区间：{summary['buy_range'] or '暂无'}",
        f"- 卖点信号：{summary['sell_signal'] or '暂无'}",
        f"- 卖点理由：{summary['sell_reason'] or '暂无'}",
        "",
        "## 四、验证与解释",
        "",
        f"- 午盘状态：{summary['lunch_status'] or '暂无'}",
        f"- 次日结果：{summary['next_day_result'] or '暂无'}",
        f"- 正向因子：{summary['positive_factors'] or '暂无'}",
        f"- 负向因子：{summary['negative_factors'] or '暂无'}",
    ]

    SINGLE_STOCK_DECISION_REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_single_stock_decision(stock_code: str | None = None) -> dict[str, Any]:
    code = normalize_code(stock_code or "002466")
    summary = build_single_stock_summary(code)

    if not summary["stock_name"]:
        raise RuntimeError(f"未找到单票数据：{code}")

    SINGLE_STOCK_DECISION_FILE.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([summary]).to_csv(SINGLE_STOCK_DECISION_FILE, index=False, encoding="utf-8-sig")
    write_single_stock_report(summary)

    print("单票决策已生成。")
    print(f"股票：{summary['stock_code']} {summary['stock_name']}")
    print(f"最终操作：{summary['final_action'] or '暂无'}")
    print(f"输出：{SINGLE_STOCK_DECISION_FILE}")

    return {
        "stock_code": summary["stock_code"],
        "stock_name": summary["stock_name"],
        "csv": str(SINGLE_STOCK_DECISION_FILE),
        "report": str(SINGLE_STOCK_DECISION_REPORT_FILE),
    }


if __name__ == "__main__":
    run_single_stock_decision()
