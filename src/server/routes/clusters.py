"""
Cluster Routes — /api/governance/clusters

GET /api/governance/clusters
    → List[ClusterSummary] ordered by cohesion_score desc

GET /api/governance/clusters/{cluster_id}
    → ClusterDetail with suspect_edges, pairwise scores, per-workbook recs

GET /api/governance/clusters/{cluster_id}/comparison
    → Comparison table data for the cluster detail view

GET /api/governance/clusters/{cluster_id}/multi-compare?workbook_ids=1,2,3
    → Pre-computed pairwise overlap data for multiple candidates vs the Target
"""
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from src.server.models.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/governance/clusters", tags=["Clusters"])


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


def _get_cluster_members(db, cluster_id: int) -> List[Dict[str, Any]]:
    """Return workbook IDs for a cluster."""
    rows = db.query(
        "SELECT workbook_id FROM workbook_cluster_members WHERE cluster_id = ?",
        (cluster_id,),
    )
    return [r["workbook_id"] for r in rows]


def _build_cluster_summary(db, cluster: Dict[str, Any]) -> Dict[str, Any]:
    cluster_id = cluster["id"]
    member_ids = _get_cluster_members(db, cluster_id)

    # canonical target name
    canonical_name = None
    if cluster.get("canonical_target_id"):
        cw = db.query_one(
            "SELECT name FROM workbooks WHERE id = ?",
            (cluster["canonical_target_id"],)
        )
        canonical_name = cw["name"] if cw else None

    # per-member summary
    members = []
    for wb_id in member_ids:
        wb = db.query_one(
            "SELECT id, name, extraction_complexity, extraction_quality_score FROM workbooks WHERE id = ?",
            (wb_id,)
        ) or {}
        rec = db.query_one(
            """
            SELECT action, cluster_role, decommission_after_merge,
                   kpi_overlap_score, datasource_overlap_score
            FROM governance_recommendations WHERE workbook_id = ?
            """,
            (wb_id,),
        ) or {}

        kpi_count = db.query_one(
            "SELECT COUNT(DISTINCT name) as cnt FROM calculated_fields WHERE workbook_id = ?",
            (wb_id,),
        ) or {}
        ds_count = db.query_one(
            "SELECT COUNT(DISTINCT name) as cnt FROM datasources WHERE workbook_id = ?",
            (wb_id,),
        ) or {}
        formula_count = db.query_one(
            "SELECT COALESCE(SUM(formula_count),0) as cnt FROM dashboards WHERE workbook_id = ?",
            (wb_id,),
        ) or {}

        members.append({
            "workbook_id": wb_id,
            "workbook_name": wb.get("name", str(wb_id)),
            "cluster_role": rec.get("cluster_role", "keep"),
            "action": rec.get("action", "keep"),
            "kpi_count": kpi_count.get("cnt", 0),
            "ds_count": ds_count.get("cnt", 0),
            "unique_kpi_count": 0,  # enriched in detail endpoint
            "formula_count": formula_count.get("cnt", 0),
            "extraction_quality_score": wb.get("extraction_quality_score"),
            "decommission_after_merge": bool(rec.get("decommission_after_merge", 0)),
        })

    return {
        "id": cluster_id,
        "cluster_name": cluster["cluster_name"],
        "cluster_size": cluster["cluster_size"],
        "cohesion_score": cluster["cohesion_score"],
        "canonical_target_id": cluster.get("canonical_target_id"),
        "canonical_target_name": canonical_name,
        "cluster_action_summary": cluster.get("cluster_action_summary"),
        "cluster_validation_flag": cluster.get("cluster_validation_flag"),
        "llm_validation_skipped": bool(cluster.get("llm_validation_skipped", 0)),
        "target_override_reason": cluster.get("target_override_reason"),
        "members": members,
    }


@router.get("")
async def list_clusters():
    """List all workbook clusters ordered by cohesion_score descending."""
    db = get_database()
    clusters = db.query(
        "SELECT * FROM workbook_clusters ORDER BY cohesion_score DESC"
    )

    result = []
    for cluster in clusters:
        result.append(_build_cluster_summary(db, cluster))

    return result


