"""
Overlap Scorer — Phase 2 of the rationalization pipeline.

Computes Jaccard overlap scores across workbooks:
  - KPI overlap (canonical KPI sets)
  - Raw source overlap (normalized ultimate_raw_sources + datasources + primary_inputs)
  - Fingerprint dedup (canonicalized computation signatures)
  - Structural context (shared final_outputs)
  - Semantic similarity (LOB + domain + filename prefix) [new in v2]

Also computes cluster_edge_score = 5-signal weighted composite,
writes results to pairwise_overlap_cache with hash-based invalidation.
"""
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.server.models.database import Database
from src.rationalization.source_normalizer import (
    normalize_datasource_headers,
    normalize_source_set,
    parse_json_list,
)
from src.rationalization.semantic_similarity import (
    get_workbook_semantic_features,
    compute_semantic_similarity,
    check_semantic_data_available,
)

from src.parsers.formula_lineage import LINEAGE_SCHEMA_VERSION

logger = logging.getLogger(__name__)


def _lineage_hash_suffix() -> str:
    """Include lineage schema version so cache invalidates on semantic fixes."""
    return f"|lineage:{LINEAGE_SCHEMA_VERSION}"


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
    """
    Normalize fingerprint for cross-workbook comparison.

    IMPORTANT: Do NOT replace SUM:/WHERE:/GROUP_BY: operand tokens with
    canonical KPI names — that collapses Paid vs Incurred into the same
    fingerprint when both KPIs are labeled "Total Claims".
    Only light whitespace normalization is applied.
    """
    if not fingerprint:
        return ""
    # Preserve measure/filter/group semantics; only normalize separators
    return re.sub(r"\s+", "", fingerprint.strip().lower())


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


def _get_cluster_edge_score(overlap: Dict[str, Any]) -> float:
    """Compute 5-signal cluster_edge_score from overlap dict."""
    w_kpi = float(os.getenv("CLUSTER_WEIGHT_KPI", "0.30"))
    w_ds = float(os.getenv("CLUSTER_WEIGHT_DS", "0.25"))
    w_fp = float(os.getenv("CLUSTER_WEIGHT_FP", "0.20"))
    w_struct = float(os.getenv("CLUSTER_WEIGHT_STRUCT", "0.10"))
    w_sem = float(os.getenv("CLUSTER_WEIGHT_SEM", "0.15"))
    return (
        w_kpi * overlap.get("kpi_overlap", 0.0)
        + w_ds * overlap.get("ds_overlap", 0.0)
        + w_fp * overlap.get("fingerprint_ratio", 0.0)
        + w_struct * overlap.get("structural_overlap", 0.0)
        + w_sem * overlap.get("semantic_similarity", 0.0)
    )


def _get_cached_overlap(
    db: Database, id_a: int, id_b: int, hash_a: str, hash_b: str
) -> Optional[Dict[str, Any]]:
    """Return cached pairwise overlap if hashes match, else None."""
    min_id, max_id = min(id_a, id_b), max(id_a, id_b)
    h_min = hash_a if id_a < id_b else hash_b
    h_max = hash_b if id_a < id_b else hash_a
    row = db.query_one(
        "SELECT * FROM pairwise_overlap_cache WHERE workbook_id_a=? AND workbook_id_b=?",
        (min_id, max_id),
    )
    if row and row.get("hash_a") == h_min and row.get("hash_b") == h_max:
        # Deserialize JSON columns
        for col in ("common_kpis", "unique_kpis_a", "unique_kpis_b",
                    "common_datasources", "matching_fingerprints"):
            if isinstance(row.get(col), str):
                try:
                    row[col] = json.loads(row[col])
                except Exception:
                    row[col] = []
        return dict(row)
    return None


