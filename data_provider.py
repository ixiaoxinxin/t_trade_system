# data_provider.py
# -*- coding: utf-8 -*-

"""
新浪数据源版 A股数据获取模块
适合收盘后获取当天日线数据
"""

import time
import json
import requests
import pandas as pd
from io import StringIO


HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.sina.com.cn/"
}


def stock_code_to_sina_symbol(code: str) -> str:
    """
    普通A股代码转新浪代码
    """

    code = str(code).zfill(6)

    if code.startswith(("6", "9")):
        return "sh" + code
    else:
        return "sz" + code


def sina_symbol_to_stock_code(symbol: str) -> str:
    """
    新浪代码转普通股票代码
    """

    return str(symbol)[-6:]


def get_all_stocks() -> pd.DataFrame:
    """
    获取A股股票列表
    返回字段：
    - 代码
    - 名称
    """

    count = 6000

    result = []
    page_size = 80
    pages = count // page_size + 1

    for page in range(1, pages + 1):
        url = (
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "Market_Center.getHQNodeData?"
            f"page={page}&num={page_size}&sort=symbol&asc=1&node=hs_a&symbol=&_s_r_a=init"
        )

        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            text = r.text

            if not text or text == "null":
                continue

            # 新浪返回的是JSON数组字符串
            data = json.loads(text)

            for item in data:
                symbol = item.get("symbol")
                name = item.get("name")

                if not symbol or not name:
                    continue

                code = sina_symbol_to_stock_code(symbol)

                result.append({
                    "代码": code,
                    "名称": name
                })

            time.sleep(0.15)

        except Exception as e:
            print(f"第 {page} 页股票列表获取失败：{e}")
            continue

    df = pd.DataFrame(result)

    if df.empty:
        return pd.DataFrame(columns=["代码", "名称"])

    df = df.drop_duplicates(subset=["代码"]).reset_index(drop=True)

    return df


def get_stock_daily(symbol: str) -> pd.DataFrame:
    """
    获取A股日线数据

    参数：
        symbol: 股票代码，例如 002466、002192、603799

    返回字段：
    - 日期
    - 开盘
    - 收盘
    - 最高
    - 最低
    - 成交量
    - 成交额
    """

    code = str(symbol).zfill(6)
    sina_symbol = stock_code_to_sina_symbol(code)

    url = (
        "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData"
        f"?symbol={sina_symbol}&scale=240&ma=no&datalen=300"
    )

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        text = r.text

        start = text.find("[")
        end = text.rfind("]") + 1

        if start == -1 or end == 0:
            return pd.DataFrame()

        json_text = text[start:end]

        # 关键修复：用 StringIO 包起来
        data = pd.read_json(StringIO(json_text))

        if data.empty:
            return pd.DataFrame()

        df = data.rename(columns={
            "day": "日期",
            "open": "开盘",
            "high": "最高",
            "low": "最低",
            "close": "收盘",
            "volume": "成交量"
        })

        for col in ["开盘", "收盘", "最高", "最低", "成交量"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # 新浪 volume 通常是股数，不是手
        # 这里成交额近似为：成交量 × 收盘价
        df["成交额"] = df["成交量"] * df["收盘"]

        df = df[["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]]

        df = df.dropna().reset_index(drop=True)

        return df

    except Exception as e:
        print(f"获取股票 {code} 新浪日线失败：{e}")
        return pd.DataFrame()


if __name__ == "__main__":
    print("测试获取股票列表：")
    stocks = get_all_stocks()
    print(stocks.head())
    print(stocks.shape)

    print("\n测试获取天齐锂业日线：")
    daily = get_stock_daily("002466")
    print(daily.tail())