"""
KPI Canonicalizer — Phase 1 of the rationalization pipeline.

Step 1: Lexical pre-clustering (Token Sort Ratio ≥ 0.85)
Step 2: LLM refinement of ambiguous clusters
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from src.server.models.database import Database

logger = logging.getLogger(__name__)

# Stop words to strip from KPI names for normalization
_STOP_WORDS = {"of", "the", "and", "for", "by", "in", "to", "a", "an", "is", "from", "with"}

# Common prefixes/suffixes to strip
_STRIP_PREFIXES = ["sum of", "total of", "count of", "average of", "avg of", "grand total"]
_STRIP_SUFFIXES = ["total", "grand total", "check"]


def _normalize_kpi_name(name: str) -> str:
    """Normalize a KPI name for comparison."""
    n = name.strip().lower()

    # Strip common prefixes
    for prefix in _STRIP_PREFIXES:
        if n.startswith(prefix):
            n = n[len(prefix):].strip()

    # Strip common suffixes
    for suffix in _STRIP_SUFFIXES:
        if n.endswith(suffix):
            n = n[:-len(suffix)].strip()

    # Remove punctuation, replace spaces with underscores
    n = re.sub(r'[^a-z0-9\s]', '', n)
    # Remove stop words
    tokens = [t for t in n.split() if t not in _STOP_WORDS]
    return "_".join(tokens)


def _token_sort_ratio(a: str, b: str) -> float:
    """
    Compute Token Sort Ratio between two strings.
    Uses rapidfuzz if available, falls back to simple implementation.
    """
    try:
        from rapidfuzz import fuzz
        return fuzz.token_sort_ratio(a, b) / 100.0
    except ImportError:
        # Simple fallback: Jaccard on sorted token sets
        tokens_a = set(sorted(a.lower().split()))
        tokens_b = set(sorted(b.lower().split()))
        if not tokens_a and not tokens_b:
            return 1.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union) if union else 0.0


def lexical_pre_cluster(kpi_names: List[str], threshold: float = 0.85) -> List[List[str]]:
    """
    Group KPI names by Token Sort Ratio ≥ threshold.

    Returns a list of clusters, each cluster is a list of original KPI names.
    """
    if not kpi_names:
        return []

    # Normalize all names
    normalized = [(name, _normalize_kpi_name(name)) for name in kpi_names]

    # Greedy clustering
    clusters: List[List[str]] = []
    assigned: Set[int] = set()

    for i, (name_i, norm_i) in enumerate(normalized):
        if i in assigned:
            continue

        cluster = [name_i]
        assigned.add(i)

        for j, (name_j, norm_j) in enumerate(normalized):
            if j in assigned:
                continue

            ratio = _token_sort_ratio(norm_i, norm_j)
            if ratio >= threshold:
                cluster.append(name_j)
                assigned.add(j)

        clusters.append(cluster)

    return clusters


def build_pre_cluster_context(
    clusters: List[List[str]],
    fingerprint_map: Dict[str, str],
    source_map: Dict[str, List[str]]
) -> str:
    """
    Build the pre-cluster context string for the LLM prompt.

    Args:
        clusters: List of KPI name clusters from lexical pre-clustering
        fingerprint_map: {kpi_name: fingerprint_string}
        source_map: {kpi_name: [ultimate_raw_source_1, ...]}
    """
    lines = []
    for i, cluster in enumerate(clusters, 1):
        lines.append(f"  Group {i}: {json.dumps(cluster)}")

        # Collect fingerprints
        fps = set()
        for name in cluster:
            fp = fingerprint_map.get(name, "")
            if fp:
                fps.add(fp)
        if fps:
            lines.append(f"    Fingerprints: {json.dumps(list(fps))}")

        # Collect raw sources
        sources = set()
        for name in cluster:
            for src in source_map.get(name, []):
                sources.add(src)
        if sources:
            lines.append(f"    Raw sources: {json.dumps(list(sources))}")

        lines.append("")

    return "\n".join(lines)


def run_kpi_canonicalization(
    db: Database,
    llm_caller: Optional[Any] = None,
    workbook_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """
    Run Phase 1: KPI Canonicalization.

    1. Collect all unique KPI names from calculated_fields
    2. Lexical pre-cluster
    3. Optionally refine with LLM
    4. Write results to kpi_cluster_cache table

    Returns the list of canonical clusters.
    """
    # 1. Collect unique KPI names + metadata
    if workbook_ids:
        placeholders = ",".join("?" * len(workbook_ids))
        rows = db.query(f"""
            SELECT DISTINCT name, fingerprint, ultimate_raw_sources
            FROM calculated_fields
            WHERE column_type IN ('formula_based', 'pivot_value')
              AND workbook_id IN ({placeholders})
        """, tuple(workbook_ids))
    else:
        rows = db.query("""
            SELECT DISTINCT name, fingerprint, ultimate_raw_sources
            FROM calculated_fields
            WHERE column_type IN ('formula_based', 'pivot_value')
        """)

    if not rows:
        logger.info("No calculated fields found — skipping KPI canonicalization")
        return []

    kpi_names = list(set(r["name"] for r in rows))
    logger.info("KPI canonicalization: %d unique KPI names", len(kpi_names))

    # Build lookup maps
    fingerprint_map: Dict[str, str] = {}
    source_map: Dict[str, List[str]] = {}
    for r in rows:
        name = r["name"]
        fingerprint_map[name] = r.get("fingerprint", "") or ""
        raw_src = r.get("ultimate_raw_sources", "[]")
        if isinstance(raw_src, str):
            try:
                source_map[name] = json.loads(raw_src)
            except Exception:
                source_map[name] = []
        elif isinstance(raw_src, list):
            source_map[name] = raw_src
        else:
            source_map[name] = []

    # 2. Lexical pre-clustering
    clusters = lexical_pre_cluster(kpi_names, threshold=0.85)
    logger.info("Lexical pre-clustering: %d clusters from %d names", len(clusters), len(kpi_names))

    # 3. LLM refinement (if available)
    final_clusters = []
    cluster_method = "lexical"

    if llm_caller is not None:
        try:
            from src.rationalization.prompts import KPI_CANONICALIZATION_PROMPT

            context = build_pre_cluster_context(clusters, fingerprint_map, source_map)
            prompt = KPI_CANONICALIZATION_PROMPT.format(pre_clusters=context)

            response = llm_caller(prompt)
            if response and isinstance(response, list):
                final_clusters = response
                cluster_method = "llm"
                logger.info("LLM refined KPI clusters: %d groups", len(final_clusters))
        except Exception as e:
            logger.warning("LLM KPI canonicalization failed, using lexical fallback: %s", e)

    # Fallback to lexical clusters
    if not final_clusters:
        for cluster in clusters:
            # Use the shortest name as canonical (often the cleanest)
            canonical = min(cluster, key=len)
            final_clusters.append({
                "canonical_name": canonical,
                "members": cluster,
            })

    # 4. Write to kpi_cluster_cache
    if workbook_ids:
        placeholders = ",".join("?" * len(workbook_ids))
        scoped_names = db.query(f"""
            SELECT DISTINCT cf.name FROM calculated_fields cf
            WHERE cf.workbook_id IN ({placeholders})
        """, tuple(workbook_ids))
        scoped_name_set = {r["name"] for r in scoped_names}
        existing = db.query("SELECT original_name FROM kpi_cluster_cache")
        for row in existing:
            if row["original_name"] in scoped_name_set:
                db.execute(
                    "DELETE FROM kpi_cluster_cache WHERE original_name = ?",
                    (row["original_name"],),
                )
    else:
        db.execute("DELETE FROM kpi_cluster_cache")

    for cluster in final_clusters:
        canonical = cluster.get("canonical_name", "")
        members = cluster.get("members", [])
        for member in members:
            try:
                db.insert("kpi_cluster_cache", {
                    "original_name": member,
                    "canonical_name": canonical,
                    "cluster_method": cluster_method,
                    "confidence": 1.0 if cluster_method == "llm" else 0.85,
                })
            except Exception as e:
                # Handle duplicates gracefully
                logger.debug("Skipping duplicate KPI cluster entry '%s': %s", member, e)

    logger.info("KPI cluster cache populated: %d entries", len(kpi_names))
    return final_clusters
