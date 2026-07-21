import sqlite3
import unittest

import pandas as pd

from model_calibration import write_calibration_tables


class ModelCalibrationTest(unittest.TestCase):
    def test_write_calibration_tables_allows_empty_calibration_frame(self):
        with sqlite3.connect(":memory:") as conn:
            explanation_df = pd.DataFrame(
                [
                    {
                        "explanation_id": "e1",
                        "sample_id": "s1",
                        "stock_code": "002466",
                        "stock_name": "天齐锂业",
                        "predict_date": "2026-07-21",
                        "model_version": "v2.8",
                        "source_model_version": "v2.7",
                        "top_positive_factors": "样本不足",
                        "top_negative_factors": "样本不足",
                        "explanation_method": "baseline_summary",
                        "created_at": "2026-07-21 17:30:00",
                    }
                ]
            )

            write_calibration_tables(conn, pd.DataFrame(), explanation_df)

            calibration_count = conn.execute("SELECT COUNT(*) FROM probability_calibration_curves").fetchone()[0]
            explanation_count = conn.execute("SELECT COUNT(*) FROM model_explanations").fetchone()[0]

            self.assertEqual(calibration_count, 0)
            self.assertEqual(explanation_count, 1)


if __name__ == "__main__":
    unittest.main()
