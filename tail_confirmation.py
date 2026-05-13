# tail_confirmation.py
# -*- coding: utf-8 -*-

"""
v1.5-tail-confirm：尾盘隔夜确认系统

功能：
1. 读取 output/overnight_t_candidates.csv
2. 自动调用 data_provider.get_stock_daily()
3. 自动调用 data_provider.get_stock_minute()
4. 自动计算尾盘确认字段
5. 输出：
   - output/final_watchlist.csv
   - output/final_watchlist.md
"""

from pathlib import Path
from datetime import datetime

import pandas as pd

from data_provider import get_stock_daily, get_stock_minute


INPUT_FILE = Path("output/overnight_t_candidates.csv")
OUTPUT_CSV = Path("output/final_watchlist.csv")
OUTPUT_MD = Path("output/final_watchlist.md")

TOP_N = 20


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

    for col in ["open", "close", "high", "low", "amount", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def standardize_minute_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    兼容新浪/AKShare不同分钟字段。
    目标字段：
    datetime, open, high, low, close, volume, amount
    """

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
        # 如果没有时间列，直接返回空，避免误判
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


def get_previous_close(symbol: str, fallback_close: float = 0.0) -> float:
    """
    获取昨收。
    优先日线倒数第2根。
    如果失败，用候选池里的最新收盘价兜底。
    """

    try:
        daily_df = get_stock_daily(symbol)
        daily_df = standardize_daily_columns(daily_df)

        if daily_df.empty or "close" not in daily_df.columns:
            return fallback_close

        daily_df = daily_df.dropna(subset=["close"])

        if len(daily_df) >= 2:
            return float(daily_df["close"].iloc[-2])

        if len(daily_df) == 1:
            return float(daily_df["close"].iloc[-1])

        return fallback_close

    except Exception as e:
        print(f"{symbol} 获取昨收失败，使用兜底值，原因：{e}")
        return fallback_close


def get_intraday_base_fields(symbol: str, fallback_close: float = 0.0) -> dict | None:
    """
    自动获取并计算：
    昨收、今日开盘、上午最高、上午最低、午盘价、今日最高、今日最低、收盘价、今日成交额
    """

    symbol = normalize_code(symbol)

    prev_close = get_previous_close(symbol, fallback_close=fallback_close)

    try:
        minute_df = get_stock_minute(symbol)
        minute_df = standardize_minute_columns(minute_df)

        if minute_df.empty:
            print(f"{symbol} 分钟数据为空")
            return None

        # 只取最新交易日
        latest_date = minute_df["datetime"].dt.date.max()
        today_df = minute_df[minute_df["datetime"].dt.date == latest_date].copy()

        if today_df.empty:
            print(f"{symbol} 今日分钟数据为空")
            return None

        today_df = today_df.sort_values("datetime").reset_index(drop=True)

        morning_df = today_df[
            (today_df["datetime"].dt.time >= pd.to_datetime("09:30").time())
            & (today_df["datetime"].dt.time <= pd.to_datetime("11:30").time())
        ].copy()

        if morning_df.empty:
            morning_df = today_df.copy()

        open_price = float(today_df["open"].iloc[0])
        morning_high = float(morning_df["high"].max())
        morning_low = float(morning_df["low"].min())
        noon_price = float(morning_df["close"].iloc[-1])

        today_high = float(today_df["high"].max())
        today_low = float(today_df["low"].min())
        close_price = float(today_df["close"].iloc[-1])

        amount = 0.0
        if "amount" in today_df.columns:
            amount = float(today_df["amount"].sum())

        return {
            "昨收": round(prev_close, 2),
            "今日开盘": round(open_price, 2),
            "上午最高": round(morning_high, 2),
            "上午最低": round(morning_low, 2),
            "午盘价": round(noon_price, 2),
            "今日最高": round(today_high, 2),
            "今日最低": round(today_low, 2),
            "收盘价": round(close_price, 2),
            "今日成交额": round(amount, 2),
        }

    except Exception as e:
        print(f"{symbol} 获取分钟数据失败：{e}")
        return None


def calculate_tail_metrics(row: dict) -> dict:
    """
    计算尾盘确认指标。
    """

    prev_close = safe_float(row.get("昨收"))
    morning_high = safe_float(row.get("上午最高"))
    noon_price = safe_float(row.get("午盘价"))
    today_high = safe_float(row.get("今日最高"))
    today_low = safe_float(row.get("今日最低"))
    close_price = safe_float(row.get("收盘价"))

    if prev_close <= 0 or today_high <= today_low:
        close_position = 0
        today_pct = 0
        today_amp = 0
        repair_from_low = 0
        pullback_from_high = 0
    else:
        today_pct = (close_price - prev_close) / prev_close * 100
        today_amp = (today_high - today_low) / prev_close * 100
        close_position = (close_price - today_low) / (today_high - today_low)
        repair_from_low = (close_price - today_low) / today_low * 100 if today_low > 0 else 0
        pullback_from_high = (today_high - close_price) / today_high * 100 if today_high > 0 else 0

    break_morning_high = close_price > morning_high
    close_high_area = close_position >= 0.75

    row.update({
        "今日涨跌幅": round(today_pct, 2),
        "今日振幅": round(today_amp, 2),
        "收盘位置": round(close_position, 4),
        "从低点修复幅度": round(repair_from_low, 2),
        "从高点回落幅度": round(pullback_from_high, 2),
        "是否突破上午高点": "是" if break_morning_high else "否",
        "是否收在全天高位区": "是" if close_high_area else "否",
    })

    return row


def classify_intraday_structure(row: dict) -> str:
    """
    分时结构标签。
    """

    prev_close = safe_float(row.get("昨收"))
    morning_high = safe_float(row.get("上午最高"))
    noon_price = safe_float(row.get("午盘价"))
    today_low = safe_float(row.get("今日最低"))
    today_pct = safe_float(row.get("今日涨跌幅"))
    today_amp = safe_float(row.get("今日振幅"))
    close_position = safe_float(row.get("收盘位置"))
    repair_from_low = safe_float(row.get("从低点修复幅度"))

    if prev_close <= 0:
        return "数据不足"

    # 冲高回落再转强型：环旭电子这类
    if (
        morning_high > prev_close * 1.015
        and noon_price < morning_high * 0.985
        and close_position >= 0.75
    ):
        return "冲高回落再转强型"

    # 急跌修复成功型
    if (
        today_low < prev_close * 0.98
        and repair_from_low >= 2
        and close_position >= 0.6
    ):
        return "急跌修复成功型"

    # 急跌修复失败型：潍柴这类弱修复失败
    if (
        today_low < prev_close * 0.98
        and close_position < 0.5
    ):
        return "急跌修复失败型"

    # 全天阴跌型
    if today_pct < -1.5 and close_position < 0.4:
        return "全天阴跌型"

    # 强势横盘型
    if today_pct >= 0 and close_position >= 0.6 and today_amp <= 6:
        return "强势横盘型"

    # 高波动震荡型
    if today_amp > 5 and 0.4 <= close_position <= 0.6:
        return "高波动震荡型"

    if close_position >= 0.75:
        return "尾盘资金回流型"

    if close_position < 0.4:
        return "弱势收盘型"

    return "普通震荡型"


def get_overnight_grade(row: dict) -> str:
    """
    隔夜建议等级。
    """

    structure = str(row.get("分时结构标签", ""))
    today_pct = safe_float(row.get("今日涨跌幅"))
    close_position = safe_float(row.get("收盘位置"))

    if structure == "冲高回落再转强型":
        return "A"

    if close_position >= 0.75 and today_pct > 0:
        return "A"

    if structure in ["急跌修复成功型", "强势横盘型", "尾盘资金回流型"] and close_position >= 0.6:
        return "B"

    if 0.4 <= close_position < 0.6:
        return "C"

    if structure in ["全天阴跌型", "急跌修复失败型", "弱势收盘型"]:
        return "D"

    if close_position < 0.4:
        return "D"

    return "C"


def get_overnight_advice(row: dict) -> str:
    """
    隔夜建议说明。
    """

    grade = row.get("隔夜建议等级", "C")
    structure = row.get("分时结构标签", "")
    close_position = safe_float(row.get("收盘位置"))
    today_pct = safe_float(row.get("今日涨跌幅"))

    if grade == "A":
        return f"尾盘强，结构为【{structure}】，收盘位置 {close_position:.2f}，可作为隔夜优先观察。"

    if grade == "B":
        return f"结构尚可，属于【{structure}】，可观察但不追高，需控制仓位。"

    if grade == "C":
        return f"结构一般，属于【{structure}】，只观察，不作为主动隔夜首选。"

    return f"结构偏弱，属于【{structure}】，不建议隔夜。"


def build_markdown(df: pd.DataFrame) -> str:
    today = datetime.now().strftime("%Y-%m-%d")

    def table_by_grade(title: str, grade: str) -> str:
        sub = df[df["隔夜建议等级"] == grade].copy()

        if sub.empty:
            return f"## {title}\n\n无。\n"

        cols = [
            "股票代码",
            "股票名称",
            "热点标签",
            "综合评分",
            "收盘价",
            "今日涨跌幅",
            "今日振幅",
            "收盘位置",
            "分时结构标签",
            "隔夜建议说明",
        ]

        existing_cols = [col for col in cols if col in sub.columns]
        return f"## {title}\n\n" + sub[existing_cols].to_markdown(index=False) + "\n"

    md = f"""# 尾盘隔夜确认报告 v1.5

生成日期：{today}

数据来源：
- `output/overnight_t_candidates.csv`
- `data_provider.get_stock_daily()`
- `data_provider.get_stock_minute()`

---

{table_by_grade("一、隔夜优先：A", "A")}

---

{table_by_grade("二、可观察：B", "B")}

---

{table_by_grade("三、只观察：C", "C")}

---

{table_by_grade("四、放弃：D", "D")}

---

## 五、使用规则

1. A 级：可作为隔夜优先观察，但仍需结合仓位和风险控制。
2. B 级：只低吸，不追高。
3. C 级：只观察，不主动买。
4. D 级：放弃，不参与隔夜。
5. 本模块只做尾盘确认，不替代人工判断。
"""

    return md


def run_tail_confirmation(top_n: int = TOP_N):
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"找不到候选池文件：{INPUT_FILE}")

    candidates = pd.read_csv(INPUT_FILE, dtype={"股票代码": str})

    if candidates.empty:
        raise ValueError("候选池为空，无法进行尾盘确认")

    candidates["股票代码"] = candidates["股票代码"].astype(str).str.zfill(6)

    if "综合评分" in candidates.columns:
        candidates["综合评分"] = pd.to_numeric(candidates["综合评分"], errors="coerce")
        candidates = candidates.sort_values("综合评分", ascending=False)

    candidates = candidates.head(top_n).copy()

    results = []
    failed = []

    print(f"开始尾盘确认，处理前 {len(candidates)} 只候选股。")

    for i, row in enumerate(candidates.itertuples(index=False), start=1):
        row_dict = row._asdict()

        symbol = normalize_code(row_dict.get("股票代码"))
        name = str(row_dict.get("股票名称", ""))
        fallback_close = safe_float(row_dict.get("最新收盘价", 0))

        print(f"正在处理 {i}/{len(candidates)}：{symbol} {name}")

        base_fields = get_intraday_base_fields(symbol, fallback_close=fallback_close)

        if base_fields is None:
            failed.append(symbol)
            continue

        result = {
            "股票代码": symbol,
            "股票名称": name,
            "热点标签": row_dict.get("热点标签", "未归类"),
            "综合评分": safe_float(row_dict.get("综合评分", 0)),
        }

        result.update(base_fields)
        result = calculate_tail_metrics(result)

        structure = classify_intraday_structure(result)
        result["分时结构标签"] = structure

        grade = get_overnight_grade(result)
        result["隔夜建议等级"] = grade
        result["隔夜建议说明"] = get_overnight_advice(result)

        results.append(result)

    result_df = pd.DataFrame(results)

    if result_df.empty:
        print("没有成功生成任何尾盘确认结果。")
        return

    result_df = result_df.sort_values(
        by=["隔夜建议等级", "综合评分"],
        ascending=[True, False]
    ).reset_index(drop=True)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    result_df.to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    md = build_markdown(result_df)
    OUTPUT_MD.write_text(md, encoding="utf-8")

    print("\n尾盘确认完成。")
    print(f"结果CSV：{OUTPUT_CSV}")
    print(f"结果MD：{OUTPUT_MD}")
    print(f"总处理数量：{len(candidates)}")
    print(f"成功数量：{len(result_df)}")
    print(f"失败数量：{len(failed)}")

    if failed:
        print(f"失败股票：{failed}")

    print("\n等级统计：")
    print(result_df["隔夜建议等级"].value_counts().sort_index())


if __name__ == "__main__":
    run_tail_confirmation()