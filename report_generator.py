# report_generator.py
# -*- coding: utf-8 -*-

"""
A股隔日T交易计划生成器 v2.0

升级点：
1. 优先读取 output/final_watchlist.csv
2. 接入 output/market_environment.json
3. 根据市场环境调整交易池和仓位
4. 系统风险日自动降仓
5. 情绪冰点日自动空仓
"""

from pathlib import Path
from datetime import datetime
import json

import pandas as pd

from common import PRODUCT_VERSION, load_yaml_config, normalize_code, safe_float
from contracts import FINAL_WATCHLIST_REQUIRED_COLUMNS, validate_csv_columns, validate_market_environment


CONFIG_FILE = Path("config.yaml")

FINAL_WATCHLIST_FILE = Path("output/final_watchlist.csv")
CANDIDATES_FILE = Path("output/overnight_t_candidates.csv")
MARKET_ENV_FILE = Path("output/market_environment.json")
OUTPUT_FILE = Path("output/daily_plan.md")
FINAL_DECISION_FILE = Path("output/final_decision_v3.0.csv")


def load_config() -> dict:
    default_config = {
        "capital": {
            "single_stock_min": 3000,
            "single_stock_max": 5000,
            "max_trade_count": 2,
        },
        "sector_filter": {
            "enabled": True,
            "max_per_sector": 1,
            "avoid_statuses": ["回避"],
            "cautious_statuses": ["谨慎"],
            "cautious_score_penalty": 8,
        },
    }

    return load_yaml_config(CONFIG_FILE, default_config)


CONFIG = load_config()

SINGLE_STOCK_MIN = float(CONFIG["capital"]["single_stock_min"])
SINGLE_STOCK_MAX = float(CONFIG["capital"]["single_stock_max"])
MAX_TRADE_COUNT = int(CONFIG["capital"]["max_trade_count"])
SECTOR_FILTER = CONFIG.get("sector_filter", {})


def load_market_environment() -> dict:
    """
    读取市场环境判断。
    如果文件不存在，则默认市场环境正常。
    """

    default_env = {
        "市场环境": "未知",
        "风险等级": "未知",
        "是否允许隔夜": "是",
        "建议仓位": "按原计划",
        "交易建议": "未读取到市场环境文件，按原计划执行，但需人工确认。",
    }

    if not MARKET_ENV_FILE.exists():
        return default_env

    try:
        env = json.loads(MARKET_ENV_FILE.read_text(encoding="utf-8"))
        validate_market_environment(env)
        return env
    except Exception:
        return default_env


MARKET_ENV = load_market_environment()


