# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

import pandas as pd

from mobile_push import build_mobile_opening_levels_html, build_mobile_sell_signal_html


class MobilePushTest(unittest.TestCase):
    def test_sell_signal_html_uses_mobile_cards(self):
        df = pd.DataFrame([
            {
                "股票代码": "002192",
                "股票名称": "融捷股份",
                "固定持仓": "是",
                "隔夜等级": "持仓",
                "当前价": 72.15,
                "当前涨幅": -6.12,
                "高点回撤": 4.85,
                "冲高保持率": 0,
                "均线状态": "跌破均线",
                "卖出信号": "止损",
                "卖出理由": "当前跌幅已触发-2%止损线。",
            }
        ])

        html = build_mobile_sell_signal_html(df)

        self.assertIn('name="viewport"', html)
        self.assertIn("<article class=\"card\">", html)
        self.assertIn("融捷股份", html)
        self.assertNotIn("<table", html)
        self.assertNotIn("| 股票代码 |", html)

    def test_opening_levels_html_uses_mobile_cards(self):
        df = pd.DataFrame([
            {
                "股票代码": "603799",
                "股票名称": "华友钴业",
                "状态": "成功",
                "操作": "可低吸",
                "买进区间": "36.2-36.8",
                "卖出区间": "38.1-38.8",
                "支撑位": 36.4,
                "压力位": 38.5,
                "当前价": 36.6,
                "集合竞价价": 36.7,
                "AI辅助": "靠近支撑，低吸需控制仓位",
            }
        ])

        html = build_mobile_opening_levels_html(df)

        self.assertIn('name="viewport"', html)
        self.assertIn("开盘T区间", html)
        self.assertIn("买进区间", html)
        self.assertIn("华友钴业", html)
        self.assertNotIn("<table", html)


if __name__ == "__main__":
    unittest.main()
