# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from opening_levels import action_text, build_levels, resolve_stock


class OpeningLevelsTest(unittest.TestCase):
    def test_build_levels_returns_ordered_ranges(self):
        levels = build_levels(
            previous_close=20,
            previous_high=21,
            previous_low=19,
            auction_price=20.2,
            current_price=20.1,
            atr=1.2,
        )

        self.assertLess(levels["buy_low"], levels["buy_high"])
        self.assertLess(levels["buy_high"], levels["sell_low"])
        self.assertLess(levels["support"], levels["pressure"])

    def test_action_text_marks_buy_zone(self):
        levels = {
            "buy_low": 19.5,
            "buy_high": 20.0,
            "sell_low": 21.0,
        }

        self.assertEqual(action_text(19.8, levels), "可低吸")
        self.assertEqual(action_text(21.1, levels), "看卖出")

    def test_resolve_fixed_holding_name(self):
        code, name = resolve_stock("华友钴业")

        self.assertEqual(code, "603799")
        self.assertEqual(name, "华友钴业")


if __name__ == "__main__":
    unittest.main()