def read_source_data() -> tuple[pd.DataFrame, str]:
    if FINAL_WATCHLIST_FILE.exists():
        df = validate_csv_columns(
            FINAL_WATCHLIST_FILE,
            FINAL_WATCHLIST_REQUIRED_COLUMNS,
            "final_watchlist.csv",
        )
        return df, str(FINAL_WATCHLIST_FILE)

    if CANDIDATES_FILE.exists():
        df = pd.read_csv(CANDIDATES_FILE, dtype={"股票代码": str})
        return df, str(CANDIDATES_FILE)

    raise FileNotFoundError("找不到 final_watchlist.csv 或 overnight_t_candidates.csv")


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)

    default_cols = {
        "候选评分": 0,
        "尾盘评分": 0,
        "最终评分": df["综合评分"] if "综合评分" in df.columns else 0,
        "隔夜建议等级": "C",
        "隔夜建议说明": "无尾盘确认，仅观察。",
        "MA5": 0,
        "收盘价": df["最新收盘价"] if "最新收盘价" in df.columns else 0,
        "最新收盘价": df["收盘价"] if "收盘价" in df.columns else 0,
        "今日振幅": df["最近5日振幅"] if "最近5日振幅" in df.columns else 0,
        "风险等级": "中",
        "所属板块": "",
        "板块数据状态": "未知",
        "板块涨跌幅": 0,
        "主力净流入": 0,
        "板块当日资金排名": 0,
        "板块近5日排名": 0,
        "板块广度": 0,
        "龙头涨幅": 0,
        "板块过滤原因": "",
    }

    for col, default_value in default_cols.items():
        if col not in df.columns:
            df[col] = default_value

    numeric_cols = [
        "候选评分",
        "尾盘评分",
        "最终评分",
        "MA5",
        "收盘价",
        "最新收盘价",
        "今日振幅",
        "板块涨跌幅",
        "主力净流入",
        "板块当日资金排名",
        "板块近5日排名",
        "板块广度",
        "龙头涨幅",
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    return df


def get_base_price(row: pd.Series) -> float:
    ma5 = safe_float(row.get("MA5", 0))
    close_price = safe_float(row.get("收盘价", 0))
    latest_close = safe_float(row.get("最新收盘价", 0))

    if ma5 > 0:
        return ma5

    if close_price > 0:
        return close_price

    return latest_close


def get_low_buy_range(row: pd.Series) -> str:
    ma5 = safe_float(row.get("MA5", 0))
    base_price = get_base_price(row)

    if base_price <= 0:
        return "-"

    if ma5 > 0:
        low = ma5 * 0.99
        high = ma5 * 1.01
    else:
        low = base_price * 0.98
        high = base_price * 0.99

    return f"{low:.2f} - {high:.2f}"


def get_stop_loss(row: pd.Series) -> str:
    base_price = get_base_price(row)
    amplitude = safe_float(row.get("今日振幅", 0))

    if base_price <= 0:
        return "-"

    if amplitude >= 6:
        stop_loss = base_price * 0.96
    elif amplitude >= 4:
        stop_loss = base_price * 0.97
    else:
        stop_loss = base_price * 0.98

    return f"{stop_loss:.2f}"


def get_position_range_by_market(row: pd.Series) -> tuple[float, float, str]:
    """
    根据市场环境返回仓位区间。
    """

    env = MARKET_ENV.get("市场环境", "未知")
    grade = str(row.get("隔夜建议等级", "C"))
    risk_level = str(row.get("风险等级", "中"))

    min_capital = SINGLE_STOCK_MIN
    max_capital = SINGLE_STOCK_MAX
    reason = "按原计划。"

    if env == "正常":
        reason = "市场正常，按原仓位计划。"

    elif env == "偏弱":
        min_capital = max(1000, SINGLE_STOCK_MIN * 0.5)
        max_capital = max(1500, SINGLE_STOCK_MAX * 0.5)
        reason = "市场偏弱，仓位减半。"

    elif env == "系统风险":
        if grade == "A" and risk_level in ["低", "未知"]:
            min_capital = 1000
            max_capital = 2000
            reason = "系统风险日，只允许A级低风险，小仓位。"
        else:
            min_capital = 0
            max_capital = 0
            reason = "系统风险日，非A级低风险不交易。"

    elif env == "情绪冰点":
        min_capital = 0
        max_capital = 0
        reason = "情绪冰点，不隔夜。"

    return min_capital, max_capital, reason


def get_position_advice(row: pd.Series) -> str:
    close_price = safe_float(row.get("收盘价", 0))
    latest_close = safe_float(row.get("最新收盘价", 0))
    price = close_price if close_price > 0 else latest_close

    if price <= 0:
        return "价格异常，不操作。"

    min_capital, max_capital, reason = get_position_range_by_market(row)

    if max_capital <= 0:
        return f"不操作。{reason}"

    min_shares = int(min_capital // price // 100 * 100)
    max_shares = int(max_capital // price // 100 * 100)

    if min_shares <= 0:
        return f"价格偏高，最多100股观察。{reason}"

    if max_shares <= min_shares:
        return f"建议 {min_shares} 股。{reason}"

    return f"建议 {min_shares}-{max_shares} 股。{reason}"


def apply_sector_filter(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or not SECTOR_FILTER.get("enabled", True):
        return df

    result = df.copy()

    if "板块过滤原因" not in result.columns:
        result["板块过滤原因"] = ""

    result["板块过滤原因"] = result["板块过滤原因"].fillna("").astype(str)

    status = result["板块数据状态"].fillna("未知").astype(str)
    avoid_statuses = set(SECTOR_FILTER.get("avoid_statuses", ["回避"]))
    cautious_statuses = set(SECTOR_FILTER.get("cautious_statuses", ["谨慎"]))
    penalty = safe_float(SECTOR_FILTER.get("cautious_score_penalty", 8))

    avoid_mask = status.isin(avoid_statuses)
    result.loc[avoid_mask, "板块过滤原因"] = "板块资金状态回避，不进入交易池。"

    cautious_mask = status.isin(cautious_statuses)
    result.loc[cautious_mask, "最终评分"] = (result.loc[cautious_mask, "最终评分"] - penalty).clip(lower=0)
    result.loc[cautious_mask, "板块过滤原因"] = "板块资金状态谨慎，最终评分降权。"

    return result


def apply_sector_concentration_limit(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or not SECTOR_FILTER.get("enabled", True):
        return df

    max_per_sector = int(SECTOR_FILTER.get("max_per_sector", 1))

    if max_per_sector <= 0 or "所属板块" not in df.columns:
        return df

    result = df.copy()

    if "板块过滤原因" not in result.columns:
        result["板块过滤原因"] = ""

    result["_sector_name"] = result["所属板块"].fillna("").astype(str)
    result["_sector_rank"] = (
        result[result["_sector_name"].ne("")]
        .groupby("_sector_name")
        .cumcount()
        + 1
    )
    result["_sector_rank"] = result["_sector_rank"].fillna(0)

    over_limit_mask = (
        result["隔夜建议等级"].isin(["A", "B"])
        & result["_sector_name"].ne("")
        & (result["_sector_rank"] > max_per_sector)
    )

    result.loc[over_limit_mask, "隔夜建议等级"] = "C"
    result.loc[over_limit_mask, "板块过滤原因"] = (
        "同板块候选超过限制，仅保留评分靠前标的；本标的转入观察。"
    )

    return result.drop(columns=["_sector_name", "_sector_rank"], errors="ignore")


def build_plan_row(row: pd.Series) -> dict:
    return {
        "股票代码": normalize_code(row.get("股票代码", "")),
        "股票名称": format_optional_text(row.get("股票名称", "")),
        "所属板块": format_optional_text(row.get("所属板块", "")),
        "板块状态": format_optional_text(row.get("板块数据状态", "")),
        "板块当日排名": format_optional_int(row.get("板块当日资金排名", "")),
        "板块近5日排名": format_optional_int(row.get("板块近5日排名", "")),
        "板块广度": format_optional_pct(row.get("板块广度", "")),
        "龙头涨幅": format_optional_pct(row.get("龙头涨幅", "")),
        "候选评分": f"{safe_float(row.get('候选评分', 0)):.2f}",
        "尾盘评分": f"{safe_float(row.get('尾盘评分', 0)):.2f}",
        "最终评分": f"{safe_float(row.get('最终评分', 0)):.2f}",
        "风险等级": format_optional_text(row.get("风险等级", "")),
        "隔夜等级": format_optional_text(row.get("隔夜建议等级", "")),
        "参考低吸区间": get_low_buy_range(row),
        "止损价": get_stop_loss(row),
        "仓位建议": get_position_advice(row),
        "板块过滤原因": format_optional_text(row.get("板块过滤原因", "")),
        "隔夜建议说明": format_optional_text(row.get("隔夜建议说明", "")),
    }


def format_optional_text(value) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.lower() in ["nan", "none", "null"]:
        return ""

    return text


def format_optional_int(value) -> str:
    number = safe_float(value, default=0)
    if number <= 0:
        return "-"
    return str(int(number))


def format_optional_pct(value) -> str:
    number = safe_float(value, default=0)
    if number == 0:
        return "-"
    return f"{number:.2f}%"


def make_markdown_table(rows: list[dict]) -> str:
    if not rows:
        return "无。\n"

    headers = [
        "股票代码",
        "股票名称",
        "所属板块",
        "板块状态",
        "板块当日排名",
        "板块近5日排名",
        "板块广度",
        "龙头涨幅",
        "候选评分",
        "尾盘评分",
        "最终评分",
        "风险等级",
        "隔夜等级",
        "参考低吸区间",
        "止损价",
        "仓位建议",
        "板块过滤原因",
        "隔夜建议说明",
    ]

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")

    return "\n".join(lines) + "\n"


def refresh_final_decision() -> tuple[pd.DataFrame, str]:
    try:
        from decision_fusion import run_decision_fusion

        run_decision_fusion()
    except Exception as exc:
        return load_final_decision(), f"融合决策未刷新：{exc}"

    return load_final_decision(), "融合决策已刷新。"


def load_final_decision() -> pd.DataFrame:
    if not FINAL_DECISION_FILE.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(FINAL_DECISION_FILE, dtype={"stock_code": str}, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()

    if "stock_code" in df.columns:
        df["stock_code"] = df["stock_code"].apply(normalize_code)

    return df


def make_final_decision_table(decision_df: pd.DataFrame, *, fixed_only: bool | None = None, limit: int = 12) -> str:
    if decision_df.empty:
        return "无。\n"

    work = decision_df.copy()
    if fixed_only is not None and "is_fixed_holding" in work.columns:
        work = work[work["is_fixed_holding"].astype(str).isin(["True", "true", "1"]) == fixed_only].copy()

    if work.empty:
        return "无。\n"

    work = work.sort_values(["is_fixed_holding", "fusion_score"], ascending=[False, False]).head(limit)

    headers = ["股票", "固定持仓", "最终操作", "融合分", "上涨概率", "+1%概率", "止损概率", "风险收益比", "解释"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]

    for _, row in work.iterrows():
        lines.append(
            "| "
            + " | ".join([
                f"{normalize_code(row.get('stock_code', ''))} {format_optional_text(row.get('stock_name', ''))}",
                "是" if str(row.get("is_fixed_holding", "")).lower() in ["true", "1"] else "否",
                format_optional_text(row.get("final_action", "")),
                f"{safe_float(row.get('fusion_score', 0)):.1f}",
                f"{safe_float(row.get('next_day_up_probability', 0)):.1%}",
                f"{safe_float(row.get('hit_1pct_probability', 0)):.1%}",
                f"{safe_float(row.get('stop_2pct_probability', 0)):.1%}",
                format_optional_text(row.get("risk_reward_ratio", "")),
                format_optional_text(row.get("decision_reason", "")),
            ])
            + " |"
        )

    return "\n".join(lines) + "\n"


def filter_trade_pool_by_market(df: pd.DataFrame) -> pd.DataFrame:
    """
    根据市场环境过滤交易池。
    """

    env = MARKET_ENV.get("市场环境", "未知")

    if env == "情绪冰点":
        return df.iloc[0:0].copy()

    if env == "系统风险":
        return df[
            (df["隔夜建议等级"] == "A")
            & (df["风险等级"].astype(str).isin(["低", "未知"]))
            & (~df["板块数据状态"].astype(str).isin(SECTOR_FILTER.get("avoid_statuses", ["回避"])))
        ].copy()

    return df[
        df["隔夜建议等级"].isin(["A", "B"])
        & (~df["板块数据状态"].astype(str).isin(SECTOR_FILTER.get("avoid_statuses", ["回避"])))
    ].copy()


def generate_daily_plan() -> None:
    df, source_name = read_source_data()

    if df.empty:
        raise ValueError("输入数据为空，无法生成交易计划")

    df = ensure_columns(df)

    df = apply_sector_filter(df)

    df = df.sort_values(
        by=["隔夜建议等级", "最终评分"],
        ascending=[True, False]
    ).reset_index(drop=True)

    df = apply_sector_concentration_limit(df)

    trade_df = filter_trade_pool_by_market(df)
    watch_df = df[df["隔夜建议等级"] == "C"].copy()
    abandon_df = df[df["隔夜建议等级"] == "D"].copy()

    trade_df = trade_df.sort_values("最终评分", ascending=False).head(MAX_TRADE_COUNT)

    trade_rows = [build_plan_row(row) for _, row in trade_df.iterrows()]
    watch_rows = [build_plan_row(row) for _, row in watch_df.iterrows()]
    abandon_rows = [build_plan_row(row) for _, row in abandon_df.iterrows()]
    final_decision_df, final_decision_status = refresh_final_decision()

    today = datetime.now().strftime("%Y-%m-%d")

    env = MARKET_ENV.get("市场环境", "未知")
    env_risk = MARKET_ENV.get("风险等级", "未知")
    env_allow = MARKET_ENV.get("是否允许隔夜", "未知")
    env_position = MARKET_ENV.get("建议仓位", "未知")
    env_advice = MARKET_ENV.get("交易建议", "未读取到交易建议。")

    if trade_df.empty:
        trade_summary = "明日交易池为空：当前市场环境或个股等级不满足隔夜条件，原则上空仓。"
    else:
        trade_summary = f"明日交易池共 {len(trade_df)} 只，最多只做 {MAX_TRADE_COUNT} 只。"

    md = f"""# A股隔日T交易计划 v{PRODUCT_VERSION}

生成日期：{today}

数据来源：`{source_name}`

---

## 一、市场环境判断

| 项目 | 结果 |
|---|---|
| 市场环境 | {env} |
| 风险等级 | {env_risk} |
| 是否允许隔夜 | {env_allow} |
| 建议仓位 | {env_position} |
| 交易建议 | {env_advice} |

---

## 二、执行原则

- 正常：允许 `A/B` 低风险票隔夜
- 偏弱：只做 `A/B` 低风险，仓位减半
- 系统风险：只允许 `A` 级低风险，单票不超过 `2000 元`
- 情绪冰点：不隔夜
- `C` 级只观察，不主动买入
- `D` 级放弃
- 低吸区间不到，不开仓
- 跌破止损价，不补仓，先退出
- 高开冲高优先兑现，不恋战
- 可靠板块状态为 `回避` 的标的不进入交易池
- 同一板块最多进入 `{int(SECTOR_FILTER.get("max_per_sector", 1))}` 只

---

## 三、v3.0 最终操作

{final_decision_status}

### 3.1 明日重点

{make_final_decision_table(final_decision_df, fixed_only=False, limit=8)}

### 3.2 固定持仓处理

{make_final_decision_table(final_decision_df, fixed_only=True, limit=8)}

---

## 四、明日交易池

{trade_summary}

{make_markdown_table(trade_rows)}

---

## 五、观察池

{make_markdown_table(watch_rows)}

---

## 六、放弃池

{make_markdown_table(abandon_rows)}

---

## 七、盘后交易记录字段

| 股票代码 | 是否买入 | 买入价 | 卖出价 | 盈亏 | 是否按计划执行 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |

"""

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(md, encoding="utf-8")

    print(f"交易计划已生成：{OUTPUT_FILE}")
    print(f"数据来源：{source_name}")
    print(f"市场环境：{env}")
    print(f"交易建议：{env_advice}")
    print(f"交易池数量：{len(trade_rows)}")
    print(f"观察池数量：{len(watch_rows)}")
    print(f"放弃池数量：{len(abandon_rows)}")


if __name__ == "__main__":
    generate_daily_plan()
