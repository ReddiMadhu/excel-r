"""
Database — SQLite connection manager with thread-safe locking.

Manages bi_governance.db: schema creation, connection pooling,
and a threading.Lock for all write operations.
"""
import os
import json
import sqlite3
import threading
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default DB path
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "data", "output", "bi_governance.db"
)

# ──────────────────────────────────────────────────────────────
# Schema DDL
# ──────────────────────────────────────────────────────────────

SCHEMA_SQL = """
-- Table 1: scans
CREATE TABLE IF NOT EXISTS scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id         VARCHAR UNIQUE NOT NULL,
    directory_path  VARCHAR,
    status          VARCHAR DEFAULT 'pending',
    total_files     INTEGER DEFAULT 0,
    processed_files INTEGER DEFAULT 0,
    current_file    VARCHAR,
    phase           VARCHAR DEFAULT 'extraction',
    errors          JSON,
    started_at      DATETIME,
    completed_at    DATETIME
);

-- Table 2: workbooks
CREATE TABLE IF NOT EXISTS workbooks (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id                     INTEGER NOT NULL,
    name                        VARCHAR NOT NULL,
    source_file                 VARCHAR NOT NULL,
    file_hash_md5               VARCHAR,
    schema_version              VARCHAR,
    generated_at                DATETIME,
    purpose                     TEXT,
    sheet_count                 INTEGER,
    sheet_names                 JSON,
    has_vba_macros              BOOLEAN DEFAULT 0,
    vba_macro_streams           JSON,
    external_links              JSON,
    named_ranges                JSON,
    raw_data_sheet_name         VARCHAR,
    summary_sheet_name          VARCHAR,
    primary_inputs              JSON,
    intermediate_calculations   JSON,
    final_outputs               JSON,
    vulnerability_rating        VARCHAR,
    extraction_complexity       FLOAT,
    structural_risk             FLOAT,
    computation_depth           FLOAT,
    extraction_quality_score    FLOAT,
    comparison_mode             VARCHAR DEFAULT 'insufficient',
    json_output_path            VARCHAR,
    uploaded_at                 DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(scan_id) REFERENCES scans(id)
);

-- Table 3: dashboards (= Excel Sheets)
CREATE TABLE IF NOT EXISTS dashboards (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    workbook_id             INTEGER NOT NULL,
    name                    VARCHAR NOT NULL,
    sheet_type              VARCHAR,
    sheet_range             VARCHAR,
    row_count               INTEGER,
    column_count            INTEGER,
    formula_count           INTEGER,
    non_empty_cells         INTEGER,
    table_count             INTEGER,
    pivot_table_count       INTEGER,
    hidden_row_count        INTEGER DEFAULT 0,
    hidden_column_count     INTEGER DEFAULT 0,
    print_area              VARCHAR,
    columns_list            JSON,
    filters                 JSON,
    ai_summary              TEXT,
    domain_classification   VARCHAR,
    line_of_business        VARCHAR,
    complexity_score        FLOAT,
    is_real_ai              BOOLEAN DEFAULT 0,
    raw_metadata            JSON,
    user_groups             JSON DEFAULT '[]',
    FOREIGN KEY(workbook_id) REFERENCES workbooks(id)
);

-- Table 4: worksheets (= Excel Tables / Pivot Tables within a sheet)
CREATE TABLE IF NOT EXISTS worksheets (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    workbook_id             INTEGER NOT NULL,
    dashboard_id            INTEGER NOT NULL,
    name                    VARCHAR NOT NULL,
    table_type              VARCHAR,
    table_range             VARCHAR,
    section_title           VARCHAR,
    header_row              INTEGER,
    data_start_row          INTEGER,
    data_end_row            INTEGER,
    row_count               INTEGER,
    column_count            INTEGER,
    input_cell_count        INTEGER,
    total_rows              JSON,
    check_rows              JSON,
    row_header_columns      JSON,
    column_header_rows      JSON,
    business_purpose        TEXT,
    measures                JSON,
    dimensions              JSON,
    inter_table_relationships JSON,
    summary_rows            JSON,
    pivot_configuration     JSON,
    mark_type               VARCHAR DEFAULT 'table',
    used_calculated_fields  JSON,
    filters_and_marks       JSON,
    FOREIGN KEY(workbook_id) REFERENCES workbooks(id),
    FOREIGN KEY(dashboard_id) REFERENCES dashboards(id)
);

-- Table 5: columns (= every column across all tables)
CREATE TABLE IF NOT EXISTS columns (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    worksheet_id        INTEGER NOT NULL,
    dashboard_id        INTEGER NOT NULL,
    workbook_id         INTEGER NOT NULL,
    column_name         VARCHAR NOT NULL,
    table_name          VARCHAR,
    data_type           VARCHAR,
    column_type         VARCHAR,
    formula             TEXT,
    formula_count       INTEGER DEFAULT 0,
    formula_pattern     VARCHAR,
    number_format       VARCHAR,
    number_format_type  VARCHAR,
    sample_values       JSON,
    nesting_depth       INTEGER DEFAULT 0,
    function_chain      JSON,
    definition          TEXT,
    formula_lineage     JSON,
    resolved_by         VARCHAR,
    FOREIGN KEY(worksheet_id) REFERENCES worksheets(id),
    FOREIGN KEY(dashboard_id) REFERENCES dashboards(id),
    FOREIGN KEY(workbook_id) REFERENCES workbooks(id)
);

-- Table 6: calculated_fields (BI Compass compat — formula columns only)
CREATE TABLE IF NOT EXISTS calculated_fields (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    dashboard_id            INTEGER NOT NULL,
    workbook_id             INTEGER NOT NULL,
    name                    VARCHAR NOT NULL,
    formula                 TEXT,
    datatype                VARCHAR,
    formula_pattern         VARCHAR,
    definition              TEXT,
    column_type             VARCHAR,
    nesting_depth           INTEGER DEFAULT 0,
    function_chain          JSON,
    computation_type        VARCHAR,
    ultimate_raw_sources    JSON,
    fingerprint             VARCHAR,
    table_name              VARCHAR,
    FOREIGN KEY(dashboard_id) REFERENCES dashboards(id),
    FOREIGN KEY(workbook_id) REFERENCES workbooks(id)
);

-- Table 7: datasources (= raw data sheets)
CREATE TABLE IF NOT EXISTS datasources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workbook_id     INTEGER NOT NULL,
    name            VARCHAR NOT NULL,
    caption         VARCHAR,
    column_headers  JSON,
    row_count       INTEGER,
    column_count    INTEGER,
    FOREIGN KEY(workbook_id) REFERENCES workbooks(id)
);

-- Table 8: tables (= physical data structures in raw sheets)
CREATE TABLE IF NOT EXISTS tables (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    datasource_id   INTEGER NOT NULL,
    name            VARCHAR NOT NULL,
    business_name   VARCHAR,
    columns         JSON,
    FOREIGN KEY(datasource_id) REFERENCES datasources(id)
);

-- Table 9: table_joins (= inter-table formula references)
CREATE TABLE IF NOT EXISTS table_joins (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    datasource_id   INTEGER,
    workbook_id     INTEGER NOT NULL,
    left_table      VARCHAR,
    right_table     VARCHAR,
    join_type       VARCHAR DEFAULT 'formula_ref',
    left_column     VARCHAR,
    right_column    VARCHAR,
    FOREIGN KEY(datasource_id) REFERENCES datasources(id),
    FOREIGN KEY(workbook_id) REFERENCES workbooks(id)
);

-- Table 10: kpi_cluster_cache (Rationalization — KPI canonicalization)
CREATE TABLE IF NOT EXISTS kpi_cluster_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    original_name   VARCHAR UNIQUE NOT NULL,
    canonical_name  VARCHAR NOT NULL,
    cluster_method  VARCHAR,
    confidence      FLOAT DEFAULT 1.0
);

-- Table 11: governance_risks (Rationalization — detected risks)
CREATE TABLE IF NOT EXISTS governance_risks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    workbook_id         INTEGER NOT NULL,
    dashboard_id        INTEGER,
    risk_category       VARCHAR,
    severity            VARCHAR,
    description         TEXT,
    affected_element    VARCHAR,
    detected_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(workbook_id) REFERENCES workbooks(id),
    FOREIGN KEY(dashboard_id) REFERENCES dashboards(id)
);

-- Table 12: governance_recommendations (Rationalization — final decisions)
CREATE TABLE IF NOT EXISTS governance_recommendations (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    workbook_id             INTEGER UNIQUE NOT NULL,
    action                  VARCHAR NOT NULL,
    merge_with_name         VARCHAR,
    merge_with_id           INTEGER,
    reasons                 JSON,
    common_kpis             JSON,
    common_datasources      JSON,
    matching_fingerprints   JSON,
    kpi_overlap_score       FLOAT,
    datasource_overlap_score FLOAT,
    uniqueness_score        FLOAT,
    llm_override            BOOLEAN DEFAULT 0,
    llm_justification       TEXT,
    calculated_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(workbook_id) REFERENCES workbooks(id)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_workbooks_scan_id ON workbooks(scan_id);
CREATE INDEX IF NOT EXISTS idx_workbooks_file_hash ON workbooks(file_hash_md5);
CREATE INDEX IF NOT EXISTS idx_workbooks_source_file ON workbooks(source_file);
CREATE INDEX IF NOT EXISTS idx_dashboards_workbook_id ON dashboards(workbook_id);
CREATE INDEX IF NOT EXISTS idx_worksheets_dashboard_id ON worksheets(dashboard_id);
CREATE INDEX IF NOT EXISTS idx_worksheets_workbook_id ON worksheets(workbook_id);
CREATE INDEX IF NOT EXISTS idx_columns_worksheet_id ON columns(worksheet_id);
CREATE INDEX IF NOT EXISTS idx_columns_workbook_id ON columns(workbook_id);
CREATE INDEX IF NOT EXISTS idx_calculated_fields_workbook_id ON calculated_fields(workbook_id);
CREATE INDEX IF NOT EXISTS idx_datasources_workbook_id ON datasources(workbook_id);
CREATE INDEX IF NOT EXISTS idx_governance_recs_workbook_id ON governance_recommendations(workbook_id);
CREATE INDEX IF NOT EXISTS idx_governance_risks_workbook_id ON governance_risks(workbook_id);
CREATE INDEX IF NOT EXISTS idx_kpi_cluster_canonical ON kpi_cluster_cache(canonical_name);
"""


