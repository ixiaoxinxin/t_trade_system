# -*- coding: utf-8 -*-

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from common import normalize_code, now_text, safe_float
from fixed_holdings import fixed_holding_codes, fixed_holding_name_map, is_fixed_holding
from sqlite_store import DATABASE_FILE


FINAL_WATCHLIST_FILE = Path("output/final_watchlist.csv")
MODEL_PREDICTION_FILE = Path("output/model_predictions_v2.6.csv")
PROFIT_PROBABILITY_FILE = Path("output/profit_probabilities_v2.7.csv")
CALIBRATED_PROBABILITY_FILE = Path("output/calibrated_probabilities_v2.8.csv")
MODEL_SCORECARD_FILE = Path("output/model_scorecard_v2.9.csv")

FINAL_DECISION_FILE = Path("output/final_decision_v3.0.csv")
FINAL_DECISION_REPORT_FILE = Path("output/final_decision_v3.0.md")

MODEL_VERSION = "v3.0-decision-fusion-001"


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    return pd.read_csv(path, dtype={"股票代码": str, "stock_code": str}, encoding="utf-8-sig")


def code_column(df: pd.DataFrame) -> str:
    if "股票代码" in df.columns:
        return "股票代码"
    if "stock_code" in df.columns:
        return "stock_code"
    return ""


def normalize_stock_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    work = df.copy()
    col = code_column(work)
    if col:
        work["stock_code_norm"] = work[col].apply(normalize_code)

    return work


