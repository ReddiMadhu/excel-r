"""
Semantic Similarity — composite LOB + domain + filename-prefix signal.

semantic_similarity(A, B) =
    (lob_match * 0.40) + (domain_match * 0.35) + (filename_prefix_jaccard * 0.25)

All weights configurable via env vars:
    CLUSTER_SEM_LOB_WEIGHT    (default 0.40)
    CLUSTER_SEM_DOMAIN_WEIGHT (default 0.35)
    CLUSTER_SEM_FILENAME_WEIGHT (default 0.25)

LOB/domain are resolved from summary_report dashboards with is_real_ai=1.
If multiple summary sheets disagree, the mode (most common value) wins.
If none exist, lob/domain match = 0.
"""
import os
import re
import logging
from collections import Counter
from typing import Dict, Optional, Set, Tuple

from src.server.models.database import Database

logger = logging.getLogger(__name__)


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _tokenize_filename(name: str) -> Set[str]:
    """Tokenize a filename into lowercase words for Jaccard comparison."""
    # Strip extension
    name = re.sub(r'\.[^.]+$', '', name)
    # Split on underscores, spaces, hyphens, and camelCase boundaries
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    tokens = re.split(r'[\s_\-\.]+', name.lower())
    # Filter short or numeric-only tokens
    return {t for t in tokens if len(t) >= 2 and not t.isdigit()}


def _jaccard(set_a: Set[str], set_b: Set[str]) -> float:
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def _resolve_workbook_lob_domain(
    db: Database, workbook_id: int
) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve workbook-level LOB and domain from summary_report dashboards
    with is_real_ai=1. Takes the mode value if multiple sheets disagree.
    """
    rows = db.query(
        """
        SELECT line_of_business, domain_classification
        FROM dashboards
        WHERE workbook_id = ?
          AND sheet_type = 'summary_report'
          AND is_real_ai = 1
          AND (line_of_business IS NOT NULL OR domain_classification IS NOT NULL)
        """,
        (workbook_id,),
    )
    if not rows:
        return None, None

    lob_counter: Counter = Counter()
    domain_counter: Counter = Counter()
    for row in rows:
        lob = (row.get("line_of_business") or "").strip()
        domain = (row.get("domain_classification") or "").strip()
        if lob:
            lob_counter[lob] += 1
        if domain:
            domain_counter[domain] += 1

    lob = lob_counter.most_common(1)[0][0] if lob_counter else None
    domain = domain_counter.most_common(1)[0][0] if domain_counter else None
    return lob, domain


def get_workbook_semantic_features(
    db: Database, workbook_id: int, workbook_name: str
) -> Dict:
    """Return semantic features for a workbook (cached-friendly dict)."""
    lob, domain = _resolve_workbook_lob_domain(db, workbook_id)
    filename_tokens = _tokenize_filename(workbook_name)
    return {
        "lob": lob,
        "domain": domain,
        "filename_tokens": filename_tokens,
        "has_ai_data": lob is not None or domain is not None,
    }


def compute_semantic_similarity(features_a: Dict, features_b: Dict) -> float:
    """
    Compute semantic_similarity between two workbooks given their feature dicts.
    Returns 0.0–1.0.
    """
    w_lob = _env_float("CLUSTER_SEM_LOB_WEIGHT", 0.40)
    w_domain = _env_float("CLUSTER_SEM_DOMAIN_WEIGHT", 0.35)
    w_filename = _env_float("CLUSTER_SEM_FILENAME_WEIGHT", 0.25)

    lob_match = 0.0
    if features_a["lob"] and features_b["lob"]:
        lob_match = 1.0 if features_a["lob"].lower() == features_b["lob"].lower() else 0.0

    domain_match = 0.0
    if features_a["domain"] and features_b["domain"]:
        domain_match = 1.0 if features_a["domain"].lower() == features_b["domain"].lower() else 0.0

    filename_sim = _jaccard(features_a["filename_tokens"], features_b["filename_tokens"])

    score = w_lob * lob_match + w_domain * domain_match + w_filename * filename_sim
    return round(score, 4)


def check_semantic_data_available(db: Database) -> bool:
    """
    Returns True if at least one dashboard has is_real_ai=1 (Intelligence ran).
    Used as a precondition check before overlap scoring.
    """
    row = db.query_one(
        "SELECT COUNT(*) as cnt FROM dashboards WHERE is_real_ai = 1"
    )
    return (row["cnt"] if row else 0) > 0