@router.get("/{cluster_id}")
async def get_cluster_detail(cluster_id: int):
    """Full cluster detail: members, pairwise scores, recommendations, suspect edges."""
    db = get_database()
    cluster = db.query_one(
        "SELECT * FROM workbook_clusters WHERE id = ?", (cluster_id,)
    )
    if not cluster:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")

    summary = _build_cluster_summary(db, cluster)
    member_ids = _get_cluster_members(db, cluster_id)

    # Pairwise scores within cluster
    pairwise_scores: Dict[str, float] = {}
    member_name_map: Dict[int, str] = {
        m["workbook_id"]: m["workbook_name"] for m in summary["members"]
    }
    for i in range(len(member_ids)):
        for j in range(i + 1, len(member_ids)):
            a, b = member_ids[i], member_ids[j]
            min_id, max_id = min(a, b), max(a, b)
            row = db.query_one(
                "SELECT cluster_edge_score FROM pairwise_overlap_cache "
                "WHERE workbook_id_a=? AND workbook_id_b=?",
                (min_id, max_id),
            )
            score = row["cluster_edge_score"] if row else 0.0
            name_a = (member_name_map.get(a) or str(a))[:25]
            name_b = (member_name_map.get(b) or str(b))[:25]
            pairwise_scores[f"{name_a}↔{name_b}"] = round(score, 3)

    # Suspect edges
    suspect_edges = _pj(cluster.get("suspect_edges")) or []

    # Full recommendations per member
    recommendations = []
    for wb_id in member_ids:
        rec = db.query_one(
            "SELECT * FROM governance_recommendations WHERE workbook_id = ?",
            (wb_id,)
        )
        if rec:
            rec = dict(rec)
            for col in ("reasons", "common_kpis", "common_datasources",
                        "matching_fingerprints", "merge_partners"):
                rec[col] = _pj(rec.get(col))

            # Resolve canonical target name
            canonical_target_id = rec.get("canonical_target_id")
            if canonical_target_id:
                cw = db.query_one(
                    "SELECT name FROM workbooks WHERE id = ?", (canonical_target_id,)
                )
                rec["canonical_target_name"] = cw["name"] if cw else None

            # Resolve merge_partners_names
            partners = rec.get("merge_partners") or []
            partner_names = []
            for pid in partners:
                pw = db.query_one("SELECT name FROM workbooks WHERE id = ?", (pid,))
                if pw:
                    partner_names.append(pw["name"])
            rec["merge_partners_names"] = partner_names

            # Workbook name
            wb = db.query_one("SELECT name FROM workbooks WHERE id = ?", (wb_id,))
            rec["workbook_name"] = wb["name"] if wb else str(wb_id)

            recommendations.append(rec)

    return {
        **summary,
        "suspect_edges": suspect_edges,
        "pairwise_scores": pairwise_scores,
        "llm_stage1_reasoning": cluster.get("llm_stage1_reasoning"),
        "recommendations": recommendations,
    }