def _upsert_overlap_cache(
    db: Database,
    id_a: int,
    id_b: int,
    hash_a: str,
    hash_b: str,
    overlap: Dict[str, Any],
) -> None:
    """UPSERT overlap result into pairwise_overlap_cache."""
    min_id, max_id = min(id_a, id_b), max(id_a, id_b)
    h_min = hash_a if id_a < id_b else hash_b
    h_max = hash_b if id_a < id_b else hash_a
    try:
        db.execute(
            """
            INSERT INTO pairwise_overlap_cache
                (workbook_id_a, workbook_id_b, hash_a, hash_b,
                 kpi_overlap, ds_overlap, structural_overlap, fingerprint_ratio,
                 semantic_similarity, cluster_edge_score, combined_score,
                 overlap_class, overlap_relationship,
                 common_kpis, unique_kpis_a, unique_kpis_b,
                 common_datasources, matching_fingerprints)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(workbook_id_a, workbook_id_b)
            DO UPDATE SET
                hash_a=excluded.hash_a, hash_b=excluded.hash_b,
                kpi_overlap=excluded.kpi_overlap, ds_overlap=excluded.ds_overlap,
                structural_overlap=excluded.structural_overlap,
                fingerprint_ratio=excluded.fingerprint_ratio,
                semantic_similarity=excluded.semantic_similarity,
                cluster_edge_score=excluded.cluster_edge_score,
                combined_score=excluded.combined_score,
                overlap_class=excluded.overlap_class,
                overlap_relationship=excluded.overlap_relationship,
                common_kpis=excluded.common_kpis, unique_kpis_a=excluded.unique_kpis_a,
                unique_kpis_b=excluded.unique_kpis_b,
                common_datasources=excluded.common_datasources,
                matching_fingerprints=excluded.matching_fingerprints,
                computed_at=datetime('now')
            """,
            (
                min_id, max_id, h_min, h_max,
                overlap.get("kpi_overlap", 0.0),
                overlap.get("ds_overlap", 0.0),
                overlap.get("structural_overlap", 0.0),
                overlap.get("fingerprint_ratio", 0.0),
                overlap.get("semantic_similarity", 0.0),
                overlap.get("cluster_edge_score", 0.0),
                overlap.get("combined_score", 0.0),
                overlap.get("overlap_class", "distinct"),
                overlap.get("overlap_relationship", "distinct"),
                json.dumps(overlap.get("common_kpis", [])),
                json.dumps(overlap.get("unique_kpis_a", [])),
                json.dumps(overlap.get("unique_kpis_b", [])),
                json.dumps(overlap.get("common_datasources", [])),
                json.dumps(overlap.get("matching_fingerprints", [])),
            ),
        )
    except Exception as e:
        logger.warning("Failed to upsert pairwise cache for (%d,%d): %s", min_id, max_id, e)


