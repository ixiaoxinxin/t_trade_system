# -*- coding: utf-8 -*-

import unittest

import pandas as pd

from ds_analysis import compact_text
from metal_macro_engine import build_metal_macro_snapshot
from performance_report import append_ds_rows, fallback_performance_ds_analysis, summarize_system, summarize_trades
from preopen_predictor import classify_opening, fallback_preopen_ds_analysis
from sector_rotation import classify_rotation, fallback_sector_ds_analysis
from t_mode_decision import build_t_mode_decisions, parse_price_range


class V4EngineTest(unittest.TestCase):
    def test_parse_price_range(self):
        self.assertEqual(parse_price_range("10.2-10.6"), (10.2, 10.6))
        self.assertEqual(parse_price_range("10.6 至 10.2"), (10.2, 10.6))
        self.assertEqual(parse_price_range(""), (0.0, 0.0))

    def test_t_mode_prefers_sell_first_near_sell_zone(self):
        opening = pd.DataFrame([
            {
                "股票代码": "002213",
                "股票名称": "大为股份",
                "买进区间": "20.0-20.5",
                "卖出区间": "22.0-22.6",
                "当前价": 22.1,
                "支撑位": 20.0,
                "压力位": 22.2,
            }
        ])
        decisions = build_t_mode_decisions(
            opening,
            pd.DataFrame(),
            pd.DataFrame([{"市场环境": "正常", "风险等级": "中低"}]),
            pd.DataFrame(),
            pd.DataFrame(),
        )
        self.assertEqual(decisions.iloc[0]["推荐模式"], "先卖再买")

    def test_t_mode_prefers_buy_first_inside_buy_zone(self):
        opening = pd.DataFrame([
            {
                "股票代码": "603799",
                "股票名称": "华友钴业",
                "买进区间": "39.0-40.0",
                "卖出区间": "42.0-43.0",
                "当前价": 39.6,
                "支撑位": 38.8,
                "压力位": 42.2,
            }
        ])
        decisions = build_t_mode_decisions(
            opening,
            pd.DataFrame(),
            pd.DataFrame([{"市场环境": "正常", "风险等级": "中低"}]),
            pd.DataFrame(),
            pd.DataFrame(),
        )
        self.assertEqual(decisions.iloc[0]["推荐模式"], "先买再卖")

    def test_metal_macro_missing_data_is_explicit(self):
        df = build_metal_macro_snapshot(pd.DataFrame())
        self.assertTrue(df["数据状态"].eq("缺少价格").all())
        self.assertEqual(df.iloc[0]["金属模块状态"], "数据缺失")

    def test_preopen_score_reacts_to_strong_inputs(self):
        result = classify_opening(
            "正常",
            pd.DataFrame([{"板块名称": "半导体", "主力净流入": 1000, "板块涨跌幅": 1.2}]),
            pd.DataFrame([{"金属模块状态": "偏强"}]),
            pd.DataFrame([{"集合竞价价": 10.2, "昨收": 10.0}]),
        )
        self.assertGreaterEqual(result["开盘评分"], 70)
        self.assertIn(result["今日策略"], {"可进攻", "只低吸"})

    def test_sector_rotation_status(self):
        row = pd.Series({"主力净流入": 1000, "板块涨跌幅": 1.5, "板块广度": 70, "板块近5日排名": 3})
        self.assertEqual(classify_rotation(row), "主线延续")

    def test_performance_summary_uses_trade_records(self):
        trades = pd.DataFrame([
            {"记录ID": "1", "交易日期": "2026-09-01", "到手利润": 100, "收益率": 1.2},
            {"记录ID": "2", "交易日期": "2026-09-02", "到手利润": -20, "收益率": -0.3},
        ])
        summary = summarize_trades(trades, "周")
        self.assertEqual(int(summary.iloc[0]["交易笔数"]), 2)
        self.assertEqual(round(float(summary.iloc[0]["胜率"]), 2), 50.0)

    def test_system_summary_has_rates(self):
        next_day = pd.DataFrame([
            {"是否触达低吸区间": "是", "是否达到1%": "是", "是否触发-2%止损": "否"},
            {"是否触达低吸区间": "否", "是否达到1%": "否", "是否触发-2%止损": "是"},
        ])
        summary = summarize_system(next_day)
        self.assertIn("买点触达率", set(summary["指标"]))

    def test_ds_text_is_compacted_for_live_ui(self):
        text = compact_text("资金流向判断需要压缩成实盘能快速识别的短句，避免页面出现长段解释。", max_chars=20)
        self.assertLessEqual(len(text), 20)
        self.assertTrue(text.endswith("…"))

    def test_sector_ds_fallback_has_operational_fields(self):
        rotation = pd.DataFrame([
            {"所属板块": "半导体", "主力净流入": 1000, "板块轮动状态": "主线延续"},
            {"所属板块": "锂电池", "主力净流入": -200, "板块轮动状态": "资金流出"},
        ])
        result = fallback_sector_ds_analysis(rotation, pd.DataFrame())
        self.assertIn("DS操作指引", result)
        self.assertIn("DS风险提示", result)

    def test_preopen_ds_fallback_has_defense_condition(self):
        row = {"今日策略": "先防守", "开盘定性": "弱开", "金融拉盘预警": "无"}
        result = fallback_preopen_ds_analysis(row, pd.DataFrame(), pd.DataFrame())
        self.assertIn("DS操作建议", result)
        self.assertIn("DS防守条件", result)

    def test_performance_ds_rows_are_appended(self):
        result = fallback_performance_ds_analysis(
            pd.DataFrame([{"到手利润": 10}]),
            pd.DataFrame([{"是否触发-2%止损": "否"}]),
            pd.DataFrame(),
            ["继续复核买点"],
        )
        df = append_ds_rows(pd.DataFrame([{"报表类型": "周度交易"}]), result, "disabled")
        self.assertIn("DS分析", set(df["报表类型"].astype(str)))


if __name__ == "__main__":
    unittest.main()
