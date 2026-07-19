# lunch_validator.py
# -*- coding: utf-8 -*-

"""
A股隔日T系统 v2.0：午盘验证系统

新增：
1. 上午最大回撤
2. 冲高保持率
3. 回撤风险等级
4. 冲高质量标签

目的：
区分“真强”和“假强”：
- 真强：上午冲高后还能横住
- 假强：上午冲高后午盘大幅回落
"""

from pathlib import Path
from datetime import datetime

import pandas as pd

from data_provider import get_stock_minute
from common import normalize_code, safe_float
from contracts import FINAL_WATCHLIST_REQUIRED_COLUMNS, validate_csv_columns
from fixed_holdings import enrich_watchlist_with_fixed_holdings


INPUT_FILE = Path("output/final_watchlist.csv")
OUTPUT_CSV = Path("output/lunch_review.csv")
OUTPUT_MD = Path("output/lunch_review.md")


CONFIG = {
    "include_grades": ["A", "B", "C"],
    "take_profit_1": 1.0,
    "take_profit_2": 2.0,
    "stop_loss": -2.0,
    "strong_close_position": 0.65,
    "weak_close_position": 0.35,
    "strong_drawdown_threshold": 1.5,
    "normal_drawdown_threshold": 3.0,
    "true_strength_keep_ratio": 60.0,
    "normal_keep_ratio": 30.0,
}


def standardize_minute_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()

    rename_map = {
        "时间": "datetime",
        "日期": "datetime",
        "day": "datetime",
        "date": "datetime",
        "成交时间": "datetime",
        "开盘": "open",
        "开盘价": "open",
        "最高": "high",
        "最高价": "high",
        "最低": "low",
        "最低价": "low",
        "收盘": "close",
        "收盘价": "close",
        "最新价": "close",
        "成交量": "volume",
        "成交额": "amount",
    }

    df = df.rename(columns=rename_map)

    if "datetime" not in df.columns:
        return pd.DataFrame()

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")

    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    required = ["datetime", "open", "high", "low", "close"]

    if any(col not in df.columns for col in required):
        return pd.DataFrame()

    df = df.dropna(subset=required)
    df = df.sort_values("datetime").reset_index(drop=True)

    if "amount" not in df.columns:
        df["amount"] = 0.0

    return df


def get_today_morning_data(symbol: str) -> pd.DataFrame:
    minute_df = get_stock_minute(symbol)
    minute_df = standardize_minute_columns(minute_df)

    if minute_df.empty:
        return pd.DataFrame()

    latest_date = minute_df["datetime"].dt.date.max()
    today_df = minute_df[minute_df["datetime"].dt.date == latest_date].copy()

    morning_df = today_df[
        (today_df["datetime"].dt.time >= pd.to_datetime("09:30").time())
        & (today_df["datetime"].dt.time <= pd.to_datetime("11:30").time())
    ].copy()

    return morning_df.sort_values("datetime").reset_index(drop=True)


def calculate_drawdown_metrics(high_pct: float, lunch_pct: float) -> dict:
    """
    计算冲高后的回撤质量。
    """

    morning_drawdown = high_pct - lunch_pct

    if high_pct > 0:
        keep_ratio = lunch_pct / high_pct * 100
    else:
        keep_ratio = 0.0

    if morning_drawdown < CONFIG["strong_drawdown_threshold"]:
        drawdown_level = "强承接"
    elif morning_drawdown <= CONFIG["normal_drawdown_threshold"]:
        drawdown_level = "普通"
    else:
        drawdown_level = "高回撤风险"

    if high_pct <= 0:
        strength_tag = "无冲高"
    elif keep_ratio >= CONFIG["true_strength_keep_ratio"]:
        strength_tag = "真强"
    elif keep_ratio >= CONFIG["normal_keep_ratio"]:
        strength_tag = "一般"
    else:
        strength_tag = "假强"

    return {
        "上午最大回撤": round(morning_drawdown, 2),
        "冲高保持率": round(keep_ratio, 2),
        "回撤风险等级": drawdown_level,
        "冲高质量标签": strength_tag,
    }


