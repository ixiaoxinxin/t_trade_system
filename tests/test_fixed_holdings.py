import unittest

import pandas as pd

from fixed_holdings import calculate_buy_zone, classify_buy_status


class FixedHoldingsBuyZoneTest(unittest.TestCase):
    def test_buy_zone_uses_previous_close_pullback_not_ma5(self):
        daily_df = pd.DataFrame({"close": [120, 118, 116, 114, 112]})

        low, high, basis = calculate_buy_zone(daily_df, 100)

        self.assertEqual(round(low, 2), 98.00)
        self.assertEqual(round(high, 2), 99.00)
        self.assertEqual(basis, "昨收回撤1%-2%")

    def test_classify_buy_status_for_rebuy_zone(self):
        self.assertEqual(classify_buy_status(98.5, 98, 99, 100), "进入回补区")
        self.assertEqual(classify_buy_status(97.5, 98, 99, 100), "跌破回补区，先等止跌")
        self.assertEqual(classify_buy_status(101.2, 98, 99, 100), "高于回补区，不追")


if __name__ == "__main__":
    unittest.main()
