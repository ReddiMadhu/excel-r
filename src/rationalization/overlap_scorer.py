"""
Overlap Scorer — Phase 2 of the rationalization pipeline.

Computes Jaccard overlap scores across workbooks:
  - KPI overlap (canonical KPI sets)
  - Raw source overlap (normalized ultimate_raw_sources + datasources + primary_inputs)
  - Fingerprint dedup (canonicalized computation signatures)
  - Structural context (shared final_outputs)
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from src.server.models.database import Database
from src.rationalization.source_normalizer import (
    normalize_datasource_headers,
    normalize_source_set,
    parse_json_list,
)

logger = logging.getLogger(__name__)


def _get_canonical_kpis_for_workbook(
    db: Database, workbook_id: int
) -> Set[str]:
    """Get the set of canonical KPI names for a workbook."""
    rows = db.query("""
        SELECT DISTINCT kc.canonical_name
        FROM calculated_fields cf
        JOIN kpi_cluster_cache kc ON cf.name = kc.original_name COLLATE NOCASE
        WHERE cf.workbook_id = ?
          AND cf.column_type IN ('formula_based', 'pivot_value', 'total')
    """, (workbook_id,))
    return {r["canonical_name"] for r in rows}


def _get_raw_sources_for_workbook(
    db: Database, workbook_id: int
) -> Set[str]:
    """
    Get normalized raw source set for a workbook.

    Source priority:
      1. ultimate_raw_sources from calculated_fields — formula-lineage derived,
         tracks exactly which raw columns each formula references.  This is the
         gold standard for both pivot_value and formula_based columns.
      2. primary_inputs from workbooks — manually tagged or inferred inputs.
      3. Datasource column headers (fallback ONLY) — all column headers from raw
         data sheets.  Only used when lineage extraction produced no sources at
         all.  Including these unconditionally inflates Jaccard to ~100% for any
         two workbooks sharing the same raw data sheet (e.g. a pivot table
         workbook and a regular formula workbook both sitting on SQL_data), even
         when their formulas reference entirely different columns.
    """
    sources: Set[str] = set()

    # 1. Formula-lineage sources (specific columns actually used by formulas)
    rows = db.query("""
        SELECT ultimate_raw_sources
        FROM calculated_fields
        WHERE workbook_id = ?
          AND ultimate_raw_sources IS NOT NULL
          AND ultimate_raw_sources != '[]'
    """, (workbook_id,))
    for r in rows:
        sources |= normalize_source_set(parse_json_list(r.get("ultimate_raw_sources")))

    # 2. Workbook-level primary inputs
    wb = db.query_one("SELECT primary_inputs FROM workbooks WHERE id = ?", (workbook_id,))
    if wb:
        sources |= normalize_source_set(parse_json_list(wb.get("primary_inputs")))

    # 3. Fallback: raw datasource column headers, only when lineage is absent
    if not sources:
        ds_rows = db.query(
            "SELECT name, column_headers FROM datasources WHERE workbook_id = ?",
            (workbook_id,),
        )
        for ds in ds_rows:
            headers = parse_json_list(ds.get("column_headers"))
            sources |= normalize_datasource_headers(ds.get("name", ""), headers)

    return sources


def _get_structural_outputs_for_workbook(db: Database, workbook_id: int) -> Set[str]:
    """Get normalized final_outputs for structural context overlap."""
    wb = db.query_one("SELECT final_outputs FROM workbooks WHERE id = ?", (workbook_id,))
    if not wb:
        return set()
    outputs = parse_json_list(wb.get("final_outputs"))
    return {o.lower().strip().replace(" ", "_") for o in outputs if o}


def _get_fingerprints_for_workbook(
    db: Database, workbook_id: int
) -> Set[str]:
    """Get the set of computation fingerprints for a workbook."""
    rows = db.query("""
        SELECT DISTINCT fingerprint
        FROM calculated_fields
        WHERE workbook_id = ?
          AND fingerprint IS NOT NULL
          AND fingerprint != ''
    """, (workbook_id,))
    return {r["fingerprint"] for r in rows}


def _canonicalize_fingerprint(
    fingerprint: str,
    kpi_cache: Dict[str, str]
) -> str:
    """Replace column names in a fingerprint with canonical equivalents."""
    result = fingerprint
    for original, canonical in kpi_cache.items():
        orig_norm = original.lower().replace(" ", "_").replace("-", "_")
        canon_norm = canonical.lower().replace(" ", "_").replace("-", "_")
        if orig_norm in result.lower():
            result = result.replace(orig_norm, canon_norm)
    return result


def jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    """Compute Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def _workbook_query(db: Database, workbook_ids: Optional[List[int]] = None) -> List[Dict]:
    """Fetch workbooks, optionally filtered to a scan subset."""
    if workbook_ids:
        placeholders = ",".join("?" * len(workbook_ids))
        return db.query(
            f"SELECT id, name FROM workbooks WHERE id IN ({placeholders}) ORDER BY id",
            tuple(workbook_ids),
        )
    return db.query("SELECT id, name FROM workbooks ORDER BY id")


