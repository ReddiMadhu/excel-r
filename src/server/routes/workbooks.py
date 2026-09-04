"""
Workbook Routes — GET /api/workbooks, GET /api/workbooks/{id}, DELETE /api/workbooks/{id}
"""
import io
import json
import logging
import os
from typing import List, Optional
import zipfile

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from src.server.models.database import get_database
from src.server.models.schemas import WorkbookSummary, WorkbookDetail

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Workbooks"])

INPUT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "input")
)


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
            user_groups=_parse_json_field(d.get("user_groups")),
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


# ─── Input File Download Endpoints ─────────────────────────────────────

@router.get("/input-files")
async def list_input_files():
    """List all available input Excel files with metadata and download URLs."""
    if not os.path.exists(INPUT_DIR):
        return {"files": [], "total_files": 0, "download_all_url": None}

    files = []
    for fname in sorted(os.listdir(INPUT_DIR)):
        if fname.lower().endswith((".xlsx", ".xls", ".xlsm")):
            fpath = os.path.join(INPUT_DIR, fname)
            if os.path.isfile(fpath):
                files.append({
                    "filename": fname,
                    "size_bytes": os.path.getsize(fpath),
                    "download_url": f"/api/input-files/{fname}",
                })
    return {
        "files": files,
        "total_files": len(files),
        "download_all_url": "/api/input-files/download-all",
    }


@router.get("/input-files/download-all")
async def download_all_input_files():
    """Download all input Excel files bundled as a single zip archive."""
    if not os.path.exists(INPUT_DIR):
        raise HTTPException(status_code=404, detail="Input files directory not found")

    excel_files = [
        f for f in sorted(os.listdir(INPUT_DIR))
        if f.lower().endswith((".xlsx", ".xls", ".xlsm")) and os.path.isfile(os.path.join(INPUT_DIR, f))
    ]
    if not excel_files:
        raise HTTPException(status_code=404, detail="No input files found to download")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in excel_files:
            fpath = os.path.join(INPUT_DIR, fname)
            zf.write(fpath, arcname=fname)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="input_excel_files.zip"'},
    )


@router.get("/input-files/{filename}")
async def download_input_file(filename: str):
    """Download a single input Excel file by filename (e.g. 1.xlsx, 4.xlsx)."""
    safe_name = os.path.basename(filename)
    fpath = os.path.abspath(os.path.join(INPUT_DIR, safe_name))
    if not fpath.startswith(INPUT_DIR) or not os.path.isfile(fpath):
        raise HTTPException(status_code=404, detail=f"File '{safe_name}' not found in input files directory")

    return FileResponse(
        path=fpath,
        filename=safe_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/workbooks/{workbook_id}/download")
async def download_workbook_file(workbook_id: int):
    """Download the original Excel file for a workbook by its workbook ID."""
    db = get_database()
    wb = db.query_one("SELECT id, name, source_file FROM workbooks WHERE id = ?", (workbook_id,))

    candidates = []
    if wb:
        if wb.get("source_file"):
            candidates.append(wb["source_file"])
            candidates.append(os.path.join(INPUT_DIR, os.path.basename(wb["source_file"])))
        if wb.get("name"):
            candidates.append(os.path.join(INPUT_DIR, f"{wb['name']}.xlsx"))
    candidates.append(os.path.join(INPUT_DIR, f"{workbook_id}.xlsx"))

    found_path = None
    for cand in candidates:
        if cand and os.path.isfile(cand):
            found_path = cand
            break

    if not found_path:
        raise HTTPException(
            status_code=404,
            detail=f"Source Excel file not found for workbook {workbook_id}",
        )

    download_name = os.path.basename(found_path)
    return FileResponse(
        path=found_path,
        filename=download_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