def classify_morning_structure(
    open_pct: float,
    high_pct: float,
    low_pct: float,
    lunch_pct: float,
    lunch_position: float,
    drawdown_level: str,
    strength_tag: str,
) -> str:
    if high_pct >= 2 and strength_tag == "真强":
        return "上午强势兑现型"

    if high_pct >= 2 and drawdown_level == "高回撤风险":
        return "上午冲高回落型"

    if low_pct <= -2 and lunch_position >= 0.5:
        return "上午急跌修复型"

    if lunch_pct <= -1.5 and lunch_position <= CONFIG["weak_close_position"]:
        return "上午弱势阴跌型"

    return "上午震荡型"


def get_afternoon_advice(
    hit_1: bool,
    hit_2: bool,
    stop_loss_hit: bool,
    structure: str,
    lunch_position: float,
    drawdown_level: str,
    strength_tag: str,
) -> str:
    if stop_loss_hit:
        return "上午已触发-2%风险，下午放弃。"

    if drawdown_level == "高回撤风险" and strength_tag == "假强":
        return "上午冲高后大幅回落，属于假强，下午放弃。"

    if hit_2 and strength_tag == "真强":
        return "上午达到2%且保持较好，下午继续观察，尾盘再确认。"

    if hit_2:
        return "上午达到2%止盈空间，但承接一般，下午不追，优先看是否已兑现。"

    if hit_1 and structure in ["上午强势兑现型", "上午冲高回落型"]:
        return "上午达到1%套利空间，下午不追，等尾盘确认。"

    if structure == "上午急跌修复型":
        return "上午急跌后有修复，下午继续观察，等尾盘确认。"

    if structure == "上午弱势阴跌型":
        return "上午弱势阴跌，下午放弃。"

    if lunch_position >= CONFIG["strong_close_position"] and strength_tag in ["真强", "一般"]:
        return "午盘位置较强，下午继续观察。"

    return "上午结构一般，下午只低吸不追高。"


