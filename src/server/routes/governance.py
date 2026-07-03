"""
Governance Routes — recommendations, risks, pairwise overlap, review queue.
"""
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.server.models.database import get_database
from src.server.models.schemas import (
    GovernanceRecommendation,
    GovernanceRisk,
    PairwiseMatrixResponse,
    PairwiseOverlap,
)
from src.rationalization.overlap_scorer import compute_pairwise_overlaps

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/governance", tags=["Governance"])


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


@router.get("/recommendations", response_model=List[GovernanceRecommendation])
async def list_recommendations():
    """List all workbook rationalization recommendations."""
    from datetime import datetime
    db = get_database()
    rows = db.query("""
        SELECT gr.*, w.name AS workbook_name, w.uploaded_at, w.sheet_names,
               w.extraction_complexity, w.structural_risk, w.computation_depth,
               w.extraction_quality_score, w.comparison_mode
        FROM governance_recommendations gr
        JOIN workbooks w ON gr.workbook_id = w.id
        ORDER BY gr.action, w.name
    """)

    results = []
    for r in rows:
        scores = {
            "extraction_complexity": r.get("extraction_complexity"),
            "structural_risk": r.get("structural_risk"),
            "computation_depth": r.get("computation_depth"),
            "extraction_quality_score": r.get("extraction_quality_score"),
            "comparison_mode": r.get("comparison_mode"),
        }

        # Calculate days_ago
        uploaded_at_str = r.get("uploaded_at")
        days_ago = 15
        if uploaded_at_str:
            try:
                uploaded_at_str_clean = uploaded_at_str.replace("T", " ").split(".")[0]
                uploaded_dt = datetime.strptime(uploaded_at_str_clean, "%Y-%m-%d %H:%M:%S")
                days_ago = max(1, (datetime.utcnow() - uploaded_dt).days)
            except Exception as e:
                logger.error(f"Error parsing uploaded_at {uploaded_at_str}: {e}")

        # Resolve user_groups for this workbook
        db_user_groups = db.query("SELECT DISTINCT user_groups FROM dashboards WHERE workbook_id = ?", (r["workbook_id"],))
        user_groups_set = set()
        for ug_row in db_user_groups:
            try:
                groups = json.loads(ug_row["user_groups"] or "[]")
                for g in groups:
                    if g:
                        user_groups_set.add(g)
            except Exception:
                pass
        user_groups = sorted(list(user_groups_set))

        # Resolve KPIs (distinct calculated fields)
        db_kpis = db.query("SELECT DISTINCT name FROM calculated_fields WHERE workbook_id = ?", (r["workbook_id"],))
        kpis = sorted([k["name"] for k in db_kpis if k["name"]])

        # Resolve Tables (distinct datasources)
        db_tables = db.query("SELECT DISTINCT name FROM datasources WHERE workbook_id = ?", (r["workbook_id"],))
        tables = sorted([t["name"] for t in db_tables if t["name"]])

        results.append(GovernanceRecommendation(
            id=r["id"],
            workbook_id=r["workbook_id"],
            workbook_name=r.get("workbook_name"),
            action=r["action"],
            merge_with_name=r.get("merge_with_name"),
            merge_with_id=r.get("merge_with_id"),
            kpi_overlap_score=r.get("kpi_overlap_score"),
            datasource_overlap_score=r.get("datasource_overlap_score"),
            uniqueness_score=r.get("uniqueness_score"),
            ds_sources_count=r.get("ds_sources_count", 0),
            ds_shared_count=r.get("ds_shared_count", 0),
            common_kpis=_pj(r.get("common_kpis")),
            common_datasources=_pj(r.get("common_datasources")),
            matching_fingerprints=_pj(r.get("matching_fingerprints")),
            reasons=_pj(r.get("reasons")),
            llm_justification=r.get("llm_justification"),
            llm_override=bool(r.get("llm_override", 0)),
            scores=scores,
            calculated_at=r.get("calculated_at"),
            sheet_names=_pj(r.get("sheet_names")),
            user_groups=user_groups,
            kpis=kpis,
            tables=tables,
            days_ago=days_ago,
            uploaded_at=uploaded_at_str,
        ))

    return results


@router.get("/review", response_model=List[GovernanceRecommendation])
async def list_review_queue():
    """List workbooks flagged for manual review."""
    recs = await list_recommendations()
    return [r for r in recs if r.action == "review"]


@router.get("/pairwise", response_model=PairwiseMatrixResponse)
async def get_pairwise_matrix(
    workbook_ids: Optional[str] = Query(None, description="Comma-separated workbook IDs"),
):
    """Return full pairwise overlap matrix for heatmap visualization."""
    db = get_database()
    wb_id_list = None
    if workbook_ids:
        wb_id_list = [int(x.strip()) for x in workbook_ids.split(",") if x.strip()]

    workbooks = db.query("SELECT id, name FROM workbooks ORDER BY id")
    if wb_id_list:
        workbooks = [w for w in workbooks if w["id"] in wb_id_list]

    pairwise = compute_pairwise_overlaps(db, workbook_ids=wb_id_list)

    pairs = []
    for (id_a, id_b), overlap in pairwise.items():
        pairs.append(PairwiseOverlap(
            workbook_id_a=id_a,
            workbook_id_b=id_b,
            workbook_name_a=overlap.get("name_a", ""),
            workbook_name_b=overlap.get("name_b", ""),
            kpi_overlap=round(overlap.get("kpi_overlap", 0), 4),
            ds_overlap=round(overlap.get("ds_overlap", 0), 4),
            structural_overlap=round(overlap.get("structural_overlap", 0), 4),
            fingerprint_ratio=round(overlap.get("fingerprint_ratio", 0), 4),
            combined_score=round(overlap.get("combined_score", 0), 4),
            overlap_class=overlap.get("overlap_class", "distinct"),
            overlap_relationship=overlap.get("overlap_relationship", "distinct"),
            common_kpis=overlap.get("common_kpis", []),
            unique_kpis_a=overlap.get("unique_kpis_a", []),
            unique_kpis_b=overlap.get("unique_kpis_b", []),
        ))

    return PairwiseMatrixResponse(
        workbooks=[{"id": w["id"], "name": w["name"]} for w in workbooks],
        pairs=pairs,
    )


@router.get("/risks", response_model=List[GovernanceRisk])
async def list_risks():
    """List all detected risks per workbook."""
    db = get_database()
    rows = db.query("""
        SELECT gr.*, w.name AS workbook_name,
               d.name AS dashboard_name
        FROM governance_risks gr
        JOIN workbooks w ON gr.workbook_id = w.id
        LEFT JOIN dashboards d ON gr.dashboard_id = d.id
        ORDER BY gr.severity DESC, w.name
    """)

    return [
        GovernanceRisk(
            id=r["id"],
            workbook_id=r["workbook_id"],
            workbook_name=r.get("workbook_name"),
            dashboard_id=r.get("dashboard_id"),
            dashboard_name=r.get("dashboard_name"),
            risk_category=r.get("risk_category"),
            severity=r.get("severity"),
            description=r.get("description"),
            affected_element=r.get("affected_element"),
            detected_at=r.get("detected_at"),
        )
        for r in rows
    ]


class SendEmailRequest(BaseModel):
    email: str
    subject: Optional[str] = None
    body: Optional[str] = None


@router.post("/send-email")
async def send_email_to_team(req: SendEmailRequest):
    """Simulate sending the rationalization results email to the governance team."""
    logger.info("Governance team notified at %s: rationalization results compiled. Subject: %s", req.email, req.subject)
    return {"status": "success", "message": f"Governance report has been successfully emailed to {req.email}."}

