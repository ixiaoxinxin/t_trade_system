# tail_confirmation.py
# -*- coding: utf-8 -*-

"""
A股隔日T系统 v2.0：尾盘隔夜确认系统

功能：
1. 读取 output/overnight_t_candidates.csv
2. 自动获取日线和分钟数据
3. 计算尾盘结构
4. 计算尾盘评分
5. 计算最终评分
6. 输出 final_watchlist.csv 和 final_watchlist.md
"""

from pathlib import Path
from datetime import datetime

import pandas as pd
import yaml

from data_provider import get_stock_daily, get_stock_minute


CONFIG_FILE = Path("config.yaml")

INPUT_FILE = Path("output/overnight_t_candidates.csv")
OUTPUT_CSV = Path("output/final_watchlist.csv")
OUTPUT_MD = Path("output/final_watchlist.md")


def load_config() -> dict:
    default_config = {
        "score_weight": {
            "daily_score_weight": 0.4,
            "tail_score_weight": 0.6,
        },
        "tail_confirm": {
            "high_close_position": 0.75,
            "mid_close_position": 0.6,
            "weak_close_position": 0.4,
            "morning_break_threshold": 1.015,
            "repair_threshold": 2.0,
        },
        "runtime": {
            "top_n_tail_confirm": 20,
        },
    }

    if not CONFIG_FILE.exists():
        return default_config

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}

        for section, values in default_config.items():
            if section not in user_config:
                user_config[section] = values
            else:
                for key, value in values.items():
                    user_config[section].setdefault(key, value)

        return user_config

    except Exception as e:
        print(f"读取 config.yaml 失败，使用默认配置。原因：{e}")
        return default_config


CONFIG = load_config()

DAILY_SCORE_WEIGHT = float(CONFIG["score_weight"]["daily_score_weight"])
TAIL_SCORE_WEIGHT = float(CONFIG["score_weight"]["tail_score_weight"])

HIGH_CLOSE_POSITION = float(CONFIG["tail_confirm"]["high_close_position"])
MID_CLOSE_POSITION = float(CONFIG["tail_confirm"]["mid_close_position"])
WEAK_CLOSE_POSITION = float(CONFIG["tail_confirm"]["weak_close_position"])
REPAIR_THRESHOLD = float(CONFIG["tail_confirm"]["repair_threshold"])

TOP_N = int(CONFIG["runtime"]["top_n_tail_confirm"])


def safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def normalize_code(code) -> str:
    return str(code).zfill(6)


def standardize_daily_columns(df: pd.DataFrame) -> pd.DataFrame:
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

    required = ["datetime", "open", "high", "low", "close"]

    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if any(col not in df.columns for col in required):
        return pd.DataFrame()

    df = df.dropna(subset=required)
    df = df.sort_values("datetime").reset_index(drop=True)

    if "amount" not in df.columns:
        df["amount"] = 0.0

    return df


def get_previous_close(symbol: str, fallback_close: float) -> float:
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
        print(f"{symbol} 获取昨收失败，使用兜底值。原因：{e}")
        return fallback_close