def compute_pairwise_overlaps(
    db: Database,
    workbook_ids: Optional[List[int]] = None,
    use_cache: bool = True,
) -> Dict[Tuple[int, int], Dict[str, Any]]:
    """
    Compute overlap scores for workbook pairs (5-signal, with cache).

    If workbook_ids is provided, only compares within that subset.
    """
    semantic_available = check_semantic_data_available(db)
    if not semantic_available:
        logger.warning(
            "Intelligence agent not yet run — semantic_similarity will be computed "
            "from filename tokens only. Run Intelligence first for better cluster accuracy."
        )

    workbooks = _workbook_query(db, workbook_ids)
    if len(workbooks) < 2:
        logger.info("Fewer than 2 workbooks — no pairwise comparison needed")
        return {}

    kpi_rows = db.query("SELECT original_name, canonical_name FROM kpi_cluster_cache")
    kpi_cache = {r["original_name"]: r["canonical_name"] for r in kpi_rows}

    # Get file hashes for cache lookup
    wb_hashes: Dict[int, str] = {}
    for wb in workbooks:
        row = db.query_one("SELECT file_hash_md5 FROM workbooks WHERE id = ?", (wb["id"],))
        wb_hashes[wb["id"]] = (row.get("file_hash_md5") or "" if row else "") + _lineage_hash_suffix()

    wb_data: Dict[int, Dict[str, Any]] = {}
    for wb in workbooks:
        wb_id = wb["id"]
        raw_sources = _get_raw_sources_for_workbook(db, wb_id)
        semantic_features = get_workbook_semantic_features(db, wb_id, wb["name"])
        wb_data[wb_id] = {
            "name": wb["name"],
            "canonical_kpis": _get_canonical_kpis_for_workbook(db, wb_id),
            "raw_sources": raw_sources,
            "fingerprints": _get_fingerprints_for_workbook(db, wb_id),
            "structural_outputs": _get_structural_outputs_for_workbook(db, wb_id),
            "semantic_features": semantic_features,
            "semantic_data_available": semantic_available,
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

            # Cache lookup
            if use_cache:
                cached = _get_cached_overlap(
                    db, id_a, id_b, wb_hashes.get(id_a, ""), wb_hashes.get(id_b, "")
                )
                if cached:
                    results[(id_a, id_b)] = cached
                    continue

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

            # Semantic similarity (5th signal)
            sem_sim = compute_semantic_similarity(
                data_a["semantic_features"], data_b["semantic_features"]
            )

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
            if kpi_a and kpi_b and kpi_a == kpi_b and fp_ratio >= 0.90:
                overlap_relationship = "same"
            elif kpi_a and kpi_b and kpi_a == kpi_b:
                overlap_relationship = "identical"
            elif kpi_containment_a >= 1.0 and unique_kpis_b:
                overlap_relationship = "a_subset_of_b"
            elif kpi_containment_b >= 1.0 and unique_kpis_a:
                overlap_relationship = "b_subset_of_a"
            elif common_kpis and unique_kpis_a and unique_kpis_b:
                # Related: share measure/sources but extras on both sides (e.g. filters)
                if ds_overlap >= 0.5 and fp_ratio < 0.90:
                    overlap_relationship = "related"
                else:
                    overlap_relationship = "both_have_extras"
            elif not matching_fps and not common_kpis:
                overlap_relationship = "different"
            elif fp_ratio == 0 and kpi_overlap == 0:
                overlap_relationship = "unknown" if not src_a or not src_b else "different"

            overlap_class = "distinct"
            # Semantic classes for rationalization:
            #   same / related / different / unknown (+ legacy duplicate/merge_candidate)
            if overlap_relationship == "same" or (
                overlap_relationship in ("identical", "a_subset_of_b", "b_subset_of_a")
                and fp_ratio >= 0.70
            ):
                overlap_class = "same" if overlap_relationship == "same" else "duplicate"
            elif overlap_relationship == "related":
                overlap_class = "related"
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
            elif overlap_relationship in ("different", "unknown"):
                overlap_class = overlap_relationship
            elif fp_ratio == 0 and kpi_overlap < 0.2:
                overlap_class = "different"

            entry = {
                "kpi_overlap": kpi_overlap,
                "ds_overlap": ds_overlap,
                "structural_overlap": structural_overlap,
                "fingerprint_matches": len(matching_fps),
                "fingerprint_total": total_fps,
                "fingerprint_ratio": fp_ratio,
                "semantic_similarity": sem_sim,
                "combined_score": combined_score,
                "overlap_class": overlap_class,
                "common_kpis": common_kpis,
                "unique_kpis_a": unique_kpis_a,
                "unique_kpis_b": unique_kpis_b,
                "kpi_containment_a": round(kpi_containment_a, 4),
                "kpi_containment_b": round(kpi_containment_b, 4),
                "overlap_relationship": overlap_relationship,
                "common_datasources": common_ds,
                "ds_count_a": len(src_a),
                "ds_count_b": len(src_b),
                "matching_fingerprints": matching_fps,
                "name_a": data_a["name"],
                "name_b": data_b["name"],
                "cluster_edge_score": 0.0,  # computed below
            }
            entry["cluster_edge_score"] = round(_get_cluster_edge_score(entry), 4)
            results[(id_a, id_b)] = entry

            # Write to cache
            if use_cache:
                _upsert_overlap_cache(
                    db, id_a, id_b, wb_hashes.get(id_a, ""), wb_hashes.get(id_b, ""), entry
                )

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
