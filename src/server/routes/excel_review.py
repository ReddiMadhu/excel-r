"""
Excel Review API — cell/formula findings (distinct from governance review queue).
"""
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from src.server.models.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/excel-review", tags=["Excel Review"])


def _parse_json_field(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (list, dict)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    return val


def _serialize_finding(row: Dict[str, Any], workbook_name: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "workbook_id": row["workbook_id"],
        "workbook_name": workbook_name,
        "type": row.get("finding_type"),
        "finding_type": row.get("finding_type"),
        "sheet": row.get("sheet"),
        "cell": row.get("cell"),
        "severity": row.get("severity"),
        "confidence": row.get("confidence"),
        "confidence_score": row.get("confidence_score"),
        "actual": row.get("actual"),
        "expected_pattern": row.get("expected_pattern"),
        "evidence": _parse_json_field(row.get("evidence")) or [],
        "dependencies": _parse_json_field(row.get("dependencies")) or [],
        "dependents": _parse_json_field(row.get("dependents")) or [],
        "signals": _parse_json_field(row.get("signals")) or {},
        "status": row.get("status", "OPEN"),
        "detected_at": row.get("detected_at"),
    }


@router.get("/findings")
async def list_findings(
    workbook_id: Optional[int] = Query(None),
    finding_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
):
    """List Excel Review findings (optionally filtered)."""
    db = get_database()
    sql = """
        SELECT f.*, w.name as workbook_name
        FROM excel_review_findings f
        JOIN workbooks w ON w.id = f.workbook_id
        WHERE 1=1
    """
    params: List[Any] = []
    if workbook_id is not None:
        sql += " AND f.workbook_id = ?"
        params.append(workbook_id)
    if finding_type:
        sql += " AND f.finding_type = ?"
        params.append(finding_type)
    if severity:
        sql += " AND f.severity = ?"
        params.append(severity)
    sql += " ORDER BY CASE f.severity WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, f.id"

    try:
        rows = db.query(sql, tuple(params))
    except Exception as e:
        # Table may not exist on very old DBs — migrate on the fly
        logger.warning("excel_review_findings query failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    return [_serialize_finding(r, r.get("workbook_name")) for r in rows]


@router.get("/findings/{workbook_id}")
async def findings_for_workbook(workbook_id: int):
    """Findings + analysis status for one workbook."""
    db = get_database()
    wb = db.query_one("SELECT id, name, source_file FROM workbooks WHERE id = ?", (workbook_id,))
    if not wb:
        raise HTTPException(status_code=404, detail="Workbook not found")

    rows = db.query(
        "SELECT * FROM excel_review_findings WHERE workbook_id = ? ORDER BY id",
        (workbook_id,),
    )
    findings = [_serialize_finding(r, wb["name"]) for r in rows]
    by_type: Dict[str, int] = {}
    for f in findings:
        t = f["finding_type"]
        by_type[t] = by_type.get(t, 0) + 1

    unsupported = any(f["finding_type"] == "UNSUPPORTED_FEATURE" for f in findings)
    return {
        "workbook_id": workbook_id,
        "workbook_name": wb["name"],
        "status": "completed",
        "findings_count": len(findings),
        "by_type": by_type,
        "unsupported_features_present": unsupported,
        "findings": findings,
        "empty_meaning": (
            "No review findings detected"
            if findings
            else "No review findings detected"
        ),
    }


@router.post("/run")
async def run_review(workbook_id: Optional[int] = Query(None)):
    """Re-run Excel Review for one workbook or the full portfolio."""
    db = get_database()
    from src.review.engine import run_excel_review, run_excel_review_for_scan

    if workbook_id is not None:
        wb = db.query_one("SELECT id, source_file FROM workbooks WHERE id = ?", (workbook_id,))
        if not wb:
            raise HTTPException(status_code=404, detail="Workbook not found")
        return run_excel_review(db, workbook_id, wb.get("source_file"))
    return run_excel_review_for_scan(db)


@router.get("/summary")
async def review_summary():
    """Portfolio-level Excel Review summary for sidebar / empty states."""
    db = get_database()
    wb_count = db.query_one("SELECT COUNT(*) as cnt FROM workbooks")
    finding_count = db.query_one("SELECT COUNT(*) as cnt FROM excel_review_findings")
    by_type = db.query(
        "SELECT finding_type, COUNT(*) as cnt FROM excel_review_findings GROUP BY finding_type"
    )
    wb_with = db.query_one(
        "SELECT COUNT(DISTINCT workbook_id) as cnt FROM excel_review_findings"
    )
    return {
        "workbooks": wb_count["cnt"] if wb_count else 0,
        "findings": finding_count["cnt"] if finding_count else 0,
        "workbooks_with_findings": wb_with["cnt"] if wb_with else 0,
        "by_type": {r["finding_type"]: r["cnt"] for r in by_type},
    }
