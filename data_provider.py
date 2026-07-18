# data_provider.py
# -*- coding: utf-8 -*-

"""
v2.0-data-source 数据源重构

优先级：
1. 新浪
2. 腾讯
3. 东方财富 / AKShare 备用

统一接口：
1. get_all_stocks()
2. get_stock_daily(symbol)
3. get_stock_minute(symbol, period="1")

缓存：
1. cache/daily/
2. cache/minute/
"""

from pathlib import Path
from datetime import datetime
from io import StringIO
import json
import re
import time

import pandas as pd
import requests


try:
    import akshare as ak
except Exception:
    ak = None


CACHE_DIR = Path("cache")
DAILY_CACHE_DIR = CACHE_DIR / "daily"
MINUTE_CACHE_DIR = CACHE_DIR / "minute"

DAILY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
MINUTE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.sina.com.cn/",
}


DATA_STATS = {
    "当前使用的数据源": "",
    "fallback次数": 0,
    "缓存命中次数": 0,
    "缓存未命中次数": 0,
    "失败次数": 0,
}


def reset_provider_stats():
    """
    重置数据源统计
    """

    for key in DATA_STATS:
        DATA_STATS[key] = 0 if key != "当前使用的数据源" else ""


def get_provider_stats() -> dict:
    """
    获取数据源统计
    """

    return DATA_STATS.copy()


def log_source(source: str):
    """
    记录当前使用的数据源
    """

    DATA_STATS["当前使用的数据源"] = source


def request_get(url: str, timeout: int = 10) -> requests.Response:
    """
    requests 请求封装

    关键点：
    session.trust_env = False
    避免 Python requests 读取系统代理环境变量，降低 VPN 代理报错概率。
    """

    session = requests.Session()
    session.trust_env = False

    response = session.get(
        url,
        headers=HEADERS,
        timeout=timeout
    )

    response.raise_for_status()

    return response


def normalize_code(code) -> str:
    """
    股票代码统一为6位字符串
    """

    if pd.isna(code):
        return ""

    code = str(code).strip()

    if "." in code:
        code = code.split(".")[0]

    code = code.replace("sh", "").replace("sz", "")

    return code.zfill(6)


def to_sina_symbol(code: str) -> str:
    """
    转新浪代码格式
    """

    code = normalize_code(code)

    if code.startswith(("6", "9")):
        return "sh" + code

    return "sz" + code


def to_tencent_symbol(code: str) -> str:
    """
    转腾讯代码格式
    """

    return to_sina_symbol(code)


def safe_float(value, default=0.0) -> float:
    """
    安全转换 float
    """

    try:
        if pd.isna(value):
            return default

        text = str(value).strip().replace(",", "")

        if text in ["", "-", "--", "None", "nan", "null"]:
            return default

        return float(text)

    except Exception:
        return default


def is_file_today(file_path: Path) -> bool:
    """
    判断缓存是否为当天
    """

    if not file_path.exists():
        return False

    file_date = datetime.fromtimestamp(file_path.stat().st_mtime).date()

    return file_date == datetime.now().date()


def after_1455() -> bool:
    """
    判断当前是否已经到 14:55 后

    分钟缓存只在 14:55 后允许复用。
    """

    now = datetime.now()

    return now.hour > 14 or (now.hour == 14 and now.minute >= 55)


# =========================================================
# 一、获取全市场实时行情
# =========================================================

def parse_sina_item(item_text: str, key: str) -> str:
    """
    从新浪 JS 对象字符串中提取字段
    """
    

    pattern1 = rf'{key}\s*:\s*"([^"]*)"'
    pattern2 = rf'"{key}"\s*:\s*"([^"]*)"'
    pattern3 = rf'{key}\s*:\s*([^,\}}]+)'
    

    

    for pattern in [pattern1, pattern2, pattern3]:
        match = re.search(pattern, item_text)

        if match:
            return match.group(1).strip().strip('"')

    return ""


