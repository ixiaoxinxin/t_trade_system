# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

import dataset_builder
from dataset_builder import build_daily_cache_features, sample_id, yes_no_to_int
from dataset_splitter import build_time_series_split
from llm_labeler import build_provider_status_table, estimate_cost, load_local_env


class DatasetBuilderTest(unittest.TestCase):
    def test_sample_id_normalizes_stock_code(self):
        self.assertEqual(
            sample_id("2378", "2026-07-19", "v2.0"),
            "002378_2026-07-19_v2.0",
        )

    def test_yes_no_to_int(self):
        self.assertEqual(yes_no_to_int("是"), 1)
        self.assertEqual(yes_no_to_int("否"), 0)
        self.assertIsNone(yes_no_to_int("待验证"))

    def test_build_split_uses_chronological_order(self):
        samples = pd.DataFrame([
            {"sample_id": "b", "predict_date": "2026-07-20"},
            {"sample_id": "a", "predict_date": "2026-07-19"},
            {"sample_id": "c", "predict_date": "2026-07-21"},
            {"sample_id": "d", "predict_date": "2026-07-22"},
        ])

        with TemporaryDirectory() as temp_dir:
            split_path = build_time_series_split(samples, Path(temp_dir))
            split = json.loads(Path(split_path).read_text(encoding="utf-8"))

        self.assertEqual(split["method"], "chronological_fallback")
        self.assertEqual(split["counts"]["total"], 4)
        self.assertEqual(split["train"], ["a", "b"])
        self.assertEqual(split["validation"], ["c"])
        self.assertEqual(split["test"], ["d"])
        self.assertEqual(split["date_ranges"]["all"]["start"], "2026-07-19")

    def test_estimate_cost_uses_provider_prices(self):
        cost = estimate_cost(
            {
                "input_price_cny_per_million": 1,
                "output_price_cny_per_million": 5,
            },
            input_tokens=1000,
            output_tokens=2000,
        )

        self.assertEqual(cost, 0.011)

    def test_daily_cache_features_cover_core_fields(self):
        with TemporaryDirectory() as temp_dir:
            original_cache_dir = dataset_builder.CACHE_DAILY_DIR
            dataset_builder.CACHE_DAILY_DIR = Path(temp_dir)

            try:
                rows = []

                for i in range(25):
                    close = 10 + i * 0.1
                    rows.append({
                        "日期": f"2026-06-{i + 1:02d}",
                        "开盘": close - 0.05,
                        "收盘": close,
                        "最高": close + 0.2,
                        "最低": close - 0.2,
                        "成交量": 1000 + i * 10,
                        "成交额": (1000 + i * 10) * close,
                    })

                pd.DataFrame(rows).to_csv(Path(temp_dir) / "002378.csv", index=False)
                features = build_daily_cache_features("2378", "2026-06-25")
            finally:
                dataset_builder.CACHE_DAILY_DIR = original_cache_dir

        self.assertIsNotNone(features["ret_20d"])
        self.assertIsNotNone(features["ma20_gap"])
        self.assertIsNotNone(features["atr_14"])
        self.assertIsNotNone(features["hist_vol_20"])
        self.assertIsNotNone(features["body_pct"])
        self.assertIsNotNone(features["volume_ratio"])

    def test_provider_status_checks_key_presence_without_exposing_value(self):
        config = {
            "llm_labeling": {
                "enabled": True,
                "provider_priority": ["deepseek"],
                "providers": {
                    "deepseek": {
                        "api_key_env": "DEEPSEEK_API_KEY_FOR_TEST",
                        "base_url": "https://api.deepseek.com/chat/completions",
                        "model": "deepseek-chat",
                    },
                },
            },
        }

        status_df = build_provider_status_table(config)

        self.assertEqual(status_df.iloc[0]["provider"], "deepseek")
        self.assertEqual(status_df.iloc[0]["has_api_key"], 0)
        self.assertEqual(status_df.iloc[0]["status"], "missing_api_key")
        self.assertNotIn("sk-", status_df.to_string())

    def test_load_local_env_reads_key_without_overriding_existing_value(self):
        with TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "LOCAL_ENV_TEST_KEY=from_file\nLOCAL_ENV_EXISTING=from_file\n",
                encoding="utf-8",
            )
            os.environ.pop("LOCAL_ENV_TEST_KEY", None)
            os.environ["LOCAL_ENV_EXISTING"] = "existing"

            try:
                load_local_env(env_path)

                self.assertEqual(os.environ["LOCAL_ENV_TEST_KEY"], "from_file")
                self.assertEqual(os.environ["LOCAL_ENV_EXISTING"], "existing")
            finally:
                os.environ.pop("LOCAL_ENV_TEST_KEY", None)
                os.environ.pop("LOCAL_ENV_EXISTING", None)


if __name__ == "__main__":
    unittest.main()