class Database:
    """Thread-safe SQLite database manager for bi_governance.db."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
        self._write_lock = threading.Lock()
        self._local = threading.local()

        # Ensure the output directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # Initialize schema
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local connection (one per thread)."""
        if not hasattr(self._local, "connection") or self._local.connection is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.connection = conn
        return self._local.connection

    def _init_schema(self):
        """Create all tables if they don't exist."""
        conn = self._get_connection()
        with self._write_lock:
            conn.executescript(SCHEMA_SQL)
            self._migrate_schema(conn)
            conn.commit()
        logger.info("Database schema initialized at %s", self.db_path)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Add columns introduced after initial schema without recreating tables."""
        migrations = [
            "ALTER TABLE workbooks ADD COLUMN extraction_quality_score FLOAT",
            "ALTER TABLE workbooks ADD COLUMN comparison_mode VARCHAR DEFAULT 'insufficient'",
        ]
        for sql in migrations:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # column already exists

    # ── Read operations (no lock needed) ─────────────────────

    def query(self, sql: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        """Execute a read query and return list of dicts."""
        conn = self._get_connection()
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def query_one(self, sql: str, params: Tuple = ()) -> Optional[Dict[str, Any]]:
        """Execute a read query and return a single dict or None."""
        conn = self._get_connection()
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    # ── Write operations (lock-protected) ────────────────────

    def execute(self, sql: str, params: Tuple = ()) -> int:
        """Execute a write statement. Returns lastrowid."""
        conn = self._get_connection()
        with self._write_lock:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.lastrowid

    def execute_many(self, sql: str, params_list: List[Tuple]) -> None:
        """Execute a write statement for multiple parameter sets."""
        conn = self._get_connection()
        with self._write_lock:
            conn.executemany(sql, params_list)
            conn.commit()

    def execute_batch(self, statements: List[Tuple[str, Tuple]]) -> List[int]:
        """Execute multiple write statements atomically. Returns list of lastrowids."""
        conn = self._get_connection()
        row_ids = []
        with self._write_lock:
            try:
                for sql, params in statements:
                    cursor = conn.execute(sql, params)
                    row_ids.append(cursor.lastrowid)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return row_ids

    # ── Helpers ──────────────────────────────────────────────

    def insert(self, table: str, data: Dict[str, Any]) -> int:
        """Insert a single row into a table. Returns the new row id."""
        # Serialize any dict/list values to JSON strings
        processed = {}
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                processed[key] = json.dumps(value)
            else:
                processed[key] = value

        columns = ", ".join(processed.keys())
        placeholders = ", ".join(["?"] * len(processed))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        return self.execute(sql, tuple(processed.values()))

    def update(self, table: str, data: Dict[str, Any],
               where: str, where_params: Tuple) -> None:
        """Update rows in a table."""
        processed = {}
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                processed[key] = json.dumps(value)
            else:
                processed[key] = value

        set_clause = ", ".join([f"{k} = ?" for k in processed.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
        params = tuple(processed.values()) + where_params
        self.execute(sql, params)

    def delete(self, table: str, where: str, where_params: Tuple) -> None:
        """Delete rows from a table."""
        sql = f"DELETE FROM {table} WHERE {where}"
        self.execute(sql, where_params)

    def delete_workbook_cascade(self, workbook_id: int) -> None:
        """Delete a workbook and all its dependent data across all tables."""
        conn = self._get_connection()
        with self._write_lock:
            try:
                conn.execute("DELETE FROM governance_recommendations WHERE workbook_id = ?", (workbook_id,))
                conn.execute("DELETE FROM governance_risks WHERE workbook_id = ?", (workbook_id,))
                conn.execute("DELETE FROM calculated_fields WHERE workbook_id = ?", (workbook_id,))
                conn.execute("DELETE FROM columns WHERE workbook_id = ?", (workbook_id,))
                conn.execute("DELETE FROM worksheets WHERE workbook_id = ?", (workbook_id,))

                # Delete table_joins and tables via datasources
                ds_ids = [r[0] for r in conn.execute(
                    "SELECT id FROM datasources WHERE workbook_id = ?", (workbook_id,)
                ).fetchall()]
                for ds_id in ds_ids:
                    conn.execute("DELETE FROM tables WHERE datasource_id = ?", (ds_id,))
                conn.execute("DELETE FROM table_joins WHERE workbook_id = ?", (workbook_id,))
                conn.execute("DELETE FROM datasources WHERE workbook_id = ?", (workbook_id,))
                conn.execute("DELETE FROM dashboards WHERE workbook_id = ?", (workbook_id,))
                conn.execute("DELETE FROM workbooks WHERE id = ?", (workbook_id,))
                conn.commit()
                logger.info("Cascade-deleted workbook id=%d", workbook_id)
            except Exception:
                conn.rollback()
                raise

    def close(self):
        """Close the thread-local connection."""
        if hasattr(self._local, "connection") and self._local.connection:
            self._local.connection.close()
            self._local.connection = None


# ── Singleton for the app ────────────────────────────────────

_db_instance: Optional[Database] = None


def get_database(db_path: Optional[str] = None) -> Database:
    """Get or create the singleton Database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database(db_path)
    return _db_instance


def reset_database():
    """Reset the singleton (for testing)."""
    global _db_instance
    if _db_instance:
        _db_instance.close()
    _db_instance = None
