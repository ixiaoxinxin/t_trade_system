# market_environment.py
# -*- coding: utf-8 -*-

from pathlib import Path
from datetime import datetime
from urllib.request import Request, urlopen
import json

import pandas as pd


OUTPUT_DIR = Path("output")

OUTPUT_CSV = OUTPUT_DIR / "market_environment.csv"
OUTPUT_MD = OUTPUT_DIR / "market_environment.md"
OUTPUT_JSON = OUTPUT_DIR / "market_environment.json"

SECTOR_FLOW_CSV = OUTPUT_DIR / "sector_fund_flow.csv"
SECTOR_FLOW_MD = OUTPUT_DIR / "sector_fund_flow.md"


INDEX_MAP = {
    "s_sh000001": "上证指数",
    "s_sz399001": "深证成指",
    "s_sz399006": "创业板指",
}


CONFIG = {
    "top_sector_count": 10,
    "avoid_sector_count": 10,
    "sector_hot_min_inflow": 0,
}


def safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def fetch_sina_index_quotes() -> pd.DataFrame:
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

            rows.append({
                "指数代码": code,
                "指数名称": INDEX_MAP.get(code, parts[0]),
                "最新点位": safe_float(parts[1]),
                "涨跌点": safe_float(parts[2]),
                "涨跌幅": safe_float(parts[3]),
            })

        except Exception:
            continue

    return pd.DataFrame(rows)


def fetch_sector_fund_flow() -> pd.DataFrame:
    """
    板块资金流。
    优先使用 AKShare 东方财富板块资金流接口。
    如果失败，不中断主流程。
    """

    try:
        import akshare as ak

        df = ak.stock_sector_fund_flow_rank(indicator="今日")

        if df is None or df.empty:
            return pd.DataFrame()

        df = df.copy()

        rename_map = {
            "名称": "板块名称",
            "今日涨跌幅": "板块涨跌幅",
            "今日主力净流入-净额": "主力净流入",
            "今日主力净流入-净占比": "主力净流入占比",
            "今日超大单净流入-净额": "超大单净流入",
            "今日大单净流入-净额": "大单净流入",
        }

        df = df.rename(columns=rename_map)

        keep_cols = [
            "板块名称",
            "板块涨跌幅",
            "主力净流入",
            "主力净流入占比",
            "超大单净流入",
            "大单净流入",
        ]

        existing = [col for col in keep_cols if col in df.columns]
        df = df[existing].copy()

        for col in ["板块涨跌幅", "主力净流入", "主力净流入占比", "超大单净流入", "大单净流入"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["主力净流入"])
        df = df.sort_values("主力净流入", ascending=False).reset_index(drop=True)
        df["资金排名"] = range(1, len(df) + 1)

        df["板块资金标签"] = df["主力净流入"].apply(
            lambda x: "资金流入" if x > 0 else "资金流出"
        )

        df["隔夜建议"] = df.apply(classify_sector_advice, axis=1)

        return df

    except Exception as e:
        print(f"板块资金流获取失败：{e}")
        return pd.DataFrame()


def classify_sector_advice(row: pd.Series) -> str:
    inflow = safe_float(row.get("主力净流入", 0))
    pct = safe_float(row.get("板块涨跌幅", 0))

    if inflow > 0 and pct >= 0:
        return "优先观察"

    if inflow > 0 and pct < 0:
        return "资金流入但价格弱，谨慎"

    if inflow <= 0 and pct >= 0:
        return "涨但资金未跟，谨慎"

    return "资金未去，避免隔夜"


