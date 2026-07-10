"""
Cluster Builder — Phase 3 of the rationalization pipeline.

Builds the workbook overlap graph, applies the one-hop bridge-node guard,
runs connected-components to form hard-partitioned clusters, and writes
the result to workbook_clusters + workbook_cluster_members tables.

Bridge-node guard (GAP-01 fix):
    B is a bridge if edge_score(A,B) < THRESHOLD AND edge_score(B,C) < THRESHOLD
    → transitivity A↔C is blocked.
    → B joins whichever partner it has the highest direct score with.
    → the other partner becomes a singleton (unless it has other direct edges).

Maximum transitivity depth: 1 hop.
"""
import logging
import os
import uuid
from collections import defaultdict
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from src.server.models.database import Database

logger = logging.getLogger(__name__)


# ─── Threshold helpers ────────────────────────────────────────────────

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


# ─── Graph construction ───────────────────────────────────────────────

def _qualifies_for_edge(overlap: Dict[str, Any]) -> bool:
    """
    An edge forms between A and B if ANY of the four conditions hold:
      1. cluster_edge_score >= CLUSTER_SEED_THRESHOLD
      2. kpi_overlap       >= CLUSTER_KPI_THRESHOLD
      3. ds_overlap        >= CLUSTER_DS_THRESHOLD
      4. fingerprint_ratio >= CLUSTER_FP_THRESHOLD
    Semantic similarity alone cannot qualify an edge.
    """
    seed_thresh = _env_float("CLUSTER_SEED_THRESHOLD", 0.30)
    kpi_thresh = _env_float("CLUSTER_KPI_THRESHOLD", 0.40)
    ds_thresh = _env_float("CLUSTER_DS_THRESHOLD", 0.60)
    fp_thresh = _env_float("CLUSTER_FP_THRESHOLD", 0.50)

    return (
        overlap.get("cluster_edge_score", 0.0) >= seed_thresh
        or overlap.get("kpi_overlap", 0.0) >= kpi_thresh
        or overlap.get("ds_overlap", 0.0) >= ds_thresh
        or overlap.get("fingerprint_ratio", 0.0) >= fp_thresh
    )


def build_direct_edges(
    pairwise: Dict[Tuple[int, int], Dict[str, Any]]
) -> Dict[int, Dict[int, float]]:
    """
    Build adjacency dict of direct qualifying edges.
    Returns: {wb_id: {neighbor_id: cluster_edge_score}}
    """
    adj: Dict[int, Dict[int, float]] = defaultdict(dict)
    for (id_a, id_b), overlap in pairwise.items():
        if _qualifies_for_edge(overlap):
            score = overlap.get("cluster_edge_score", 0.0)
            adj[id_a][id_b] = score
            adj[id_b][id_a] = score
    return dict(adj)


# ─── Bridge-node guard ─────────────────────────────────────────────────

def _is_bridge(
    id_b: int,
    score_ab: float,
    score_bc: float,
    bridge_threshold: float,
) -> bool:
    """
    B is a bridge if BOTH its direct edges are weak:
        score(A,B) < BRIDGE_THRESHOLD AND score(B,C) < BRIDGE_THRESHOLD
    """
    return score_ab < bridge_threshold and score_bc < bridge_threshold


