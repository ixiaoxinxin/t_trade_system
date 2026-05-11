# strategy_overnight_t.py
# -*- coding: utf-8 -*-

"""
隔日T全市场选股策略 v1.0 bugfix

本版只修复：
1. 所属板块识别
2. 热点标签识别
3. 增加 output/sector_cache.csv 板块缓存
4. 增加匹配统计日志

不修改原有选股逻辑：
1. 最近5日振幅 > 10%
2. 最近5日平均成交额 > 5亿
3. 最新收盘价 > MA5
4. 最近5日涨幅在 -5% 到 +20%
5. 价格区间 30-50 元
"""

from pathlib import Path
import time

import pandas as pd

from data_provider import get_all_stocks, get_stock_daily
from sector_mapper import enrich_candidates_with_sector, print_sector_stats


CAPITAL = 30000
MIN_PRICE = 30
MAX_PRICE = 50

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "overnight_t_candidates.csv"


def get_market_type(code: str) -> str:
    """
    根据股票代码判断所属市场
    """

    code = str(code).zfill(6)

    if code.startswith("688"):
        return "科创板"
    elif code.startswith("6"):
        return "沪市主板"
    elif code.startswith("3"):
        return "创业板"
    elif code.startswith("0"):
        return "深市主板"
    elif code.startswith(("8", "9", "4")):
        return "北交所"
    else:
        return "其他"


def safe_get_stock_daily(symbol: str, retry: int = 3, sleep_seconds: float = 1.2) -> pd.DataFrame:
    """
    安全获取单只股票日线数据
    """

    symbol = str(symbol).zfill(6)

    for i in range(retry):
        try:
            df = get_stock_daily(symbol)

            if df is not None and not df.empty:
                return df

        except Exception as e:
            print(f"{symbol} 日线获取失败，第 {i + 1} 次，原因：{e}")

        time.sleep(sleep_seconds)

    return pd.DataFrame()


