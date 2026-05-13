# next_day_validator.py
# -*- coding: utf-8 -*-

"""
A股隔日T系统 v1.7.0：次日验证系统

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


INPUT_FILE = Path("output/final_watchlist.csv")
OUTPUT_REVIEW_CSV = Path("output/next_day_review.csv")
OUTPUT_REVIEW_MD = Path("output/next_day_review.md")
OUTPUT_FACTOR_CSV = Path("output/factor_performance.csv")
HISTORY_DIR = Path("history")


def safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def normalize_code(code) -> str:
    return str(code).zfill(6)


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

    hit_1pct = high_pct >= 1
    hit_2pct = high_pct >= 2
    stop_loss_hit = low_pct <= -2

    # 当前版本成功标准：
    # 1. 次日最高涨幅 >= 1%，代表有可T空间
    # 2. 且没有先跌破 -2%
    success = hit_1pct and not stop_loss_hit

    result = {
        "验证日期": datetime.now().strftime("%Y-%m-%d"),
        "股票代码": symbol,
        "股票名称": name,
        "热点标签": row.get("热点标签", ""),
        "分时结构标签": row.get("分时结构标签", ""),
        "尾盘抢筹标签": row.get("尾盘抢筹标签", ""),
        "隔夜建议等级": row.get("隔夜建议等级", ""),
        "候选评分": safe_float(row.get("候选评分", 0)),
        "尾盘评分": safe_float(row.get("尾盘评分", 0)),
        "最终评分": safe_float(row.get("最终评分", 0)),
        "买入参考价": round(buy_ref_price, 2),
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
    ).reset_index()

    summary["成功率"] = summary["成功数"] / summary["数量"] * 100
    summary["达到1%率"] = summary["达到1数量"] / summary["数量"] * 100
    summary["达到2%率"] = summary["达到2数量"] / summary["数量"] * 100
    summary["止损率"] = summary["止损数量"] / summary["数量"] * 100

    numeric_cols = [
        "成功率",
        "达到1%率",
        "达到2%率",
        "止损率",
        "平均最高涨幅",
        "平均收盘涨幅",
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

    md = f"""# 次日验证报告 v1.7.0

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

1. 次日最高涨幅达到 `1%`
2. 且没有触发 `-2%` 止损

后续可以根据实盘结果调整成功标准。
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

    watchlist = pd.read_csv(INPUT_FILE, dtype={"股票代码": str})

    if watchlist.empty:
        raise ValueError("final_watchlist.csv 为空，无法验证")

    watchlist["股票代码"] = watchlist["股票代码"].astype(str).str.zfill(6)

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