def get_all_stocks_sina() -> pd.DataFrame:
    """
    使用新浪接口获取A股实时行情

    返回标准字段：
    - 代码
    - 名称
    - 最新价
    - 涨跌幅
    - 成交额
    """

    count = 6000
    page_size = 80
    pages = count // page_size + 1

    rows = []

    for page in range(1, pages + 1):
        url = (
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "Market_Center.getHQNodeData?"
            f"page={page}&num={page_size}&sort=symbol&asc=1"
            "&node=hs_a&symbol=&_s_r_a=init"
        )

        try:
            response = request_get(url, timeout=10)
            text = response.text.strip()

            if not text or text == "null":
                continue

            # 新浪返回有时不是严格 JSON，所以用正则按对象切分
            item_texts = re.findall(r"\{.*?\}", text)

            for item in item_texts:
                symbol = parse_sina_item(item, "symbol")
                code = parse_sina_item(item, "code")
                name = parse_sina_item(item, "name")

                # 修复新浪返回的 Unicode 转义中文名

                try:

                    name = name.encode("utf-8").decode("unicode_escape")

                except Exception:

                 pass

                if not code and symbol:
                    code = symbol[-6:]

                code = normalize_code(code)

                if not code or not name:
                    continue

                price = safe_float(parse_sina_item(item, "trade"))
                pct_chg = safe_float(parse_sina_item(item, "changepercent"))
                amount = safe_float(parse_sina_item(item, "amount"))

                rows.append({
                    "代码": code,
                    "名称": name,
                    "最新价": price,
                    "涨跌幅": pct_chg,
                    "成交额": amount,
                    "数据源": "新浪",
                })

            time.sleep(0.08)

        except Exception as e:
            DATA_STATS["失败次数"] += 1
            print(f"新浪行情第 {page} 页失败：{e}")
            continue

    df = pd.DataFrame(rows)

    if df.empty:
        raise ValueError("新浪全市场行情为空")

    df = df.drop_duplicates(subset=["代码"]).reset_index(drop=True)

    log_source("新浪")

    return df


def get_all_stocks_akshare() -> pd.DataFrame:
    """
    使用 AKShare / 东方财富接口兜底获取A股实时行情
    """

    if ak is None:
        raise RuntimeError("AKShare 未安装，无法使用东方财富备用接口")

    df = ak.stock_zh_a_spot_em()

    if df is None or df.empty:
        raise ValueError("AKShare 行情为空")

    df = df.rename(columns={
        "代码": "代码",
        "名称": "名称",
        "最新价": "最新价",
        "涨跌幅": "涨跌幅",
        "成交额": "成交额",
    })

    required = ["代码", "名称", "最新价", "涨跌幅", "成交额"]

    for col in required:
        if col not in df.columns:
            df[col] = 0 if col not in ["代码", "名称"] else ""

    df = df[required].copy()
    df["代码"] = df["代码"].apply(normalize_code)
    df["数据源"] = "东方财富"

    log_source("东方财富")

    return df


def get_all_stocks() -> pd.DataFrame:
    """
    统一获取A股实时行情

    优先：
    1. 新浪
    2. 东方财富 / AKShare 备用
    """

    try:
        return get_all_stocks_sina()

    except Exception as e:
        DATA_STATS["fallback次数"] += 1
        print(f"新浪 get_all_stocks 失败，尝试东方财富备用：{e}")

    try:
        return get_all_stocks_akshare()

    except Exception as e:
        DATA_STATS["失败次数"] += 1
        print(f"东方财富 get_all_stocks 也失败：{e}")

    return pd.DataFrame(columns=["代码", "名称", "最新价", "涨跌幅", "成交额", "数据源"])


# =========================================================
# 二、日线数据
# =========================================================

def get_daily_cache_file(symbol: str) -> Path:
    """
    日线缓存路径
    """

    symbol = normalize_code(symbol)

    return DAILY_CACHE_DIR / f"{symbol}.csv"


def read_daily_cache(symbol: str) -> pd.DataFrame:
    """
    读取日线缓存
    """

    cache_file = get_daily_cache_file(symbol)

    if not is_file_today(cache_file):
        DATA_STATS["缓存未命中次数"] += 1
        return pd.DataFrame()

    try:
        df = pd.read_csv(cache_file)

        if df.empty:
            DATA_STATS["缓存未命中次数"] += 1
            return pd.DataFrame()

        DATA_STATS["缓存命中次数"] += 1

        return df

    except Exception:
        DATA_STATS["缓存未命中次数"] += 1
        return pd.DataFrame()


def write_daily_cache(symbol: str, df: pd.DataFrame):
    """
    写入日线缓存
    """

    if df is None or df.empty:
        return

    cache_file = get_daily_cache_file(symbol)

    df.to_csv(cache_file, index=False, encoding="utf-8-sig")


