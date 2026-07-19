# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

import pandas as pd

from probability_model import build_prediction_rows, probability_risk_reward, probability_signal, prepare_features


class ProbabilityModelTest(unittest.TestCase):
    def test_probability_signal_prioritizes_stop_risk(self):
        self.assertEqual(probability_signal(0.60, 0.40, 0.70), "风险优先")
        self.assertEqual(probability_signal(0.62, 0.58, 0.20), "进攻")
        self.assertEqual(probability_signal(0.58, 0.30, 0.30), "偏多")
        self.assertEqual(probability_signal(0.30, 0.20, 0.50), "放弃")

    def test_probability_risk_reward_is_positive(self):
        self.assertGreater(probability_risk_reward(0.6, 0.3, 0.2), 0)

    def test_prepare_features_drops_target_labels(self):
        df = pd.DataFrame([
            {
                "sample_id": "1",
                "stock_code": "002378",
                "hit_1pct_after_touch": 1,
                "hit_2pct_after_touch": 0,
                "stop_2pct_after_touch": 0,
                "final_score": 88,
                "market_regime": "正常",
            }
        ])

        features, columns = prepare_features(df)

        self.assertNotIn("hit_1pct_after_touch", columns)
        self.assertNotIn("hit_2pct_after_touch", columns)
        self.assertNotIn("stop_2pct_after_touch", columns)
        self.assertIn("final_score", columns)
        self.assertEqual(len(features), 1)

    def test_build_prediction_rows_outputs_risk_fields(self):
        df = pd.DataFrame([
            {
                "sample_id": "002378_2026-07-19_v2.0",
                "stock_code": "2378",
                "stock_name": "章源钨业",
                "predict_date": "2026-07-19",
                "rule_version": "v2.0",
                "market_regime": "正常",
                "sector_name": "小金属",
            }
        ])
        rows = build_prediction_rows(
            df,
            {
                "hit_1pct_after_touch": [0.7],
                "hit_2pct_after_touch": [0.4],
                "stop_2pct_after_touch": [0.2],
            },
        )

        self.assertEqual(rows.iloc[0]["stock_code"], "002378")
        self.assertEqual(rows.iloc[0]["final_probability_signal"], "偏多")
        self.assertAlmostEqual(rows.iloc[0]["risk_adjusted_1pct"], 0.5)


if __name__ == "__main__":
    unittest.main()