@router.get("/{cluster_id}/comparison")
async def get_cluster_comparison(cluster_id: int):
    """
    Comparison table for cluster detail view.
    Returns columns = workbooks, rows = metrics.
    """
    db = get_database()
    cluster = db.query_one(
        "SELECT * FROM workbook_clusters WHERE id = ?", (cluster_id,)
    )
    if not cluster:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")

    member_ids = _get_cluster_members(db, cluster_id)
    columns = []
    for wb_id in member_ids:
        wb = db.query_one("SELECT * FROM workbooks WHERE id = ?", (wb_id,)) or {}
        rec = db.query_one(
            "SELECT action, cluster_role, kpi_overlap_score, datasource_overlap_score "
            "FROM governance_recommendations WHERE workbook_id = ?",
            (wb_id,),
        ) or {}
        kpi_count = db.query_one(
            "SELECT COUNT(DISTINCT name) as cnt FROM calculated_fields WHERE workbook_id = ?",
            (wb_id,),
        ) or {}
        ds_count = db.query_one(
            "SELECT COUNT(DISTINCT name) as cnt FROM datasources WHERE workbook_id = ?",
            (wb_id,),
        ) or {}
        formula_count = db.query_one(
            "SELECT COALESCE(SUM(formula_count),0) as total FROM dashboards WHERE workbook_id = ?",
            (wb_id,),
        ) or {}

        # Unique KPIs — not in any other member
        all_kpis = {r["name"] for r in db.query(
            "SELECT DISTINCT name FROM calculated_fields WHERE workbook_id = ?", (wb_id,)
        )}
        other_kpis: set = set()
        for other_id in member_ids:
            if other_id != wb_id:
                other_kpis |= {r["name"] for r in db.query(
                    "SELECT DISTINCT name FROM calculated_fields WHERE workbook_id = ?",
                    (other_id,)
                )}
        unique_kpi_count = len(all_kpis - other_kpis)

        columns.append({
            "workbook_id": wb_id,
            "workbook_name": wb.get("name", str(wb_id)),
            "cluster_role": rec.get("cluster_role", "keep"),
            "action": rec.get("action", "keep"),
            "kpi_count": kpi_count.get("cnt", 0),
            "ds_count": ds_count.get("cnt", 0),
            "unique_kpi_count": unique_kpi_count,
            "formula_count": formula_count.get("total", 0),
            "extraction_complexity": wb.get("extraction_complexity"),
            "extraction_quality_score": wb.get("extraction_quality_score"),
            "kpi_overlap_score": rec.get("kpi_overlap_score"),
            "datasource_overlap_score": rec.get("datasource_overlap_score"),
            "is_canonical": rec.get("cluster_role") == "canonical_target",
        })

    return {
        "cluster_id": cluster_id,
        "cluster_name": cluster["cluster_name"],
        "columns": columns,
    }


def _get_workbook_kpis(db, workbook_id: int) -> List[str]:
    """
    Get canonical KPI names for a workbook.
    Uses kpi_cluster_cache for canonical name mapping, falls back to raw names.
    """
    # Build canonical name lookup from kpi_cluster_cache
    canon_rows = db.query(
        "SELECT original_name, canonical_name FROM kpi_cluster_cache"
    )
    canon_map = {}
    for cr in canon_rows:
        canon_map[cr["original_name"].lower()] = cr["canonical_name"]

    # Get formula-based / pivot / total calculated fields for this workbook
    wb_fields = db.query(
        """SELECT DISTINCT name FROM calculated_fields
           WHERE workbook_id = ?
             AND column_type IN ('formula_based', 'pivot_value', 'total')""",
        (workbook_id,),
    )

    # Deduplicate by canonical name (case-insensitive)
    kpi_map = {}
    for cf in wb_fields:
        orig_lower = cf["name"].lower()
        canon_name = canon_map.get(orig_lower, cf["name"])
        dedupe_key = canon_name.lower()
        if dedupe_key not in kpi_map:
            kpi_map[dedupe_key] = canon_name

    return sorted(kpi_map.values())


