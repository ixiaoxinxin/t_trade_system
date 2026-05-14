# market_environment.py
# -*- coding: utf-8 -*-

"""
A股隔日T系统 v1.9.0：市场环境过滤器

用途：
1. 判断当天是否系统性风险日
2. 决定是否允许隔夜
3. 给尾盘交易提供大盘风控参考

输出：
1. output/market_environment.csv
2. output/market_environment.md
"""

from pathlib import Path
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import quote
import json

import pandas as pd


OUTPUT_DIR = Path("output")
OUTPUT_CSV = OUTPUT_DIR / "market_environment.csv"
OUTPUT_MD = OUTPUT_DIR / "market_environment.md"
OUTPUT_JSON = OUTPUT_DIR / "market_environment.json"


INDEX_MAP = {
    "s_sh000001": "上证指数",
    "s_sz399001": "深证成指",
    "s_sz399006": "创业板指",
}


def safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def fetch_sina_index_quotes() -> pd.DataFrame:
    """
    使用新浪公开指数接口获取指数行情。

    新浪格式示例：
    var hq_str_s_sh000001="上证指数,4199.19,-43.38,-1.02,xxxx,xxxx";
    """

    codes = ",".join(INDEX_MAP.keys())
    url = f"https://hq.sinajs.cn/list={codes}"

    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        },
    )

    with urlopen(req, timeout=10) as response:
        raw = response.read().decode("gbk", errors="ignore")

    rows = []

    for line in raw.splitlines():
        if not line.strip():
            continue

        try:
            left, right = line.split("=", 1)
            code = left.split("hq_str_")[-1].strip()
            content = right.strip().strip('";')
            parts = content.split(",")

            if len(parts) < 4:
                continue

            name = parts[0]
            latest = safe_float(parts[1])
            change = safe_float(parts[2])
            pct_chg = safe_float(parts[3])

            rows.append({
                "指数代码": code,
                "指数名称": INDEX_MAP.get(code, name),
                "最新点位": latest,
                "涨跌点": change,
                "涨跌幅": pct_chg,
            })

        except Exception:
            continue

    return pd.DataFrame(rows)


def classify_market_environment(df: pd.DataFrame) -> dict:
    """
    判断市场环境。
    """

    if df.empty:
        return {
            "市场环境": "未知",
            "风险等级": "未知",
            "是否允许隔夜": "否",
            "建议仓位": "0",
            "交易建议": "指数数据获取失败，不建议隔夜。",
        }

    pct_map = dict(zip(df["指数名称"], df["涨跌幅"]))

    sh_pct = safe_float(pct_map.get("上证指数", 0))
    sz_pct = safe_float(pct_map.get("深证成指", 0))
    cy_pct = safe_float(pct_map.get("创业板指", 0))

    # 情绪冰点
    if sh_pct <= -1.5 or sz_pct <= -2.0 or cy_pct <= -2.0:
        env = "情绪冰点"
        risk = "极高"
        allow = "否"
        position = "0"
        advice = "市场处于情绪冰点，不建议隔夜。"

    # 系统风险
    elif sh_pct <= -1.0 or sz_pct <= -1.5 or cy_pct <= -1.5:
        env = "系统风险"
        risk = "高"
        allow = "谨慎"
        position = "单票不超过2000元"
        advice = "系统性风险日，只允许A级低风险票，小仓位观察。"

    # 偏弱
    elif sh_pct <= -0.5 or sz_pct <= -1.0 or cy_pct <= -1.0:
        env = "偏弱"
        risk = "中高"
        allow = "谨慎"
        position = "仓位减半"
        advice = "市场偏弱，只做A/B低风险票，仓位减半。"

    # 正常
    else:
        env = "正常"
        risk = "中低"
        allow = "是"
        position = "按原计划"
        advice = "市场环境正常，可按A/B低风险策略执行。"

    return {
        "市场环境": env,
        "风险等级": risk,
        "是否允许隔夜": allow,
        "建议仓位": position,
        "交易建议": advice,
        "上证涨跌幅": sh_pct,
        "深成指涨跌幅": sz_pct,
        "创业板涨跌幅": cy_pct,
    }


def build_markdown(index_df: pd.DataFrame, env_result: dict) -> str:
    """
    生成 Markdown 报告。
    """

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    md = f"""# 市场环境报告 v1.9.0

生成时间：{now}

---

## 一、指数表现

{index_df.to_markdown(index=False) if not index_df.empty else "指数数据为空。"}

---

## 二、市场环境判断

| 项目 | 结果 |
|---|---|
| 市场环境 | {env_result.get("市场环境", "")} |
| 风险等级 | {env_result.get("风险等级", "")} |
| 是否允许隔夜 | {env_result.get("是否允许隔夜", "")} |
| 建议仓位 | {env_result.get("建议仓位", "")} |
| 交易建议 | {env_result.get("交易建议", "")} |

---

## 三、执行规则

| 市场环境 | 执行规则 |
|---|---|
| 正常 | 允许 A/B 低风险票隔夜 |
| 偏弱 | 仓位减半，只做 A/B 低风险 |
| 系统风险 | 只允许 A 级低风险，单票不超过 2000 元 |
| 情绪冰点 | 不隔夜 |

---

## 四、说明

如果当天指数大跌，个股午盘验证结果可能被系统性风险污染。  
这种情况下，不应直接否定个股尾盘结构，而应优先降低仓位或暂停隔夜。
"""

    return md


def run_market_environment() -> None:
    """
    主流程。
    """

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("开始获取市场环境数据...")

    index_df = fetch_sina_index_quotes()

    if index_df.empty:
        print("指数数据获取失败。")

    env_result = classify_market_environment(index_df)

    # CSV：指数明细 + 环境判断字段
    output_df = index_df.copy()

    for key, value in env_result.items():
        if key not in output_df.columns:
            output_df[key] = value

    output_df.to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    # JSON：给后续策略模块调用
    OUTPUT_JSON.write_text(
        json.dumps(env_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Markdown
    OUTPUT_MD.write_text(
        build_markdown(index_df, env_result),
        encoding="utf-8",
    )

    print("市场环境判断完成。")
    print(f"CSV：{OUTPUT_CSV}")
    print(f"Markdown：{OUTPUT_MD}")
    print(f"JSON：{OUTPUT_JSON}")
    print(f"市场环境：{env_result.get('市场环境')}")
    print(f"交易建议：{env_result.get('交易建议')}")


if __name__ == "__main__":
    run_market_environment()