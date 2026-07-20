# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from trade_journal import (
    append_trade_record,
    build_trade_record,
    calculate_commission,
    calculate_sell_stamp_tax,
    load_trade_records,
)


class TradeJournalTest(unittest.TestCase):
    def test_build_trade_record_calculates_net_profit_with_cmbc_commission_and_stamp_tax(self):
        record = build_trade_record(
            stock_code="2378",
            stock_name="章源钨业",
            trade_date=date(2026, 7, 19),
            trade_type="隔日T",
            direction="买入并卖出",
            buy_price=40,
            sell_price=41,
            quantity=200,
            strategy_source="系统候选",
            followed_plan="是",
            note="按计划低吸后卖出",
            recorded_at=datetime(2026, 7, 19, 10, 30, 0),
        )

        self.assertEqual(record["股票代码"], "002378")
        self.assertEqual(record["闭环状态"], "已闭环")
        self.assertEqual(record["买入手续费"], 5.0)
        self.assertEqual(record["卖出手续费"], 5.0)
        self.assertEqual(record["卖出印花税"], 4.1)
        self.assertEqual(record["手续费合计"], 14.1)
        self.assertEqual(record["到手利润"], 185.9)
        self.assertEqual(record["收益率"], 2.32)

    def test_calculate_commission_uses_minimum_fee(self):
        self.assertEqual(calculate_commission(1000), 5.0)
        self.assertEqual(calculate_commission(100000), 25.0)

    def test_calculate_sell_stamp_tax_only_scales_with_sell_amount(self):
        self.assertEqual(calculate_sell_stamp_tax(0), 0.0)
        self.assertEqual(calculate_sell_stamp_tax(10000), 5.0)

    def test_append_and_load_trade_record(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trade_records.csv"
            record = build_trade_record(
                stock_code="000960",
                stock_name="锡业股份",
                trade_date="2026-07-19",
                trade_type="日内T",
                direction="买入",
                buy_price=45.2,
                sell_price=0,
                quantity=100,
                recorded_at=datetime(2026, 7, 19, 11, 0, 0),
            )

            append_trade_record(record, path)
            df = load_trade_records(path)

            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0]["股票代码"], "000960")
            self.assertEqual(df.iloc[0]["闭环状态"], "未闭环")

    def test_rejects_non_t_trade_type(self):
        with self.assertRaises(ValueError):
            build_trade_record(
                stock_code="000960",
                stock_name="锡业股份",
                trade_date="2026-07-19",
                trade_type="建仓",
                direction="买入",
                buy_price=45.2,
                quantity=100,
            )


if __name__ == "__main__":
    unittest.main()
