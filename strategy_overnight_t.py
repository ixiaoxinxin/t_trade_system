# strategy_overnight_t.py
# -*- coding: utf-8 -*-

"""
A股隔日T选股系统 v1.4-speed

本次只做性能优化：
1. 使用 get_all_stocks() 实时行情先做预过滤
2. 只有通过预过滤的股票才调用 get_stock_daily()
3. 增加日线缓存 cache/daily/
4. 增加性能日志

不修改：
1. 原选股逻辑
2. 原评分模型
3. sector_mapper.py 板块 / 热点标签逻辑
4. report_generator.py
5. app.py
"""

from pathlib import Path
from datetime import datetime
import time

import pandas as pd

from data_provider import get_all_stocks, get_stock_daily
from sector_mapper import enrich_candidates_with_sector, print_sector_stats


# =========================
# 基础配置
# =========================

CAPITAL = 30000
MIN_PRICE = 30
MAX_PRICE = 50

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "overnight_t_candidates.csv"

DAILY_CACHE_DIR = Path("cache/daily")


# =========================
# 工具函数
# =========================

def normalize_code(code) -> str:
    """
    股票代码统一为6位字符串，保留前导0
    """

    if pd.isna(code):
        return ""

    code = str(code).strip()

    if "." in code:
        code = code.split(".")[0]

    return code.zfill(6)


def safe_float(value, default=0.0) -> float:
    """
    安全转 float
    兼容：
    - 字符串
    - 空值
    - 带逗号的数字
    - '--'
    """

    try:
        if pd.isna(value):
            return default

        text = str(value).strip().replace(",", "")

        if text in ["", "-", "--", "nan", "None", "null"]:
            return default

        return float(text)

    except Exception:
        return default


def is_file_today(file_path: Path) -> bool:
    """
    判断缓存文件是否为今天生成
    """

    if not file_path.exists():
        return False

    file_date = datetime.fromtimestamp(file_path.stat().st_mtime).date()
    today = datetime.now().date()

    return file_date == today


def get_market_type(code: str) -> str:
    """
    根据股票代码判断所属市场
    """

    code = normalize_code(code)

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
    保留原评分逻辑，不做改动
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


# =========================
# 实时行情字段标准化
# =========================

def standardize_spot_columns(stock_df: pd.DataFrame) -> pd.DataFrame:
    """
    统一 get_all_stocks() 返回字段

    如果只有【代码、名称】，说明当前数据源不含实时行情字段，
    此时不报错，直接返回基础股票列表，后续走降级扫描。
    """

    if stock_df is None or stock_df.empty:
        return pd.DataFrame()

    df = stock_df.copy()

    rename_map = {}

    if "代码" in df.columns:
        rename_map["代码"] = "股票代码"
    elif "symbol" in df.columns:
        rename_map["symbol"] = "股票代码"

    if "名称" in df.columns:
        rename_map["名称"] = "股票名称"
    elif "name" in df.columns:
        rename_map["name"] = "股票名称"

    if "最新价" in df.columns:
        rename_map["最新价"] = "最新价"
    elif "price" in df.columns:
        rename_map["price"] = "最新价"

    if "涨跌幅" in df.columns:
        rename_map["涨跌幅"] = "涨跌幅"
    elif "pct_chg" in df.columns:
        rename_map["pct_chg"] = "涨跌幅"

    if "成交额" in df.columns:
        rename_map["成交额"] = "成交额"
    elif "amount" in df.columns:
        rename_map["amount"] = "成交额"

    df = df.rename(columns=rename_map)

    if "股票代码" not in df.columns:
        raise ValueError(f"实时行情字段缺少股票代码，当前字段为：{list(stock_df.columns)}")

    if "股票名称" not in df.columns:
        df["股票名称"] = ""

    df["股票代码"] = df["股票代码"].apply(normalize_code)
    df["股票名称"] = df["股票名称"].astype(str)

    # 如果没有实时行情字段，直接返回代码和名称
    optional_cols = ["最新价", "涨跌幅", "成交额"]
    for col in optional_cols:
        if col not in df.columns:
            df[col] = None

    df = df[["股票代码", "股票名称", "最新价", "涨跌幅", "成交额"]].copy()

    df["最新价"] = df["最新价"].apply(safe_float)
    df["涨跌幅"] = df["涨跌幅"].apply(safe_float)
    df["成交额"] = df["成交额"].apply(safe_float)

    return df
    """
    统一 get_all_stocks() 返回字段

    支持中文字段：
    - 代码
    - 名称
    - 最新价
    - 涨跌幅
    - 成交额

    支持英文标准字段：
    - symbol
    - name
    - price
    - pct_chg
    - amount
    """

    if stock_df is None or stock_df.empty:
        return pd.DataFrame()

    df = stock_df.copy()

    rename_map = {}

    if "代码" in df.columns:
        rename_map["代码"] = "股票代码"
    elif "symbol" in df.columns:
        rename_map["symbol"] = "股票代码"

    if "名称" in df.columns:
        rename_map["名称"] = "股票名称"
    elif "name" in df.columns:
        rename_map["name"] = "股票名称"

    if "最新价" in df.columns:
        rename_map["最新价"] = "最新价"
    elif "price" in df.columns:
        rename_map["price"] = "最新价"

    if "涨跌幅" in df.columns:
        rename_map["涨跌幅"] = "涨跌幅"
    elif "pct_chg" in df.columns:
        rename_map["pct_chg"] = "涨跌幅"

    if "成交额" in df.columns:
        rename_map["成交额"] = "成交额"
    elif "amount" in df.columns:
        rename_map["amount"] = "成交额"

    df = df.rename(columns=rename_map)

    required_cols = ["股票代码", "股票名称", "最新价", "涨跌幅", "成交额"]
    missing_cols = [col for col in required_cols if col not in df.columns]

    if missing_cols:
        raise ValueError(
            f"实时行情字段缺失：{missing_cols}，当前字段为：{list(stock_df.columns)}"
        )

    df = df[required_cols].copy()

    df["股票代码"] = df["股票代码"].apply(normalize_code)
    df["股票名称"] = df["股票名称"].astype(str)

    df["最新价"] = df["最新价"].apply(safe_float)
    df["涨跌幅"] = df["涨跌幅"].apply(safe_float)
    df["成交额"] = df["成交额"].apply(safe_float)

    return df


