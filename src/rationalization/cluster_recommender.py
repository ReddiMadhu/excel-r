"""
Cluster Recommender — Phase 5 of the rationalization pipeline.

Intra-cluster role assignment:
  1. Compute cluster-union KPI set for each cluster (GAP-02 fix)
  2. Two-pass canonical target selection (GAP-03 fix)
  3. Deterministic per-workbook role assignment
  4. decommission_after_merge pass (GAP-04 fix)

Roles: canonical_target | merge_source | decommission | review | keep
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from src.server.models.database import Database

logger = logging.getLogger(__name__)


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


# ─── KPI helpers ──────────────────────────────────────────────────────

def _get_canonical_kpis(db: Database, workbook_id: int) -> Set[str]:
    rows = db.query(
        """
        SELECT DISTINCT kc.canonical_name
        FROM calculated_fields cf
        JOIN kpi_cluster_cache kc ON cf.name = kc.original_name COLLATE NOCASE
        WHERE cf.workbook_id = ?
          AND cf.column_type IN ('formula_based', 'pivot_value', 'total')
        """,
        (workbook_id,),
    )
    return {r["canonical_name"] for r in rows}


def _ds_overlap(
    pairwise: Dict[Tuple[int, int], Dict[str, Any]],
    id_a: int,
    id_b: int,
) -> float:
    key = (min(id_a, id_b), max(id_a, id_b))
    return pairwise.get(key, {}).get("ds_overlap", 0.0)


def _cluster_edge_score(
    pairwise: Dict[Tuple[int, int], Dict[str, Any]],
    id_a: int,
    id_b: int,
) -> float:
    key = (min(id_a, id_b), max(id_a, id_b))
    return pairwise.get(key, {}).get("cluster_edge_score", 0.0)


# ─── Two-pass canonical target selection ──────────────────────────────

def _select_tentative_canonical(
    member_ids: List[int],
    pairwise: Dict[Tuple[int, int], Dict[str, Any]],
    wb_map: Dict[int, Dict],
    min_quality: float,
) -> int:
    """
    Pass 1: Select the Jaccard centroid (highest avg cluster_edge_score to
    all other members), with quality gate.
    """
    if len(member_ids) == 1:
        return member_ids[0]

    scores: Dict[int, float] = {}
    for wb_id in member_ids:
        others = [m for m in member_ids if m != wb_id]
        avg = sum(_cluster_edge_score(pairwise, wb_id, o) for o in others) / len(others)
        scores[wb_id] = avg

    # Sort descending by centroid score
    ranked = sorted(member_ids, key=lambda i: scores[i], reverse=True)

    # Quality gate: skip candidates below min extraction quality
    for candidate in ranked:
        quality = wb_map.get(candidate, {}).get("extraction_quality_score")
        if quality is None or quality >= min_quality:
            return candidate

    # If all fail quality gate, return highest-scoring anyway
    return ranked[0]


def _select_complexity_canonical(
    member_ids: List[int],
    wb_map: Dict[int, Dict],
) -> int:
    """
    Pass 2 (decommission clusters only): Select workbook with highest
    extraction_complexity (formula coverage).
    """
    def complexity_score(wb_id: int) -> float:
        ec = wb_map.get(wb_id, {}).get("extraction_complexity")
        return ec if ec is not None else 0.0

    return max(member_ids, key=complexity_score)


# ─── Role assignment ──────────────────────────────────────────────────

def assign_roles_for_cluster(
    cluster: Dict[str, Any],
    pairwise: Dict[Tuple[int, int], Dict[str, Any]],
    wb_map: Dict[int, Dict],
    db: Database,
) -> List[Dict[str, Any]]:
    """
    Assign cluster_role to every workbook in the cluster.
    Returns list of per-workbook decision dicts.
    """
    member_ids: List[int] = cluster["member_ids"]
    min_quality = _env_float("MIN_EXTRACTION_QUALITY", 0.60)
    decomm_ds_thresh = _env_float("DECOMMISSION_DS_THRESHOLD", 0.85)
    merge_ds_thresh = _env_float("MERGE_DS_THRESHOLD", 0.35)

    # ── Singleton shortcut ────────────────────────────────────
    if len(member_ids) == 1:
        wb_id = member_ids[0]
        return [{
            "workbook_id": wb_id,
            "cluster_role": "keep",
            "action": "keep",
            "decommission_after_merge": False,
            "canonical_target_id": wb_id,
            "merge_partners": [],
            "reasons": ["Singleton cluster — no overlap detected with other workbooks."],
            "unique_kpis_in_cluster": [],
        }]

    # ── Pass 1: Tentative centroid canonical ──────────────────
    tentative_canonical = _select_tentative_canonical(
        member_ids, pairwise, wb_map, min_quality
    )

    # ── Fetch raw sources for all members to compute containment ──
    from src.rationalization.overlap_scorer import _get_raw_sources_for_workbook
    from src.rationalization.source_normalizer import build_datasource_canonical_mapping
    ds_mapping = build_datasource_canonical_mapping(db, member_ids)
    ds_sets: Dict[int, Set[str]] = {}
    for wb_id in member_ids:
        sheet_map = ds_mapping.get(wb_id, {})
        sources, _mode = _get_raw_sources_for_workbook(db, wb_id, sheet_mapping=sheet_map)
        ds_sets[wb_id] = sources

    # ── Cluster-union KPI computation (GAP-02 fix) ────────────
    kpi_sets: Dict[int, Set[str]] = {
        wb_id: _get_canonical_kpis(db, wb_id) for wb_id in member_ids
    }
    cluster_kpi_union = set().union(*kpi_sets.values())

    # Unique KPIs per member = KPIs in M that no other member has
    def unique_to_member(wb_id: int) -> Set[str]:
        others_union = set().union(*(
            kpis for mid, kpis in kpi_sets.items() if mid != wb_id
        ))
        return kpi_sets[wb_id] - others_union

    # ── Deterministic role assignment ─────────────────────────
    decisions: Dict[int, Dict[str, Any]] = {}
    canonical_id = tentative_canonical


    for wb_id in member_ids:
        if wb_id == canonical_id:
            continue

        quality = wb_map.get(wb_id, {}).get("extraction_quality_score")
        comparison_mode = wb_map.get(wb_id, {}).get("comparison_mode")
        if quality is None:
            # Missing quality → cannot safely decommission/merge; force review
            quality = 0.0

        # Strict containment: evaluate directly against the canonical target Y
        my_kpis = kpi_sets[wb_id]
        target_kpis = kpi_sets[canonical_id]
        kpi_containment_in_target = (
            len(my_kpis & target_kpis) / len(my_kpis)
            if my_kpis else 0.0
        )
        unique_kpis = unique_to_member(wb_id)
        kpis_not_in_target = my_kpis - target_kpis

        # Primary: compare against canonical target directly (no peer metric borrowing)
        ds_overlap_with_canonical = _ds_overlap(pairwise, wb_id, canonical_id)
        
        my_sources = ds_sets[wb_id]
        canonical_sources = ds_sets[canonical_id]
        ds_containment_with_canonical = (
            len(my_sources & canonical_sources) / len(my_sources)
            if my_sources else 0.0
        )

        # Priority order
        role: str
        reasons: List[str] = []

        if comparison_mode == "insufficient" or quality < min_quality:
            role = "review"
            # Fetch extraction readiness details for diagnostic context
            _diag_parts = []
            wb_row = db.query_one(
                "SELECT extraction_quality_score, comparison_mode FROM workbooks WHERE id = ?",
                (wb_id,),
            )
            if wb_row:
                _diag_parts.append(
                    f"extraction_quality={wb_row.get('extraction_quality_score', 'N/A')}, "
                    f"comparison_mode={wb_row.get('comparison_mode', 'N/A')}"
                )
            # Count non-ready columns for context
            _total_cf = db.query_one(
                "SELECT COUNT(*) as cnt FROM calculated_fields WHERE workbook_id = ? "
                "AND column_type IN ('formula_based','pivot_value','total')",
                (wb_id,),
            )
            _cf_count = _total_cf["cnt"] if _total_cf else 0
            _diag_parts.append(f"KPI columns extracted: {_cf_count}")

            if comparison_mode == "insufficient":
                reasons.append(
                    f"comparison_mode=insufficient — extraction could not produce "
                    f"reliable lineage for KPI columns. "
                    f"Governance Review required (quality={quality:.0%}). "
                    f"Diagnostics: {'; '.join(_diag_parts)}."
                )
            else:
                reasons.append(
                    f"Extraction quality {quality:.0%} below {min_quality:.0%} threshold — "
                    f"manual Governance Review required before decommission. "
                    f"Diagnostics: {'; '.join(_diag_parts)}."
                )
            logger.info(
                "Review gate: workbook %d — quality=%.2f mode=%s (%s)",
                wb_id, quality, comparison_mode, "; ".join(_diag_parts),
            )

        elif not my_kpis:
            role = "review"
            # Check whether this is a KPI canonicalization issue or extraction issue
            _raw_cf = db.query_one(
                "SELECT COUNT(*) as cnt FROM calculated_fields WHERE workbook_id = ?",
                (wb_id,),
            )
            _raw_count = _raw_cf["cnt"] if _raw_cf else 0
            _kpi_cache_count = db.query_one(
                "SELECT COUNT(*) as cnt FROM kpi_cluster_cache",
            )
            _cache_count = _kpi_cache_count["cnt"] if _kpi_cache_count else 0
            if _raw_count == 0:
                reasons.append(
                    "No calculated fields (KPI columns) were extracted from this workbook — "
                    "the extraction pipeline found no formula_based/pivot_value/total columns "
                    "in summary_report sheets. Cannot assess redundancy."
                )
            elif _cache_count == 0:
                reasons.append(
                    f"Workbook has {_raw_count} calculated field(s) but KPI canonicalization "
                    f"has not been run (kpi_cluster_cache is empty). "
                    f"Run BI Intelligence first to group metrics across workbooks."
                )
            else:
                reasons.append(
                    f"Workbook has {_raw_count} calculated field(s) but none matched "
                    f"the KPI cluster cache ({_cache_count} canonical entries). "
                    f"Column names may not have been canonicalized correctly."
                )
            logger.info(
                "Review gate: workbook %d — no canonical KPIs (raw_cf=%d, cache=%d)",
                wb_id, _raw_count, _cache_count,
            )

        elif kpi_containment_in_target >= 1.0 and ds_containment_with_canonical >= decomm_ds_thresh:
            role = "decommission"
            reasons.append(
                f"All {len(my_kpis)} KPIs and {ds_containment_with_canonical:.0%} of data sources in this workbook "
                f"are fully covered by canonical target (workbook {canonical_id})."
            )

        elif (len(kpis_not_in_target) > 0 or len(unique_kpis) > 0 or ds_containment_with_canonical < decomm_ds_thresh) and (ds_overlap_with_canonical >= merge_ds_thresh or kpi_containment_in_target >= 0.50):
            role = "merge_source"
            if len(kpis_not_in_target) > 0:
                reasons.append(
                    f"Merge candidate — contributes {len(kpis_not_in_target)} unique KPI(s) to be consolidated into canonical target "
                    f"(datasource overlap {ds_overlap_with_canonical:.0%} with canonical target)."
                )
            else:
                reasons.append(
                    f"Merge candidate — shares {len(my_kpis)} KPI definitions with canonical target, "
                    f"requiring data source consolidation into canonical target "
                    f"(datasource overlap {ds_overlap_with_canonical:.0%}, containment {ds_containment_with_canonical:.0%})."
                )

        else:
            role = "review"
            if kpi_containment_in_target >= 1.0 and ds_containment_with_canonical < decomm_ds_thresh:
                reasons.append(
                    f"Governance Review required — all {len(my_kpis)} KPIs match canonical target, "
                    f"but datasource containment with canonical target ({ds_containment_with_canonical:.0%}) "
                    f"is below decommission threshold ({decomm_ds_thresh:.0%}). "
                    f"Canonical target does not encompass this report's underlying data sources."
                )
            elif len(kpis_not_in_target) > 0:
                reasons.append(
                    f"Governance Review required — report contains {len(kpis_not_in_target)} KPI(s) not found in canonical target, "
                    f"and datasource overlap with canonical target ({ds_overlap_with_canonical:.0%}) "
                    f"is below merge threshold ({merge_ds_thresh:.0%})."
                )
            else:
                reasons.append(
                    f"Ambiguous overlap within cluster — Governance Review required. "
                    f"Diagnostics: KPI containment in target = {kpi_containment_in_target:.1%} (decommission target: 100%), "
                    f"DS containment with canonical = {ds_containment_with_canonical:.1%} (decommission target: {decomm_ds_thresh:.0%}), "
                    f"DS overlap with canonical = {ds_overlap_with_canonical:.1%} (merge target: {merge_ds_thresh:.0%}), "
                    f"Unique KPIs = {len(kpis_not_in_target)}."
                )

        decisions[wb_id] = {
            "workbook_id": wb_id,
            "cluster_role": role,
            "action": _role_to_action(role),
            "decommission_after_merge": False,
            "reasons": reasons,
            "unique_kpis_in_cluster": sorted(unique_kpis),
            "_kpi_containment": kpi_containment_in_target,
            "_ds_containment": ds_containment_with_canonical,
            "_ds_overlap": ds_overlap_with_canonical,
        }

    # ── Pass 2: Canonical role refinement (GAP-03 fix) ───────
    # Check if cluster is decommission-type (zero merge_sources)
    has_merge_sources = any(
        d["cluster_role"] == "merge_source"
        for d in decisions.values()
    )
    if not has_merge_sources:
        # Pure decommission cluster → use complexity-based canonical
        complexity_canonical = _select_complexity_canonical(member_ids, wb_map)
        if complexity_canonical != tentative_canonical:
            logger.info(
                "Cluster %s: switching canonical from centroid %d to complexity %d "
                "(decommission-type cluster)",
                cluster.get("cluster_name", "?"),
                tentative_canonical,
                complexity_canonical,
            )
            # Re-derive decisions with new canonical
            canonical_id = complexity_canonical
            decisions = {}
            for wb_id in member_ids:
                if wb_id == canonical_id:
                    continue
                my_kpis = kpi_sets[wb_id]
                target_kpis = kpi_sets[canonical_id]
                kpi_containment_in_target = (
                    len(my_kpis & target_kpis) / len(my_kpis)
                    if my_kpis else 0.0
                )
                unique_kpis = unique_to_member(wb_id)
                kpis_not_in_target = my_kpis - target_kpis
                ds_overlap_with_canonical = _ds_overlap(pairwise, wb_id, canonical_id)
                
                my_sources = ds_sets[wb_id]
                canonical_sources = ds_sets[canonical_id]
                ds_containment_with_canonical = (
                    len(my_sources & canonical_sources) / len(my_sources)
                    if my_sources else 0.0
                )
                
                quality = wb_map.get(wb_id, {}).get("extraction_quality_score")
                if quality is None:
                    quality = 0.0  # missing ⇒ never prefer for decommission
                comparison_mode = wb_map.get(wb_id, {}).get("comparison_mode")

                if comparison_mode == "insufficient" or quality < min_quality:
                    role, reasons = "review", [
                        f"Extraction quality {quality:.0%} / mode={comparison_mode} — "
                        "Governance Review required."
                    ]
                elif not my_kpis:
                    role, reasons = "review", ["No KPIs extracted — cannot assess redundancy."]
                elif kpi_containment_in_target >= 1.0 and ds_containment_with_canonical >= decomm_ds_thresh:
                    role = "decommission"
                    reasons = [
                        f"All {len(my_kpis)} KPIs and {ds_containment_with_canonical:.0%} of data sources in this workbook "
                        f"are fully covered by canonical target (workbook {canonical_id})."
                    ]
                elif (len(kpis_not_in_target) > 0 or len(unique_kpis) > 0 or ds_containment_with_canonical < decomm_ds_thresh) and (ds_overlap_with_canonical >= merge_ds_thresh or kpi_containment_in_target >= 0.50):
                    role = "merge_source"
                    if len(kpis_not_in_target) > 0:
                        reasons = [
                            f"Merge candidate — contributes {len(kpis_not_in_target)} unique KPI(s) to be consolidated into canonical target "
                            f"(datasource overlap {ds_overlap_with_canonical:.0%} with canonical target)."
                        ]
                    else:
                        reasons = [
                            f"Merge candidate — shares {len(my_kpis)} KPI definitions with canonical target, "
                            f"requiring data source consolidation into canonical target "
                            f"(datasource overlap {ds_overlap_with_canonical:.0%}, containment {ds_containment_with_canonical:.0%})."
                        ]
                else:
                    role = "review"
                    if kpi_containment_in_target >= 1.0 and ds_containment_with_canonical < decomm_ds_thresh:
                        reasons = [
                            f"Governance Review required — all {len(my_kpis)} KPIs match canonical target, "
                            f"but datasource containment with canonical target ({ds_containment_with_canonical:.0%}) "
                            f"is below decommission threshold ({decomm_ds_thresh:.0%}). "
                            f"Canonical target does not encompass this report's underlying data sources."
                        ]
                    elif len(kpis_not_in_target) > 0:
                        reasons = [
                            f"Governance Review required — report contains {len(kpis_not_in_target)} KPI(s) not found in canonical target, "
                            f"and datasource overlap with canonical target ({ds_overlap_with_canonical:.0%}) "
                            f"is below merge threshold ({merge_ds_thresh:.0%})."
                        ]
                    else:
                        reasons = [
                            f"Ambiguous overlap within cluster — Governance Review required. "
                            f"Diagnostics: KPI containment in target = {kpi_containment_in_target:.1%} (decommission target: 100%), "
                            f"DS containment with canonical = {ds_containment_with_canonical:.1%} (decommission target: {decomm_ds_thresh:.0%}), "
                            f"DS overlap with canonical = {ds_overlap_with_canonical:.1%} (merge target: {merge_ds_thresh:.0%}), "
                            f"Unique KPIs = {len(kpis_not_in_target)}."
                        ]

                decisions[wb_id] = {
                    "workbook_id": wb_id,
                    "cluster_role": role,
                    "action": _role_to_action(role),
                    "decommission_after_merge": False,
                    "reasons": reasons,
                    "unique_kpis_in_cluster": sorted(unique_kpis),
                    "_kpi_containment": kpi_containment_in_target,
                    "_ds_containment": ds_containment_with_canonical,
                    "_ds_overlap": ds_overlap_with_canonical,
                }

    # ── canonical_target entry ─────────────────────────────────
    decisions[canonical_id] = {
        "workbook_id": canonical_id,
        "cluster_role": "canonical_target",
        "action": "keep",
        "decommission_after_merge": False,
        "reasons": ["Retained as canonical workbook for this cluster."],
        "unique_kpis_in_cluster": sorted(unique_to_member(canonical_id)),
        "_kpi_containment": 1.0,
        "_ds_containment": 1.0,
        "_ds_overlap": 1.0,
    }

    # ── decommission_after_merge pass (GAP-04 fix) ────────────
    has_merge_sources_final = any(
        d["cluster_role"] == "merge_source" for d in decisions.values()
    )
    for d in decisions.values():
        if d["cluster_role"] == "decommission" and has_merge_sources_final:
            d["decommission_after_merge"] = True

    # ── Attach canonical + merge_partners to all members ──────
    all_merge_ids = [
        d["workbook_id"] for d in decisions.values()
        if d["cluster_role"] in ("canonical_target", "merge_source")
    ]
    for d in decisions.values():
        d["canonical_target_id"] = canonical_id
        d["merge_partners"] = all_merge_ids if d["cluster_role"] in ("merge_source",) else []

    # Update cluster record with canonical target
    cluster["canonical_target_id"] = canonical_id

    return list(decisions.values())


def _role_to_action(role: str) -> str:
    mapping = {
        "canonical_target": "keep",
        "merge_source": "merge",
        "decommission": "decommission",
        "review": "review",
        "keep": "keep",
    }
    return mapping.get(role, "review")


# ─── Main entry point ──────────────────────────────────────────────────

def run_cluster_recommendations(
    db: Database,
    clusters: List[Dict[str, Any]],
    pairwise: Dict[Tuple[int, int], Dict[str, Any]],
    workbook_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """
    Run intra-cluster role assignment for all clusters.
    Returns flat list of all per-workbook decisions.
    """
    if workbook_ids:
        placeholders = ",".join("?" * len(workbook_ids))
        workbooks = db.query(
            f"SELECT id, name, purpose, extraction_quality_score, extraction_complexity, "
            f"comparison_mode FROM workbooks WHERE id IN ({placeholders})",
            tuple(workbook_ids),
        )
    else:
        workbooks = db.query(
            "SELECT id, name, purpose, extraction_quality_score, extraction_complexity, "
            "comparison_mode FROM workbooks"
        )
    wb_map = {wb["id"]: wb for wb in workbooks}

    all_decisions: List[Dict[str, Any]] = []
    for cluster in clusters:
        decisions = assign_roles_for_cluster(cluster, pairwise, wb_map, db)
        all_decisions.extend(decisions)

        # Update canonical_target_id on the cluster DB record
        if cluster.get("canonical_target_id") and cluster.get("id"):
            db.update(
                "workbook_clusters",
                {"canonical_target_id": cluster["canonical_target_id"]},
                "id = ?",
                (cluster["id"],),
            )

    logger.info(
        "Role assignment complete: %d keep, %d merge, %d decommission, %d review",
        sum(1 for d in all_decisions if d["action"] == "keep"),
        sum(1 for d in all_decisions if d["action"] == "merge"),
        sum(1 for d in all_decisions if d["action"] == "decommission"),
        sum(1 for d in all_decisions if d["action"] == "review"),
    )

    # ── Phase 6: Evidence-Based Audit Trail ──────────────────
    try:
        from src.rationalization.audit_logger import record_rationalization_audit
        audit_entries = []
        for cluster in clusters:
            cid = cluster.get("id")
            cname = cluster.get("cluster_name", "N/A")
            canonical_id = cluster.get("canonical_target_id")
            canonical_name = wb_map.get(canonical_id, {}).get("name", str(canonical_id)) if canonical_id else "None"
            member_ids = cluster.get("member_ids", [])

            for d in all_decisions:
                wid = d["workbook_id"]
                if wid not in member_ids:
                    continue
                wb_info = wb_map.get(wid, {})
                pw_key = (min(wid, canonical_id), max(wid, canonical_id)) if canonical_id and wid != canonical_id else None
                pw = pairwise.get(pw_key, {}) if pw_key else {}

                k_cont = d.get("_kpi_containment", 1.0 if wid == canonical_id else 0.0)
                d_cont = d.get("_ds_containment", 1.0 if wid == canonical_id else 0.0)
                d_ov = d.get("_ds_overlap", 1.0 if wid == canonical_id else 0.0)
                cand_ov = pw.get("candidate_column_overlap", 0.0)
                q_score = wb_info.get("extraction_quality_score")
                c_mode = wb_info.get("comparison_mode", "insufficient")

                audit_entries.append({
                    "workbook_id": wid,
                    "workbook_name": wb_info.get("name", str(wid)),
                    "cluster_id": cid,
                    "cluster_name": cname,
                    "canonical_target_id": canonical_id,
                    "canonical_target_name": canonical_name,
                    "cluster_role": d.get("cluster_role"),
                    "action": d.get("action"),
                    "decommission_after_merge": d.get("decommission_after_merge", False),
                    "kpi_containment": k_cont,
                    "ds_containment": d_cont,
                    "ds_overlap": d_ov,
                    "candidate_column_overlap": cand_ov,
                    "extraction_quality": q_score,
                    "comparison_mode": c_mode,
                    "safety_gates_summary": {
                        "KPI containment in cluster (>=100%)": k_cont >= 1.0 if wid != canonical_id else True,
                        "DS containment with canonical (>=85%)": d_cont >= 0.85 if wid != canonical_id else True,
                        "Extraction quality (>=60%)": (q_score is not None and q_score >= 0.60),
                        "Comparison mode (not insufficient)": (c_mode != "insufficient"),
                    },
                    "evidence": {
                        "unique_kpis": d.get("unique_kpis_in_cluster", []),
                        "common_kpis": pw.get("common_kpis", []),
                        "fingerprint_matches": pw.get("fingerprint_matches", 0),
                        "fingerprint_total": pw.get("fingerprint_total", 0),
                    },
                    "reasons": d.get("reasons", []),
                })

        if audit_entries:
            record_rationalization_audit(db, audit_entries)
    except Exception as e:
        logger.warning("Could not record rationalization audit: %s", e)

    return all_decisions