def compute_pairwise_overlaps(
    db: Database,
    workbook_ids: Optional[List[int]] = None,
) -> Dict[Tuple[int, int], Dict[str, Any]]:
    """
    Compute overlap scores for workbook pairs.

    If workbook_ids is provided, only compares within that subset.
    """
    workbooks = _workbook_query(db, workbook_ids)
    if len(workbooks) < 2:
        logger.info("Fewer than 2 workbooks — no pairwise comparison needed")
        return {}

    kpi_rows = db.query("SELECT original_name, canonical_name FROM kpi_cluster_cache")
    kpi_cache = {r["original_name"]: r["canonical_name"] for r in kpi_rows}

    wb_data: Dict[int, Dict[str, Any]] = {}
    for wb in workbooks:
        wb_id = wb["id"]
        raw_sources = _get_raw_sources_for_workbook(db, wb_id)
        wb_data[wb_id] = {
            "name": wb["name"],
            "canonical_kpis": _get_canonical_kpis_for_workbook(db, wb_id),
            "raw_sources": raw_sources,
            "fingerprints": _get_fingerprints_for_workbook(db, wb_id),
            "structural_outputs": _get_structural_outputs_for_workbook(db, wb_id),
        }

    for wb_id, data in wb_data.items():
        data["canon_fingerprints"] = {
            _canonicalize_fingerprint(fp, kpi_cache) for fp in data["fingerprints"]
        }

    results: Dict[Tuple[int, int], Dict[str, Any]] = {}
    wb_ids = list(wb_data.keys())

    for i in range(len(wb_ids)):
        for j in range(i + 1, len(wb_ids)):
            id_a, id_b = wb_ids[i], wb_ids[j]
            data_a, data_b = wb_data[id_a], wb_data[id_b]

            kpi_a = data_a["canonical_kpis"]
            kpi_b = data_b["canonical_kpis"]
            kpi_overlap = jaccard_similarity(kpi_a, kpi_b)
            common_kpis = sorted(kpi_a & kpi_b)
            unique_kpis_a = sorted(kpi_a - kpi_b)
            unique_kpis_b = sorted(kpi_b - kpi_a)

            src_a = data_a["raw_sources"]
            src_b = data_b["raw_sources"]
            ds_overlap = jaccard_similarity(src_a, src_b)
            common_ds = list(src_a & src_b)

            struct_a = data_a["structural_outputs"]
            struct_b = data_b["structural_outputs"]
            structural_overlap = jaccard_similarity(struct_a, struct_b)

            fp_a = data_a["canon_fingerprints"]
            fp_b = data_b["canon_fingerprints"]
            matching_fps = list(fp_a & fp_b)
            total_fps = len(fp_a | fp_b)
            fp_ratio = len(matching_fps) / total_fps if total_fps > 0 else 0.0

            alpha = float(os.getenv("OVERLAP_WEIGHT_KPI", "0.35"))
            beta = float(os.getenv("OVERLAP_WEIGHT_DS", "0.25"))
            gamma = float(os.getenv("OVERLAP_WEIGHT_FINGERPRINT", "0.25"))
            delta = float(os.getenv("OVERLAP_WEIGHT_STRUCTURAL", "0.15"))
            combined_score = (
                alpha * kpi_overlap + beta * ds_overlap
                + gamma * fp_ratio + delta * structural_overlap
            )

            kpi_containment_a = (
                len(kpi_a & kpi_b) / len(kpi_a) if kpi_a else 0.0
            )
            kpi_containment_b = (
                len(kpi_a & kpi_b) / len(kpi_b) if kpi_b else 0.0
            )

            overlap_relationship = "distinct"
            if kpi_a and kpi_b and kpi_a == kpi_b:
                overlap_relationship = "identical"
            elif kpi_containment_a >= 1.0 and unique_kpis_b:
                overlap_relationship = "a_subset_of_b"
            elif kpi_containment_b >= 1.0 and unique_kpis_a:
                overlap_relationship = "b_subset_of_a"
            elif common_kpis and unique_kpis_a and unique_kpis_b:
                overlap_relationship = "both_have_extras"

            overlap_class = "distinct"
            # Relationship-first classification (mirrors Recommender):
            #   duplicate       → subset, identical, or near-duplicate (Jaccard gates)
            #   merge_candidate → shared KPIs with extras on BOTH sides
            if overlap_relationship in ("identical", "a_subset_of_b", "b_subset_of_a"):
                overlap_class = "duplicate"
            elif (
                kpi_overlap >= 0.85 and ds_overlap >= 0.85 and fp_ratio >= 0.70
            ):
                overlap_class = "duplicate"
            elif (
                overlap_relationship == "both_have_extras"
                and kpi_overlap >= 0.50
                and ds_overlap >= 0.60
            ):
                overlap_class = "merge_candidate"

            results[(id_a, id_b)] = {
                "kpi_overlap": kpi_overlap,
                "ds_overlap": ds_overlap,
                "structural_overlap": structural_overlap,
                "fingerprint_matches": len(matching_fps),
                "fingerprint_total": total_fps,
                "fingerprint_ratio": fp_ratio,
                "combined_score": combined_score,
                "overlap_class": overlap_class,
                "common_kpis": common_kpis,
                "unique_kpis_a": unique_kpis_a,
                "unique_kpis_b": unique_kpis_b,
                "kpi_containment_a": round(kpi_containment_a, 4),
                "kpi_containment_b": round(kpi_containment_b, 4),
                "overlap_relationship": overlap_relationship,
                "common_datasources": common_ds,
                "matching_fingerprints": matching_fps,
                "name_a": data_a["name"],
                "name_b": data_b["name"],
            }

    logger.info(
        "Computed %d pairwise overlaps for %d workbooks",
        len(results), len(workbooks)
    )
    return results


