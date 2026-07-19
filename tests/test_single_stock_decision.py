# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

import single_stock_decision as single


class SingleStockDecisionTest(unittest.TestCase):
    def test_build_single_stock_summary_merges_existing_outputs(self):
        frames = {
            single.FINAL_DECISION_FILE: pd.DataFrame([
                {
                    "stock_code": "002466",
                    "stock_name": "天齐锂业",
                    "final_action": "继续持有",
                    "fusion_score": 66.5,
                    "decision_reason": "规则B；概率偏多",
                    "rule_grade": "B",
                    "rule_score": 70,
                    "market_regime": "震荡",
                    "sector_name": "锂矿",
                    "sector_status": "未知",
                }
            ]),
            single.MODEL_PREDICTION_FILE: pd.DataFrame([
                {"stock_code": "002466", "next_day_up_probability": 0.61}
            ]),
            single.CALIBRATED_PROBABILITY_FILE: pd.DataFrame([
                {
                    "stock_code": "002466",
                    "calibrated_hit_1pct_probability": 0.58,
                    "calibrated_hit_2pct_probability": 0.34,
                    "calibrated_stop_2pct_probability": 0.22,
                }
            ]),
            single.FIXED_HOLDINGS_SIGNAL_FILE: pd.DataFrame([
                {
                    "股票代码": "002466",
                    "股票名称": "天齐锂业",
                    "买点下限": 40,
                    "买点上限": 41,
                    "买点状态": "高于买点，等回落",
                    "卖点信号": "继续持有",
                }
            ]),
            single.MODEL_EXPLANATION_FILE: pd.DataFrame([
                {"stock_code": "002466", "top_positive_factors": "momentum:0.2", "top_negative_factors": "risk:-0.1"}
            ]),
        }

        def fake_read_csv(path):
            return frames.get(path, pd.DataFrame())

        with patch.object(single, "read_csv", side_effect=fake_read_csv):
            summary = single.build_single_stock_summary("2466")

        self.assertEqual(summary["stock_code"], "002466")
        self.assertEqual(summary["stock_name"], "天齐锂业")
        self.assertEqual(summary["final_action"], "继续持有")
        self.assertEqual(summary["buy_range"], "40.00 - 41.00")
        self.assertAlmostEqual(summary["hit_1pct_probability"], 0.58)


if __name__ == "__main__":
    unittest.main()
