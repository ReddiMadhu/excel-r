"""
Risk Detector — Populates governance_risks from workbook metadata and extraction quality.

Runs before complexity scoring in the rationalization pipeline.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from src.server.models.database import Database

logger = logging.getLogger(__name__)


def _parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def detect_workbook_risks(
    db: Database,
    workbook_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """
    Detect governance risks for workbooks and write to governance_risks table.

    Returns list of inserted risk dicts.
    """
    if workbook_ids:
        placeholders = ",".join("?" * len(workbook_ids))
        workbooks = db.query(
            f"SELECT * FROM workbooks WHERE id IN ({placeholders})",
            tuple(workbook_ids),
        )
        db.execute(
            f"DELETE FROM governance_risks WHERE workbook_id IN ({placeholders})",
            tuple(workbook_ids),
        )
    else:
        workbooks = db.query("SELECT * FROM workbooks")
        db.execute("DELETE FROM governance_risks")

    risks: List[Dict[str, Any]] = []

    for wb in workbooks:
        wb_id = wb["id"]
        wb_name = wb.get("name", "")

        # VBA macros
        if wb.get("has_vba_macros"):
            risks.append(_insert_risk(db, wb_id, None, "vba_macros", "critical",
                f"Workbook '{wb_name}' contains VBA macros.",
                "workbook"))

        # External links
        ext_links = _parse_json(wb.get("external_links")) or []
        if ext_links:
            risks.append(_insert_risk(db, wb_id, None, "external_links", "warning",
                f"Workbook '{wb_name}' has {len(ext_links)} external link(s).",
                ", ".join(str(l) for l in ext_links[:3])))

        # Low extraction quality
        quality = wb.get("extraction_quality_score")
        if quality is not None and quality < 0.6:
            risks.append(_insert_risk(db, wb_id, None, "low_extraction_quality", "warning",
                f"Extraction quality score {quality:.0%} is below 0.6 — auto-decommission blocked.",
                f"comparison_mode={wb.get('comparison_mode', 'unknown')}"))

        # Hidden rows/columns on summary sheets
        dashboards = db.query(
            "SELECT id, name, hidden_row_count, hidden_column_count FROM dashboards "
            "WHERE workbook_id = ? AND sheet_type = 'summary_report'",
            (wb_id,),
        )
        for dash in dashboards:
            hidden = (dash.get("hidden_row_count") or 0) + (dash.get("hidden_column_count") or 0)
            if hidden > 0:
                risks.append(_insert_risk(db, wb_id, dash["id"], "hidden_cells", "info",
                    f"Sheet '{dash['name']}' has {hidden} hidden row/column cells.",
                    dash["name"]))

        # Degraded lineage columns
        degraded_cols = db.query("""
            SELECT c.column_name, c.table_name, c.resolved_by
            FROM columns c
            WHERE c.workbook_id = ?
              AND c.column_type IN ('formula_based', 'pivot_value', 'total')
              AND (c.resolved_by = 'degraded' OR c.formula_lineage IS NULL
                   OR c.formula_lineage = 'null' OR c.formula_lineage = '{}')
        """, (wb_id,))
        for col in degraded_cols[:20]:  # cap per workbook
            risks.append(_insert_risk(
                db, wb_id, None, "degraded_lineage", "info",
                f"Column '{col['column_name']}' in table '{col.get('table_name', '')}' "
                f"has degraded or missing lineage.",
                col["column_name"],
            ))

        # Hardcoded overrides: formula_based with empty formula but has values
        hardcoded = db.query("""
            SELECT column_name, table_name
            FROM columns
            WHERE workbook_id = ?
              AND column_type = 'formula_based'
              AND (formula IS NULL OR formula = '')
        """, (wb_id,))
        for col in hardcoded[:10]:
            risks.append(_insert_risk(
                db, wb_id, None, "hardcoded_override", "warning",
                f"Column '{col['column_name']}' marked formula_based but has no formula "
                f"(possible hardcoded override).",
                col["column_name"],
            ))

    logger.info("Detected %d governance risks for %d workbooks", len(risks), len(workbooks))
    return risks


def _insert_risk(
    db: Database,
    workbook_id: int,
    dashboard_id: Optional[int],
    category: str,
    severity: str,
    description: str,
    affected_element: str,
) -> Dict[str, Any]:
    row_id = db.insert("governance_risks", {
        "workbook_id": workbook_id,
        "dashboard_id": dashboard_id,
        "risk_category": category,
        "severity": severity,
        "description": description,
        "affected_element": affected_element,
    })
    return {
        "id": row_id,
        "workbook_id": workbook_id,
        "risk_category": category,
        "severity": severity,
    }
