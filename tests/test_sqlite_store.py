# -*- coding: utf-8 -*-

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from sqlite_store import (
    ensure_document_tables,
    load_document,
    migrate_cache_file,
    migrate_document_file,
    table_for_file,
)


class SqliteStoreTest(unittest.TestCase):
    def test_table_for_output_csv(self):
        self.assertEqual(table_for_file(Path("output/final_watchlist.csv")), "page_final_watchlist")
        self.assertEqual(table_for_file(Path("data/dataset/dataset_samples.csv")), "dataset_samples")

    def test_migrate_document_file(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "store.sqlite3"
            doc_path = Path(temp_dir) / "daily_plan.md"
            doc_path.write_text("# plan\n", encoding="utf-8")

            with sqlite3.connect(db_path) as conn:
                ensure_document_tables(conn)
                migrated = migrate_document_file(conn, doc_path)
                conn.commit()

            self.assertEqual(migrated, 1)
            self.assertEqual(load_document(doc_path, db_path), "# plan\n")

    def test_migrate_cache_file_keeps_payload_rows(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "store.sqlite3"
            cache_path = Path(temp_dir) / "000960.csv"
            pd.DataFrame([
                {"日期": "2026-07-19", "开盘": 10.0, "收盘": 10.5},
                {"日期": "2026-07-20", "开盘": 10.5, "收盘": 10.8},
            ]).to_csv(cache_path, index=False)

            with sqlite3.connect(db_path) as conn:
                ensure_document_tables(conn)
                migrated = migrate_cache_file(conn, cache_path, "cache_daily_rows")
                count = conn.execute("SELECT COUNT(*) FROM cache_files").fetchone()[0]
                row_count = conn.execute("SELECT row_count FROM cache_files LIMIT 1").fetchone()[0]
                stock_code = conn.execute("SELECT stock_code FROM cache_files LIMIT 1").fetchone()[0]

            self.assertEqual(migrated, 2)
            self.assertEqual(count, 1)
            self.assertEqual(row_count, 2)
            self.assertEqual(stock_code, "000960")


if __name__ == "__main__":
    unittest.main()
