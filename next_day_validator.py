# next_day_validator.py
# -*- coding: utf-8 -*-

"""
A股隔日T系统 v2.0：次日验证系统

功能：
1. 读取 output/final_watchlist.csv
2. 使用 data_provider.get_stock_daily() 获取次日行情
3. 验证隔夜建议 A/B/C/D 是否有效
4. 输出：
   - output/next_day_review.csv
   - output/next_day_review.md
   - output/factor_performance.csv
5. 自动归档到 history/
"""

from pathlib import Path
from datetime import datetime

import pandas as pd

from data_provider import get_stock_daily
from common import normalize_code, safe_float
from contracts import FINAL_WATCHLIST_REQUIRED_COLUMNS, validate_csv_columns


INPUT_FILE = Path("output/final_watchlist.csv")
OUTPUT_REVIEW_CSV = Path("output/next_day_review.csv")
OUTPUT_REVIEW_MD = Path("output/next_day_review.md")
OUTPUT_FACTOR_CSV = Path("output/factor_performance.csv")
HISTORY_DIR = Path("history")


def standardize_daily_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    兼容中文/英文字段。
    """

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()

    rename_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交额": "amount",
        "成交量": "volume",
    }

    df = df.rename(columns=rename_map)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    for col in ["open", "close", "high", "low", "amount", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    required = ["date", "open", "high", "low", "close"]

    if any(col not in df.columns for col in required):
        return pd.DataFrame()

    df = df.dropna(subset=required)
    df = df.sort_values("date").reset_index(drop=True)

    return df


def get_plan_buy_range(row: pd.Series, reference_price: float) -> tuple[float, float]:
    ma5 = safe_float(row.get("MA5", 0))

    if ma5 > 0:
        return ma5 * 0.99, ma5 * 1.01

    return reference_price * 0.98, reference_price * 0.99


def classify_execution_result(
    *,
    touched_buy_range: bool,
    hit_1pct_after_plan_buy: bool,
    stop_loss_hit_after_plan_buy: bool,
) -> str:
    if not touched_buy_range:
        return "未给买点"

    if stop_loss_hit_after_plan_buy:
        return "风险触发"

    if hit_1pct_after_plan_buy:
        return "给买点且成功"

    return "给买点但失败"


def get_next_day_daily(symbol: str, confirm_date: str | None = None) -> pd.Series | None:
    """
    获取次日行情。

    如果传入 confirm_date：
    - 取日期大于 confirm_date 的第一根日线。
    如果没有 confirm_date：
    - 取最新一根日线。
    """

    try:
        daily_df = get_stock_daily(symbol)
        daily_df = standardize_daily_columns(daily_df)

        if daily_df.empty:
            print(f"{symbol} 日线为空")
            return None

        if confirm_date:
            confirm_dt = pd.to_datetime(confirm_date, errors="coerce")

            if pd.notna(confirm_dt):
                next_df = daily_df[daily_df["date"] > confirm_dt]

                if not next_df.empty:
                    return next_df.iloc[0]

        return daily_df.iloc[-1]

    except Exception as e:
        print(f"{symbol} 获取次日行情失败：{e}")
        return None


def calculate_review(row: pd.Series) -> dict | None:
    """
    计算单只股票次日验证结果。
    """

    symbol = normalize_code(row.get("股票代码", ""))
    name = str(row.get("股票名称", ""))

    buy_ref_price = safe_float(row.get("收盘价", row.get("最新收盘价", 0)))

    if buy_ref_price <= 0:
        print(f"{symbol} {name} 缺少有效收盘价，跳过")
        return None

    confirm_date = None
    if "确认日期" in row.index:
        confirm_date = str(row.get("确认日期", ""))

    next_day = get_next_day_daily(symbol, confirm_date=confirm_date)

    if next_day is None:
        return None

    next_open = safe_float(next_day.get("open"))
    next_high = safe_float(next_day.get("high"))
    next_low = safe_float(next_day.get("low"))
    next_close = safe_float(next_day.get("close"))
    next_date = next_day.get("date")

    if next_open <= 0 or next_high <= 0 or next_low <= 0 or next_close <= 0:
        return None

    open_pct = (next_open - buy_ref_price) / buy_ref_price * 100
    high_pct = (next_high - buy_ref_price) / buy_ref_price * 100
    low_pct = (next_low - buy_ref_price) / buy_ref_price * 100
    close_pct = (next_close - buy_ref_price) / buy_ref_price * 100

    plan_buy_low, plan_buy_high = get_plan_buy_range(row, buy_ref_price)
    plan_buy_price = plan_buy_high
    touched_buy_range = next_low <= plan_buy_high and next_high >= plan_buy_low
    plan_stop_loss_price = plan_buy_price * 0.98
    plan_target_1_price = plan_buy_price * 1.01
    plan_target_2_price = plan_buy_price * 1.02

    hit_1pct = next_high >= buy_ref_price * 1.01
    hit_2pct = next_high >= buy_ref_price * 1.02
    stop_loss_hit = next_low <= buy_ref_price * 0.98

    hit_1pct_after_plan_buy = touched_buy_range and next_high >= plan_target_1_price
    hit_2pct_after_plan_buy = touched_buy_range and next_high >= plan_target_2_price
    stop_loss_hit_after_plan_buy = touched_buy_range and next_low <= plan_stop_loss_price

    execution_result = classify_execution_result(
        touched_buy_range=touched_buy_range,
        hit_1pct_after_plan_buy=hit_1pct_after_plan_buy,
        stop_loss_hit_after_plan_buy=stop_loss_hit_after_plan_buy,
    )
    success = execution_result == "给买点且成功"

    result = {
        "验证日期": datetime.now().strftime("%Y-%m-%d"),
        "股票代码": symbol,
        "股票名称": name,
        "分时结构标签": row.get("分时结构标签", ""),
        "尾盘抢筹标签": row.get("尾盘抢筹标签", ""),
        "隔夜建议等级": row.get("隔夜建议等级", ""),
        "候选评分": safe_float(row.get("候选评分", 0)),
        "尾盘评分": safe_float(row.get("尾盘评分", 0)),
        "最终评分": safe_float(row.get("最终评分", 0)),
        "买入参考价": round(buy_ref_price, 2),
        "计划低吸下限": round(plan_buy_low, 2),
        "计划低吸上限": round(plan_buy_high, 2),
        "计划验证买入价": round(plan_buy_price, 2),
        "计划止损价": round(plan_stop_loss_price, 2),
        "次日日期": str(pd.to_datetime(next_date).date()) if pd.notna(next_date) else "",
        "次日开盘": round(next_open, 2),
        "次日最高": round(next_high, 2),
        "次日最低": round(next_low, 2),
        "次日收盘": round(next_close, 2),
        "次日开盘涨幅": round(open_pct, 2),
        "次日最高涨幅": round(high_pct, 2),
        "次日最低涨幅": round(low_pct, 2),
        "次日收盘涨幅": round(close_pct, 2),
        "是否达到1%": "是" if hit_1pct else "否",
        "是否达到2%": "是" if hit_2pct else "否",
        "是否触发-2%止损": "是" if stop_loss_hit else "否",
        "是否触达低吸区间": "是" if touched_buy_range else "否",
        "触达后是否达到1%": "是" if hit_1pct_after_plan_buy else "否",
        "触达后是否达到2%": "是" if hit_2pct_after_plan_buy else "否",
        "触达后是否触发-2%止损": "是" if stop_loss_hit_after_plan_buy else "否",
        "执行验证结果": execution_result,
        "时序判断": "日线OHLC无法确认高低点先后，按计划买入价做保守验证。",
        "是否验证成功": "是" if success else "否",
    }

    return result


def summarize_by_column(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """
    按指定字段统计表现。
    """

    if df.empty or col not in df.columns:
        return pd.DataFrame()

    temp = df.copy()

    temp["成功数"] = temp["是否验证成功"].eq("是").astype(int)
    temp["达到1%数"] = temp["是否达到1%"].eq("是").astype(int)
    temp["达到2%数"] = temp["是否达到2%"].eq("是").astype(int)
    temp["止损数"] = temp["是否触发-2%止损"].eq("是").astype(int)

    summary = temp.groupby(col).agg(
        数量=("股票代码", "count"),
        成功数=("成功数", "sum"),
        达到1数量=("达到1%数", "sum"),
        达到2数量=("达到2%数", "sum"),
        止损数量=("止损数", "sum"),
        平均最高涨幅=("次日最高涨幅", "mean"),
        平均收盘涨幅=("次日收盘涨幅", "mean"),
        触达低吸数量=("是否触达低吸区间", lambda s: s.astype(str).eq("是").sum()),
    ).reset_index()

    summary["成功率"] = summary["成功数"] / summary["数量"] * 100
    summary["达到1%率"] = summary["达到1数量"] / summary["数量"] * 100
    summary["达到2%率"] = summary["达到2数量"] / summary["数量"] * 100
    summary["止损率"] = summary["止损数量"] / summary["数量"] * 100
    summary["触达低吸率"] = summary["触达低吸数量"] / summary["数量"] * 100

    numeric_cols = [
        "成功率",
        "达到1%率",
        "达到2%率",
        "止损率",
        "平均最高涨幅",
        "平均收盘涨幅",
        "触达低吸率",
    ]

    for c in numeric_cols:
        summary[c] = summary[c].round(2)

    return summary


def build_markdown(review_df: pd.DataFrame, grade_summary: pd.DataFrame, structure_summary: pd.DataFrame) -> str:
    """
    生成 Markdown 复盘报告。
    """

    today = datetime.now().strftime("%Y-%m-%d")

    total = len(review_df)
    success_count = review_df["是否验证成功"].eq("是").sum()
    hit_1_count = review_df["是否达到1%"].eq("是").sum()
    hit_2_count = review_df["是否达到2%"].eq("是").sum()
    stop_count = review_df["是否触发-2%止损"].eq("是").sum()

    success_rate = success_count / total * 100 if total else 0
    hit_1_rate = hit_1_count / total * 100 if total else 0
    hit_2_rate = hit_2_count / total * 100 if total else 0
    stop_rate = stop_count / total * 100 if total else 0

    md = f"""# 次日验证报告 v2.0

