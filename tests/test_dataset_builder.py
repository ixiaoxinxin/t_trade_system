# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from dataset_builder import build_split, sample_id, yes_no_to_int
from llm_labeler import estimate_cost


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
            split_path = build_split(samples, Path(temp_dir))
            split = json.loads(Path(split_path).read_text(encoding="utf-8"))

        self.assertEqual(split["method"], "chronological")
        self.assertEqual(split["counts"]["total"], 4)
        self.assertEqual(split["train"], ["a", "b"])
        self.assertEqual(split["validation"], ["c"])
        self.assertEqual(split["test"], ["d"])

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


if __name__ == "__main__":
    unittest.main()