def pre_filter_stocks(stock_df: pd.DataFrame, max_count: int | None = None) -> pd.DataFrame:
    """
    预过滤股票列表

    如果 get_all_stocks() 有实时行情字段：
    - 按价格、成交额、涨跌幅预过滤

    如果 get_all_stocks() 只有代码和名称：
    - 自动降级，只做 ST / 北交所过滤
    - 不再报错
    """

    df = standardize_spot_columns(stock_df)

    if df.empty:
        return df

    # 排除空代码
    df = df[df["股票代码"] != ""]

    # 名称不包含 ST
    df = df[~df["股票名称"].astype(str).str.contains("ST", na=False)]

    # 排除北交所
    df = df[~df["股票代码"].astype(str).str.startswith(("8", "9", "4"))]

    has_realtime_fields = (
        df["最新价"].sum() > 0
        and df["成交额"].sum() > 0
    )

    if has_realtime_fields:
        print("检测到实时行情字段，启用 v1.4-speed 预过滤")

        df = df[
            (df["最新价"] >= MIN_PRICE)
            & (df["最新价"] <= MAX_PRICE)
        ]

        df = df[df["成交额"] > 500000000]

        df = df[
            (df["涨跌幅"] >= -8)
            & (df["涨跌幅"] <= 10)
        ]

    else:
        print("当前 get_all_stocks() 只有代码和名称，未检测到实时行情字段")
        print("自动降级：只做 ST / 北交所过滤，日线缓存仍然生效")

    df = df.drop_duplicates(subset=["股票代码"]).reset_index(drop=True)

    if max_count is not None:
        df = df.head(max_count)

    return df

# =========================
# 日线缓存
# =========================

def read_daily_cache(symbol: str) -> pd.DataFrame:
    """
    读取单只股票日线缓存
    """

    symbol = normalize_code(symbol)
    cache_file = DAILY_CACHE_DIR / f"{symbol}.csv"

    if not is_file_today(cache_file):
        return pd.DataFrame()

    try:
        df = pd.read_csv(cache_file)

        if df is None or df.empty:
            return pd.DataFrame()

        return df

    except Exception:
        return pd.DataFrame()


def write_daily_cache(symbol: str, df: pd.DataFrame):
    """
    写入单只股票日线缓存
    """

    if df is None or df.empty:
        return

    DAILY_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    symbol = normalize_code(symbol)
    cache_file = DAILY_CACHE_DIR / f"{symbol}.csv"

    df.to_csv(cache_file, index=False, encoding="utf-8-sig")


