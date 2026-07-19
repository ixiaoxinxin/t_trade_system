# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

import pandas as pd

from decision_fusion import build_final_decision_frame, model_quality_score


class DecisionFusionTest(unittest.TestCase):
    def test_d_grade_cannot_be_upgraded_to_buy_action(self):
        watchlist = pd.DataFrame([
            {
                "股票代码": "300085",
                "股票名称": "银之杰",
                "确认日期": "2026-07-19",
                "隔夜建议等级": "D",
                "最终评分": 38,
                "所属板块": "软件开发",
                "板块数据状态": "未知",
            }
        ])
        direction = pd.DataFrame([
            {"stock_code": "300085", "stock_name": "银之杰", "predict_date": "2026-07-19", "next_day_up_probability": 0.9}
        ])
        profit = pd.DataFrame([
            {
                "stock_code": "300085",
                "stock_name": "银之杰",
                "predict_date": "2026-07-19",
                "hit_1pct_probability": 0.9,
                "hit_2pct_probability": 0.8,
                "stop_2pct_probability": 0.1,
            }
        ])

        decision = build_final_decision_frame(watchlist, direction, profit, pd.DataFrame(), pd.DataFrame())

        row = decision[decision["stock_code"].eq("300085")].iloc[0]
        self.assertEqual(row["final_action"], "放弃")
        self.assertLessEqual(row["fusion_score"], 49)

    def test_sector_avoid_blocks_aggressive_action(self):
        watchlist = pd.DataFrame([
            {
                "股票代码": "600536",
                "股票名称": "中国软件",
                "确认日期": "2026-07-19",
                "隔夜建议等级": "B",
                "最终评分": 80,
                "所属板块": "IT服务",
                "板块数据状态": "回避",
            }
        ])
        direction = pd.DataFrame([
            {"stock_code": "600536", "stock_name": "中国软件", "predict_date": "2026-07-19", "next_day_up_probability": 0.9}
        ])
        profit = pd.DataFrame([
            {
                "stock_code": "600536",
                "stock_name": "中国软件",
                "predict_date": "2026-07-19",
                "hit_1pct_probability": 0.9,
                "hit_2pct_probability": 0.8,
                "stop_2pct_probability": 0.1,
            }
        ])

        decision = build_final_decision_frame(watchlist, direction, profit, pd.DataFrame(), pd.DataFrame())

        row = decision[decision["stock_code"].eq("600536")].iloc[0]
        self.assertEqual(row["final_action"], "放弃")

    def test_fixed_holding_uses_holding_actions(self):
        watchlist = pd.DataFrame()
        direction = pd.DataFrame([
            {"stock_code": "002192", "stock_name": "融捷股份", "predict_date": "2026-07-19", "next_day_up_probability": 0.7}
        ])
        profit = pd.DataFrame([
            {
                "stock_code": "002192",
                "stock_name": "融捷股份",
                "predict_date": "2026-07-19",
                "hit_1pct_probability": 0.7,
                "hit_2pct_probability": 0.6,
                "stop_2pct_probability": 0.2,
            }
        ])

        decision = build_final_decision_frame(watchlist, direction, profit, pd.DataFrame(), pd.DataFrame())

        fixed_row = decision[decision["stock_code"].eq("002192")].iloc[0]
        self.assertTrue(fixed_row["is_fixed_holding"])
        self.assertIn(fixed_row["final_action"], ["继续持有", "止盈", "减仓", "止损"])

    def test_model_quality_score_uses_scorecard(self):
        scorecard = pd.DataFrame([
            {"metric_name": "direction_hit_rate", "segment_type": "all", "score": 0.8},
            {"metric_name": "hit_1pct_brier", "segment_type": "all", "score": 0.2},
        ])

        self.assertGreater(model_quality_score(scorecard), 0.5)


if __name__ == "__main__":
    unittest.main()
