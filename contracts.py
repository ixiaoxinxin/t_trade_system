# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path

import pandas as pd


FINAL_WATCHLIST_REQUIRED_COLUMNS = [
    "股票代码",
    "股票名称",
    "候选评分",
    "尾盘评分",
    "最终评分",
    "隔夜建议等级",
    "隔夜建议说明",
    "分时结构标签",
    "尾盘抢筹标签",
]

MARKET_ENV_REQUIRED_KEYS = [
    "市场环境",
    "风险等级",
    "是否允许隔夜",
    "建议仓位",
    "交易建议",
]


def validate_columns(df: pd.DataFrame, required_columns: list[str], source_name: str) -> None:
    missing = [col for col in required_columns if col not in df.columns]

    if missing:
        raise ValueError(
            f"{source_name} 缺少必需字段：{', '.join(missing)}。"
            "请先运行上游脚本生成完整文件。"
        )


def validate_csv_columns(path: str | Path, required_columns: list[str], source_name: str) -> pd.DataFrame:
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"找不到文件：{file_path}，请先运行上游脚本。")

    df = pd.read_csv(file_path, dtype={"股票代码": str})

    if df.empty:
        raise ValueError(f"{file_path} 为空，无法继续。")

    validate_columns(df, required_columns, source_name)

    return df


def validate_market_environment(env: dict) -> None:
    missing = [key for key in MARKET_ENV_REQUIRED_KEYS if key not in env]

    if missing:
        raise ValueError(f"market_environment.json 缺少必需字段：{', '.join(missing)}。")