def calculate_lunch_review(row: pd.Series) -> dict | None:
    symbol = normalize_code(row.get("股票代码", ""))
    name = str(row.get("股票名称", ""))
    fixed_flag = str(row.get("固定持仓", "否"))
    fixed_reason = str(row.get("置顶原因", ""))
    refresh_status = str(row.get("行情刷新状态", ""))

    reference_price = safe_float(row.get("收盘价", row.get("最新收盘价", 0)))

    if reference_price <= 0:
        if fixed_flag == "是":
            return {
                "验证时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "股票代码": symbol,
                "股票名称": name,
                "固定持仓": fixed_flag,
                "置顶原因": fixed_reason,
                "行情刷新状态": refresh_status or "参考价为空",
                "隔夜建议等级": row.get("隔夜建议等级", "持仓"),
                "分时结构标签": row.get("分时结构标签", ""),
                "尾盘抢筹标签": row.get("尾盘抢筹标签", ""),
                "最终评分": safe_float(row.get("最终评分", 0)),
                "隔夜参考价": 0,
                "今日开盘": 0,
                "上午最高": 0,
                "上午最低": 0,
                "午盘价": 0,
                "上午成交额": 0,
                "开盘涨幅": 0,
                "上午最高涨幅": 0,
                "上午最低涨幅": 0,
                "午盘涨幅": 0,
                "午盘位置": 0,
                "是否达到1%": "否",
                "是否达到2%": "否",
                "是否触发-2%止损": "否",
                "上午结构标签": "待刷新",
                "下午操作建议": "固定持仓已置顶，但参考价为空；请刷新日线/分钟行情。",
                "上午最大回撤": 0,
                "冲高保持率": 0,
                "回撤风险等级": "待刷新",
                "冲高质量标签": "待刷新",
            }
        print(f"{symbol} {name} 缺少参考价，跳过")
        return None

    morning_df = get_today_morning_data(symbol)

    if morning_df.empty:
        if fixed_flag == "是":
            return {
                "验证时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "股票代码": symbol,
                "股票名称": name,
                "固定持仓": fixed_flag,
                "置顶原因": fixed_reason,
                "行情刷新状态": refresh_status or "上午分钟数据为空",
                "隔夜建议等级": row.get("隔夜建议等级", "持仓"),
                "分时结构标签": row.get("分时结构标签", ""),
                "尾盘抢筹标签": row.get("尾盘抢筹标签", ""),
                "最终评分": safe_float(row.get("最终评分", 0)),
                "隔夜参考价": round(reference_price, 2),
                "今日开盘": 0,
                "上午最高": 0,
                "上午最低": 0,
                "午盘价": 0,
                "上午成交额": 0,
                "开盘涨幅": 0,
                "上午最高涨幅": 0,
                "上午最低涨幅": 0,
                "午盘涨幅": 0,
                "午盘位置": 0,
                "是否达到1%": "否",
                "是否达到2%": "否",
                "是否触发-2%止损": "否",
                "上午结构标签": "待刷新",
                "下午操作建议": "固定持仓已置顶，但上午分钟数据为空；请稍后刷新或检查行情源。",
                "上午最大回撤": 0,
                "冲高保持率": 0,
                "回撤风险等级": "待刷新",
                "冲高质量标签": "待刷新",
            }
        print(f"{symbol} {name} 上午分钟数据为空，跳过")
        return None

    open_price = safe_float(morning_df["open"].iloc[0])
    morning_high = safe_float(morning_df["high"].max())
    morning_low = safe_float(morning_df["low"].min())
    lunch_price = safe_float(morning_df["close"].iloc[-1])
    morning_amount = safe_float(morning_df["amount"].sum())

    open_pct = (open_price - reference_price) / reference_price * 100
    high_pct = (morning_high - reference_price) / reference_price * 100
    low_pct = (morning_low - reference_price) / reference_price * 100
    lunch_pct = (lunch_price - reference_price) / reference_price * 100

    if morning_high > morning_low:
        lunch_position = (lunch_price - morning_low) / (morning_high - morning_low)
    else:
        lunch_position = 0

    hit_1 = high_pct >= CONFIG["take_profit_1"]
    hit_2 = high_pct >= CONFIG["take_profit_2"]
    stop_loss_hit = low_pct <= CONFIG["stop_loss"]

    drawdown_metrics = calculate_drawdown_metrics(
        high_pct=high_pct,
        lunch_pct=lunch_pct,
    )

    structure = classify_morning_structure(
        open_pct=open_pct,
        high_pct=high_pct,
        low_pct=low_pct,
        lunch_pct=lunch_pct,
        lunch_position=lunch_position,
        drawdown_level=drawdown_metrics["回撤风险等级"],
        strength_tag=drawdown_metrics["冲高质量标签"],
    )

    advice = get_afternoon_advice(
        hit_1=hit_1,
        hit_2=hit_2,
        stop_loss_hit=stop_loss_hit,
        structure=structure,
        lunch_position=lunch_position,
        drawdown_level=drawdown_metrics["回撤风险等级"],
        strength_tag=drawdown_metrics["冲高质量标签"],
    )

    result = {
        "验证时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "股票代码": symbol,
        "股票名称": name,
        "固定持仓": fixed_flag,
        "置顶原因": fixed_reason,
        "行情刷新状态": refresh_status or "上午分钟已刷新",
        "隔夜建议等级": row.get("隔夜建议等级", ""),
        "分时结构标签": row.get("分时结构标签", ""),
        "尾盘抢筹标签": row.get("尾盘抢筹标签", ""),
        "最终评分": safe_float(row.get("最终评分", 0)),
        "隔夜参考价": round(reference_price, 2),
        "今日开盘": round(open_price, 2),
        "上午最高": round(morning_high, 2),
        "上午最低": round(morning_low, 2),
        "午盘价": round(lunch_price, 2),
        "上午成交额": round(morning_amount, 2),
        "开盘涨幅": round(open_pct, 2),
        "上午最高涨幅": round(high_pct, 2),
        "上午最低涨幅": round(low_pct, 2),
        "午盘涨幅": round(lunch_pct, 2),
        "午盘位置": round(lunch_position, 4),
        "是否达到1%": "是" if hit_1 else "否",
        "是否达到2%": "是" if hit_2 else "否",
        "是否触发-2%止损": "是" if stop_loss_hit else "否",
        "上午结构标签": structure,
        "下午操作建议": advice,
    }

    result.update(drawdown_metrics)

    return result


