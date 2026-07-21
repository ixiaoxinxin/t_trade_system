import unittest

from data_provider import parse_sina_realtime_quote_text


class DataProviderRealtimeQuoteTest(unittest.TestCase):
    def test_parse_sina_realtime_quote_text(self):
        text = (
            'var hq_str_sz002466="天齐锂业,40.990,42.290,42.680,43.270,40.440,'
            '42.680,42.690,42088800,1760165258.860,119300,42.680,1200,42.670,'
            '4000,42.660,900,42.650,300,42.640,1300,42.690,6200,42.700,'
            '5200,42.710,100,42.720,100,42.730,2026-07-21,10:43:42,00";'
        )

        quote = parse_sina_realtime_quote_text(text, "002466")

        self.assertEqual(quote["代码"], "002466")
        self.assertEqual(quote["名称"], "天齐锂业")
        self.assertEqual(quote["最新价"], 42.68)
        self.assertEqual(quote["昨收"], 42.29)
        self.assertEqual(quote["最高"], 43.27)
        self.assertEqual(quote["最低"], 40.44)
        self.assertAlmostEqual(quote["涨跌幅"], 0.9222, places=4)
        self.assertEqual(quote["行情日期"], "2026-07-21")
        self.assertEqual(quote["行情时间"], "10:43:42")


if __name__ == "__main__":
    unittest.main()
