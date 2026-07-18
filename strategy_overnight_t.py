# strategy_overnight_t.py
# -*- coding: utf-8 -*-

"""
A股隔日T选股系统 v2.0

本版本目标：
1. 接入 config.yaml
2. 所有核心参数配置化
3. 拆分评分体系：
   - 日线评分
   - 风险扣分
   - 候选评分
4. 增加：
   - 风险等级
   - 策略类型
   - 买入优先级
5. v2.0 去掉轻量板块/热点标签识别逻辑
"""

from pathlib import Path
import time
from datetime import datetime

import pandas as pd
import yaml

from data_provider import get_all_stocks, get_stock_daily
from common import PRODUCT_VERSION, normalize_code


CONFIG_FILE = Path("config.yaml")
OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "overnight_t_candidates.csv"


def load_config() -> dict:
    """
    读取 config.yaml。
    如果配置缺失，则使用默认值兜底。
    """

    default_config = {
        "capital": {
            "total_capital": 30000,
            "single_stock_min": 3000,
            "single_stock_max": 5000,
            "max_trade_count": 2,
        },
        "stock_filter": {
            "min_price": 30,
            "max_price": 50,
            "min_amount": 500000000,
            "min_amplitude_5d": 10,
            "max_rise_5d": 20,
            "max_ma5_deviation": 10,
        },
        "risk": {
            "max_rise_5d_warning": 18,
            "max_amplitude_5d_warning": 35,
            "high_risk_ma5_deviation": 8,
        },
        "runtime": {
            "enable_cache": True,
            "cache_dir": "cache",
        },
    }

    if not CONFIG_FILE.exists():
        print("未找到 config.yaml，使用默认配置。")
        return default_config

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}

        # 简单合并，避免某些字段缺失导致报错
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

CAPITAL = float(CONFIG["capital"]["total_capital"])
MIN_PRICE = float(CONFIG["stock_filter"]["min_price"])
MAX_PRICE = float(CONFIG["stock_filter"]["max_price"])
MIN_AMOUNT = float(CONFIG["stock_filter"]["min_amount"])
MIN_AMPLITUDE_5D = float(CONFIG["stock_filter"]["min_amplitude_5d"])
MAX_RISE_5D = float(CONFIG["stock_filter"]["max_rise_5d"])
MAX_MA5_DEVIATION = float(CONFIG["stock_filter"]["max_ma5_deviation"])

MAX_RISE_WARNING = float(CONFIG["risk"]["max_rise_5d_warning"])
MAX_AMPLITUDE_WARNING = float(CONFIG["risk"]["max_amplitude_5d_warning"])
HIGH_RISK_MA5_DEVIATION = float(CONFIG["risk"]["high_risk_ma5_deviation"])


def get_market_type(code: str) -> str:
    """
    根据股票代码判断所属市场。
    """

    code = str(code).zfill(6)

    if code.startswith("688"):
        return "科创板"
    if code.startswith("6"):
        return "沪市主板"
    if code.startswith("3"):
        return "创业板"
    if code.startswith("0"):
        return "深市主板"
    if code.startswith(("8", "9", "4")):
        return "北交所"

    return "其他"


