# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
import json

from common import PRODUCT_VERSION, now_text


OUTPUT_FILE = Path("output/run_manifest.json")


def write_run_manifest(
    *,
    command: str,
    steps: list[dict],
    outputs: list[str],
    config_summary: dict | None = None,
) -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "product_version": PRODUCT_VERSION,
        "generated_at": now_text(),
        "command": command,
        "config_summary": config_summary or {},
        "steps": steps,
        "outputs": outputs,
        "success": all(step.get("success") for step in steps),
    }

    OUTPUT_FILE.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
