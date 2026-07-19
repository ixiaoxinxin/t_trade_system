# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

import pandas as pd

from prediction_review import build_review_frame, build_scorecard, probability_bucket, range_overlap


class PredictionReviewTest(unittest.TestCase):
    def test_probability_bucket(self):
        self.assertEqual(probability_bucket(0.1), "0-20%")
        self.assertEqual(probability_bucket(0.5), "40-60%")
        self.assertEqual(probability_bucket(0.9), "80-100%")

    def test_build_review_frame_aligns_predictions_and_labels(self):
        labels = pd.DataFrame([
            {
                "sample_id": "a",
                "stock_code": "2378",
                "stock_name": "章源钨业",
                "predict_date": "2026-07-19",
                "target_date": "2026-07-20",
                "direction_up_close": 1,
                "hit_1pct_after_touch": 1,
                "hit_2pct_after_touch": 0,
                "stop_2pct_after_touch": 0,
                "touch_buy_range": 1,
                "first_event": "hit_1pct",
                "next_day_high_pct": 2.5,
                "next_day_low_pct": -0.8,
                "realized_path_type": "",
                "execution_quality": "可执行",
                "market_regime": "正常",
                "sector_name": "小金属",
            }
        ])
        direction = pd.DataFrame([{"sample_id": "a", "model_version": "v2.6", "next_day_up_probability": 0.7}])
        profit = pd.DataFrame([
            {
                "sample_id": "a",
                "model_version": "v2.7",
                "hit_1pct_probability": 0.8,
                "hit_2pct_probability": 0.4,
                "stop_2pct_probability": 0.2,
            }
        ])
        calibrated = pd.DataFrame([
            {
                "sample_id": "a",
                "calibration_model_version": "v2.8",
                "calibrated_hit_1pct_probability": 0.75,
                "calibrated_hit_2pct_probability": 0.35,
                "calibrated_stop_2pct_probability": 0.25,
            }
        ])

        review = build_review_frame(labels, direction, profit, calibrated)

        self.assertEqual(review.iloc[0]["stock_code"], "002378")
        self.assertEqual(review.iloc[0]["direction_hit"], 1)
        self.assertEqual(review.iloc[0]["hit_1pct_bucket"], "80-100%")
        self.assertEqual(review.iloc[0]["intraday_path_label"], "先涨达标")
        self.assertEqual(review.iloc[0]["buy_range_executable"], 1)
        self.assertIn("range_overlap_rate", review.columns)

    def test_scorecard_contains_core_metrics(self):
        review = pd.DataFrame([
            {
                "direction_hit": 1,
                "hit_1pct_after_touch": 1,
                "hit_2pct_after_touch": 0,
                "stop_2pct_after_touch": 0,
                "hit_1pct_probability": 0.8,
                "hit_2pct_probability": 0.4,
                "stop_2pct_probability": 0.2,
                "calibrated_hit_1pct_probability": 0.7,
                "calibrated_hit_2pct_probability": 0.3,
                "calibrated_stop_2pct_probability": 0.2,
                "market_regime": "正常",
                "sector_name": "小金属",
                "hit_1pct_bucket": "80-100%",
                "hit_2pct_bucket": "40-60%",
                "stop_2pct_bucket": "20-40%",
                "range_coverage_rate": 0.8,
                "range_overlap_rate": 0.5,
                "buy_range_executable": 1,
                "intraday_path_label": "先涨达标",
            }
        ])

        scorecard = build_scorecard(review)

        self.assertIn("direction_hit_rate", scorecard["metric_name"].tolist())
        self.assertIn("hit_1pct_brier", scorecard["metric_name"].tolist())
        self.assertIn("range_overlap_rate", scorecard["metric_name"].tolist())
        self.assertIn("intraday_path_distribution", scorecard["metric_name"].tolist())

    def test_range_overlap(self):
        coverage, overlap = range_overlap(-1, 3, -2, 2)
        self.assertGreater(coverage, 0)
        self.assertGreater(overlap, 0)


if __name__ == "__main__":
    unittest.main()