def classify_market_environment(index_df: pd.DataFrame, sector_df: pd.DataFrame) -> dict:
    if index_df.empty:
        return {
            "市场环境": "未知",
            "风险等级": "未知",
            "是否允许隔夜": "否",
            "建议仓位": "0",
            "交易建议": "指数数据获取失败，不建议隔夜。",
        }

    pct_map = dict(zip(index_df["指数名称"], index_df["涨跌幅"]))

    sh_pct = safe_float(pct_map.get("上证指数", 0))
    sz_pct = safe_float(pct_map.get("深证成指", 0))
    cy_pct = safe_float(pct_map.get("创业板指", 0))

    if sh_pct <= -1.5 or sz_pct <= -2.0 or cy_pct <= -2.0:
        env = "情绪冰点"
        risk = "极高"
        allow = "否"
        position = "0"
        advice = "情绪冰点，不建议隔夜。"

    elif sh_pct <= -1.0 or sz_pct <= -1.5 or cy_pct <= -1.5:
        env = "系统风险"
        risk = "高"
        allow = "谨慎"
        position = "单票不超过2000元"
        advice = "系统风险日，只允许A级低风险，小仓位观察。"

    elif sh_pct <= -0.5 or sz_pct <= -1.0 or cy_pct <= -1.0:
        env = "偏弱"
        risk = "中高"
        allow = "谨慎"
        position = "仓位减半"
        advice = "市场偏弱，只做A/B低风险票，仓位减半。"

    else:
        env = "正常"
        risk = "中低"
        allow = "是"
        position = "按原计划"
        advice = "市场环境正常，可按A/B低风险策略执行。"

    hot_sectors = []
    avoid_sectors = []

    if not sector_df.empty:
        hot_sectors = (
            sector_df[sector_df["隔夜建议"].isin(["优先观察", "资金流入但价格弱，谨慎"])]
            .head(5)["板块名称"]
            .astype(str)
            .tolist()
        )

        avoid_sectors = (
            sector_df[sector_df["隔夜建议"].eq("资金未去，避免隔夜")]
            .tail(5)["板块名称"]
            .astype(str)
            .tolist()
        )

    return {
        "市场环境": env,
        "风险等级": risk,
        "是否允许隔夜": allow,
        "建议仓位": position,
        "交易建议": advice,
        "上证涨跌幅": sh_pct,
        "深成指涨跌幅": sz_pct,
        "创业板涨跌幅": cy_pct,
        "资金流入方向": "、".join(hot_sectors) if hot_sectors else "暂无",
        "资金回避方向": "、".join(avoid_sectors) if avoid_sectors else "暂无",
    }


def build_market_markdown(index_df: pd.DataFrame, sector_df: pd.DataFrame, env_result: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    top_sector_df = sector_df.head(CONFIG["top_sector_count"]) if not sector_df.empty else pd.DataFrame()
    avoid_sector_df = sector_df.tail(CONFIG["avoid_sector_count"]) if not sector_df.empty else pd.DataFrame()

    md = f"""# 市场环境报告 v2.3.0

生成时间：{now}

---

## 一、市场判断

| 项目 | 结果 |
|---|---|
| 市场环境 | {env_result.get("市场环境", "")} |
| 风险等级 | {env_result.get("风险等级", "")} |
| 是否允许隔夜 | {env_result.get("是否允许隔夜", "")} |
| 建议仓位 | {env_result.get("建议仓位", "")} |
| 交易建议 | {env_result.get("交易建议", "")} |
| 资金流入方向 | {env_result.get("资金流入方向", "")} |
| 资金回避方向 | {env_result.get("资金回避方向", "")} |

---

## 二、指数表现

{index_df.to_markdown(index=False) if not index_df.empty else "指数数据为空。"}

---

## 三、资金主要流入板块

{top_sector_df.to_markdown(index=False) if not top_sector_df.empty else "暂无板块资金数据。"}

---

## 四、资金回避板块

{avoid_sector_df.to_markdown(index=False) if not avoid_sector_df.empty else "暂无板块资金数据。"}

---

## 五、执行规则

| 条件 | 操作 |
|---|---|
| 资金流入板块 + 个股A/B | 优先观察 |
| 资金未流入板块 | 不做或降权 |
| 高Beta板块 + 弱市 | 降仓或放弃 |
| 同一板块多只候选 | 最多选1只 |
"""

    return md


def export_sector_markdown(sector_df: pd.DataFrame) -> None:
    if sector_df.empty:
        SECTOR_FLOW_MD.write_text("# 板块资金流\n\n暂无数据。", encoding="utf-8")
        return

    md = f"""# 板块资金流 v2.3.0

生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

## 资金流入前10

{sector_df.head(10).to_markdown(index=False)}

---

## 资金流出后10

{sector_df.tail(10).to_markdown(index=False)}
"""

    SECTOR_FLOW_MD.write_text(md, encoding="utf-8")


def run_market_environment() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("开始获取指数环境...")
    index_df = fetch_sina_index_quotes()

    print("开始获取板块资金流...")
    sector_df = fetch_sector_fund_flow()

    env_result = classify_market_environment(index_df, sector_df)

    output_df = index_df.copy()

    for key, value in env_result.items():
        if key not in output_df.columns:
            output_df[key] = value

    output_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    OUTPUT_JSON.write_text(json.dumps(env_result, ensure_ascii=False, indent=2), encoding="utf-8")

    if not sector_df.empty:
        sector_df.to_csv(SECTOR_FLOW_CSV, index=False, encoding="utf-8-sig")

    OUTPUT_MD.write_text(
        build_market_markdown(index_df, sector_df, env_result),
        encoding="utf-8",
    )

    export_sector_markdown(sector_df)

    print("市场环境判断完成。")
    print(f"市场环境：{env_result.get('市场环境')}")
    print(f"资金流入方向：{env_result.get('资金流入方向')}")


if __name__ == "__main__":
    run_market_environment()