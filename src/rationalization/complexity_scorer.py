"""
Complexity Scorer — Computes 3-axis complexity scores per workbook.

Axes:
  1. extraction_complexity  — formula density, nesting depth, pivot count
  2. structural_risk        — VBA macros, external links, hidden cells
  3. computation_depth      — max lineage depth, fingerprint variety, helper sheets
"""
import json
import logging
from typing import Any, Dict

from src.server.models.database import Database

logger = logging.getLogger(__name__)


def compute_complexity_scores(db: Database) -> Dict[int, Dict[str, float]]:
    """
    Compute 3-axis complexity scores for all workbooks and store in DB.

    Returns: {workbook_id: {extraction_complexity, structural_risk, computation_depth}}
    """
    workbooks = db.query("SELECT * FROM workbooks")

    scores: Dict[int, Dict[str, float]] = {}

    for wb in workbooks:
        wb_id = wb["id"]

        # ── Axis 1: Extraction Complexity ─────────────────────
        # formula_count across all dashboards
        fc_row = db.query_one(
            "SELECT COALESCE(SUM(formula_count), 0) as total FROM dashboards WHERE workbook_id = ?",
            (wb_id,)
        )
        formula_count = fc_row["total"] if fc_row else 0

        # max nesting depth from columns
        nd_row = db.query_one(
            "SELECT COALESCE(MAX(nesting_depth), 0) as max_depth FROM columns WHERE workbook_id = ?",
            (wb_id,)
        )
        max_nesting = nd_row["max_depth"] if nd_row else 0

        # pivot table count
        pt_row = db.query_one(
            "SELECT COALESCE(SUM(pivot_table_count), 0) as total FROM dashboards WHERE workbook_id = ?",
            (wb_id,)
        )
        pivot_count = pt_row["total"] if pt_row else 0

        extraction_complexity = min(5.0, 0.03 * formula_count + 0.50 * max_nesting + 1.0 * pivot_count)

        # ── Axis 2: Structural Risk ──────────────────────────
        has_vba = 1 if wb.get("has_vba_macros") else 0

        ext_links = wb.get("external_links", "[]")
        if isinstance(ext_links, str):
            try:
                ext_links = json.loads(ext_links)
            except Exception:
                ext_links = []
        ext_link_count = len(ext_links) if isinstance(ext_links, list) else 0

        hr_row = db.query_one(
            "SELECT COALESCE(SUM(hidden_row_count), 0) as total FROM dashboards WHERE workbook_id = ?",
            (wb_id,)
        )
        hidden_rows = hr_row["total"] if hr_row else 0

        hc_row = db.query_one(
            "SELECT COALESCE(SUM(hidden_column_count), 0) as total FROM dashboards WHERE workbook_id = ?",
            (wb_id,)
        )
        hidden_cols = hc_row["total"] if hc_row else 0

        structural_risk = min(5.0, 2.0 * has_vba + 1.5 * ext_link_count + 0.1 * (hidden_rows + hidden_cols))

        # ── Axis 3: Computation Depth ────────────────────────
        # Max lineage depth from formula_lineage JSON
        lineage_rows = db.query("""
            SELECT formula_lineage FROM columns
            WHERE workbook_id = ? AND formula_lineage IS NOT NULL AND formula_lineage != 'null'
        """, (wb_id,))

        max_lineage_depth = 0
        for lr in lineage_rows:
            lineage = lr.get("formula_lineage", "{}")
            if isinstance(lineage, str):
                try:
                    lineage = json.loads(lineage)
                except Exception:
                    continue
            if isinstance(lineage, dict):
                depth = lineage.get("lineage_depth", 0)
                max_lineage_depth = max(max_lineage_depth, depth)

        # Unique fingerprint count
        fp_row = db.query_one(
            "SELECT COUNT(DISTINCT fingerprint) as cnt FROM calculated_fields WHERE workbook_id = ? AND fingerprint IS NOT NULL AND fingerprint != ''",
            (wb_id,)
        )
        unique_fps = fp_row["cnt"] if fp_row else 0

        # Helper sheet count
        helper_row = db.query_one(
            "SELECT COUNT(*) as cnt FROM dashboards WHERE workbook_id = ? AND sheet_type = 'helper'",
            (wb_id,)
        )
        helper_count = helper_row["cnt"] if helper_row else 0

        computation_depth = min(5.0, 0.5 * max_lineage_depth + 0.05 * unique_fps + 0.8 * helper_count)

        # Store scores
        scores[wb_id] = {
            "extraction_complexity": round(extraction_complexity, 2),
            "structural_risk": round(structural_risk, 2),
            "computation_depth": round(computation_depth, 2),
        }

        # Update workbook in DB
        db.update("workbooks", {
            "extraction_complexity": round(extraction_complexity, 2),
            "structural_risk": round(structural_risk, 2),
            "computation_depth": round(computation_depth, 2),
        }, "id = ?", (wb_id,))

    logger.info("Computed complexity scores for %d workbooks", len(scores))
    return scores
