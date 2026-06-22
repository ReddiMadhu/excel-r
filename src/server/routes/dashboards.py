"""
Dashboard Routes — GET /api/dashboards, GET /api/dashboards/{id}

Dashboards map to Excel Sheets in our domain.
"""
import json
import logging
from typing import List

from fastapi import APIRouter, HTTPException

from src.server.models.database import get_database
from src.server.models.schemas import (
    DashboardSummary, DashboardDetail, WorksheetSummary, ColumnSummary
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Dashboards"])


def _pj(val):
    """Parse JSON string to Python object."""
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


@router.get("/dashboards", response_model=List[DashboardSummary])
async def list_dashboards():
    """List all sheets across all workbooks with AI fields and complexity scores."""
    db = get_database()
    rows = db.query("""
        SELECT d.*, w.name AS workbook_name
        FROM dashboards d
        JOIN workbooks w ON d.workbook_id = w.id
        ORDER BY w.name, d.id
    """)

    return [
        DashboardSummary(
            id=r["id"],
            workbook_id=r["workbook_id"],
            workbook_name=r.get("workbook_name"),
            name=r["name"],
            sheet_type=r.get("sheet_type"),
            row_count=r.get("row_count"),
            column_count=r.get("column_count"),
            formula_count=r.get("formula_count"),
            table_count=r.get("table_count"),
            pivot_table_count=r.get("pivot_table_count"),
            hidden_row_count=r.get("hidden_row_count", 0),
            hidden_column_count=r.get("hidden_column_count", 0),
            ai_summary=r.get("ai_summary"),
            domain_classification=r.get("domain_classification"),
            line_of_business=r.get("line_of_business"),
            complexity_score=r.get("complexity_score"),
            is_real_ai=bool(r.get("is_real_ai", 0)),
        )
        for r in rows
    ]


@router.get("/dashboards/{dashboard_id}", response_model=DashboardDetail)
async def get_dashboard(dashboard_id: int):
    """Get dashboard detail with tables, columns, KPIs, filters, lineage."""
    db = get_database()
    row = db.query_one("""
        SELECT d.*, w.name AS workbook_name
        FROM dashboards d
        JOIN workbooks w ON d.workbook_id = w.id
        WHERE d.id = ?
    """, (dashboard_id,))

    if not row:
        raise HTTPException(status_code=404, detail=f"Dashboard not found: {dashboard_id}")

    # Get worksheets (tables) for this dashboard
    worksheets = db.query(
        "SELECT * FROM worksheets WHERE dashboard_id = ? ORDER BY id",
        (dashboard_id,)
    )

    # Get columns for this dashboard
    columns = db.query(
        "SELECT * FROM columns WHERE dashboard_id = ? ORDER BY id",
        (dashboard_id,)
    )

    ws_models = [
        WorksheetSummary(
            id=ws["id"],
            name=ws["name"],
            table_type=ws.get("table_type"),
            table_range=ws.get("table_range"),
            section_title=ws.get("section_title"),
            row_count=ws.get("row_count"),
            column_count=ws.get("column_count"),
            business_purpose=ws.get("business_purpose"),
            measures=_pj(ws.get("measures")),
            dimensions=_pj(ws.get("dimensions")),
            mark_type=ws.get("mark_type", "table"),
        )
        for ws in worksheets
    ]

    col_models = [
        ColumnSummary(
            id=c["id"],
            column_name=c["column_name"],
            table_name=c.get("table_name"),
            data_type=c.get("data_type"),
            column_type=c.get("column_type"),
            formula=c.get("formula"),
            formula_pattern=c.get("formula_pattern"),
            nesting_depth=c.get("nesting_depth", 0),
            definition=c.get("definition"),
            formula_lineage=_pj(c.get("formula_lineage")),
        )
        for c in columns
    ]

    return DashboardDetail(
        id=row["id"],
        workbook_id=row["workbook_id"],
        workbook_name=row.get("workbook_name"),
        name=row["name"],
        sheet_type=row.get("sheet_type"),
        row_count=row.get("row_count"),
        column_count=row.get("column_count"),
        formula_count=row.get("formula_count"),
        table_count=row.get("table_count"),
        pivot_table_count=row.get("pivot_table_count"),
        hidden_row_count=row.get("hidden_row_count", 0),
        hidden_column_count=row.get("hidden_column_count", 0),
        ai_summary=row.get("ai_summary"),
        domain_classification=row.get("domain_classification"),
        line_of_business=row.get("line_of_business"),
        complexity_score=row.get("complexity_score"),
        is_real_ai=bool(row.get("is_real_ai", 0)),
        sheet_range=row.get("sheet_range"),
        non_empty_cells=row.get("non_empty_cells"),
        print_area=row.get("print_area"),
        columns_list=_pj(row.get("columns_list")),
        filters=_pj(row.get("filters")),
        raw_metadata=_pj(row.get("raw_metadata")),
        worksheets=ws_models,
        columns=col_models,
    )