def get_stock_daily_with_cache(
    symbol: str,
    stats: dict,
    retry: int = 3,
    sleep_seconds: float = 1.2
) -> pd.DataFrame:
    """
    获取日线数据，优先读取当天缓存

    如果缓存不存在、过期或读取失败，再调用 get_stock_daily()
    """

    symbol = normalize_code(symbol)

    cached_df = read_daily_cache(symbol)

    if cached_df is not None and not cached_df.empty:
        stats["缓存命中数量"] += 1
        return cached_df

    stats["缓存未命中数量"] += 1

    for i in range(retry):
        try:
            df = get_stock_daily(symbol)
            stats["实际拉取日线数量"] += 1

            if df is not None and not df.empty:
                write_daily_cache(symbol, df)
                return df

        except Exception as e:
            print(f"{symbol} 日线获取失败，第 {i + 1} 次，原因：{e}")

        time.sleep(sleep_seconds)

    return pd.DataFrame()


# =========================
# 核心扫描逻辑
# =========================

def scan_overnight_t_stocks(max_count: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    扫描隔日T候选股

    参数：
        max_count:
            None = 扫描全部通过预过滤的股票
            100 = 只扫描预过滤后的前100只，用于调试

    返回：
        candidates_df: 候选股结果
        stock_df_for_sector: 给 sector_mapper 使用的股票列表
        perf_stats: 性能统计
    """

    start_time = time.time()

    perf_stats = {
        "全市场股票数量": 0,
        "预过滤后数量": 0,
        "实际拉取日线数量": 0,
        "缓存命中数量": 0,
        "缓存未命中数量": 0,
        "最终候选数量": 0,
        "总耗时": 0,
    }

    result = []

    raw_stock_df = get_all_stocks()

    if raw_stock_df is None or raw_stock_df.empty:
        raise ValueError("股票列表为空，请检查 data_provider.py")

    perf_stats["全市场股票数量"] = len(raw_stock_df)

    # 实时行情预过滤
    pre_df = pre_filter_stocks(raw_stock_df, max_count=max_count)
    perf_stats["预过滤后数量"] = len(pre_df)

    if pre_df.empty:
        perf_stats["总耗时"] = round(time.time() - start_time, 2)
        return pd.DataFrame(), pd.DataFrame(), perf_stats

    # 给 sector_mapper 使用，保持字段名为 代码 / 名称
    stock_df_for_sector = pre_df.rename(
        columns={
            "股票代码": "代码",
            "股票名称": "名称",
        }
    )[["代码", "名称"]].copy()

    total = len(pre_df)

    print(f"开始扫描股票数量：{total}")
    print(f"价格区间：{MIN_PRICE}-{MAX_PRICE} 元")
    print(f"单只股票预算资金：{CAPITAL} 元")

    for i, row in enumerate(pre_df.itertuples(index=False), start=1):
        symbol = normalize_code(row.股票代码)
        name = str(row.股票名称)

        print(f"正在扫描 {i}/{total}：{symbol} {name}")

        daily_df = get_stock_daily_with_cache(
            symbol=symbol,
            stats=perf_stats
        )

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

            # 保留原价格逻辑
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

            # =========================
            # 保留原选股条件，不改动
            # =========================

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

        time.sleep(0.05)

    candidates_df = pd.DataFrame(result)

    if not candidates_df.empty:
        candidates_df["股票代码"] = candidates_df["股票代码"].astype(str).str.zfill(6)
        candidates_df = candidates_df.sort_values(
            by="综合评分",
            ascending=False
        ).reset_index(drop=True)

    perf_stats["最终候选数量"] = len(candidates_df)
    perf_stats["总耗时"] = round(time.time() - start_time, 2)

    return candidates_df, stock_df_for_sector, perf_stats


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

    existing = [col for col in columns if col in df.columns]

    return df[existing]


def print_performance_stats(stats: dict):
    """
    打印性能统计日志
    """

    print("\n性能统计：")
    print(f"全市场股票数量：{stats.get('全市场股票数量', 0)}")
    print(f"预过滤后数量：{stats.get('预过滤后数量', 0)}")
    print(f"实际拉取日线数量：{stats.get('实际拉取日线数量', 0)}")
    print(f"缓存命中数量：{stats.get('缓存命中数量', 0)}")
    print(f"缓存未命中数量：{stats.get('缓存未命中数量', 0)}")
    print(f"最终候选数量：{stats.get('最终候选数量', 0)}")
    print(f"总耗时：{stats.get('总耗时', 0)} 秒")


# =========================
# 主入口
# =========================

if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DAILY_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 调试时可以改成 100
    # 正式运行用 None
    candidates_df, stock_df_for_sector, perf_stats = scan_overnight_t_stocks(
        max_count=None
    )

    # 保留原板块 / 热点标签逻辑，不在本文件中修改
    candidates_df, sector_stats = enrich_candidates_with_sector(
        candidates_df=candidates_df,
        stock_df=stock_df_for_sector
    )

    print_sector_stats(sector_stats)

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

    print_performance_stats(perf_stats)