def normalize_stock_list_columns(stock_df: pd.DataFrame) -> pd.DataFrame:
    """
    兼容 data_provider.py 返回的中文字段或英文字段。
    统一为：
    代码、名称、最新价、涨跌幅、成交额
    """

    if stock_df is None or stock_df.empty:
        return pd.DataFrame()

    df = stock_df.copy()

    rename_map = {
        "symbol": "代码",
        "name": "名称",
        "price": "最新价",
        "pct_chg": "涨跌幅",
        "amount": "成交额",
    }

    df = df.rename(columns=rename_map)

    if "代码" not in df.columns:
        raise ValueError(f"股票列表缺少【代码】字段，当前字段为：{list(df.columns)}")

    if "名称" not in df.columns:
        df["名称"] = ""

    df["代码"] = df["代码"].astype(str).str.zfill(6)

    for col in ["最新价", "涨跌幅", "成交额"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df

def pre_filter_stock_list(stock_df: pd.DataFrame) -> pd.DataFrame:
    """
    预过滤股票池，减少后续日线请求数量。
    安全版：
    1. 永远不允许因为某个字段异常把股票池过滤成0
    2. 每一步过滤都有日志
    3. 如果某一步过滤后为0，自动回退
    """

    df = normalize_stock_list_columns(stock_df)

    if df.empty:
        return df

    total_count = len(df)

    print("\n预过滤字段检查：")
    print(f"字段列表：{list(df.columns)}")
    print(df.head(3))

    # 基础过滤：只排除 ST 和北交所
    base_df = df.copy()

    base_df = base_df[~base_df["名称"].astype(str).str.contains("ST", na=False)]
    base_df = base_df[~base_df["代码"].astype(str).str.startswith(("8", "9", "4"))]

    print(f"全市场股票数量：{total_count}")
    print(f"排除ST/北交所后数量：{len(base_df)}")

    filtered_df = base_df.copy()

    # 价格预过滤
    if "最新价" in filtered_df.columns:
        before_df = filtered_df.copy()

        filtered_df["最新价"] = pd.to_numeric(filtered_df["最新价"], errors="coerce")

        temp_df = filtered_df[
            (filtered_df["最新价"] >= MIN_PRICE)
            & (filtered_df["最新价"] <= MAX_PRICE)
        ]

        print(f"价格过滤后数量：{len(temp_df)}")

        if len(temp_df) > 0:
            filtered_df = temp_df
        else:
            print("价格过滤后为0，自动回退，跳过价格预过滤。")
            filtered_df = before_df

    # 成交额预过滤
    if "成交额" in filtered_df.columns:
        before_df = filtered_df.copy()

        filtered_df["成交额"] = pd.to_numeric(filtered_df["成交额"], errors="coerce")

        temp_df = filtered_df[
            (filtered_df["成交额"].isna())
            | (filtered_df["成交额"] >= MIN_AMOUNT)
        ]

        print(f"成交额过滤后数量：{len(temp_df)}")

        if len(temp_df) > 0:
            filtered_df = temp_df
        else:
            print("成交额过滤后为0，自动回退，跳过成交额预过滤。")
            filtered_df = before_df

    # 涨跌幅预过滤
    if "涨跌幅" in filtered_df.columns:
        before_df = filtered_df.copy()

        filtered_df["涨跌幅"] = pd.to_numeric(filtered_df["涨跌幅"], errors="coerce")

        temp_df = filtered_df[
            (filtered_df["涨跌幅"].isna())
            | (
                (filtered_df["涨跌幅"] >= -8)
                & (filtered_df["涨跌幅"] <= 10)
            )
        ]

        print(f"涨跌幅过滤后数量：{len(temp_df)}")

        if len(temp_df) > 0:
            filtered_df = temp_df
        else:
            print("涨跌幅过滤后为0，自动回退，跳过涨跌幅预过滤。")
            filtered_df = before_df

    filtered_df = filtered_df[["代码", "名称"]].drop_duplicates().reset_index(drop=True)

    print(f"预过滤后数量：{len(filtered_df)}")

    return filtered_df
    """
    预过滤股票池，减少后续日线请求数量。
    兼容新浪/东方财富不同字段质量。
    """

    df = normalize_stock_list_columns(stock_df)

    if df.empty:
        return df

    total_count = len(df)

    # 排除 ST
    df = df[~df["名称"].astype(str).str.contains("ST", na=False)]

    # 排除北交所
    df = df[~df["代码"].astype(str).str.startswith(("8", "9", "4"))]

    # 价格预过滤
    if "最新价" in df.columns:
        df["最新价"] = pd.to_numeric(df["最新价"], errors="coerce")
        valid_price_ratio = df["最新价"].notna().mean()

        if valid_price_ratio > 0.3:
            df = df[
                (df["最新价"] >= MIN_PRICE)
                & (df["最新价"] <= MAX_PRICE)
            ]

    # 成交额预过滤
    if "成交额" in df.columns:
        df["成交额"] = pd.to_numeric(df["成交额"], errors="coerce")
        valid_amount_ratio = df["成交额"].notna().mean()

        if valid_amount_ratio > 0.3:
            df = df[
                (df["成交额"].isna())
                | (df["成交额"] >= MIN_AMOUNT)
            ]

    # 涨跌幅预过滤
    if "涨跌幅" in df.columns:
        df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce")
        valid_pct_ratio = df["涨跌幅"].notna().mean()

        if valid_pct_ratio > 0.3:
            df = df[
                (df["涨跌幅"].isna())
                | (
                    (df["涨跌幅"] >= -8)
                    & (df["涨跌幅"] <= 10)
                )
            ]

    df = df[["代码", "名称"]].drop_duplicates().reset_index(drop=True)

    print(f"全市场股票数量：{total_count}")
    print(f"预过滤后数量：{len(df)}")

    return df

def safe_get_stock_daily(symbol: str, retry: int = 3, sleep_seconds: float = 0.2) -> pd.DataFrame:
    """
    安全获取单只股票日线数据。
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


def normalize_daily_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    兼容 data_provider 返回的中文/英文字段。
    统一为：
    close, high, low, amount
    """

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()

    rename_map = {
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交额": "amount",
        "开盘": "open",
        "成交量": "volume",
        "日期": "date",
    }

    df = df.rename(columns=rename_map)

    required_cols = ["close", "high", "low", "amount"]

    if any(col not in df.columns for col in required_cols):
        return pd.DataFrame()

    for col in required_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=required_cols)

    return df


