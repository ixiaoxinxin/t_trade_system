# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


LLM_LABEL_COLUMNS = [
    "sample_id",
    "provider",
    "model",
    "prompt_version",
    "realized_path_type",
    "execution_quality",
    "label_confidence",
    "needs_manual_review",
    "conflict_fields",
    "reason",
    "created_at",
]

API_USAGE_COLUMNS = [
    "usage_id",
    "provider",
    "model",
    "prompt_version",
    "input_tokens",
    "output_tokens",
    "cost_estimate_cny",
    "status",
    "created_at",
]

LOCAL_ENV_FILE = Path(".env")

PROVIDER_STATUS_COLUMNS = [
    "provider",
    "model",
    "api_key_env",
    "has_api_key",
    "base_url",
    "status",
    "checked_at",
]


def usage_row(
    *,
    provider: str,
    model: str,
    prompt_version: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_estimate_cny: float = 0.0,
    status: str,
) -> dict:
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_provider = provider or "none"
    safe_status = status.replace(" ", "_")

    return {
        "usage_id": f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}_{safe_provider}_{safe_status}",
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_estimate_cny": round(cost_estimate_cny, 6),
        "status": status,
        "created_at": created_at,
    }


def estimate_cost(
    provider_config: dict,
    input_tokens: int,
    output_tokens: int,
) -> float:
    input_price = float(provider_config.get("input_price_cny_per_million", 0) or 0)
    output_price = float(provider_config.get("output_price_cny_per_million", 0) or 0)

    return input_tokens / 1_000_000 * input_price + output_tokens / 1_000_000 * output_price


def load_local_env(path: Path = LOCAL_ENV_FILE) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


def build_provider_status_table(config: dict) -> pd.DataFrame:
    load_local_env()
    llm_config = config.get("llm_labeling", {})
    provider_priority = llm_config.get("provider_priority", [])
    providers = llm_config.get("providers", {})
    enabled = bool(llm_config.get("enabled", False))
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []

    for provider_name in provider_priority:
        provider_config = providers.get(provider_name, {})
        api_key_env = str(provider_config.get("api_key_env", "")).strip()
        base_url = str(provider_config.get("base_url", "")).strip()
        model = str(provider_config.get("model", "")).strip()
        has_api_key = bool(api_key_env and os.environ.get(api_key_env, "").strip())

        if not enabled:
            status = "disabled"
        elif not api_key_env:
            status = "missing_api_key_env_name"
        elif not has_api_key:
            status = "missing_api_key"
        elif not base_url:
            status = "missing_base_url"
        elif not model:
            status = "missing_model"
        else:
            status = "ready"

        rows.append({
            "provider": str(provider_name),
            "model": model,
            "api_key_env": api_key_env,
            "has_api_key": int(has_api_key),
            "base_url": base_url,
            "status": status,
            "checked_at": checked_at,
        })

    return pd.DataFrame(rows, columns=PROVIDER_STATUS_COLUMNS)


def build_prompt(sample: dict, label: dict) -> list[dict]:
    payload = {
        "sample": sample,
        "rule_labels": label,
        "allowed_output": {
            "realized_path_type": ["高开高走", "冲高回落", "探底回升", "弱势震荡", "强势横盘", "数据不足"],
            "execution_quality": ["可执行盈利", "可执行止损", "未触达", "高开无法低吸", "数据不足"],
            "label_confidence": "0到1的小数",
            "needs_manual_review": "布尔值",
            "conflict_fields": "冲突字段数组",
            "reason": "不超过80字的中文说明",
        },
    }

    return [
        {
            "role": "system",
            "content": "你是交易数据标签质检助手。只根据输入做路径标签和质检解释，必须输出严格 JSON。",
        },
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        },
    ]


