"""
Workbook Routes — GET /api/workbooks, GET /api/workbooks/{id}, DELETE /api/workbooks/{id}
"""
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from src.server.models.database import get_database
from src.server.models.schemas import WorkbookSummary, WorkbookDetail

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Workbooks"])


def _parse_json_field(value):
    """Parse a JSON string field from SQLite into a Python object."""
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


@router.get("/workbooks", response_model=List[WorkbookSummary])
async def list_workbooks():
    """List all parsed workbooks with metadata and counts."""
    db = get_database()
    rows = db.query("""
        SELECT w.*,
               (SELECT COUNT(*) FROM dashboards WHERE workbook_id = w.id) AS dashboard_count,
               (SELECT COUNT(*) FROM calculated_fields WHERE workbook_id = w.id) AS calculated_field_count,
               (SELECT COUNT(*) FROM datasources WHERE workbook_id = w.id) AS datasource_count
        FROM workbooks w
        ORDER BY w.uploaded_at DESC
    """)

    results = []
    for row in rows:
        results.append(WorkbookSummary(
            id=row["id"],
            name=row["name"],
            source_file=row["source_file"],
            file_hash_md5=row.get("file_hash_md5"),
            schema_version=row.get("schema_version"),
            purpose=row.get("purpose"),
            sheet_count=row.get("sheet_count"),
            has_vba_macros=bool(row.get("has_vba_macros", 0)),
            vulnerability_rating=row.get("vulnerability_rating"),
            extraction_complexity=row.get("extraction_complexity"),
            structural_risk=row.get("structural_risk"),
            computation_depth=row.get("computation_depth"),
            extraction_quality_score=row.get("extraction_quality_score"),
            comparison_mode=row.get("comparison_mode"),
            uploaded_at=row.get("uploaded_at"),
            dashboard_count=row.get("dashboard_count", 0),
            calculated_field_count=row.get("calculated_field_count", 0),
            datasource_count=row.get("datasource_count", 0),
        ))

    return results


@router.get("/workbooks/{workbook_id}", response_model=WorkbookDetail)
async def get_workbook(workbook_id: int):
    """Get full workbook detail including sheets and datasources."""
    db = get_database()
    row = db.query_one("SELECT * FROM workbooks WHERE id = ?", (workbook_id,))

    if not row:
        raise HTTPException(status_code=404, detail=f"Workbook not found: {workbook_id}")

    # Get dashboards
    dashboards = db.query(
        "SELECT * FROM dashboards WHERE workbook_id = ? ORDER BY id", (workbook_id,)
    )

    # Get datasources
    datasources = db.query(
        "SELECT * FROM datasources WHERE workbook_id = ? ORDER BY id", (workbook_id,)
    )

    # Count calculated fields
    cf_count = db.query_one(
        "SELECT COUNT(*) as cnt FROM calculated_fields WHERE workbook_id = ?",
        (workbook_id,)
    )

    from src.server.models.schemas import DashboardSummary, DatasourceSummary

    dashboard_models = []
    for d in dashboards:
        dashboard_models.append(DashboardSummary(
            id=d["id"],
            workbook_id=d["workbook_id"],
            workbook_name=row["name"],
            name=d["name"],
            sheet_type=d.get("sheet_type"),
            row_count=d.get("row_count"),
            column_count=d.get("column_count"),
            formula_count=d.get("formula_count"),
            table_count=d.get("table_count"),
            pivot_table_count=d.get("pivot_table_count"),
            hidden_row_count=d.get("hidden_row_count", 0),
            hidden_column_count=d.get("hidden_column_count", 0),
            ai_summary=d.get("ai_summary"),
            domain_classification=d.get("domain_classification"),
            line_of_business=d.get("line_of_business"),
            complexity_score=d.get("complexity_score"),
            is_real_ai=bool(d.get("is_real_ai", 0)),
        ))

    datasource_models = []
    for ds in datasources:
        datasource_models.append(DatasourceSummary(
            id=ds["id"],
            workbook_id=ds["workbook_id"],
            workbook_name=row["name"],
            name=ds["name"],
            caption=ds.get("caption"),
            column_headers=_parse_json_field(ds.get("column_headers")),
            row_count=ds.get("row_count"),
            column_count=ds.get("column_count"),
        ))

    return WorkbookDetail(
        id=row["id"],
        name=row["name"],
        source_file=row["source_file"],
        file_hash_md5=row.get("file_hash_md5"),
        schema_version=row.get("schema_version"),
        purpose=row.get("purpose"),
        sheet_count=row.get("sheet_count"),
        has_vba_macros=bool(row.get("has_vba_macros", 0)),
        vulnerability_rating=row.get("vulnerability_rating"),
        extraction_complexity=row.get("extraction_complexity"),
        structural_risk=row.get("structural_risk"),
        computation_depth=row.get("computation_depth"),
        extraction_quality_score=row.get("extraction_quality_score"),
        comparison_mode=row.get("comparison_mode"),
        uploaded_at=row.get("uploaded_at"),
        sheet_names=_parse_json_field(row.get("sheet_names")),
        external_links=_parse_json_field(row.get("external_links")),
        named_ranges=_parse_json_field(row.get("named_ranges")),
        raw_data_sheet_name=row.get("raw_data_sheet_name"),
        summary_sheet_name=row.get("summary_sheet_name"),
        primary_inputs=_parse_json_field(row.get("primary_inputs")),
        intermediate_calculations=_parse_json_field(row.get("intermediate_calculations")),
        final_outputs=_parse_json_field(row.get("final_outputs")),
        vba_macro_streams=_parse_json_field(row.get("vba_macro_streams")),
        json_output_path=row.get("json_output_path"),
        dashboard_count=len(dashboards),
        calculated_field_count=cf_count["cnt"] if cf_count else 0,
        datasource_count=len(datasources),
        dashboards=dashboard_models,
        datasources=datasource_models,
    )


@router.delete("/workbooks/{workbook_id}")
async def delete_workbook(workbook_id: int):
    """Delete a workbook and all its dependent data; mark downstream agents stale."""
    db = get_database()

    existing = db.query_one("SELECT id, name FROM workbooks WHERE id = ?", (workbook_id,))
    if not existing:
        raise HTTPException(status_code=404, detail=f"Workbook not found: {workbook_id}")

    workbook_name = existing["name"]
    db.delete_workbook_cascade(workbook_id)

    from src.server.services.agent_orchestrator import get_agent_orchestrator
    get_agent_orchestrator(db).notify_workbooks_changed()

    return {
        "message": f"Workbook '{workbook_name}' (id={workbook_id}) deleted successfully.",
        "agents_stale": True,
    }
