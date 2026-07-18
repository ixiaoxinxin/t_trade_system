# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


PRODUCT_VERSION = "2.0"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_code(code: Any) -> str:
    if pd.isna(code):
        return ""

    text = str(code).strip()

    if "." in text:
        text = text.split(".")[0]

    text = text.replace("sh", "").replace("sz", "")

    return text.zfill(6)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default

        text = str(value).strip().replace(",", "")

        if text in ["", "-", "--", "None", "nan", "null"]:
            return default

        return float(text)
    except Exception:
        return default


def load_yaml_config(path: str | Path, defaults: dict) -> dict:
    config_path = Path(path)

    if not config_path.exists():
        return defaults.copy()

    try:
        with config_path.open("r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
    except Exception:
        return defaults.copy()

    def deep_merge(default_value: Any, user_value: Any) -> Any:
        if isinstance(default_value, dict) and isinstance(user_value, dict):
            merged_dict = default_value.copy()

            for key, value in user_value.items():
                merged_dict[key] = deep_merge(merged_dict.get(key), value)

            return merged_dict

        return default_value if user_value is None else user_value

    merged = defaults.copy()

    for section, values in defaults.items():
        merged[section] = deep_merge(values, user_config.get(section))

    for section, values in user_config.items():
        if section not in merged:
            merged[section] = values

    return merged


def read_csv_with_code(path: str | Path) -> pd.DataFrame:
    file_path = Path(path)

    if not file_path.exists():
        return pd.DataFrame()

    df = pd.read_csv(file_path, dtype={"股票代码": str})

    if "股票代码" in df.columns:
        df["股票代码"] = df["股票代码"].apply(normalize_code)

    return df