def build_markdown(review_df: pd.DataFrame) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total = len(review_df)
    hit_1_count = review_df["是否达到1%"].eq("是").sum()
    hit_2_count = review_df["是否达到2%"].eq("是").sum()
    stop_count = review_df["是否触发-2%止损"].eq("是").sum()

    md = f"""# 午盘验证报告 v2.0

生成时间：{now}

数据来源：`output/final_watchlist.csv`

---

## 一、总体情况

| 指标 | 数值 |
| --- | --- |
| 验证股票数 | {total} |
| 上午达到1%数量 | {hit_1_count} |
| 上午达到2%数量 | {hit_2_count} |
| 上午触发-2%止损数量 | {stop_count} |

---

## 二、上午结构分布

{review_df["上午结构标签"].value_counts().to_frame("数量").to_markdown()}

---

## 三、回撤风险分布

{review_df["回撤风险等级"].value_counts().to_frame("数量").to_markdown()}

---

## 四、冲高质量分布

{review_df["冲高质量标签"].value_counts().to_frame("数量").to_markdown()}

---

## 五、明细

{review_df.to_markdown(index=False)}

---

## 六、使用规则

1. 上午达到2%不等于强，必须看冲高保持率。
2. 冲高保持率高，说明资金承接好。
3. 上午最大回撤过大，说明是假强。
4. 高回撤风险 + 假强：下午放弃。
5. 真强 + 午盘位置高：下午继续观察，尾盘再确认。
"""

    return md


def run_lunch_validation() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"找不到尾盘确认文件：{INPUT_FILE}")

    watchlist = validate_csv_columns(
        INPUT_FILE,
        FINAL_WATCHLIST_REQUIRED_COLUMNS,
        "final_watchlist.csv",
    )

    watchlist["股票代码"] = watchlist["股票代码"].apply(normalize_code)
    watchlist = enrich_watchlist_with_fixed_holdings(watchlist, include_grades=CONFIG["include_grades"])

    results = []
    failed = []

    print(f"开始午盘验证，股票数量：{len(watchlist)}")

    for i, row in enumerate(watchlist.itertuples(index=False), start=1):
        row_dict = row._asdict()
        symbol = normalize_code(row_dict.get("股票代码"))
        name = str(row_dict.get("股票名称", ""))

        print(f"正在验证 {i}/{len(watchlist)}：{symbol} {name}")

        result = calculate_lunch_review(pd.Series(row_dict))

        if result is None:
            failed.append(symbol)
            continue

        results.append(result)

    review_df = pd.DataFrame(results)

    if review_df.empty:
        print("没有成功生成午盘验证结果。")
        return

    review_df = review_df.sort_values(
        by=["固定持仓", "隔夜建议等级", "最终评分"],
        ascending=[False, True, False],
    ).reset_index(drop=True)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    review_df.to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    OUTPUT_MD.write_text(build_markdown(review_df), encoding="utf-8")

    print("\n午盘验证完成。")
    print(f"CSV：{OUTPUT_CSV}")
    print(f"Markdown：{OUTPUT_MD}")
    print(f"成功数量：{len(review_df)}")
    print(f"失败数量：{len(failed)}")

    if failed:
        print(f"失败股票：{failed}")

    print("\n上午结构分布：")
    print(review_df["上午结构标签"].value_counts())

    print("\n回撤风险分布：")
    print(review_df["回撤风险等级"].value_counts())

    print("\n冲高质量分布：")
    print(review_df["冲高质量标签"].value_counts())


if __name__ == "__main__":
    run_lunch_validation()