def _get_workbook_rec_full(db, workbook_id: int) -> Optional[Dict[str, Any]]:
    """Get full recommendation record for a workbook, with resolved names."""
    from datetime import datetime
    rec = db.query_one(
        "SELECT * FROM governance_recommendations WHERE workbook_id = ?",
        (workbook_id,),
    )
    if not rec:
        return None

    rec = dict(rec)
    for col in ("reasons", "common_kpis", "common_datasources",
                "matching_fingerprints", "merge_partners"):
        rec[col] = _pj(rec.get(col))

    # Resolve workbook name
    wb = db.query_one("SELECT name FROM workbooks WHERE id = ?", (workbook_id,))
    rec["workbook_name"] = wb["name"] if wb else str(workbook_id)

    # Resolve merge_with_name
    if rec.get("merge_with_id"):
        mw = db.query_one("SELECT name FROM workbooks WHERE id = ?", (rec["merge_with_id"],))
        if mw:
            rec["merge_with_name"] = mw["name"]

    # Resolve canonical_target_name
    if rec.get("canonical_target_id"):
        cw = db.query_one("SELECT name FROM workbooks WHERE id = ?", (rec["canonical_target_id"],))
        rec["canonical_target_name"] = cw["name"] if cw else None

    # Resolve partner names
    partners = rec.get("merge_partners") or []
    partner_names = []
    for pid in partners:
        pw = db.query_one("SELECT name FROM workbooks WHERE id = ?", (pid,))
        if pw:
            partner_names.append(pw["name"])
    rec["merge_partners_names"] = partner_names

    # Resolve user_groups
    db_user_groups = db.query(
        "SELECT DISTINCT user_groups FROM dashboards WHERE workbook_id = ?",
        (workbook_id,),
    )
    user_groups_set = set()
    for ug_row in db_user_groups:
        try:
            import json as _json
            groups = _json.loads(ug_row["user_groups"] or "[]")
            for g in groups:
                if g:
                    user_groups_set.add(g)
        except Exception:
            pass
    rec["user_groups"] = sorted(list(user_groups_set))

    # Resolve tables (datasource names)
    db_tables = db.query(
        "SELECT DISTINCT name FROM datasources WHERE workbook_id = ?",
        (workbook_id,),
    )
    rec["tables"] = sorted([t["name"] for t in db_tables if t["name"]])

    # DS sources count
    ds_count_row = db.query_one(
        "SELECT COUNT(DISTINCT name) as cnt FROM datasources WHERE workbook_id = ?",
        (workbook_id,),
    ) or {}
    rec["ds_sources_count"] = rec.get("ds_sources_count") or ds_count_row.get("cnt", 0)

    # Scores from workbook table
    wb_full = db.query_one("SELECT * FROM workbooks WHERE id = ?", (workbook_id,)) or {}
    rec["scores"] = {
        "extraction_complexity": wb_full.get("extraction_complexity"),
        "structural_risk": wb_full.get("structural_risk"),
        "computation_depth": wb_full.get("computation_depth"),
        "extraction_quality_score": wb_full.get("extraction_quality_score"),
        "comparison_mode": wb_full.get("comparison_mode"),
    }

    return rec


