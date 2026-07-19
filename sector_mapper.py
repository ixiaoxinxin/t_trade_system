# -*- coding: utf-8 -*-

"""
板块 / 行业映射模块 v2.4

原则：
1. 使用可维护映射表 output/sector_cache.csv。
2. 不再使用股票名称关键词识别热点或板块。
3. 只输出可追溯字段：所属板块、映射来源、资金状态、板块广度、龙头强度。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from common import normalize_code, safe_float


SECTOR_CACHE_FILE = Path("output/sector_cache.csv")
SECTOR_FLOW_FILE = Path("output/sector_fund_flow.csv")
DAILY_CACHE_DIR = Path("cache/daily")
UNKNOWN_SECTOR_VALUES = {"", "未知", "未标记", "nan", "none", "None", "NULL", "null"}
SECTOR_OUTPUT_COLUMNS = [
    "所属板块",
    "板块映射来源",
    "板块涨跌幅",
    "主力净流入",
    "主力净流入占比",
    "资金排名",
    "板块资金标签",
    "隔夜建议",
    "板块股票数",
    "板块上涨数",
    "板块平均涨跌幅",
    "龙头涨幅",
    "板块广度",
    "板块近5日平均涨幅",
    "板块近5日样本数",
    "板块近5日排名",
    "板块当日资金排名",
    "板块数据状态",
]


def load_sector_mapping(path: Path = SECTOR_CACHE_FILE) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["股票代码", "所属板块"])

    df = pd.read_csv(path, dtype={"股票代码": str})

    if "股票代码" not in df.columns or "所属板块" not in df.columns:
        return pd.DataFrame(columns=["股票代码", "所属板块"])

    df = df[["股票代码", "所属板块"]].copy()
    df["股票代码"] = df["股票代码"].apply(normalize_code)
    df["所属板块"] = df["所属板块"].fillna("").astype(str).str.strip()
    df = df[~df["所属板块"].isin(UNKNOWN_SECTOR_VALUES)]

    return df.drop_duplicates(subset=["股票代码"]).reset_index(drop=True)


def load_sector_flow(path: Path = SECTOR_FLOW_FILE) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path)

    if "板块名称" not in df.columns:
        return pd.DataFrame()

    df = df.copy()
    df["板块名称"] = df["板块名称"].astype(str).str.strip()

    numeric_cols = [
        "板块涨跌幅",
        "主力净流入",
        "主力净流入占比",
        "资金排名",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    keep_cols = [
        "板块名称",
        "板块涨跌幅",
        "主力净流入",
        "主力净流入占比",
        "资金排名",
        "板块资金标签",
        "隔夜建议",
    ]

    existing = [col for col in keep_cols if col in df.columns]

    return df[existing].drop_duplicates(subset=["板块名称"]).reset_index(drop=True)


def calculate_sector_breadth(stock_df: pd.DataFrame, mapping_df: pd.DataFrame) -> pd.DataFrame:
    if stock_df is None or stock_df.empty or mapping_df.empty:
        return pd.DataFrame()

    df = stock_df.copy()

    rename_map = {
        "代码": "股票代码",
        "名称": "股票名称",
        "涨跌幅": "个股涨跌幅",
        "pct_chg": "个股涨跌幅",
    }
    df = df.rename(columns=rename_map)

    required = ["股票代码", "个股涨跌幅"]
    if any(col not in df.columns for col in required):
        return pd.DataFrame()

    df["股票代码"] = df["股票代码"].apply(normalize_code)
    df["个股涨跌幅"] = pd.to_numeric(df["个股涨跌幅"], errors="coerce")

    merged = df.merge(mapping_df, on="股票代码", how="inner")
    merged = merged.dropna(subset=["个股涨跌幅"])

    if merged.empty:
        return pd.DataFrame()

    summary = merged.groupby("所属板块").agg(
        板块股票数=("股票代码", "count"),
        板块上涨数=("个股涨跌幅", lambda s: int((s > 0).sum())),
        板块平均涨跌幅=("个股涨跌幅", "mean"),
        龙头涨幅=("个股涨跌幅", "max"),
    ).reset_index()

    summary["板块广度"] = summary["板块上涨数"] / summary["板块股票数"] * 100

    for col in ["板块平均涨跌幅", "龙头涨幅", "板块广度"]:
        summary[col] = summary[col].round(2)

    return summary


def calculate_sector_breadth_from_cache(mapping_df: pd.DataFrame) -> pd.DataFrame:
    if mapping_df.empty or not DAILY_CACHE_DIR.exists():
        return pd.DataFrame()

    rows = []

    for row in mapping_df.itertuples(index=False):
        code = normalize_code(getattr(row, "股票代码", ""))
        sector = str(getattr(row, "所属板块", "")).strip()
        file_path = DAILY_CACHE_DIR / f"{code}.csv"

        if not sector or not file_path.exists():
            continue

        try:
            df = pd.read_csv(file_path)
        except Exception:
            continue

        if df.empty:
            continue

        df = df.rename(columns={"收盘": "close"})

        if "close" not in df.columns:
            continue

        close = pd.to_numeric(df["close"], errors="coerce").dropna()

        if len(close) < 2:
            continue

        prev_close = safe_float(close.iloc[-2])
        last_close = safe_float(close.iloc[-1])

        if prev_close <= 0:
            continue

        rows.append({
            "股票代码": code,
            "所属板块": sector,
            "个股涨跌幅": (last_close - prev_close) / prev_close * 100,
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return pd.DataFrame()

    summary = df.groupby("所属板块").agg(
        板块股票数=("股票代码", "count"),
        板块上涨数=("个股涨跌幅", lambda s: int((s > 0).sum())),
        板块平均涨跌幅=("个股涨跌幅", "mean"),
        龙头涨幅=("个股涨跌幅", "max"),
    ).reset_index()

    summary["板块广度"] = summary["板块上涨数"] / summary["板块股票数"] * 100

    for col in ["板块平均涨跌幅", "龙头涨幅", "板块广度"]:
        summary[col] = summary[col].round(2)

    return summary


def calculate_sector_5d_rank_from_cache(mapping_df: pd.DataFrame) -> pd.DataFrame:
    if mapping_df.empty or not DAILY_CACHE_DIR.exists():
        return pd.DataFrame()

    mapping = dict(zip(mapping_df["股票代码"], mapping_df["所属板块"]))
    rows = []

    for file_path in DAILY_CACHE_DIR.glob("*.csv"):
        code = normalize_code(file_path.stem)
        sector = mapping.get(code)

        if not sector:
            continue

        try:
            df = pd.read_csv(file_path)
        except Exception:
            continue

        if df.empty:
            continue

        rename_map = {
            "收盘": "close",
            "close": "close",
        }
        df = df.rename(columns=rename_map)

        if "close" not in df.columns or len(df) < 5:
            continue

        close = pd.to_numeric(df["close"], errors="coerce").dropna()

        if len(close) < 5:
            continue

        first_close = safe_float(close.iloc[-5])
        last_close = safe_float(close.iloc[-1])

        if first_close <= 0:
            continue

        rows.append({
            "股票代码": code,
            "所属板块": sector,
            "个股近5日涨幅": (last_close - first_close) / first_close * 100,
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return pd.DataFrame()

    summary = df.groupby("所属板块").agg(
        板块近5日平均涨幅=("个股近5日涨幅", "mean"),
        板块近5日样本数=("股票代码", "count"),
    ).reset_index()
    summary["板块近5日平均涨幅"] = summary["板块近5日平均涨幅"].round(2)
    summary["板块近5日排名"] = summary["板块近5日平均涨幅"].rank(
        method="min",
        ascending=False,
    ).astype(int)

    return summary


def build_sector_profile(stock_df: pd.DataFrame | None = None) -> pd.DataFrame:
    mapping_df = load_sector_mapping()

    if mapping_df.empty:
        return pd.DataFrame()

    profile = mapping_df[["所属板块"]].drop_duplicates().reset_index(drop=True)

    flow_df = load_sector_flow()
    if not flow_df.empty:
        profile = profile.merge(
            flow_df.rename(columns={"板块名称": "所属板块"}),
            on="所属板块",
            how="left",
        )

    breadth_df = calculate_sector_breadth(stock_df, mapping_df)
    if breadth_df.empty:
        breadth_df = calculate_sector_breadth_from_cache(mapping_df)
    if not breadth_df.empty:
        profile = profile.merge(breadth_df, on="所属板块", how="left")

    rank_5d_df = calculate_sector_5d_rank_from_cache(mapping_df)
    if not rank_5d_df.empty:
        profile = profile.merge(rank_5d_df, on="所属板块", how="left")

    if "资金排名" in profile.columns:
        profile["板块当日资金排名"] = profile["资金排名"]

    profile["板块数据状态"] = profile.apply(classify_sector_status, axis=1)

    return profile


def classify_sector_status(row: pd.Series) -> str:
    advice = str(row.get("隔夜建议", ""))
    breadth = safe_float(row.get("板块广度", 0))
    leader_pct = safe_float(row.get("龙头涨幅", 0))

    if advice == "资金未去，避免隔夜":
        return "回避"

    if advice in ["优先观察", "资金流入但价格弱，谨慎"] and breadth >= 50 and leader_pct > 0:
        return "强"

    if advice in ["涨但资金未跟，谨慎", "资金流入但价格弱，谨慎"]:
        return "谨慎"

    if breadth >= 50 and leader_pct > 0:
        return "中性偏强"

    return "未知"


def enrich_candidates_with_sector(
    candidates_df: pd.DataFrame,
    stock_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict]:
    if candidates_df is None or candidates_df.empty:
        return candidates_df, {
            "候选股票数量": 0,
            "映射成功": 0,
            "映射缺失": 0,
            "映射来源": str(SECTOR_CACHE_FILE),
        }

    mapping_df = load_sector_mapping()

    df = candidates_df.copy()
    df["股票代码"] = df["股票代码"].apply(normalize_code)
    df = df.drop(columns=SECTOR_OUTPUT_COLUMNS + ["热点标签"], errors="ignore")

    if mapping_df.empty:
        df["所属板块"] = ""
        df["板块映射来源"] = "缺少 sector_cache.csv"
        return df, {
            "候选股票数量": len(df),
            "映射成功": 0,
            "映射缺失": len(df),
            "映射来源": str(SECTOR_CACHE_FILE),
        }

    df = df.merge(mapping_df, on="股票代码", how="left")
    df["所属板块"] = df["所属板块"].fillna("")
    df["板块映射来源"] = df["所属板块"].apply(
        lambda value: str(SECTOR_CACHE_FILE) if str(value).strip() else "未匹配"
    )

    profile = build_sector_profile(stock_df=stock_df)

    if not profile.empty:
        df = df.merge(profile, on="所属板块", how="left")

    mapped_count = int(df["所属板块"].astype(str).str.strip().ne("").sum())

    stats = {
        "候选股票数量": len(df),
        "映射成功": mapped_count,
        "映射缺失": len(df) - mapped_count,
        "映射来源": str(SECTOR_CACHE_FILE),
    }

    return df, stats


def print_sector_stats(stats: dict) -> None:
    print("\n板块/行业映射统计：")
    print(f"候选股票数量：{stats.get('候选股票数量', 0)}")
    print(f"映射成功：{stats.get('映射成功', 0)}")
    print(f"映射缺失：{stats.get('映射缺失', 0)}")
    print(f"映射来源：{stats.get('映射来源', '')}")
