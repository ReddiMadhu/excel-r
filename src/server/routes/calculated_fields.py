"""
Calculated Fields Routes — GET /api/calculated-fields

Lists all formula-based columns across all workbooks with fingerprints and lineage.
"""
import json
import logging
from typing import List

from fastapi import APIRouter

from src.server.models.database import get_database
from src.server.models.schemas import CalculatedFieldSummary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Calculated Fields"])


def _pj(val):
    if val is None:
        return None
    if isinstance(val, (list, dict)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return val
    return val


@router.get("/calculated-fields", response_model=List[CalculatedFieldSummary])
async def list_calculated_fields():
    """List all formula-based columns across all workbooks."""
    db = get_database()
    rows = db.query("""
        SELECT cf.*,
               w.name AS workbook_name,
               d.name AS dashboard_name
        FROM calculated_fields cf
        JOIN workbooks w ON cf.workbook_id = w.id
        JOIN dashboards d ON cf.dashboard_id = d.id
        ORDER BY w.name, cf.table_name, cf.name
    """)

    return [
        CalculatedFieldSummary(
            id=r["id"],
            workbook_id=r["workbook_id"],
            workbook_name=r.get("workbook_name"),
            dashboard_id=r["dashboard_id"],
            dashboard_name=r.get("dashboard_name"),
            name=r["name"],
            formula=r.get("formula"),
            datatype=r.get("datatype"),
            formula_pattern=r.get("formula_pattern"),
            definition=r.get("definition"),
            column_type=r.get("column_type"),
            nesting_depth=r.get("nesting_depth", 0),
            computation_type=r.get("computation_type"),
            ultimate_raw_sources=_pj(r.get("ultimate_raw_sources")),
            fingerprint=r.get("fingerprint"),
            table_name=r.get("table_name"),
        )
        for r in rows
    ]
