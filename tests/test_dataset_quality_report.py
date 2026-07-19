# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

import pandas as pd

from dataset_quality_report import build_label_review_queue


class DatasetQualityReportTest(unittest.TestCase):
    def test_review_queue_detects_rule_conflict(self):
        queue = build_label_review_queue(
            pd.DataFrame([{
                "sample_id": "002378_2026-07-19_v2.0",
                "stock_code": "002378",
                "direction_up_close": 1,
                "touch_buy_range": 0,
                "hit_1pct_after_touch": 1,
                "hit_2pct_after_touch": 0,
                "stop_2pct_after_touch": 0,
                "first_event": "hit_1pct",
                "execution_quality": "可执行盈利",
            }]),
            pd.DataFrame(),
        )

        self.assertEqual(len(queue), 1)
        self.assertIn("conflict:no_touch_but_has_event", queue.iloc[0]["reason"])


if __name__ == "__main__":
    unittest.main()