def latest_by_code(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    work = normalize_stock_frame(df)
    if "stock_code_norm" not in work.columns:
        return pd.DataFrame()

    sort_cols = [col for col in ["predict_date", "确认日期", "created_at", "calibrated_at"] if col in work.columns]
    if sort_cols:
        work = work.sort_values(sort_cols)

    return work.drop_duplicates("stock_code_norm", keep="last").copy()


def model_quality_score(scorecard_df: pd.DataFrame) -> float:
    if scorecard_df.empty:
        return 0.5

    all_rows = scorecard_df[
        scorecard_df.get("segment_type", pd.Series(dtype=str)).astype(str).eq("all")
    ].copy()
    if all_rows.empty:
        all_rows = scorecard_df.copy()

    direction = all_rows[all_rows["metric_name"].astype(str).eq("direction_hit_rate")]
    direction_score = safe_float(direction["score"].iloc[0], 0.5) if not direction.empty else 0.5

    brier_rows = all_rows[all_rows["metric_name"].astype(str).str.contains("brier", na=False)]
    if brier_rows.empty:
        probability_score = 0.5
    else:
        brier = brier_rows["score"].apply(lambda value: safe_float(value, 0.5)).mean()
        probability_score = max(0.0, min(1.0, 1.0 - safe_float(brier, 0.5)))

    return round(max(0.0, min(1.0, direction_score * 0.45 + probability_score * 0.55)), 6)


def rule_grade_score(grade: Any) -> float:
    text = str(grade).strip().upper()
    return {
        "A": 1.0,
        "B": 0.76,
        "C": 0.48,
        "D": 0.16,
    }.get(text, 0.4)


def market_score(regime: Any) -> float:
    text = str(regime).strip()
    if not text:
        return 0.5
    if "系统风险" in text or "极弱" in text:
        return 0.15
    if "冰点" in text or "偏弱" in text:
        return 0.35
    if "震荡" in text:
        return 0.55
    if "强" in text or "修复" in text:
        return 0.75
    return 0.5


def sector_score(row: pd.Series) -> float:
    status = str(row.get("板块数据状态", "")).strip()
    if "回避" in status:
        return 0.1
    if "未知" in status or not status:
        base = 0.5
    else:
        base = 0.65

    rank = safe_float(row.get("板块当日资金排名", 0), 0)
    if rank > 0:
        if rank <= 50:
            base += 0.2
        elif rank >= 300:
            base -= 0.2

    return round(max(0.0, min(1.0, base)), 6)


def pick_probability(row: pd.Series, calibrated_col: str, raw_col: str, default: float = 0.5) -> float:
    calibrated = safe_float(row.get(calibrated_col, None), -1)
    if calibrated >= 0:
        return calibrated
    return safe_float(row.get(raw_col, default), default)


def probability_component(p1: float, p2: float, p_stop: float) -> float:
    value = p1 * 0.55 + p2 * 0.25 + (1.0 - p_stop) * 0.20
    return round(max(0.0, min(1.0, value)), 6)


def final_action(row: pd.Series) -> str:
    grade = str(row.get("rule_grade", "")).upper()
    sector_status = str(row.get("sector_status", ""))
    score = safe_float(row.get("fusion_score", 0), 0)
    p1 = safe_float(row.get("hit_1pct_probability", 0.5), 0.5)
    p2 = safe_float(row.get("hit_2pct_probability", 0.5), 0.5)
    p_stop = safe_float(row.get("stop_2pct_probability", 0.5), 0.5)
    fixed = bool(row.get("is_fixed_holding", False))

    if fixed:
        if p_stop >= 0.58 or score < 32:
            return "止损"
        if grade == "D" or score < 46:
            return "减仓"
        if p2 >= 0.58 and p_stop <= 0.35:
            return "止盈"
        return "继续持有"

    if grade == "D" or "回避" in sector_status:
        return "放弃"
    if score >= 72 and p1 >= 0.55 and p_stop <= 0.42:
        return "优先低吸"
    if score >= 58 and p1 >= 0.50:
        return "小仓观察"
    if score >= 42:
        return "只观察"
    return "放弃"


def risk_reward_text(p1: float, p2: float, p_stop: float) -> str:
    expected_gain = p1 * 0.01 + p2 * 0.02
    expected_loss = max(p_stop * 0.02, 0.0001)
    ratio = expected_gain / expected_loss
    return f"{ratio:.2f}"


def explain_decision(row: pd.Series) -> str:
    action = str(row.get("final_action", ""))
    fixed = bool(row.get("is_fixed_holding", False))

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
    return fixed_text.get(action, action or "暂无操作。")


def build_base_universe(
    watchlist_df: pd.DataFrame,
    direction_df: pd.DataFrame,
    probability_df: pd.DataFrame,
    calibrated_df: pd.DataFrame,
) -> pd.DataFrame:
    watch = latest_by_code(watchlist_df)
    if watch.empty:
        watch = pd.DataFrame(columns=["stock_code_norm"])

    known_codes = set(watch.get("stock_code_norm", pd.Series(dtype=str)).dropna().astype(str))
    rows = []
    name_map = fixed_holding_name_map()

    for source in [direction_df, probability_df, calibrated_df]:
        latest = latest_by_code(source)
        if latest.empty:
            continue
        for _, item in latest.iterrows():
            code = normalize_code(item.get("stock_code_norm", ""))
            if not code or code in known_codes:
                continue
            rows.append({
                "股票代码": code,
                "股票名称": item.get("stock_name", name_map.get(code, "")),
                "确认日期": item.get("predict_date", ""),
                "隔夜建议等级": "",
                "最终评分": 0,
                "所属板块": item.get("sector_name", ""),
                "板块数据状态": "未知",
                "stock_code_norm": code,
            })
            known_codes.add(code)

    for code, name in name_map.items():
        if code not in known_codes:
            rows.append({
                "股票代码": code,
                "股票名称": name,
                "确认日期": "",
                "隔夜建议等级": "",
                "最终评分": 0,
                "所属板块": "",
                "板块数据状态": "未知",
                "stock_code_norm": code,
            })
            known_codes.add(code)

    if rows:
        watch = pd.concat([watch, pd.DataFrame(rows)], ignore_index=True)

    return watch


def build_final_decision_frame(
    watchlist_df: pd.DataFrame,
    direction_df: pd.DataFrame,
    probability_df: pd.DataFrame,
    calibrated_df: pd.DataFrame,
    scorecard_df: pd.DataFrame,
) -> pd.DataFrame:
    base = build_base_universe(watchlist_df, direction_df, probability_df, calibrated_df)
    if base.empty:
        return pd.DataFrame()

    direction = latest_by_code(direction_df).add_prefix("dir_")
    probability = latest_by_code(probability_df).add_prefix("prob_")
    calibrated = latest_by_code(calibrated_df).add_prefix("cal_")

    merged = base.copy()
    if not direction.empty:
        merged = merged.merge(direction, left_on="stock_code_norm", right_on="dir_stock_code_norm", how="left")
    if not probability.empty:
        merged = merged.merge(probability, left_on="stock_code_norm", right_on="prob_stock_code_norm", how="left")
    if not calibrated.empty:
        merged = merged.merge(calibrated, left_on="stock_code_norm", right_on="cal_stock_code_norm", how="left")

    quality = model_quality_score(scorecard_df)
    rows = []
    created_at = now_text()

    for _, row in merged.iterrows():
        code = normalize_code(row.get("stock_code_norm", ""))
        name = str(row.get("股票名称", "") or row.get("dir_stock_name", "") or row.get("prob_stock_name", ""))
        rule_grade = str(row.get("隔夜建议等级", "")).strip().upper()
        rule_score = safe_float(row.get("最终评分", 0), 0)
        rule_component = max(rule_grade_score(rule_grade), min(rule_score / 100.0, 1.0) * 0.8)
        direction_probability = safe_float(row.get("dir_next_day_up_probability", 0.5), 0.5)
        p1 = pick_probability(row, "cal_calibrated_hit_1pct_probability", "prob_hit_1pct_probability")
        p2 = pick_probability(row, "cal_calibrated_hit_2pct_probability", "prob_hit_2pct_probability")
        p_stop = pick_probability(row, "cal_calibrated_stop_2pct_probability", "prob_stop_2pct_probability")
        sector_component = sector_score(row)
        market_component = market_score(row.get("dir_market_regime", row.get("prob_market_regime", "")))
        probability_score = probability_component(p1, p2, p_stop)

        fusion = (
            rule_component * 0.35
            + direction_probability * 0.18
            + probability_score * 0.25
            + sector_component * 0.10
            + market_component * 0.07
            + quality * 0.05
        ) * 100

        if rule_grade == "D":
            fusion = min(fusion, 49.0)
        if "回避" in str(row.get("板块数据状态", "")):
            fusion = min(fusion, 56.0)

        output = {
            "decision_id": f"{MODEL_VERSION}_{code}_{row.get('确认日期', row.get('dir_predict_date', ''))}",
            "stock_code": code,
            "stock_name": name,
            "is_fixed_holding": is_fixed_holding(code),
            "predict_date": str(row.get("确认日期", "") or row.get("dir_predict_date", "") or row.get("prob_predict_date", ""))[:10],
            "rule_version": str(row.get("dir_rule_version", row.get("prob_rule_version", "v2.0"))),
            "rule_grade": rule_grade or "未评级",
            "rule_score": round(rule_score, 4),
            "next_day_up_probability": round(direction_probability, 6),
            "direction_confidence": round(safe_float(row.get("dir_direction_confidence", 0), 0), 6),
            "hit_1pct_probability": round(p1, 6),
            "hit_2pct_probability": round(p2, 6),
            "stop_2pct_probability": round(p_stop, 6),
            "sector_name": str(row.get("所属板块", "") or row.get("dir_sector_name", "") or row.get("prob_sector_name", "")),
            "sector_status": str(row.get("板块数据状态", "未知") or "未知"),
            "market_regime": str(row.get("dir_market_regime", row.get("prob_market_regime", ""))),
            "model_quality_score": quality,
            "fusion_score": round(fusion, 4),
            "risk_reward_ratio": risk_reward_text(p1, p2, p_stop),
            "created_at": created_at,
            "model_version": MODEL_VERSION,
        }
        output["final_action"] = final_action(pd.Series(output))
        output["decision_reason"] = explain_decision(pd.Series(output))
        rows.append(output)

    decision_df = pd.DataFrame(rows)
    decision_df = decision_df.sort_values(
        ["is_fixed_holding", "fusion_score", "hit_1pct_probability"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    return decision_df


def write_final_decision_report(decision_df: pd.DataFrame) -> None:
    FINAL_DECISION_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# v3.0 融合决策报告",
        "",
        f"生成时间：{now_text()}",
        f"融合版本：`{MODEL_VERSION}`",
        "",
        "## 一、决策摘要",
        "",
        f"- 决策股票数：{len(decision_df)}",
        f"- 固定持仓数：{int(decision_df['is_fixed_holding'].sum()) if not decision_df.empty else 0}",
        "",
        "| 操作 | 数量 |",
        "|---|---:|",
    ]

    if not decision_df.empty:
        for action, count in decision_df["final_action"].value_counts().items():
            lines.append(f"| {action} | {int(count)} |")

    def append_core_table(title: str, frame: pd.DataFrame) -> None:
        lines.extend([
            "",
            f"## {title}",
            "",
            "| 操作 | 股票 | 规则 | 关注分 | 一句话原因 |",
            "|---|---|---|---:|---|",
        ])

        if frame.empty:
            lines.append("| 无 | - | - | - | - |")
            return

        for _, row in frame.head(15).iterrows():
            lines.append(
                f"| {row['final_action']} | "
                f"{row['stock_name']} `{row['stock_code']}` | "
                f"{row['rule_grade']} | {safe_float(row['fusion_score']):.1f} | "
                f"{row['decision_reason']} |"
            )

    if decision_df.empty:
        fixed_df = pd.DataFrame()
        candidate_df = pd.DataFrame()
    else:
        fixed_df = decision_df[decision_df["is_fixed_holding"].astype(bool)].copy()
        candidate_df = decision_df[~decision_df["is_fixed_holding"].astype(bool)].copy()

    append_core_table("二、固定持仓处理", fixed_df)
    append_core_table("三、明日候选池", candidate_df)

    lines.extend([
        "",
        "## 四、模型依据明细",
        "",
        "| 股票 | 上涨概率 | +1%概率 | +2%概率 | 止损概率 | 风险收益比 |",
        "|---|---:|---:|---:|---:|---:|",
    ])

    for _, row in decision_df.head(30).iterrows():
        lines.append(
            f"| {row['stock_code']} {row['stock_name']} | "
            f"{safe_float(row['next_day_up_probability']):.1%} | "
            f"{safe_float(row['hit_1pct_probability']):.1%} | "
            f"{safe_float(row['hit_2pct_probability']):.1%} | "
            f"{safe_float(row['stop_2pct_probability']):.1%} | "
            f"{row['risk_reward_ratio']} |"
        )

    lines.extend([
        "",
        "## 五、融合原则",
        "",
        "- 规则等级决定能不能做，模型概率决定值不值得加大关注。",
        "- D 级不会因为模型概率高而升级为买入。",
        "- 板块为回避时，候选股只能进入观察或放弃，不给进攻动作。",
        "- 固定持仓使用持有/减仓/止盈/止损动作，不混入新开仓动作。",
    ])

    FINAL_DECISION_REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_decision_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS final_decision_v3 (
            decision_id TEXT PRIMARY KEY,
            stock_code TEXT,
            stock_name TEXT,
            is_fixed_holding INTEGER,
            predict_date TEXT,
            rule_version TEXT,
            rule_grade TEXT,
            rule_score REAL,
            next_day_up_probability REAL,
            direction_confidence REAL,
            hit_1pct_probability REAL,
            hit_2pct_probability REAL,
            stop_2pct_probability REAL,
            sector_name TEXT,
            sector_status TEXT,
            market_regime TEXT,
            model_quality_score REAL,
            fusion_score REAL,
            risk_reward_ratio TEXT,
            final_action TEXT,
            decision_reason TEXT,
            created_at TEXT,
            model_version TEXT
        )
    """)
    conn.commit()


def run_decision_fusion() -> dict[str, Any]:
    decision_df = build_final_decision_frame(
        read_csv(FINAL_WATCHLIST_FILE),
        read_csv(MODEL_PREDICTION_FILE),
        read_csv(PROFIT_PROBABILITY_FILE),
        read_csv(CALIBRATED_PROBABILITY_FILE),
        read_csv(MODEL_SCORECARD_FILE),
    )

    if decision_df.empty:
        raise RuntimeError("没有可融合的候选或模型预测，请先运行候选池和模型预测。")

    FINAL_DECISION_FILE.parent.mkdir(parents=True, exist_ok=True)
    decision_df.to_csv(FINAL_DECISION_FILE, index=False, encoding="utf-8-sig")
    write_final_decision_report(decision_df)

    with sqlite3.connect(DATABASE_FILE) as conn:
        ensure_decision_tables(conn)
        decision_df.to_sql("final_decision_v3", conn, if_exists="replace", index=False)

    print("v3.0 融合决策已生成。")
    print(f"决策明细：{FINAL_DECISION_FILE}")
    print(f"决策报告：{FINAL_DECISION_REPORT_FILE}")
    return {
        "rows": len(decision_df),
        "csv": str(FINAL_DECISION_FILE),
        "report": str(FINAL_DECISION_REPORT_FILE),
        "table": "final_decision_v3",
    }


if __name__ == "__main__":
    run_decision_fusion()