def calculate_buy_shares(price: float, capital: float = CAPITAL) -> int:
    """
    按3万元资金计算可买股数
    A股按100股一手
    """

    if price <= 0:
        return 0

    shares = int(capital // price)
    shares = shares // 100 * 100

    return shares


def calculate_score(
    amplitude_5d: float,
    turnover_5d: float,
    rise_5d: float,
    close_price: float,
    ma5: float
) -> float:
    """
    综合评分
    保留原评分逻辑
    """

    score = 0

    score += min(amplitude_5d, 30) * 2
    score += min(turnover_5d / 100000000, 20) * 3

    if close_price > ma5:
        score += 20

    if 0 <= rise_5d <= 10:
        score += 20
    elif -5 <= rise_5d < 0:
        score += 10
    elif 10 < rise_5d <= 20:
        score += 8

    ma5_deviation = (close_price - ma5) / ma5 * 100

    if 0 < ma5_deviation <= 3:
        score += 10
    elif 3 < ma5_deviation <= 6:
        score += 5

    return round(score, 2)


def scan_overnight_t_stocks(max_count: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    全市场扫描适合隔日T的股票

    返回：
        candidates_df: 候选股票
        stock_df: 全市场股票列表，用于后续板块匹配
    """

    result = []

    stock_df = get_all_stocks()

    if stock_df is None or stock_df.empty:
        raise ValueError("股票列表为空，请检查 data_provider.py")

    stock_df = stock_df.copy()

    if "代码" not in stock_df.columns:
        raise ValueError(f"股票列表缺少【代码】字段，当前字段为：{list(stock_df.columns)}")

    if "名称" not in stock_df.columns:
        stock_df["名称"] = ""

    stock_df["代码"] = stock_df["代码"].astype(str).str.zfill(6)

    # 排除 ST
    stock_df = stock_df[~stock_df["名称"].astype(str).str.contains("ST", na=False)]

    # 排除北交所
    stock_df = stock_df[~stock_df["代码"].astype(str).str.startswith(("8", "9", "4"))]

    stock_list = stock_df[["代码", "名称"]].drop_duplicates()

    if max_count is not None:
        stock_list = stock_list.head(max_count)

    total = len(stock_list)

    print(f"开始扫描股票数量：{total}")
    print(f"价格区间：{MIN_PRICE}-{MAX_PRICE} 元")
    print(f"单只股票预算资金：{CAPITAL} 元")

    for i, row in enumerate(stock_list.itertuples(index=False), start=1):
        symbol = str(row.代码).zfill(6)
        name = str(row.名称)

        print(f"正在扫描 {i}/{total}：{symbol} {name}")

        daily_df = safe_get_stock_daily(symbol)

        if daily_df.empty:
            continue

        try:
            df = daily_df.copy()

            required_cols = ["收盘", "最高", "最低", "成交额"]

            if any(col not in df.columns for col in required_cols):
                continue

            for col in required_cols:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            df = df.dropna(subset=required_cols)

            if len(df) < 5:
                continue

            last_5 = df.tail(5)

            close_price = float(last_5["收盘"].iloc[-1])

            # 保留原价格筛选逻辑
            if close_price < MIN_PRICE or close_price > MAX_PRICE:
                continue

            ma5 = float(last_5["收盘"].mean())

            high_5d = float(last_5["最高"].max())
            low_5d = float(last_5["最低"].min())

            if low_5d <= 0:
                continue

            amplitude_5d = (high_5d - low_5d) / low_5d * 100
            turnover_5d = float(last_5["成交额"].mean())

            first_close = float(last_5["收盘"].iloc[0])

            if first_close <= 0:
                continue

            rise_5d = (close_price - first_close) / first_close * 100

            # 保留原筛选条件
            if amplitude_5d <= 10:
                continue

            if turnover_5d <= 500000000:
                continue

            if close_price <= ma5:
                continue

            if not (-5 <= rise_5d <= 20):
                continue

            buy_shares = calculate_buy_shares(close_price, CAPITAL)
            used_capital = buy_shares * close_price

            if buy_shares <= 0:
                continue

            score = calculate_score(
                amplitude_5d=amplitude_5d,
                turnover_5d=turnover_5d,
                rise_5d=rise_5d,
                close_price=close_price,
                ma5=ma5,
            )

            result.append({
                "股票代码": symbol,
                "股票名称": name,
                "所属市场": get_market_type(symbol),

                # 先占位，后面由 sector_mapper.py 统一修复
                "所属板块": "未知",
                "热点标签": "未归类",

                "最新收盘价": round(close_price, 2),
                "MA5": round(ma5, 2),
                "可买股数": buy_shares,
                "预计占用资金": round(used_capital, 2),
                "最近5日振幅": round(amplitude_5d, 2),
                "最近5日涨幅": round(rise_5d, 2),
                "最近5日平均成交额": round(turnover_5d, 2),
                "综合评分": score,
            })

        except Exception as e:
            print(f"{symbol} {name} 数据处理失败，原因：{e}")
            continue

        time.sleep(0.25)

    result_df = pd.DataFrame(result)

    if not result_df.empty:
        result_df["股票代码"] = result_df["股票代码"].astype(str).str.zfill(6)

        result_df = result_df.sort_values(
            by="综合评分",
            ascending=False
        ).reset_index(drop=True)

    return result_df, stock_df


def reorder_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    保持 CSV 字段顺序
    """

    columns = [
        "股票代码",
        "股票名称",
        "所属市场",
        "所属板块",
        "热点标签",
        "最新收盘价",
        "MA5",
        "可买股数",
        "预计占用资金",
        "最近5日振幅",
        "最近5日涨幅",
        "最近5日平均成交额",
        "综合评分",
    ]

    existing_columns = [col for col in columns if col in df.columns]

    return df[existing_columns]


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    candidates_df, stock_df = scan_overnight_t_stocks(max_count=None)

    candidates_df, stats = enrich_candidates_with_sector(
        candidates_df=candidates_df,
        stock_df=stock_df
    )

    print_sector_stats(stats)

    candidates_df = reorder_columns(candidates_df)

    print("\n隔日T候选股票：")
    print(candidates_df)

    candidates_df.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"\n结果已保存到 {OUTPUT_FILE}")
    print(f"候选股票数量：{len(candidates_df)}")