def get_intraday_fields(symbol: str, fallback_close: float) -> dict | None:
    symbol = normalize_code(symbol)

    prev_close = get_previous_close(symbol, fallback_close=fallback_close)

    try:
        minute_df = get_stock_minute(symbol)
        minute_df = standardize_minute_columns(minute_df)

        if minute_df.empty:
            print(f"{symbol} 分钟数据为空")
            return None

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

        afternoon_df = today_df[
            (today_df["datetime"].dt.time >= pd.to_datetime("13:00").time())
        ].copy()

        tail_df = today_df[
            (today_df["datetime"].dt.time >= pd.to_datetime("14:30").time())
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

        today_amount = float(today_df["amount"].sum()) if "amount" in today_df.columns else 0.0
        tail_amount = float(tail_df["amount"].sum()) if not tail_df.empty and "amount" in tail_df.columns else 0.0
        afternoon_high = float(afternoon_df["high"].max()) if not afternoon_df.empty else today_high
        afternoon_low = float(afternoon_df["low"].min()) if not afternoon_df.empty else today_low

        avg_amount_per_bar = today_amount / len(today_df) if len(today_df) > 0 else 0
        tail_avg_amount = tail_amount / len(tail_df) if len(tail_df) > 0 else 0
        tail_volume_ratio = tail_avg_amount / avg_amount_per_bar if avg_amount_per_bar > 0 else 0

        return {
            "昨收": round(prev_close, 2),
            "今日开盘": round(open_price, 2),
            "上午最高": round(morning_high, 2),
            "上午最低": round(morning_low, 2),
            "午盘价": round(noon_price, 2),
            "今日最高": round(today_high, 2),
            "今日最低": round(today_low, 2),
            "下午最高": round(afternoon_high, 2),
            "下午最低": round(afternoon_low, 2),
            "收盘价": round(close_price, 2),
            "今日成交额": round(today_amount, 2),
            "尾盘成交额": round(tail_amount, 2),
            "尾盘放量倍数": round(tail_volume_ratio, 2),
        }

    except Exception as e:
        print(f"{symbol} 获取分钟数据失败：{e}")
        return None


def calculate_tail_metrics(row: dict) -> dict:
    prev_close = safe_float(row.get("昨收"))
    morning_high = safe_float(row.get("上午最高"))
    today_high = safe_float(row.get("今日最高"))
    today_low = safe_float(row.get("今日最低"))
    afternoon_low = safe_float(row.get("下午最低"))
    close_price = safe_float(row.get("收盘价"))

    if prev_close <= 0 or today_high <= today_low:
        today_pct = 0
        today_amp = 0
        close_position = 0
        repair_from_low = 0
        pullback_from_high = 0
    else:
        today_pct = (close_price - prev_close) / prev_close * 100
        today_amp = (today_high - today_low) / prev_close * 100
        close_position = (close_price - today_low) / (today_high - today_low)
        repair_from_low = (close_price - today_low) / today_low * 100 if today_low > 0 else 0
        pullback_from_high = (today_high - close_price) / today_high * 100 if today_high > 0 else 0

    afternoon_repair = (close_price - afternoon_low) / afternoon_low * 100 if afternoon_low > 0 else 0

    break_morning_high = close_price > morning_high
    close_high_area = close_position >= HIGH_CLOSE_POSITION

    row.update({
        "今日涨跌幅": round(today_pct, 2),
        "今日振幅": round(today_amp, 2),
        "收盘位置": round(close_position, 4),
        "从低点修复幅度": round(repair_from_low, 2),
        "从高点回落幅度": round(pullback_from_high, 2),
        "下午修复强度": round(afternoon_repair, 2),
        "是否突破上午高点": "是" if break_morning_high else "否",
        "是否收在全天高位区": "是" if close_high_area else "否",
    })

    return row


def classify_structure(row: dict) -> str:
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

    if (
        morning_high > prev_close * 1.015
        and noon_price < morning_high * 0.985
        and close_position >= HIGH_CLOSE_POSITION
    ):
        return "冲高回落再转强型"

    if (
        today_low < prev_close * 0.98
        and repair_from_low >= REPAIR_THRESHOLD
        and close_position >= MID_CLOSE_POSITION
    ):
        return "急跌修复成功型"

    if today_low < prev_close * 0.98 and close_position < 0.5:
        return "急跌修复失败型"

    if today_pct < -1.5 and close_position < WEAK_CLOSE_POSITION:
        return "全天阴跌型"

    if today_pct >= 0 and close_position >= MID_CLOSE_POSITION and today_amp <= 6:
        return "强势横盘型"

    if today_amp > 5 and 0.4 <= close_position <= 0.6:
        return "高波动震荡型"

    if close_position >= HIGH_CLOSE_POSITION:
        return "尾盘资金回流型"

    if close_position < WEAK_CLOSE_POSITION:
        return "弱势收盘型"

    return "普通震荡型"


def get_tail_money_tag(row: dict) -> str:
    close_position = safe_float(row.get("收盘位置"))
    tail_volume_ratio = safe_float(row.get("尾盘放量倍数"))
    break_morning_high = str(row.get("是否突破上午高点")) == "是"
    today_pct = safe_float(row.get("今日涨跌幅"))

    if close_position >= 0.8 and tail_volume_ratio >= 1.2 and today_pct > 0:
        return "尾盘抢筹"

    if close_position >= 0.7 and break_morning_high:
        return "尾盘资金回流"

    if close_position < 0.4:
        return "尾盘无承接"

    return "尾盘普通"


def calculate_tail_score(row: dict) -> float:
    score = 0.0

    close_position = safe_float(row.get("收盘位置"))
    today_pct = safe_float(row.get("今日涨跌幅"))
    repair_from_low = safe_float(row.get("从低点修复幅度"))
    tail_volume_ratio = safe_float(row.get("尾盘放量倍数"))
    break_morning_high = str(row.get("是否突破上午高点")) == "是"
    structure = str(row.get("分时结构标签", ""))
    tail_tag = str(row.get("尾盘抢筹标签", ""))

    if close_position >= 0.8:
        score += 30
    elif close_position >= 0.6:
        score += 20
    elif close_position >= 0.4:
        score += 10

    if break_morning_high:
        score += 20

    if today_pct > 0:
        score += 10

    if repair_from_low >= 2:
        score += 15

    if tail_volume_ratio >= 1.2:
        score += 10

    if tail_tag in ["尾盘抢筹", "尾盘资金回流"]:
        score += 15

    if structure in ["全天阴跌型", "弱势收盘型"]:
        score -= 40

    if structure == "急跌修复失败型":
        score -= 30

    score = max(min(score, 100), 0)

    return round(score, 2)


def calculate_final_score(candidate_score: float, tail_score: float) -> float:
    final_score = candidate_score * DAILY_SCORE_WEIGHT + tail_score * TAIL_SCORE_WEIGHT
    return round(max(min(final_score, 100), 0), 2)


def get_overnight_grade(row: dict) -> str:
    final_score = safe_float(row.get("最终评分"))
    tail_score = safe_float(row.get("尾盘评分"))
    structure = str(row.get("分时结构标签", ""))

    if structure in ["全天阴跌型", "急跌修复失败型", "弱势收盘型"]:
        return "D"

    if final_score >= 80 and tail_score >= 70:
        return "A"

    if final_score >= 65:
        return "B"

    if final_score >= 50:
        return "C"

    return "D"


def get_overnight_advice(row: dict) -> str:
    grade = str(row.get("隔夜建议等级", "C"))
    structure = str(row.get("分时结构标签", ""))
    tail_tag = str(row.get("尾盘抢筹标签", ""))
    final_score = safe_float(row.get("最终评分"))

    if grade == "A":
        return f"隔夜优先。结构【{structure}】，{tail_tag}，最终评分{final_score:.2f}。"

    if grade == "B":
        return f"可观察。结构【{structure}】，最终评分{final_score:.2f}，只低吸不追高。"

    if grade == "C":
        return f"只观察。结构【{structure}】，最终评分{final_score:.2f}，不主动隔夜。"

    return f"放弃。结构【{structure}】，最终评分{final_score:.2f}。"


def build_markdown(df: pd.DataFrame) -> str:
    today = datetime.now().strftime("%Y-%m-%d")

    def table_by_grade(title: str, grade: str) -> str:
        sub = df[df["隔夜建议等级"] == grade].copy()

        if sub.empty:
            return f"## {title}\n\n无。\n"

        cols = [
            "股票代码",
            "股票名称",
            "候选评分",
            "尾盘评分",
            "最终评分",
            "收盘价",
            "今日涨跌幅",
            "收盘位置",
            "尾盘抢筹标签",
            "分时结构标签",
            "隔夜建议说明",
        ]

        existing_cols = [col for col in cols if col in sub.columns]

        return f"## {title}\n\n" + sub[existing_cols].to_markdown(index=False) + "\n"

    md = f"""# 尾盘隔夜确认报告 v2.0

生成日期：{today}

评分公式：

`最终评分 = 候选评分 × {DAILY_SCORE_WEIGHT} + 尾盘评分 × {TAIL_SCORE_WEIGHT}`

---

{table_by_grade("一、隔夜优先：A", "A")}

---

{table_by_grade("二、可观察：B", "B")}

---

{table_by_grade("三、只观察：C", "C")}

---

{table_by_grade("四、放弃：D", "D")}

---

## 使用规则

1. A：明日可优先观察，但仍需按计划低吸。
2. B：可观察，只低吸，不追高。
3. C：只观察，不主动买。
4. D：放弃。
5. 本模块是尾盘确认，不自动下单。
"""

    return md


def run_tail_confirmation(top_n: int = TOP_N) -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"找不到候选池文件：{INPUT_FILE}")

    candidates = pd.read_csv(INPUT_FILE, dtype={"股票代码": str})

    if candidates.empty:
        raise ValueError("候选池为空，无法进行尾盘确认")

    candidates["股票代码"] = candidates["股票代码"].astype(str).str.zfill(6)

    score_col = "候选评分" if "候选评分" in candidates.columns else "综合评分"

    candidates[score_col] = pd.to_numeric(candidates[score_col], errors="coerce")
    candidates = candidates.sort_values(score_col, ascending=False).head(top_n).copy()

    results = []
    failed = []

    print(f"开始尾盘确认，处理前 {len(candidates)} 只候选股。")

    for i, row in enumerate(candidates.itertuples(index=False), start=1):
        row_dict = row._asdict()

        symbol = normalize_code(row_dict.get("股票代码"))
        name = str(row_dict.get("股票名称", ""))
        fallback_close = safe_float(row_dict.get("最新收盘价", 0))

        print(f"正在处理 {i}/{len(candidates)}：{symbol} {name}")

        intraday_fields = get_intraday_fields(symbol, fallback_close=fallback_close)

        if intraday_fields is None:
            failed.append(symbol)
            continue

        candidate_score = safe_float(row_dict.get("候选评分", row_dict.get("综合评分", 0)))

        result = {
            "股票代码": symbol,
            "股票名称": name,
            "确认日期": datetime.now().strftime("%Y-%m-%d"),
            "日线评分": safe_float(row_dict.get("日线评分", candidate_score)),
            "风险扣分": safe_float(row_dict.get("风险扣分", 0)),
            "候选评分": candidate_score,
            "风险等级": row_dict.get("风险等级", "未知"),
        }

        result.update(intraday_fields)
        result = calculate_tail_metrics(result)

        result["分时结构标签"] = classify_structure(result)
        result["尾盘抢筹标签"] = get_tail_money_tag(result)
        result["尾盘评分"] = calculate_tail_score(result)
        result["最终评分"] = calculate_final_score(
            candidate_score=result["候选评分"],
            tail_score=result["尾盘评分"],
        )
        result["隔夜建议等级"] = get_overnight_grade(result)
        result["隔夜建议说明"] = get_overnight_advice(result)

        results.append(result)

    result_df = pd.DataFrame(results)

    if result_df.empty:
        print("没有成功生成任何尾盘确认结果。")
        return

    grade_order = {"A": 1, "B": 2, "C": 3, "D": 4}
    result_df["grade_rank"] = result_df["隔夜建议等级"].map(grade_order).fillna(9)

    result_df = result_df.sort_values(
        by=["grade_rank", "最终评分"],
        ascending=[True, False]
    ).drop(columns=["grade_rank"]).reset_index(drop=True)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    result_df.to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    OUTPUT_MD.write_text(build_markdown(result_df), encoding="utf-8")

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