def calculate_buy_shares(price: float, capital: float = CAPITAL) -> int:
    """
    按资金计算可买股数。
    A股按100股一手。
    """

    if price <= 0:
        return 0

    shares = int(capital // price)
    shares = shares // 100 * 100

    return shares


def calculate_daily_score(
    amplitude_5d: float,
    amount_5d: float,
    rise_5d: float,
    close_price: float,
    ma5: float,
) -> float:
    """
    日线评分：
    只衡量“是否值得进入候选池”。
    """

    score = 0.0

    ma5_deviation = (close_price - ma5) / ma5 * 100 if ma5 > 0 else 999

    # 1. 振幅评分
    if 10 <= amplitude_5d <= 20:
        score += 20
    elif 20 < amplitude_5d <= 30:
        score += 30
    elif amplitude_5d > 30:
        score += 20

    # 2. 成交额评分
    amount_yi = amount_5d / 100000000

    if 5 <= amount_yi < 10:
        score += 15
    elif 10 <= amount_yi < 30:
        score += 25
    elif amount_yi >= 30:
        score += 20

    # 3. MA5趋势评分
    if close_price > ma5:
        score += 20

    # 4. MA5偏离评分
    if 0 <= ma5_deviation <= 3:
        score += 15
    elif 3 < ma5_deviation <= 6:
        score += 5
    elif ma5_deviation > 8:
        score -= 10

    # 5. 5日涨幅评分
    if 0 <= rise_5d <= 10:
        score += 20
    elif 10 < rise_5d <= 15:
        score += 10
    elif 15 < rise_5d <= 20:
        score -= 10
    elif -5 <= rise_5d < 0:
        score += 8

    return round(max(score, 0), 2)


def calculate_risk_penalty(
    amplitude_5d: float,
    rise_5d: float,
    ma5_deviation: float,
) -> float:
    """
    风险扣分：
    只衡量“是否过热、过远、过波动”。
    """

    penalty = 0.0

    if rise_5d > MAX_RISE_WARNING:
        penalty += 20

    if amplitude_5d > MAX_AMPLITUDE_WARNING:
        penalty += 15

    if ma5_deviation > HIGH_RISK_MA5_DEVIATION:
        penalty += 20

    return round(penalty, 2)


def calculate_candidate_score(daily_score: float, risk_penalty: float) -> float:
    """
    候选评分 = 日线评分 - 风险扣分。
    """

    return round(max(min(daily_score - risk_penalty, 100), 0), 2)


def get_risk_level(amplitude_5d: float, rise_5d: float, ma5_deviation: float) -> str:
    """
    风险等级。
    """

    if rise_5d <= 10 and amplitude_5d <= 20 and ma5_deviation <= 5:
        return "低"

    if rise_5d <= 15 and amplitude_5d <= 30 and ma5_deviation <= 8:
        return "中"

    return "高"


def get_strategy_type(risk_level: str, amplitude_5d: float, ma5_deviation: float) -> str:
    """
    策略类型。
    """

    if risk_level == "低" and 0 <= ma5_deviation <= 3:
        return "隔日T"

    if risk_level in ["低", "中"] and amplitude_5d >= 20:
        return "尾盘套利"

    if risk_level == "高":
        return "观察"

    return "趋势观察"


def get_buy_priority(candidate_score: float, risk_level: str) -> str:
    """
    买入优先级。
    """

    if risk_level == "高":
        if candidate_score >= 80:
            return "C"
        return "D"

    if candidate_score >= 80:
        return "A"

    if candidate_score >= 60:
        return "B"

    if candidate_score >= 40:
        return "C"

    return "D"


def get_operation_advice(priority: str, risk_level: str, ma5: float) -> str:
    """
    操作建议。
    """

    low = ma5 * 0.99
    high = ma5 * 1.01

    if priority == "A":
        return f"主观察，低吸区间 {low:.2f}-{high:.2f}，不追高。"

    if priority == "B":
        return f"备选观察，只在接近 MA5 {low:.2f}-{high:.2f} 时考虑。"

    if priority == "C":
        return "只观察，不作为首选交易标的。"

    return "放弃。"


def scan_overnight_t_stocks(max_count: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    扫描隔日T候选股。

    返回：
        candidates_df: 候选股
        stock_df: 全市场股票列表，用于板块缓存
    """

    start_time = time.time()
    result = []

    stock_df = get_all_stocks()

    if stock_df is None or stock_df.empty:
        raise ValueError("股票列表为空，请检查 data_provider.py")

    stock_df = normalize_stock_list_columns(stock_df)
    stock_list = pre_filter_stock_list(stock_df)

    if max_count is not None:
        stock_list = stock_list.head(max_count)

    total = len(stock_list)

    print(f"开始扫描股票数量：{total}")
    print(f"价格区间：{MIN_PRICE}-{MAX_PRICE} 元")
    print(f"最小成交额：{MIN_AMOUNT}")
    print(f"单只股票预算资金：{CAPITAL} 元")

    actual_daily_fetch_count = 0

    for i, row in enumerate(stock_list.itertuples(index=False), start=1):
        symbol = str(row.代码).zfill(6)
        name = str(row.名称)

        print(f"正在扫描 {i}/{total}：{symbol} {name}")

        daily_df = safe_get_stock_daily(symbol)
        actual_daily_fetch_count += 1

        daily_df = normalize_daily_columns(daily_df)

        if daily_df.empty:
            continue

        try:
            if len(daily_df) < 5:
                continue

            last_5 = daily_df.tail(5)

            close_price = float(last_5["close"].iloc[-1])

            if close_price < MIN_PRICE or close_price > MAX_PRICE:
                continue

            ma5 = float(last_5["close"].mean())

            high_5d = float(last_5["high"].max())
            low_5d = float(last_5["low"].min())

            if low_5d <= 0 or ma5 <= 0:
                continue

            amplitude_5d = (high_5d - low_5d) / low_5d * 100
            amount_5d = float(last_5["amount"].mean())

            first_close = float(last_5["close"].iloc[0])

            if first_close <= 0:
                continue

            rise_5d = (close_price - first_close) / first_close * 100
            ma5_deviation = (close_price - ma5) / ma5 * 100

            # 基础过滤
            if amplitude_5d <= MIN_AMPLITUDE_5D:
                continue

            if amount_5d <= MIN_AMOUNT:
                continue

            if close_price <= ma5:
                continue

            if not (-5 <= rise_5d <= MAX_RISE_5D):
                continue

            if ma5_deviation > MAX_MA5_DEVIATION:
                continue

            buy_shares = calculate_buy_shares(close_price, CAPITAL)
            used_capital = buy_shares * close_price

            if buy_shares <= 0:
                continue

            daily_score = calculate_daily_score(
                amplitude_5d=amplitude_5d,
                amount_5d=amount_5d,
                rise_5d=rise_5d,
                close_price=close_price,
                ma5=ma5,
            )

            risk_penalty = calculate_risk_penalty(
                amplitude_5d=amplitude_5d,
                rise_5d=rise_5d,
                ma5_deviation=ma5_deviation,
            )

            candidate_score = calculate_candidate_score(
                daily_score=daily_score,
                risk_penalty=risk_penalty,
            )

            risk_level = get_risk_level(
                amplitude_5d=amplitude_5d,
                rise_5d=rise_5d,
                ma5_deviation=ma5_deviation,
            )

            strategy_type = get_strategy_type(
                risk_level=risk_level,
                amplitude_5d=amplitude_5d,
                ma5_deviation=ma5_deviation,
            )

            buy_priority = get_buy_priority(
                candidate_score=candidate_score,
                risk_level=risk_level,
            )

            operation_advice = get_operation_advice(
                priority=buy_priority,
                risk_level=risk_level,
                ma5=ma5,
            )

            result.append({
                "股票代码": symbol,
                "股票名称": name,
                "所属市场": get_market_type(symbol),
                "最新收盘价": round(close_price, 2),
                "MA5": round(ma5, 2),
                "距MA5偏离率": round(ma5_deviation, 2),
                "可买股数": buy_shares,
                "预计占用资金": round(used_capital, 2),
                "最近5日振幅": round(amplitude_5d, 2),
                "最近5日涨幅": round(rise_5d, 2),
                "最近5日平均成交额": round(amount_5d, 2),
                "日线评分": daily_score,
                "风险扣分": risk_penalty,
                "候选评分": candidate_score,
                "综合评分": candidate_score,  # 兼容旧版字段
                "风险等级": risk_level,
                "策略类型": strategy_type,
                "买入优先级": buy_priority,
                "操作建议": operation_advice,
            })

        except Exception as e:
            print(f"{symbol} {name} 数据处理失败，原因：{e}")
            continue

    candidates_df = pd.DataFrame(result)

    if not candidates_df.empty:
        candidates_df["股票代码"] = candidates_df["股票代码"].astype(str).str.zfill(6)
        candidates_df = candidates_df.sort_values(
            by=["买入优先级", "候选评分"],
            ascending=[True, False]
        ).reset_index(drop=True)

    elapsed = time.time() - start_time

    print("\n性能统计：")
    print(f"预过滤后股票数量：{total}")
    print(f"实际拉取日线数量：{actual_daily_fetch_count}")
    print(f"最终候选数量：{len(candidates_df)}")
    print(f"总耗时：{elapsed:.2f} 秒")

    return candidates_df, stock_df


def reorder_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    控制 CSV 字段顺序。
    """

    columns = [
        "股票代码",
        "股票名称",
        "所属市场",
        "最新收盘价",
        "MA5",
        "距MA5偏离率",
        "可买股数",
        "预计占用资金",
        "最近5日振幅",
        "最近5日涨幅",
        "最近5日平均成交额",
        "日线评分",
        "风险扣分",
        "候选评分",
        "综合评分",
        "风险等级",
        "策略类型",
        "买入优先级",
        "操作建议",
    ]

    existing = [col for col in columns if col in df.columns]

    return df[existing]


def print_score_stats(df: pd.DataFrame) -> None:
    """
    输出评分与等级统计。
    """

    if df.empty:
        print("候选池为空，无评分统计。")
        return

    print("\n买入优先级统计：")
    print(df["买入优先级"].value_counts().sort_index())

    print("\n风险等级统计：")
    print(df["风险等级"].value_counts().sort_index())

    print("\n候选评分区间：")
    print(df["候选评分"].describe())


def run_strategy(max_count: int | None = None) -> pd.DataFrame:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"开始运行 A股隔日T选股系统 v{PRODUCT_VERSION}")
    print(f"运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    candidates_df, _stock_df = scan_overnight_t_stocks(max_count=max_count)

    candidates_df = reorder_columns(candidates_df)

    print_score_stats(candidates_df)

    print("\n隔日T候选股票：")
    print(candidates_df)

    candidates_df.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"\n结果已保存到 {OUTPUT_FILE}")
    print(f"候选股票数量：{len(candidates_df)}")

    return candidates_df


if __name__ == "__main__":
    run_strategy(max_count=None)