def get_stock_daily_sina(symbol: str) -> pd.DataFrame:
    """
    新浪日线接口

    返回字段兼容旧策略：
    - 日期
    - 开盘
    - 收盘
    - 最高
    - 最低
    - 成交量
    - 成交额
    """

    code = normalize_code(symbol)
    sina_symbol = to_sina_symbol(code)

    url = (
        "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData"
        f"?symbol={sina_symbol}&scale=240&ma=no&datalen=320"
    )

    response = request_get(url, timeout=10)
    text = response.text

    start = text.find("[")
    end = text.rfind("]") + 1

    if start == -1 or end <= start:
        raise ValueError(f"新浪日线为空：{code}")

    json_text = text[start:end]

    data = pd.read_json(StringIO(json_text))

    if data.empty:
        raise ValueError(f"新浪日线为空：{code}")

    df = data.rename(columns={
        "day": "日期",
        "open": "开盘",
        "high": "最高",
        "low": "最低",
        "close": "收盘",
        "volume": "成交量",
    })

    for col in ["开盘", "收盘", "最高", "最低", "成交量"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 新浪日线通常没有成交额，用成交量 * 收盘价近似
    df["成交额"] = df["成交量"] * df["收盘"]

    df = df[["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]]
    df = df.dropna().reset_index(drop=True)

    log_source("新浪")

    return df


def get_stock_daily_tencent(symbol: str) -> pd.DataFrame:
    """
    腾讯日线备用接口
    """

    code = normalize_code(symbol)
    tx_symbol = to_tencent_symbol(code)

    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={tx_symbol},day,,,320,qfq"
    )

    response = request_get(url, timeout=10)
    data = response.json()

    klines = (
        data.get("data", {})
        .get(tx_symbol, {})
        .get("qfqday", [])
    )

    if not klines:
        klines = (
            data.get("data", {})
            .get(tx_symbol, {})
            .get("day", [])
        )

    if not klines:
        raise ValueError(f"腾讯日线为空：{code}")

    rows = []

    for item in klines:
        rows.append({
            "日期": item[0],
            "开盘": safe_float(item[1]),
            "收盘": safe_float(item[2]),
            "最高": safe_float(item[3]),
            "最低": safe_float(item[4]),
            "成交量": safe_float(item[5]),
        })

    df = pd.DataFrame(rows)

    df["成交额"] = df["成交量"] * df["收盘"]

    log_source("腾讯")

    return df[["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]]


def get_stock_daily_akshare(symbol: str) -> pd.DataFrame:
    """
    AKShare / 东方财富日线备用接口
    """

    if ak is None:
        raise RuntimeError("AKShare 未安装")

    code = normalize_code(symbol)

    df = ak.stock_zh_a_hist(
        symbol=code,
        period="daily",
        start_date="20240101",
        end_date="20991231",
        adjust=""
    )

    if df is None or df.empty:
        raise ValueError(f"AKShare 日线为空：{code}")

    required = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]

    for col in required:
        if col not in df.columns:
            df[col] = 0

    log_source("东方财富")

    return df[required].copy()


def get_stock_daily(symbol: str) -> pd.DataFrame:
    """
    统一获取日线数据

    优先级：
    1. 当天缓存
    2. 新浪
    3. 腾讯
    4. 东方财富 / AKShare
    """

    code = normalize_code(symbol)

    cached = read_daily_cache(code)

    if not cached.empty:
        return cached

    for source_name, func in [
        ("新浪", get_stock_daily_sina),
        ("腾讯", get_stock_daily_tencent),
        ("东方财富", get_stock_daily_akshare),
    ]:
        try:
            df = func(code)

            if df is not None and not df.empty:
                write_daily_cache(code, df)
                return df

        except Exception as e:
            DATA_STATS["fallback次数"] += 1
            print(f"{code} 日线 {source_name} 失败，尝试下一个数据源：{e}")
            continue

    DATA_STATS["失败次数"] += 1

    return pd.DataFrame(columns=["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"])


# =========================================================
# 三、分钟数据
# =========================================================

def get_minute_cache_file(symbol: str, period: str) -> Path:
    """
    分钟缓存路径
    """

    symbol = normalize_code(symbol)

    return MINUTE_CACHE_DIR / f"{symbol}_{period}m.csv"


def read_minute_cache(symbol: str, period: str) -> pd.DataFrame:
    """
    读取分钟缓存

    规则：
    - 14:55 后允许使用当天缓存
    - 盘中不使用旧分钟缓存
    """

    cache_file = get_minute_cache_file(symbol, period)

    if not after_1455():
        DATA_STATS["缓存未命中次数"] += 1
        return pd.DataFrame()

    if not is_file_today(cache_file):
        DATA_STATS["缓存未命中次数"] += 1
        return pd.DataFrame()

    try:
        df = pd.read_csv(cache_file)

        if df.empty:
            DATA_STATS["缓存未命中次数"] += 1
            return pd.DataFrame()

        DATA_STATS["缓存命中次数"] += 1

        return df

    except Exception:
        DATA_STATS["缓存未命中次数"] += 1
        return pd.DataFrame()


def write_minute_cache(symbol: str, period: str, df: pd.DataFrame):
    """
    写入分钟缓存

    只有 14:55 后才写入缓存。
    """

    if df is None or df.empty:
        return

    if not after_1455():
        return

    cache_file = get_minute_cache_file(symbol, period)

    df.to_csv(cache_file, index=False, encoding="utf-8-sig")


def get_stock_minute_sina(symbol: str, period: str = "1") -> pd.DataFrame:
    """
    新浪分钟数据

    period:
    - "1"
    - "5"

    返回标准字段：
    - datetime
    - open
    - high
    - low
    - close
    - volume
    - amount
    """

    code = normalize_code(symbol)
    sina_symbol = to_sina_symbol(code)

    scale = "1" if str(period) == "1" else "5"

    url = (
        "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData"
        f"?symbol={sina_symbol}&scale={scale}&ma=no&datalen=320"
    )

    response = request_get(url, timeout=10)
    text = response.text

    start = text.find("[")
    end = text.rfind("]") + 1

    if start == -1 or end <= start:
        raise ValueError(f"新浪分钟为空：{code}")

    json_text = text[start:end]

    data = pd.read_json(StringIO(json_text))

    if data.empty:
        raise ValueError(f"新浪分钟为空：{code}")

    df = data.rename(columns={
        "day": "datetime",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    })

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["amount"] = df["volume"] * df["close"]

    df = df[["datetime", "open", "high", "low", "close", "volume", "amount"]]
    df = df.dropna().reset_index(drop=True)

    log_source("新浪")

    return df


def get_stock_minute_tencent(symbol: str, period: str = "1") -> pd.DataFrame:
    """
    腾讯分钟数据备用接口
    """

    code = normalize_code(symbol)
    tx_symbol = to_tencent_symbol(code)

    ktype = "m1" if str(period) == "1" else "m5"

    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/kline/mkline"
        f"?param={tx_symbol},{ktype},,320"
    )

    response = request_get(url, timeout=10)
    data = response.json()

    klines = (
        data.get("data", {})
        .get(tx_symbol, {})
        .get(ktype, [])
    )

    if not klines:
        raise ValueError(f"腾讯分钟为空：{code}")

    rows = []

    for item in klines:
        rows.append({
            "datetime": item[0],
            "open": safe_float(item[1]),
            "close": safe_float(item[2]),
            "high": safe_float(item[3]),
            "low": safe_float(item[4]),
            "volume": safe_float(item[5]),
        })

    df = pd.DataFrame(rows)

    df["amount"] = df["volume"] * df["close"]

    log_source("腾讯")

    return df[["datetime", "open", "high", "low", "close", "volume", "amount"]]


def get_stock_minute(symbol: str, period: str = "1") -> pd.DataFrame:
    """
    统一获取分钟数据

    优先级：
    1. 缓存
    2. 新浪
    3. 腾讯

    period:
    - "1"
    - "5"
    """

    code = normalize_code(symbol)
    period = str(period)

    if period not in ["1", "5"]:
        raise ValueError("period 只支持 '1' 或 '5'")

    cached = read_minute_cache(code, period)

    if not cached.empty:
        return cached

    for source_name, func in [
        ("新浪", get_stock_minute_sina),
        ("腾讯", get_stock_minute_tencent),
    ]:
        try:
            df = func(code, period=period)

            if df is not None and not df.empty:
                write_minute_cache(code, period, df)
                return df

        except Exception as e:
            DATA_STATS["fallback次数"] += 1
            print(f"{code} 分钟 {source_name} 失败，尝试下一个数据源：{e}")
            continue

    DATA_STATS["失败次数"] += 1

    return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "amount"])


if __name__ == "__main__":
    reset_provider_stats()

    print("测试 get_all_stocks：")
    all_stocks = get_all_stocks()
    print(all_stocks.head())
    print(all_stocks.shape)

    print("\n测试 get_stock_daily：")
    daily = get_stock_daily("002466")
    print(daily.tail())

    print("\n测试 get_stock_minute 1分钟：")
    minute = get_stock_minute("002466", period="1")
    print(minute.tail())

    print("\n数据源统计：")
    print(get_provider_stats())