@router.get("/{cluster_id}/member/{workbook_id}/detail")
async def get_cluster_member_detail(cluster_id: int, workbook_id: int):
    """
    Full rationalization detail for a single workbook within a cluster.
    Pre-computes KPI overlaps, coverage scores, and all recommendation data
    needed for the rich inline detail panel.
    """
    db = get_database()

    # Validate cluster exists
    cluster = db.query_one(
        "SELECT * FROM workbook_clusters WHERE id = ?", (cluster_id,)
    )
    if not cluster:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")

    # Validate workbook is a member of this cluster
    member_ids = _get_cluster_members(db, cluster_id)
    if workbook_id not in member_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Workbook {workbook_id} is not a member of cluster {cluster_id}"
        )

    # Get the source recommendation
    source_rec = _get_workbook_rec_full(db, workbook_id)
    if not source_rec:
        raise HTTPException(
            status_code=404,
            detail=f"No recommendation found for workbook {workbook_id}"
        )

    # Determine the type (decommission / merge / keep)
    cluster_role = source_rec.get("cluster_role", source_rec.get("action", "keep"))
    action = source_rec.get("action", "keep")

    # Determine target workbook
    target_id = source_rec.get("merge_with_id") or cluster.get("canonical_target_id")
    target_rec = None
    if target_id and target_id != workbook_id:
        target_rec = _get_workbook_rec_full(db, target_id)

    # Get KPIs for both workbooks
    source_kpis = _get_workbook_kpis(db, workbook_id)
    target_kpis = _get_workbook_kpis(db, target_id) if target_id and target_id != workbook_id else []

    # Compute overlaps
    source_kpi_set = set(source_kpis)
    target_kpi_set = set(target_kpis)

    shared_kpis = sorted([k for k in source_kpis if k in target_kpi_set])
    source_only_kpis = sorted([k for k in source_kpis if k not in target_kpi_set])
    target_only_kpis = sorted([k for k in target_kpis if k not in source_kpi_set])

    shared_count = len(shared_kpis)
    source_total = len(source_kpis)
    target_total = len(target_kpis)

    # Coverage percentages
    source_kpi_coverage = round((shared_count / source_total) * 100) if source_total > 0 else 0
    target_kpi_coverage = round((shared_count / target_total) * 100) if target_total > 0 else 0
    source_unique_pct = round(((source_total - shared_count) / source_total) * 100) if source_total > 0 else 0
    target_unique_pct = round(((target_total - shared_count) / target_total) * 100) if target_total > 0 else 0

    # DS coverage
    source_ds_count = source_rec.get("ds_sources_count", 0)
    target_ds_count = target_rec.get("ds_sources_count", 0) if target_rec else 0
    ds_shared_count = source_rec.get("ds_shared_count", 0)
    if not ds_shared_count and source_rec.get("common_datasources"):
        ds_shared_count = len(source_rec["common_datasources"])

    source_ds_coverage = round((ds_shared_count / source_ds_count) * 100) if source_ds_count > 0 else (
        round((source_rec.get("datasource_overlap_score") or 0) * 100)
    )
    target_ds_coverage = round((ds_shared_count / target_ds_count) * 100) if target_ds_count > 0 else (
        round((source_rec.get("datasource_overlap_score") or 0) * 100)
    )

    # Build response
    return {
        "workbook_id": workbook_id,
        "workbook_name": source_rec.get("workbook_name"),
        "cluster_role": cluster_role,
        "action": action,
        "type": "decommission" if cluster_role == "decommission" else (
            "merge" if cluster_role == "merge_source" else "keep"
        ),

        "rec": source_rec,
        "target_rec": target_rec,

        "source_kpis": source_kpis,
        "target_kpis": target_kpis,

        "shared_kpis": shared_kpis,
        "source_only_kpis": source_only_kpis,
        "target_only_kpis": target_only_kpis,

        "kpi_coverage": {
            "source_coverage_pct": source_kpi_coverage,
            "target_coverage_pct": target_kpi_coverage,
            "source_unique_pct": source_unique_pct,
            "target_unique_pct": target_unique_pct,
            "shared_count": shared_count,
            "source_total": source_total,
            "target_total": target_total,
            "ds_shared_count": ds_shared_count,
            "source_ds_count": source_ds_count,
            "target_ds_count": target_ds_count,
            "source_ds_coverage_pct": source_ds_coverage,
            "target_ds_coverage_pct": target_ds_coverage,
        },

        "cluster_name": cluster.get("cluster_name"),
        "canonical_target_id": cluster.get("canonical_target_id"),
        "canonical_target_name": source_rec.get("canonical_target_name"),
    }