生成日期：{today}

数据来源：`output/final_watchlist.csv`

---

## 一、总体表现

| 指标 | 数值 |
| --- | --- |
| 验证股票数 | {total} |
| 成功数 | {success_count} |
| 成功率 | {success_rate:.2f}% |
| 达到1%数量 | {hit_1_count} |
| 达到1%率 | {hit_1_rate:.2f}% |
| 达到2%数量 | {hit_2_count} |
| 达到2%率 | {hit_2_rate:.2f}% |
| 触发-2%止损数量 | {stop_count} |
| 止损率 | {stop_rate:.2f}% |

---

## 二、按隔夜建议等级统计

{grade_summary.to_markdown(index=False) if not grade_summary.empty else "无。"}

---

## 三、按分时结构标签统计

{structure_summary.to_markdown(index=False) if not structure_summary.empty else "无。"}

---

## 四、明细

{review_df.to_markdown(index=False)}

---

## 五、解释

当前成功标准：

1. 次日行情触达计划低吸区间
2. 按计划低吸上限作为保守买入价后，盘中最高达到 `1%`
3. 触达后未按该计划买入价触发 `-2%` 止损

说明：日线 OHLC 无法确认高低点发生先后，本报告只验证“计划是否给到可执行价格”和“给买点后的保守收益/风险空间”，真实执行结果仍需结合成交记录。
"""

    return md


def archive_outputs() -> None:
    """
    归档输出文件到 history/YYYY-MM-DD/
    """

    today = datetime.now().strftime("%Y-%m-%d")
    archive_dir = HISTORY_DIR / today
    archive_dir.mkdir(parents=True, exist_ok=True)

    for file_path in [
        OUTPUT_REVIEW_CSV,
        OUTPUT_REVIEW_MD,
        OUTPUT_FACTOR_CSV,
        INPUT_FILE,
    ]:
        if file_path.exists():
            target = archive_dir / file_path.name
            target.write_bytes(file_path.read_bytes())


def run_next_day_validation() -> None:
    """
    主流程。
    """

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"找不到尾盘确认文件：{INPUT_FILE}")

    watchlist = validate_csv_columns(
        INPUT_FILE,
        FINAL_WATCHLIST_REQUIRED_COLUMNS,
        "final_watchlist.csv",
    )

    watchlist["股票代码"] = watchlist["股票代码"].apply(normalize_code)

    results = []
    failed = []

    print(f"开始次日验证，股票数量：{len(watchlist)}")

    for i, row in enumerate(watchlist.itertuples(index=False), start=1):
        row_dict = row._asdict()
        symbol = normalize_code(row_dict.get("股票代码"))
        name = str(row_dict.get("股票名称", ""))

        print(f"正在验证 {i}/{len(watchlist)}：{symbol} {name}")

        result = calculate_review(pd.Series(row_dict))

        if result is None:
            failed.append(symbol)
            continue

        results.append(result)

    review_df = pd.DataFrame(results)

    if review_df.empty:
        print("没有成功生成验证结果。")
        return

    grade_summary = summarize_by_column(review_df, "隔夜建议等级")
    structure_summary = summarize_by_column(review_df, "分时结构标签")
    tail_tag_summary = summarize_by_column(review_df, "尾盘抢筹标签")

    OUTPUT_REVIEW_CSV.parent.mkdir(parents=True, exist_ok=True)

    review_df.to_csv(
        OUTPUT_REVIEW_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    factor_rows = []

    if not grade_summary.empty:
        temp = grade_summary.copy()
        temp["因子类型"] = "隔夜建议等级"
        temp = temp.rename(columns={"隔夜建议等级": "因子值"})
        factor_rows.append(temp)

    if not structure_summary.empty:
        temp = structure_summary.copy()
        temp["因子类型"] = "分时结构标签"
        temp = temp.rename(columns={"分时结构标签": "因子值"})
        factor_rows.append(temp)

    if not tail_tag_summary.empty:
        temp = tail_tag_summary.copy()
        temp["因子类型"] = "尾盘抢筹标签"
        temp = temp.rename(columns={"尾盘抢筹标签": "因子值"})
        factor_rows.append(temp)

    factor_df = pd.concat(factor_rows, ignore_index=True) if factor_rows else pd.DataFrame()

    factor_df.to_csv(
        OUTPUT_FACTOR_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    md = build_markdown(review_df, grade_summary, structure_summary)
    OUTPUT_REVIEW_MD.write_text(md, encoding="utf-8")

    archive_outputs()

    print("\n次日验证完成。")
    print(f"明细CSV：{OUTPUT_REVIEW_CSV}")
    print(f"复盘报告：{OUTPUT_REVIEW_MD}")
    print(f"因子表现：{OUTPUT_FACTOR_CSV}")
    print(f"成功数量：{len(review_df)}")
    print(f"失败数量：{len(failed)}")

    if failed:
        print(f"失败股票：{failed}")

    print("\n按隔夜等级统计：")
    print(grade_summary)


if __name__ == "__main__":
    run_next_day_validation()
