# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import gzip
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from common import normalize_code


DATABASE_FILE = Path("data/dataset/trade_dataset.sqlite3")

OUTPUT_DIR = Path("output")
CACHE_DAILY_DIR = Path("cache/daily")
CACHE_MINUTE_DIR = Path("cache/minute")

DOCUMENT_EXTENSIONS = {".md", ".json", ".jsonl"}

DATASET_TABLE_BY_FILE = {
    Path("data/dataset/dataset_samples.csv"): "dataset_samples",
    Path("data/dataset/feature_snapshot.csv"): "feature_snapshot",
    Path("data/dataset/label_snapshot.csv"): "label_snapshot",
    Path("data/dataset/prediction_log.csv"): "prediction_log",
    Path("data/dataset/llm_label_snapshot.csv"): "llm_label_snapshot",
    Path("data/dataset/api_usage_log.csv"): "api_usage_log",
}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(db_path: Path = DATABASE_FILE) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def file_hash(path: Path) -> str:
    if not path.exists():
        return ""

    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def output_table_name(path: Path) -> str:
    stem = re.sub(r"[^0-9a-zA-Z_]+", "_", path.stem.lower()).strip("_")
    return f"page_{stem}"


def table_for_file(path: Path) -> str:
    normalized = Path(path)

    if normalized in DATASET_TABLE_BY_FILE:
        return DATASET_TABLE_BY_FILE[normalized]

    if normalized.parent == OUTPUT_DIR and normalized.suffix == ".csv":
        return output_table_name(normalized)

    return ""