def call_chat_completion(
    provider_config: dict,
    messages: list[dict],
    timeout_seconds: int,
) -> tuple[dict, int, int]:
    load_local_env()
    api_key_env = str(provider_config.get("api_key_env", "")).strip()
    api_key = os.environ.get(api_key_env, "").strip()

    if not api_key:
        raise RuntimeError(f"missing_api_key:{api_key_env}")

    body = {
        "model": provider_config.get("model", ""),
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        str(provider_config.get("base_url", "")),
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        response_payload = json.loads(response.read().decode("utf-8"))

    content = response_payload["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    usage = response_payload.get("usage", {})

    return parsed, int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)


def build_sample_summary(sample_row: pd.Series, label_row: pd.Series | None) -> tuple[dict, dict]:
    sample = {
        "sample_id": sample_row.get("sample_id", ""),
        "stock_code": sample_row.get("stock_code", ""),
        "stock_name": sample_row.get("stock_name", ""),
        "predict_date": sample_row.get("predict_date", ""),
        "target_date": sample_row.get("target_date", ""),
        "rule_version": sample_row.get("rule_version", ""),
        "data_status": sample_row.get("data_status", ""),
    }

    if label_row is None:
        label = {"label_status": "missing_label"}
    else:
        label = {
            "direction_up_close": label_row.get("direction_up_close", None),
            "touch_buy_range": label_row.get("touch_buy_range", None),
            "hit_1pct_after_touch": label_row.get("hit_1pct_after_touch", None),
            "hit_2pct_after_touch": label_row.get("hit_2pct_after_touch", None),
            "stop_2pct_after_touch": label_row.get("stop_2pct_after_touch", None),
            "first_event": label_row.get("first_event", ""),
            "next_day_high_pct": label_row.get("next_day_high_pct", None),
            "next_day_low_pct": label_row.get("next_day_low_pct", None),
            "realized_path_type": label_row.get("realized_path_type", ""),
            "execution_quality": label_row.get("execution_quality", ""),
        }

    return sample, label


def build_llm_tables(
    config: dict,
    samples_df: pd.DataFrame,
    labels_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    llm_config = config.get("llm_labeling", {})
    prompt_version = str(llm_config.get("prompt_version", "v2.5-labeling-001"))

    if not bool(llm_config.get("enabled", False)):
        return (
            pd.DataFrame(columns=LLM_LABEL_COLUMNS),
            pd.DataFrame([usage_row(
                provider="",
                model="",
                prompt_version=prompt_version,
                status="skipped_disabled",
            )], columns=API_USAGE_COLUMNS),
        )

    provider_priority = llm_config.get("provider_priority", [])
    providers = llm_config.get("providers", {})
    timeout_seconds = int(llm_config.get("request_timeout_seconds", 20) or 20)
    max_daily_cost = float(llm_config.get("max_daily_cost_cny", 20) or 20)
    sample_limit = int(llm_config.get("sample_limit", 20) or 20)
    label_by_sample_id = {
        str(row.get("sample_id", "")): row for _, row in labels_df.iterrows()
    }
    llm_rows = []
    usage_rows = []
    total_cost = 0.0

    if samples_df.empty:
        usage_rows.append(usage_row(
            provider="",
            model="",
            prompt_version=prompt_version,
            status="skipped_no_samples",
        ))
        return pd.DataFrame(columns=LLM_LABEL_COLUMNS), pd.DataFrame(usage_rows, columns=API_USAGE_COLUMNS)

    for sample_index, (_, sample_row) in enumerate(samples_df.iterrows()):
        if sample_index >= sample_limit:
            usage_rows.append(usage_row(
                provider="",
                model="",
                prompt_version=prompt_version,
                status="skipped_sample_limit",
            ))
            break

        sample, label = build_sample_summary(
            sample_row,
            label_by_sample_id.get(str(sample_row.get("sample_id", ""))),
        )
        messages = build_prompt(sample, label)
        sample_completed = False

        if total_cost >= max_daily_cost:
            usage_rows.append(usage_row(
                provider="",
                model="",
                prompt_version=prompt_version,
                status="skipped_cost_limit",
            ))
            break

        for provider_name in provider_priority:
            provider_config = providers.get(provider_name, {})
            model = str(provider_config.get("model", ""))

            try:
                result, input_tokens, output_tokens = call_chat_completion(
                    provider_config=provider_config,
                    messages=messages,
                    timeout_seconds=timeout_seconds,
                )
                cost = estimate_cost(provider_config, input_tokens, output_tokens)
                total_cost += cost
                usage_rows.append(usage_row(
                    provider=str(provider_name),
                    model=model,
                    prompt_version=prompt_version,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_estimate_cny=cost,
                    status="success",
                ))
                llm_rows.append({
                    "sample_id": sample["sample_id"],
                    "provider": str(provider_name),
                    "model": model,
                    "prompt_version": prompt_version,
                    "realized_path_type": result.get("realized_path_type", ""),
                    "execution_quality": result.get("execution_quality", ""),
                    "label_confidence": result.get("label_confidence", None),
                    "needs_manual_review": int(bool(result.get("needs_manual_review", False))),
                    "conflict_fields": json.dumps(result.get("conflict_fields", []), ensure_ascii=False),
                    "reason": result.get("reason", ""),
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                sample_completed = True
                break
            except (RuntimeError, urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                usage_rows.append(usage_row(
                    provider=str(provider_name),
                    model=model,
                    prompt_version=prompt_version,
                    status=f"fallback:{exc}",
                ))

        if not sample_completed:
            usage_rows.append(usage_row(
                provider="",
                model="",
                prompt_version=prompt_version,
                status=f"failed_all_providers:{sample['sample_id']}",
            ))

    return (
        pd.DataFrame(llm_rows, columns=LLM_LABEL_COLUMNS),
        pd.DataFrame(usage_rows, columns=API_USAGE_COLUMNS),
    )
