"""
KPI Canonicalizer — Phase 1 of the rationalization pipeline.

Step 1: Content-based pre-clustering — KPIs are grouped only when their
        computation content matches on one or more of:
          (a) identical fingerprint  (same formula structure + same sources)
          (b) same normalized ultimate_raw_sources set + same computation_type
          (c) same formula_pattern string
          (d) same normalized definition text

Step 2: LLM semantic review — confirm or split ambiguous clusters.

Name similarity is NOT used. Two KPIs must share actual computation
content to be placed in the same cluster.
"""
import json
import logging
import re
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from src.server.models.database import Database
from src.rationalization.source_normalizer import normalize_source_token

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Content-based matching helpers
# ---------------------------------------------------------------------------

def _normalize_definition(text: str) -> str:
    """Normalize a definition/description for comparison."""
    if not text:
        return ""
    t = text.strip().lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _sources_key(sources: List[str]) -> FrozenSet[str]:
    """Return a frozenset of normalized source tokens for comparison."""
    return frozenset(
        normalize_source_token(s) for s in sources if s
    )


def _enrich_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add pre-computed comparison keys to a raw DB row so matching is fast.
    Modifies the dict in-place and returns it.
    """
    # Parse ultimate_raw_sources
    raw_src = row.get("ultimate_raw_sources", "[]")
    if isinstance(raw_src, str):
        try:
            sources = json.loads(raw_src)
        except Exception:
            sources = []
    elif isinstance(raw_src, list):
        sources = raw_src
    else:
        sources = []

    row["_sources_list"] = sources
    row["_sources_key"] = _sources_key(sources)
    row["_def_norm"] = _normalize_definition(row.get("definition") or "")
    row["_fp"] = (row.get("fingerprint") or "").strip()
    row["_fp_pattern"] = (row.get("formula_pattern") or "").strip()
    row["_comp_type"] = (row.get("computation_type") or "").strip()
    return row


def _names_contradict(a_name: str, b_name: str) -> bool:
    """
    Return True if two KPI names contain contradictory qualifiers that
    indicate they are semantically different metrics.

    E.g. "Flexible Premium" vs "Non-Flexible Premium" → True
         "Net Reserve" vs "Gross Reserve"              → True
         "YRT Reserve" vs "YRT Face Amount"            → False (different, not contradictory)
    """
    a_lower = a_name.lower().strip()
    b_lower = b_name.lower().strip()

    if a_lower == b_lower:
        return False

    # ── Explicit contradictory term pairs ─────────────────────
    _CONTRADICTORY_PAIRS = [
        ("flexible", "non-flexible"),
        ("flexible", "non flexible"),
        ("flexible", "nonflexible"),
        ("net", "gross"),
        ("inforce", "new business"),
        ("current", "prior"),
        ("actual", "expected"),
        ("beginning", "ending"),
        ("opening", "closing"),
        ("increase", "decrease"),
        ("credit", "debit"),
        ("positive", "negative"),
        ("direct", "assumed"),
        ("direct", "ceded"),
        ("assumed", "ceded"),
    ]
    for term1, term2 in _CONTRADICTORY_PAIRS:
        if (term1 in a_lower and term2 in b_lower) or \
           (term2 in a_lower and term1 in b_lower):
            return True

    # ── Generic negation-prefix detection ─────────────────────
    # Catches patterns like "X" vs "non-X", "non X", "not X", etc.
    a_tokens = set(re.split(r"[\s_\-]+", a_lower))
    b_tokens = set(re.split(r"[\s_\-]+", b_lower))

    negation_tokens = {"non", "not", "no", "un"}
    a_has_neg = bool(a_tokens & negation_tokens)
    b_has_neg = bool(b_tokens & negation_tokens)

    if a_has_neg != b_has_neg:
        # One name has a negation token and the other does not —
        # if the remaining tokens overlap they likely describe the
        # same concept but with opposite meaning.
        a_rest = a_tokens - negation_tokens
        b_rest = b_tokens - negation_tokens
        if a_rest & b_rest:
            return True

    return False


def _content_match(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[str]:
    """
    Return the strongest matching signal name if rows a and b represent
    the same KPI, or None if they do not match.

    Priority:
      1. fingerprint  — identical formula structure + identical sources
      2. source_type  — same normalized source set + same computation type
      3. pattern      — same formula_pattern string
      4. definition   — same normalized definition text

    Signals 2-4 are guarded by a name-contradiction check: KPIs whose
    names contain opposite qualifiers (e.g. "Flexible" vs "Non-Flexible")
    are never clustered together on these weaker signals.
    """
    # 1. Exact fingerprint match — trusted unconditionally because
    #    identical fingerprints mean the formulas are character-identical.
    if a["_fp"] and a["_fp"] == b["_fp"]:
        return "fingerprint"

    # Guard: reject weaker signals when names are contradictory
    if _names_contradict(a.get("name", ""), b.get("name", "")):
        return None

    # 2. Same sources + same computation type (both non-empty)
    if (
        a["_sources_key"]
        and a["_sources_key"] == b["_sources_key"]
        and a["_comp_type"]
        and a["_comp_type"] == b["_comp_type"]
    ):
        return "source_type"

    # 3. Same formula pattern (non-empty)
    if a["_fp_pattern"] and a["_fp_pattern"] == b["_fp_pattern"]:
        return "pattern"

    # 4. Same normalized definition (non-empty, at least 10 chars to avoid trivial matches)
    if a["_def_norm"] and len(a["_def_norm"]) >= 10 and a["_def_norm"] == b["_def_norm"]:
        return "definition"

    return None


def content_based_pre_cluster(
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Group KPI rows into clusters based on content signals.

    Returns a list of cluster dicts:
      {
        "members": [name, ...],
        "match_signals": {signal_name: count, ...},
        "fingerprints": [fp, ...],
        "sources": [[...], ...],
      }
    """
    if not rows:
        return []

    # Enrich rows with pre-computed keys (in-place)
    for r in rows:
        _enrich_row(r)

    # Union-find by row index
    parent = list(range(len(rows)))
    signal_for_pair: Dict[Tuple[int, int], str] = {}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int, signal: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx
        signal_for_pair[(min(x, y), max(x, y))] = signal

    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            sig = _content_match(rows[i], rows[j])
            if sig:
                union(i, j, sig)

    # Group by root
    groups: Dict[int, List[int]] = {}
    for i in range(len(rows)):
        root = find(i)
        groups.setdefault(root, []).append(i)

    clusters = []
    for indices in groups.values():
        members = [rows[i]["name"] for i in indices]

        # Collect match signals seen across all pairs in this cluster
        match_signals: Dict[str, int] = {}
        for ii in indices:
            for jj in indices:
                if ii >= jj:
                    continue
                key = (min(ii, jj), max(ii, jj))
                sig = signal_for_pair.get(key)
                if sig:
                    match_signals[sig] = match_signals.get(sig, 0) + 1

        # Collect unique fingerprints and sources for LLM context
        fps = sorted({rows[i]["_fp"] for i in indices if rows[i]["_fp"]})
        sources_list = [rows[i]["_sources_list"] for i in indices if rows[i]["_sources_list"]]

        clusters.append({
            "members": members,
            "match_signals": match_signals,
            "fingerprints": fps,
            "sources": sources_list,
        })

    return clusters


