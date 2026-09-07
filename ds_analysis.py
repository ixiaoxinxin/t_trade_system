# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from llm_labeler import call_chat_completion, estimate_cost, load_local_env, usage_row


CONFIG_FILE = Path("config.yaml")
USAGE_FILE = Path("output/ds_analysis_usage.csv")
MAX_FIELD_CHARS = 48


def load_config(path: Path = CONFIG_FILE) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def get_provider(config: dict[str, Any]) -> tuple[str, dict[str, Any], int]:
    llm_config = config.get("llm_labeling", {})
    priority = llm_config.get("provider_priority", ["deepseek"])
    providers = llm_config.get("providers", {})
    preferred = "deepseek" if "deepseek" in providers else str(priority[0] if priority else "")
    return preferred, providers.get(preferred, {}), int(llm_config.get("request_timeout_seconds", 20) or 20)


def append_usage(rows: list[dict[str, Any]], path: Path = USAGE_FILE) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new_df = pd.DataFrame(rows)
    if path.exists():
        old_df = pd.read_csv(path)
        new_df = pd.concat([old_df, new_df], ignore_index=True)
    new_df.to_csv(path, index=False, encoding="utf-8-sig")


def compact_records(df: pd.DataFrame, columns: list[str], limit: int = 12) -> list[dict[str, Any]]:
    if df.empty:
        return []
    keep = [col for col in columns if col in df.columns]
    if not keep:
        return []
    result = df[keep].head(limit).copy()
    return json.loads(result.fillna("").to_json(orient="records", force_ascii=False))


def compact_text(value: Any, max_chars: int = MAX_FIELD_CHARS) -> str:
    text = str(value).replace("\n", " ").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def call_ds_analysis(
    *,
    prompt_version: str,
    system_prompt: str,
    payload: dict[str, Any],
    fallback: dict[str, str],
    enabled: bool = True,
) -> tuple[dict[str, str], str]:
    config = load_config()
    llm_config = config.get("llm_labeling", {})
    provider, provider_config, timeout_seconds = get_provider(config)
    model = str(provider_config.get("model", "deepseek-chat"))

    if not enabled or not bool(llm_config.get("enabled", False)):
        return fallback, "disabled"

    load_local_env()
    try:
        result, input_tokens, output_tokens = call_chat_completion(
            provider_config,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            timeout_seconds=timeout_seconds,
        )
        cost = estimate_cost(provider_config, input_tokens, output_tokens)
        append_usage([
            usage_row(
                provider=provider,
                model=model,
                prompt_version=prompt_version,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_estimate_cny=cost,
                status="success",
            )
        ])
        merged = fallback.copy()
        merged.update({str(key): compact_text(value) for key, value in result.items() if value is not None})
        return merged, "success"
    except Exception as exc:
        append_usage([
            usage_row(
                provider=provider,
                model=model,
                prompt_version=prompt_version,
                status=f"failed:{type(exc).__name__}",
            )
        ])
        result = fallback.copy()
        result["DS状态"] = compact_text(f"未生成：{exc}")
        return result, "failed"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