def apply_bridge_guard(
    adj: Dict[int, Dict[int, float]],
    all_wb_ids: List[int],
) -> Dict[int, Dict[int, float]]:
    """
    Prune transitive edges where the intermediate node is a bridge.

    For every path A-B-C (A-B direct, B-C direct, A-C NOT direct):
      - If B is a bridge: do NOT add A↔C edge.
      - B then belongs to the cluster of its strongest direct partner.
        (handled by connected-components on the remaining graph)

    Returns the adjacency dict after bridge-pruning.
    (Note: we never ADD transitive edges to adj; we just use this function
    to validate that the existing component algorithm won't mistakenly chain
    through a bridge via shared membership.)
    """
    bridge_threshold = _env_float("CLUSTER_BRIDGE_GUARD_THRESHOLD", 0.35)
    bridge_pairs: Set[FrozenSet[int]] = set()

    for id_b, neighbors_b in adj.items():
        neighbor_ids = list(neighbors_b.keys())
        for i in range(len(neighbor_ids)):
            for j in range(i + 1, len(neighbor_ids)):
                id_a, id_c = neighbor_ids[i], neighbor_ids[j]
                score_ab = neighbors_b.get(id_a, 0.0)
                score_bc = neighbors_b.get(id_c, 0.0)

                # If A and C already have a direct edge, no bridge issue
                if id_c in adj.get(id_a, {}):
                    continue

                if _is_bridge(id_b, score_ab, score_bc, bridge_threshold):
                    bridge_pairs.add(frozenset({id_a, id_b, id_c}))
                    logger.info(
                        "Bridge guard: %d acts as bridge between %d and %d "
                        "(scores %.3f, %.3f < threshold %.3f) — blocking transitivity",
                        id_b, id_a, id_c, score_ab, score_bc, bridge_threshold
                    )
                    # Remove the weaker of B's two edges (from adj)
                    if score_ab < score_bc:
                        # B is closer to C; remove B↔A
                        if id_a in adj.get(id_b, {}):
                            del adj[id_b][id_a]
                        if id_b in adj.get(id_a, {}):
                            del adj[id_a][id_b]
                        logger.info("  Removed edge %d↔%d (weaker)", id_b, id_a)
                    else:
                        # B is closer to A; remove B↔C
                        if id_c in adj.get(id_b, {}):
                            del adj[id_b][id_c]
                        if id_b in adj.get(id_c, {}):
                            del adj[id_c][id_b]
                        logger.info("  Removed edge %d↔%d (weaker)", id_b, id_c)

    return adj


# ─── Connected components (Union-Find) ────────────────────────────────

class UnionFind:
    def __init__(self, ids: List[int]):
        self.parent = {i: i for i in ids}
        self.rank = {i: 0 for i in ids}

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


def compute_connected_components(
    adj: Dict[int, Dict[int, float]],
    all_wb_ids: List[int],
) -> Dict[int, List[int]]:
    """
    Run connected-components on the pruned adjacency graph.
    Returns: {root_id: [list of workbook_ids in this cluster]}
    Workbooks with no edges form singleton clusters.
    """
    uf = UnionFind(all_wb_ids)
    for wb_id, neighbors in adj.items():
        for neighbor_id in neighbors:
            uf.union(wb_id, neighbor_id)

    clusters: Dict[int, List[int]] = defaultdict(list)
    for wb_id in all_wb_ids:
        root = uf.find(wb_id)
        clusters[root].append(wb_id)

    return dict(clusters)


# ─── Cluster auto-naming ───────────────────────────────────────────────

