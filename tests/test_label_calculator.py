# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

import pandas as pd

from label_calculator import calculate_label_snapshot


class LabelCalculatorTest(unittest.TestCase):
    def test_calculates_no_touch_label(self):
        labels = calculate_label_snapshot(pd.DataFrame([{
            "股票代码": "2378",
            "验证日期": "2026-07-19",
            "次日日期": "2026-07-20",
            "买入参考价": 10.0,
            "次日最高": 9.8,
            "次日最低": 9.1,
            "次日收盘涨幅": -0.3,
            "是否触达低吸区间": "否",
            "是否达到1%": "否",
            "是否达到2%": "否",
            "是否触发-2%止损": "否",
            "是否验证成功": "否",
        }]))

        self.assertEqual(labels.iloc[0]["sample_id"], "002378_2026-07-19_v2.0")
        self.assertEqual(labels.iloc[0]["first_event"], "no_touch")
        self.assertEqual(labels.iloc[0]["execution_quality"], "未触达")

    def test_calculates_stop_loss_first_event(self):
        labels = calculate_label_snapshot(pd.DataFrame([{
            "股票代码": "000960",
            "验证日期": "2026-07-19",
            "次日日期": "2026-07-20",
            "买入参考价": 10.0,
            "次日最高": 10.2,
            "次日最低": 9.7,
            "次日收盘涨幅": -3.0,
            "是否触达低吸区间": "是",
            "是否达到1%": "否",
            "是否达到2%": "否",
            "是否触发-2%止损": "是",
            "是否验证成功": "否",
        }]))

        self.assertEqual(labels.iloc[0]["first_event"], "ambiguous_ohlc_path")
        self.assertEqual(labels.iloc[0]["execution_quality"], "需分时确认")


if __name__ == "__main__":
    unittest.main()