@router.get("/{cluster_id}/multi-compare")
async def get_cluster_multi_compare(cluster_id: int, workbook_ids: str = ""):
    """
    Pre-computed pairwise overlap data for multiple candidates vs the Target.
    Returns per-candidate KPI/DS overlap stats in a single call.

    Query param: workbook_ids — comma-separated list of candidate workbook IDs.
    """
    db = get_database()

    # Validate cluster
    cluster = db.query_one(
        "SELECT * FROM workbook_clusters WHERE id = ?", (cluster_id,)
    )
    if not cluster:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")

    member_ids = _get_cluster_members(db, cluster_id)
    canonical_target_id = cluster.get("canonical_target_id")

    # Parse requested workbook IDs
    requested_ids = []
    if workbook_ids:
        for wid_str in workbook_ids.split(","):
            wid_str = wid_str.strip()
            if wid_str:
                try:
                    wid = int(wid_str)
                    if wid in member_ids:
                        requested_ids.append(wid)
                except ValueError:
                    pass

    if not requested_ids:
        raise HTTPException(status_code=400, detail="No valid workbook_ids provided")

    # Get target data (cached once)
    target_rec = _get_workbook_rec_full(db, canonical_target_id) if canonical_target_id else None
    target_kpis = _get_workbook_kpis(db, canonical_target_id) if canonical_target_id else []
    target_kpi_set = set(target_kpis)

    # Target DS info
    target_ds_count = target_rec.get("ds_sources_count", 0) if target_rec else 0

    # Build per-candidate results
    candidates_result = []
    for wb_id in requested_ids:
        source_rec = _get_workbook_rec_full(db, wb_id)
        if not source_rec:
            continue

        # Determine type
        cluster_role = source_rec.get("cluster_role", source_rec.get("action", "keep"))
        action = source_rec.get("action", "keep")
        wb_type = "decommission" if cluster_role == "decommission" else (
            "merge" if cluster_role == "merge_source" else "keep"
        )

        # KPI overlap
        source_kpis = _get_workbook_kpis(db, wb_id)
        source_kpi_set = set(source_kpis)
        shared_kpis = sorted([k for k in source_kpis if k in target_kpi_set])
        source_only_kpis = sorted([k for k in source_kpis if k not in target_kpi_set])
        target_only_kpis = sorted([k for k in target_kpis if k not in source_kpi_set])

        shared_count = len(shared_kpis)
        source_total = len(source_kpis)
        target_total = len(target_kpis)

        source_kpi_coverage = round((shared_count / source_total) * 100) if source_total > 0 else 0
        target_kpi_coverage = round((shared_count / target_total) * 100) if target_total > 0 else 0
        source_unique_pct = round(((source_total - shared_count) / source_total) * 100) if source_total > 0 else 0
        target_unique_pct = round(((target_total - shared_count) / target_total) * 100) if target_total > 0 else 0

        # DS overlap
        source_ds_count = source_rec.get("ds_sources_count", 0)
        ds_shared_count = source_rec.get("ds_shared_count", 0)
        if not ds_shared_count and source_rec.get("common_datasources"):
            ds_shared_count = len(source_rec["common_datasources"])

        source_ds_coverage = round((ds_shared_count / source_ds_count) * 100) if source_ds_count > 0 else (
            round((source_rec.get("datasource_overlap_score") or 0) * 100)
        )
        target_ds_coverage = round((ds_shared_count / target_ds_count) * 100) if target_ds_count > 0 else (
            round((source_rec.get("datasource_overlap_score") or 0) * 100)
        )

        # Clean reasons
        reasons = source_rec.get("reasons") or []
        if isinstance(reasons, str):
            try:
                reasons = json.loads(reasons)
            except Exception:
                reasons = []
        reasons = [r for r in reasons if not any(
            x in r.lower() for x in ("fingerprint", "retained workbook", "retained over")
        )]

        candidates_result.append({
            "workbook_id": wb_id,
            "workbook_name": source_rec.get("workbook_name"),
            "cluster_role": cluster_role,
            "action": action,
            "type": wb_type,
            "rec": source_rec,
            "source_kpis": source_kpis,
            "shared_kpis": shared_kpis,
            "source_only_kpis": source_only_kpis,
            "target_only_kpis": target_only_kpis,
            "kpi_coverage": {
                "source_coverage_pct": source_kpi_coverage,
                "target_coverage_pct": target_kpi_coverage,
                "source_unique_pct": source_unique_pct,
                "target_unique_pct": target_unique_pct,
                "shared_count": shared_count,
                "source_total": source_total,
                "target_total": target_total,
                "ds_shared_count": ds_shared_count,
                "source_ds_count": source_ds_count,
                "target_ds_count": target_ds_count,
                "source_ds_coverage_pct": source_ds_coverage,
                "target_ds_coverage_pct": target_ds_coverage,
            },
            "reasons": reasons,
        })

    # Target reasons
    target_reasons = []
    if target_rec:
        target_reasons = target_rec.get("reasons") or []
        if isinstance(target_reasons, str):
            try:
                target_reasons = json.loads(target_reasons)
            except Exception:
                target_reasons = []
        target_reasons = [r for r in target_reasons if not any(
            x in r.lower() for x in ("fingerprint", "retained workbook", "retained over")
        )]

    return {
        "cluster_id": cluster_id,
        "cluster_name": cluster.get("cluster_name"),
        "canonical_target_id": canonical_target_id,
        "target_rec": target_rec,
        "target_kpis": target_kpis,
        "target_reasons": target_reasons,
        "candidates": candidates_result,
    }