def _generate_cluster_name(
    db: Database,
    member_ids: List[int],
    cluster_idx: int,
) -> str:
    """Auto-generate a cluster name from shared LOB, domain, and filename tokens."""
    if len(member_ids) == 1:
        row = db.query_one("SELECT name FROM workbooks WHERE id = ?", (member_ids[0],))
        return row["name"] if row else f"Group {cluster_idx}"

    # Gather LOB and domain (from summary_report dashboards, is_real_ai=1)
    from collections import Counter
    lob_counter: Counter = Counter()
    domain_counter: Counter = Counter()
    filename_token_lists: List[Set[str]] = []

    from src.rationalization.semantic_similarity import _tokenize_filename

    for wb_id in member_ids:
        rows = db.query(
            """
            SELECT line_of_business, domain_classification
            FROM dashboards
            WHERE workbook_id = ? AND sheet_type = 'summary_report' AND is_real_ai = 1
            """,
            (wb_id,),
        )
        for row in rows:
            lob = (row.get("line_of_business") or "").strip()
            domain = (row.get("domain_classification") or "").strip()
            if lob:
                lob_counter[lob] += 1
            if domain:
                domain_counter[domain] += 1

        wb = db.query_one("SELECT name FROM workbooks WHERE id = ?", (wb_id,))
        if wb:
            filename_token_lists.append(_tokenize_filename(wb["name"]))

    min_support = max(1, len(member_ids) // 2)  # ≥50% of members

    parts = []
    if lob_counter:
        best_lob, lob_count = lob_counter.most_common(1)[0]
        if lob_count >= min_support:
            parts.append(best_lob)

    if domain_counter:
        best_domain, domain_count = domain_counter.most_common(1)[0]
        if domain_count >= min_support:
            parts.append(best_domain)

    if filename_token_lists:
        # Find tokens present in ≥50% of filenames
        all_tokens: Counter = Counter()
        for token_set in filename_token_lists:
            for t in token_set:
                all_tokens[t] += 1
        common_tokens = [
            t for t, cnt in all_tokens.most_common(5)
            if cnt >= min_support and t not in {"the", "and", "of", "for", "in"}
        ]
        parts.extend(common_tokens[:3])

    if parts:
        # Deduplicate while preserving order
        seen = set()
        unique_parts = []
        for p in parts:
            if p.lower() not in seen:
                seen.add(p.lower())
                unique_parts.append(p)
        return " ".join(unique_parts)

    return f"Group {cluster_idx}"


# ─── Main cluster formation entry point ────────────────────────────────

def build_clusters(
    db: Database,
    pairwise: Dict[Tuple[int, int], Dict[str, Any]],
    workbook_ids: Optional[List[int]] = None,
    run_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Full cluster formation pipeline:
      1. Build direct edges from pairwise overlap
      2. Apply bridge-node guard
      3. Run connected components
      4. Compute cohesion scores and auto-names
      5. Write workbook_clusters + workbook_cluster_members to DB

    Returns list of cluster dicts for use in subsequent pipeline phases.
    """
    if run_id is None:
        run_id = str(uuid.uuid4())

    # Gather all workbook IDs in scope
    if workbook_ids:
        placeholders = ",".join("?" * len(workbook_ids))
        wbs = db.query(
            f"SELECT id, name FROM workbooks WHERE id IN ({placeholders})",
            tuple(workbook_ids),
        )
    else:
        wbs = db.query("SELECT id, name FROM workbooks ORDER BY id")

    all_wb_ids = [w["id"] for w in wbs]
    wb_name_map = {w["id"]: w["name"] for w in wbs}

    if not all_wb_ids:
        logger.info("No workbooks — skipping cluster formation")
        return []

    # ── Step 1: Direct edges ──────────────────────────────────
    adj = build_direct_edges(pairwise)

    # ── Step 2: Bridge-node guard ─────────────────────────────
    adj = apply_bridge_guard(adj, all_wb_ids)

    # ── Step 3: Connected components ──────────────────────────
    components = compute_connected_components(adj, all_wb_ids)

    # ── Step 4: Build cluster metadata ───────────────────────
    clusters: List[Dict[str, Any]] = []
    for cluster_idx, (root_id, member_ids) in enumerate(sorted(components.items()), start=1):
        member_ids = sorted(member_ids)
        size = len(member_ids)

        # Cohesion score = avg pairwise cluster_edge_score within cluster
        pair_scores = []
        for i in range(len(member_ids)):
            for j in range(i + 1, len(member_ids)):
                id_a = min(member_ids[i], member_ids[j])
                id_b = max(member_ids[i], member_ids[j])
                overlap = pairwise.get((id_a, id_b), {})
                pair_scores.append(overlap.get("cluster_edge_score", 0.0))

        cohesion = round(sum(pair_scores) / len(pair_scores), 4) if pair_scores else 1.0

        cluster_name = _generate_cluster_name(db, member_ids, cluster_idx)

        clusters.append({
            "cluster_name": cluster_name,
            "cluster_size": size,
            "cohesion_score": cohesion,
            "canonical_target_id": None,   # filled in Phase 5
            "cluster_action_summary": None,
            "llm_validation_skipped": 0,
            "cluster_validation_flag": None,
            "llm_stage1_reasoning": None,
            "suspect_edges": None,
            "rationalization_run_id": run_id,
            "member_ids": member_ids,
        })

    # ── Step 5: Persist to DB ─────────────────────────────────
    # Clear old cluster data first (handled by _clear_cluster_data in engine.py)
    for cluster in clusters:
        member_ids = cluster.pop("member_ids")

        cluster_id = db.insert("workbook_clusters", {
            k: v for k, v in cluster.items()
            if k not in ("member_ids",)
        })
        cluster["id"] = cluster_id
        cluster["member_ids"] = member_ids

        # Write member rows
        for wb_id in member_ids:
            db.insert("workbook_cluster_members", {
                "cluster_id": cluster_id,
                "workbook_id": wb_id,
            })

    logger.info(
        "Formed %d clusters from %d workbooks (%d singletons)",
        len(clusters),
        len(all_wb_ids),
        sum(1 for c in clusters if c["cluster_size"] == 1),
    )
    return clusters