def ensure_document_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_documents (
            source_path TEXT PRIMARY KEY,
            document_type TEXT,
            content_text TEXT,
            content_hash TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache_files (
            source_path TEXT,
            cache_type TEXT,
            stock_code TEXT,
            row_count INTEGER,
            content_blob BLOB,
            content_hash TEXT,
            migrated_at TEXT,
            PRIMARY KEY (source_path)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_migration_log (
            source_path TEXT PRIMARY KEY,
            target_table TEXT,
            data_type TEXT,
            row_count INTEGER,
            content_hash TEXT,
            migrated_at TEXT
        )
    """)
    conn.commit()


def record_migration(
    conn: sqlite3.Connection,
    *,
    source_path: Path,
    target_table: str,
    data_type: str,
    row_count: int,
    content_hash: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO data_migration_log
        (source_path, target_table, data_type, row_count, content_hash, migrated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (str(source_path), target_table, data_type, row_count, content_hash, now_text()),
    )


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()

    if "股票代码" in normalized.columns:
        normalized["股票代码"] = normalized["股票代码"].apply(normalize_code)

    return normalized


def migrate_csv_file(conn: sqlite3.Connection, path: Path) -> int:
    table_name = table_for_file(path)

    if not table_name or not path.exists():
        return 0

    df = pd.read_csv(path, dtype={"股票代码": str})
    df = normalize_dataframe(df)
    df.to_sql(table_name, conn, if_exists="replace", index=False)
    record_migration(
        conn,
        source_path=path,
        target_table=table_name,
        data_type="csv",
        row_count=len(df),
        content_hash=file_hash(path),
    )

    return len(df)


def migrate_document_file(conn: sqlite3.Connection, path: Path) -> int:
    if not path.exists() or path.suffix not in DOCUMENT_EXTENSIONS:
        return 0

    content = path.read_text(encoding="utf-8")
    conn.execute(
        """
        INSERT OR REPLACE INTO app_documents
        (source_path, document_type, content_text, content_hash, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(path), path.suffix.lstrip("."), content, file_hash(path), now_text()),
    )
    record_migration(
        conn,
        source_path=path,
        target_table="app_documents",
        data_type=path.suffix.lstrip("."),
        row_count=1,
        content_hash=file_hash(path),
    )

    return 1


def cache_stock_code(path: Path) -> str:
    name = path.stem.replace("_1m", "")
    return normalize_code(name)


def migrate_cache_file(conn: sqlite3.Connection, path: Path, target_table: str) -> int:
    if not path.exists():
        return 0

    raw = path.read_bytes()
    line_count = max(0, len(raw.splitlines()) - 1)
    content_hash = file_hash(path)
    migrated_at = now_text()
    stock_code = cache_stock_code(path)
    cache_type = "daily" if "daily" in str(path.parent) else "minute"

    conn.execute(
        """
        INSERT OR REPLACE INTO cache_files
        (source_path, cache_type, stock_code, row_count, content_blob, content_hash, migrated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(path),
            cache_type,
            stock_code,
            line_count,
            sqlite3.Binary(gzip.compress(raw, compresslevel=6)),
            content_hash,
            migrated_at,
        ),
    )

    record_migration(
        conn,
        source_path=path,
        target_table="cache_files",
        data_type="cache_csv",
        row_count=line_count,
        content_hash=content_hash,
    )

    return line_count


def prepare_cache_blob_storage(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS cache_daily_rows")
    conn.execute("DROP TABLE IF EXISTS cache_minute_rows")
    conn.execute("DELETE FROM cache_files")
    conn.execute("DELETE FROM data_migration_log WHERE target_table IN ('cache_daily_rows', 'cache_minute_rows', 'cache_files')")
    conn.commit()


def migrate_local_files_to_sqlite(db_path: Path = DATABASE_FILE) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "database": str(db_path),
        "output_csv_files": 0,
        "documents": 0,
        "daily_cache_files": 0,
        "daily_cache_rows": 0,
        "minute_cache_files": 0,
        "minute_cache_rows": 0,
    }

    with connect(db_path) as conn:
        ensure_document_tables(conn)
        prepare_cache_blob_storage(conn)

        for path in sorted(OUTPUT_DIR.glob("*.csv")):
            if path.name == "trade_records.csv":
                continue

            migrate_csv_file(conn, path)
            summary["output_csv_files"] += 1

        for path in sorted(OUTPUT_DIR.iterdir()) if OUTPUT_DIR.exists() else []:
            if path.suffix in DOCUMENT_EXTENSIONS:
                migrate_document_file(conn, path)
                summary["documents"] += 1

        for path in sorted(CACHE_DAILY_DIR.glob("*.csv")) if CACHE_DAILY_DIR.exists() else []:
            summary["daily_cache_rows"] += migrate_cache_file(conn, path, "cache_daily_rows")
            summary["daily_cache_files"] += 1

        for path in sorted(CACHE_MINUTE_DIR.glob("*.csv")) if CACHE_MINUTE_DIR.exists() else []:
            summary["minute_cache_rows"] += migrate_cache_file(conn, path, "cache_minute_rows")
            summary["minute_cache_files"] += 1

        conn.commit()

    with connect(db_path) as conn:
        conn.execute("VACUUM")

    print("本地页面数据与行情缓存已迁移到 SQLite。")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    return summary


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def load_dataframe(path: Path, db_path: Path = DATABASE_FILE) -> pd.DataFrame:
    table_name = table_for_file(path)

    if not table_name or not db_path.exists():
        return pd.DataFrame()

    with connect(db_path) as conn:
        if not table_exists(conn, table_name):
            return pd.DataFrame()

        try:
            df = pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)
        except (pd.errors.DatabaseError, sqlite3.DatabaseError):
            return pd.DataFrame()

    return normalize_dataframe(df)


def load_document(path: Path, db_path: Path = DATABASE_FILE) -> str:
    if not db_path.exists():
        return ""

    with connect(db_path) as conn:
        ensure_document_tables(conn)
        row = conn.execute(
            "SELECT content_text FROM app_documents WHERE source_path = ?",
            (str(path),),
        ).fetchone()

    return row[0] if row else ""


def load_jsonl_document(path: Path, db_path: Path = DATABASE_FILE) -> pd.DataFrame:
    content = load_document(path, db_path)

    if not content:
        return pd.DataFrame()

    rows = []

    for line in content.splitlines():
        line = line.strip()

        if not line:
            continue

        rows.append(json.loads(line))

    return pd.DataFrame(rows)


if __name__ == "__main__":
    migrate_local_files_to_sqlite()