# ---------------------------------------------------------------------------
# LLM context builder
# ---------------------------------------------------------------------------

def build_pre_cluster_context(
    clusters: List[Dict[str, Any]],
    fingerprint_map: Dict[str, str],
    source_map: Dict[str, List[str]],
) -> str:
    """
    Build the pre-cluster context string for the LLM prompt.

    Shows why each cluster was formed (which content signal matched)
    along with fingerprints and sources.
    """
    lines = []
    for i, cluster in enumerate(clusters, 1):
        members = cluster.get("members", [])
        signals = cluster.get("match_signals", {})
        fps = cluster.get("fingerprints", [])
        sources_nested = cluster.get("sources", [])

        lines.append(f"  Group {i}: {json.dumps(members)}")

        if signals:
            signal_summary = ", ".join(
                f"{sig}({count})" for sig, count in sorted(signals.items())
            )
            lines.append(f"    Matched by: {signal_summary}")

        # Fingerprints (from cluster or fallback to fingerprint_map)
        all_fps = set(fps)
        for name in members:
            fp = fingerprint_map.get(name, "")
            if fp:
                all_fps.add(fp)
        if all_fps:
            lines.append(f"    Fingerprints: {json.dumps(sorted(all_fps))}")

        # Raw sources (from cluster or fallback to source_map)
        all_sources: Set[str] = set()
        for src_list in sources_nested:
            for s in src_list:
                if s:
                    all_sources.add(s)
        for name in members:
            for s in source_map.get(name, []):
                if s:
                    all_sources.add(s)
        if all_sources:
            lines.append(f"    Raw sources: {json.dumps(sorted(all_sources))}")

        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_kpi_canonicalization(
    db: Database,
    llm_caller: Optional[Any] = None,
    workbook_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """
    Run Phase 1: KPI Canonicalization.

    1. Collect all unique KPI rows (name + computation content) from calculated_fields
    2. Content-based pre-cluster (fingerprint / source+type / formula_pattern / definition)
    3. Optionally refine with LLM
    4. Detect and log intra-workbook formula duplicates
    5. Write results to kpi_cluster_cache table

    Returns the list of canonical clusters.
    """
    # 1. Collect KPI rows with full computation content
    if workbook_ids:
        placeholders = ",".join("?" * len(workbook_ids))
        rows = db.query(f"""
            SELECT DISTINCT
                name,
                fingerprint,
                ultimate_raw_sources,
                formula_pattern,
                definition,
                computation_type
            FROM calculated_fields
            WHERE column_type IN ('formula_based', 'pivot_value', 'total')
              AND workbook_id IN ({placeholders})
        """, tuple(workbook_ids))
    else:
        rows = db.query("""
            SELECT DISTINCT
                name,
                fingerprint,
                ultimate_raw_sources,
                formula_pattern,
                definition,
                computation_type
            FROM calculated_fields
            WHERE column_type IN ('formula_based', 'pivot_value', 'total')
        """)

    if not rows:
        logger.info("No calculated fields found — skipping KPI canonicalization")
        return []

    # De-duplicate by name (keep first occurrence, DB DISTINCT covers content dupes)
    seen_names: Set[str] = set()
    unique_rows: List[Dict[str, Any]] = []
    for r in rows:
        name = r["name"]
        if name not in seen_names:
            seen_names.add(name)
            unique_rows.append(dict(r))

    logger.info("KPI canonicalization: %d unique KPI names", len(unique_rows))

    # Build legacy lookup maps (still needed for build_pre_cluster_context fallback)
    fingerprint_map: Dict[str, str] = {
        r["name"]: (r.get("fingerprint") or "") for r in unique_rows
    }
    source_map: Dict[str, List[str]] = {}
    for r in unique_rows:
        raw_src = r.get("ultimate_raw_sources", "[]")
        if isinstance(raw_src, str):
            try:
                source_map[r["name"]] = json.loads(raw_src)
            except Exception:
                source_map[r["name"]] = []
        elif isinstance(raw_src, list):
            source_map[r["name"]] = raw_src
        else:
            source_map[r["name"]] = []

    # 2. Content-based pre-clustering
    clusters = content_based_pre_cluster(unique_rows)
    logger.info(
        "Content-based pre-clustering: %d clusters from %d names",
        len(clusters), len(unique_rows),
    )

    # 3. LLM refinement (if available)
    final_clusters: List[Dict[str, Any]] = []
    cluster_method = "content"

    if llm_caller is not None:
        try:
            from src.rationalization.prompts import KPI_CANONICALIZATION_PROMPT

            context = build_pre_cluster_context(clusters, fingerprint_map, source_map)
            prompt = KPI_CANONICALIZATION_PROMPT.format(pre_clusters=context)

            response = llm_caller(prompt)
            if response and isinstance(response, list):
                # Validate: canonical_name must be one of the member names.
                # If the LLM invented a name, fall back to the longest member
                # (longest is usually the most descriptive extracted name).
                validated = []
                for cluster in response:
                    members = cluster.get("members", [])
                    canonical = cluster.get("canonical_name", "")
                    member_set = set(members)
                    if canonical not in member_set:
                        original = canonical
                        canonical = max(members, key=len) if members else (members[0] if members else "")
                        logger.warning(
                            "LLM returned invented canonical name %r (not in members) — "
                            "replaced with extracted name %r",
                            original, canonical,
                        )
                    validated.append({**cluster, "canonical_name": canonical})
                final_clusters = validated
                cluster_method = "llm"
                logger.info("LLM refined KPI clusters: %d groups", len(final_clusters))
        except Exception as e:
            logger.warning("LLM KPI canonicalization failed, using content fallback: %s", e)

    # Fallback: use content clusters directly, shortest name as canonical
    if not final_clusters:
        for cluster in clusters:
            members = cluster.get("members", [])
            canonical = min(members, key=len) if members else ""
            # Determine a representative method label from the strongest signal
            signals = cluster.get("match_signals", {})
            method = "content"
            for sig in ("fingerprint", "source_type", "pattern", "definition"):
                if sig in signals:
                    method = sig
                    break
            final_clusters.append({
                "canonical_name": canonical,
                "members": members,
                "_method": method,
            })
        cluster_method = None  # use per-cluster method below

    # 4. Intra-workbook formula duplicate detection
    _log_intra_workbook_duplicates(db, workbook_ids)

    # 5. Write to kpi_cluster_cache
    if workbook_ids:
        placeholders = ",".join("?" * len(workbook_ids))
        scoped_rows = db.query(f"""
            SELECT DISTINCT name FROM calculated_fields
            WHERE workbook_id IN ({placeholders})
        """, tuple(workbook_ids))
        scoped_name_set = {r["name"] for r in scoped_rows}
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
        method = cluster_method if cluster_method else cluster.get("_method", "content")
        # LLM clusters get full confidence; content-signal clusters get 0.9
        confidence = 1.0 if method == "llm" else 0.9

        for member in members:
            try:
                db.insert("kpi_cluster_cache", {
                    "original_name": member,
                    "canonical_name": canonical,
                    "cluster_method": method,
                    "confidence": confidence,
                })
            except Exception as e:
                logger.debug("Skipping duplicate KPI cluster entry '%s': %s", member, e)

    logger.info("KPI cluster cache populated: %d entries", len(unique_rows))
    return final_clusters


def _log_intra_workbook_duplicates(
    db: Database,
    workbook_ids: Optional[List[int]] = None,
) -> None:
    """
    Detect and log columns within the same workbook that share an identical
    fingerprint on different column names (same formula, same report).

    These are intra-workbook redundancies — the same calculation is
    defined multiple times in one report under different column headers.
    """
    if workbook_ids:
        placeholders = ",".join("?" * len(workbook_ids))
        rows = db.query(f"""
            SELECT workbook_id, name, fingerprint
            FROM calculated_fields
            WHERE column_type IN ('formula_based', 'pivot_value', 'total')
              AND fingerprint IS NOT NULL
              AND fingerprint != ''
              AND workbook_id IN ({placeholders})
        """, tuple(workbook_ids))
    else:
        rows = db.query("""
            SELECT workbook_id, name, fingerprint
            FROM calculated_fields
            WHERE column_type IN ('formula_based', 'pivot_value', 'total')
              AND fingerprint IS NOT NULL
              AND fingerprint != ''
        """)

    # Group by (workbook_id, fingerprint)
    wb_fp: Dict[Tuple[int, str], List[str]] = {}
    for r in rows:
        key = (r["workbook_id"], r["fingerprint"])
        wb_fp.setdefault(key, []).append(r["name"])

    dupes = [
        (wb_id, fp, names)
        for (wb_id, fp), names in wb_fp.items()
        if len(set(names)) > 1
    ]

    if dupes:
        logger.info(
            "Intra-workbook formula duplicates found: %d fingerprint(s) shared "
            "across multiple column names within the same workbook",
            len(dupes),
        )
        for wb_id, fp, names in dupes:
            logger.info(
                "  Workbook %d | fingerprint=%r | duplicate columns: %s",
                wb_id, fp, names,
            )
    else:
        logger.info("No intra-workbook formula duplicates detected")