def compute_uniqueness_scores(
    db: Database,
    pairwise: Dict[Tuple[int, int], Dict[str, Any]],
    alpha: float = 0.35,
    beta: float = 0.25,
    gamma: float = 0.25,
    delta: float = 0.15,
    workbook_ids: Optional[List[int]] = None,
) -> Dict[int, Dict[str, Any]]:
    """
    Compute uniqueness score for each workbook.

    Uniqueness(A) = 1.0 - max over all B of combined overlap score
    """
    workbooks = _workbook_query(db, workbook_ids)
    wb_map = {wb["id"]: wb["name"] for wb in workbooks}

    scores: Dict[int, Dict[str, Any]] = {}

    for wb_id in wb_map:
        max_combined = 0.0
        most_similar_id = None
        most_similar_name = None
        max_kpi = 0.0
        max_ds = 0.0
        max_fp_ratio = 0.0

        for (id_a, id_b), overlap in pairwise.items():
            other_id = None
            if id_a == wb_id:
                other_id = id_b
            elif id_b == wb_id:
                other_id = id_a
            else:
                continue

            combined = overlap.get("combined_score")
            if combined is None:
                kpi = overlap["kpi_overlap"]
                ds = overlap["ds_overlap"]
                total = overlap["fingerprint_total"]
                fp_ratio = overlap["fingerprint_matches"] / total if total > 0 else 0.0
                struct = overlap.get("structural_overlap", 0.0)
                combined = alpha * kpi + beta * ds + gamma * fp_ratio + delta * struct
            else:
                kpi = overlap["kpi_overlap"]
                ds = overlap["ds_overlap"]
                fp_ratio = overlap.get("fingerprint_ratio", 0.0)

            if combined > max_combined:
                max_combined = combined
                most_similar_id = other_id
                most_similar_name = wb_map.get(other_id, "")
                max_kpi = kpi
                max_ds = ds
                max_fp_ratio = fp_ratio

        uniqueness = max(0.0, 1.0 - max_combined)

        scores[wb_id] = {
            "uniqueness_score": round(uniqueness, 4),
            "most_similar_id": most_similar_id,
            "most_similar_name": most_similar_name,
            "max_combined_score": round(max_combined, 4),
            "max_kpi_overlap": round(max_kpi, 4),
            "max_ds_overlap": round(max_ds, 4),
            "max_fingerprint_ratio": round(max_fp_ratio, 4),
        }

    logger.info("Computed uniqueness scores for %d workbooks", len(scores))
    return scores
