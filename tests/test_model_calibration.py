# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

import pandas as pd

from model_calibration import apply_calibration, build_calibration_table, calculate_brier, calibration_bucket


class ModelCalibrationTest(unittest.TestCase):
    def test_calibration_bucket_uses_20pct_ranges(self):
        self.assertEqual(calibration_bucket(0.01), "0-20%")
        self.assertEqual(calibration_bucket(0.39), "20-40%")
        self.assertEqual(calibration_bucket(0.99), "80-100%")

    def test_calculate_brier(self):
        score = calculate_brier(pd.Series([1, 0]), pd.Series([0.8, 0.2]))
        self.assertAlmostEqual(score, 0.04)

    def test_build_and_apply_calibration(self):
        predictions = pd.DataFrame([
            {"sample_id": "a", "hit_1pct_probability": 0.75, "hit_2pct_probability": 0.65, "stop_2pct_probability": 0.2},
            {"sample_id": "b", "hit_1pct_probability": 0.25, "hit_2pct_probability": 0.15, "stop_2pct_probability": 0.8},
        ])
        labels = pd.DataFrame([
            {"sample_id": "a", "hit_1pct_after_touch": 1, "hit_2pct_after_touch": 1, "stop_2pct_after_touch": 0},
            {"sample_id": "b", "hit_1pct_after_touch": 0, "hit_2pct_after_touch": 0, "stop_2pct_after_touch": 1},
        ])

        calibration_df, summary = build_calibration_table(predictions, labels)
        calibrated = apply_calibration(predictions, summary)

        self.assertFalse(calibration_df.empty)
        self.assertIn("calibrated_hit_1pct_probability", calibrated.columns)
        self.assertIn("calibrated_risk_adjusted_1pct", calibrated.columns)


if __name__ == "__main__":
    unittest.main()
