"""
Datasource Routes — GET /api/datasources

Lists all raw data sheet connections across workbooks.
"""
import json
import logging
from typing import List

from fastapi import APIRouter

from src.server.models.database import get_database
from src.server.models.schemas import DatasourceSummary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Datasources"])


@router.get("/datasources", response_model=List[DatasourceSummary])
async def list_datasources():
    """List all raw data sheet connections."""
    db = get_database()
    rows = db.query("""
        SELECT ds.*, w.name AS workbook_name
        FROM datasources ds
        JOIN workbooks w ON ds.workbook_id = w.id
        ORDER BY w.name, ds.name
    """)

    results = []
    for r in rows:
        col_headers = r.get("column_headers")
        if isinstance(col_headers, str):
            try:
                col_headers = json.loads(col_headers)
            except Exception:
                col_headers = []

        results.append(DatasourceSummary(
            id=r["id"],
            workbook_id=r["workbook_id"],
            workbook_name=r.get("workbook_name"),
            name=r["name"],
            caption=r.get("caption"),
            column_headers=col_headers,
            row_count=r.get("row_count"),
            column_count=r.get("column_count"),
        ))

    return results