@router.put("/{cluster_id}/target")
async def change_cluster_target(cluster_id: int, body: dict):
    """
    Human-in-the-loop: change the recommended target for a cluster.
    Cascades role reassignment for all members in a single transaction.

    Body: { "new_target_id": int, "reason": str }
    """
    from fastapi import Request

    db = get_database()

    new_target_id = body.get("new_target_id")
    reason = body.get("reason", "").strip()

    if not new_target_id:
        raise HTTPException(status_code=400, detail="new_target_id is required")
    if not reason or len(reason) < 10:
        raise HTTPException(status_code=400, detail="A rationale of at least 10 characters is required")

    # Validate cluster
    cluster = db.query_one(
        "SELECT * FROM workbook_clusters WHERE id = ?", (cluster_id,)
    )
    if not cluster:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")

    member_ids = _get_cluster_members(db, cluster_id)
    if new_target_id not in member_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Workbook {new_target_id} is not a member of cluster {cluster_id}"
        )

    old_target_id = cluster.get("canonical_target_id")

    # No change needed
    if new_target_id == old_target_id:
        return {"status": "no_change", "message": "Selected workbook is already the target."}

    # Resolve new target name
    new_target_wb = db.query_one("SELECT name FROM workbooks WHERE id = ?", (new_target_id,))
    new_target_name = new_target_wb["name"] if new_target_wb else str(new_target_id)

    # 1. Update cluster table
    db.update(
        "workbook_clusters",
        {
            "canonical_target_id": new_target_id,
            "target_override_reason": reason,
        },
        "id = ?",
        (cluster_id,),
    )

    # 2. Update old target → merge_source
    if old_target_id:
        db.update(
            "governance_recommendations",
            {
                "cluster_role": "merge_source",
                "action": "merge",
                "merge_with_id": new_target_id,
                "merge_with_name": new_target_name,
            },
            "workbook_id = ?",
            (old_target_id,),
        )

    # 3. Update new target → canonical_target
    db.update(
        "governance_recommendations",
        {
            "cluster_role": "canonical_target",
            "action": "keep",
            "merge_with_id": None,
            "merge_with_name": None,
        },
        "workbook_id = ?",
        (new_target_id,),
    )

    # 4. Re-point all other members' merge_with_id from old target to new target
    if old_target_id:
        for mid in member_ids:
            if mid == new_target_id:
                continue
            rec = db.query_one(
                "SELECT merge_with_id FROM governance_recommendations WHERE workbook_id = ?",
                (mid,),
            )
            if rec and rec.get("merge_with_id") == old_target_id:
                db.update(
                    "governance_recommendations",
                    {
                        "merge_with_id": new_target_id,
                        "merge_with_name": new_target_name,
                    },
                    "workbook_id = ?",
                    (mid,),
                )

    # 5. Update canonical_target_id on all member recommendation rows
    for mid in member_ids:
        db.update(
            "governance_recommendations",
            {"canonical_target_id": new_target_id},
            "workbook_id = ?",
            (mid,),
        )

    logger.info(
        "Target changed for cluster %d: %s → %s. Reason: %s",
        cluster_id, old_target_id, new_target_id, reason,
    )

    return {
        "status": "ok",
        "message": f"Target changed to '{new_target_name}' successfully.",
        "new_target_id": new_target_id,
        "new_target_name": new_target_name,
    }
