"""Infer and merge workbook business metadata (LOB, domain, user groups)."""
from typing import List, Optional, Tuple

_PRIMARY_BUSINESS_ORDER = ("Actuarial", "Finance", "Underwriting", "Operations", "Claims")


def infer_business_metadata(
    purpose: Optional[str] = None,
    workbook_name: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], List[str]]:
    """Heuristic fallback when LLM metadata is missing."""
    text = f"{purpose or ''} {workbook_name or ''}".lower()
    if not text.strip():
        return None, None, []

    lob = None
    domain = None
    groups: List[str] = []

    if any(k in text for k in ("gvul", "life insurance", "lnbar", "variable universal")):
        lob = "Insurance"
    elif "worksite" in text:
        lob = "Worksite Insurance"
    elif "group benefit" in text or " eb " in f" {text} ":
        lob = "Group Benefits"
    elif "insurance" in text:
        lob = "Insurance"
    elif "annuit" in text:
        lob = "Annuities"

    if any(k in text for k in ("reserve", "statutory", "gaap", "exhibit")):
        domain = "reserves"
    elif "claim" in text:
        domain = "claims"
    elif "compensation" in text or "commission" in text:
        domain = "compensation"
    elif "underwriting" in text:
        domain = "underwriting"

    if any(k in text for k in ("reserve", "actuarial", "statutory", "exhibit")):
        groups.append("Actuarial")
    if any(k in text for k in ("finance", "gaap", "tax", "accounting")):
        groups.append("Finance")
    if "underwriting" in text:
        groups.append("Underwriting")

    return lob, domain, groups


def merge_business_metadata(
    lob: Optional[str],
    domain: Optional[str],
    user_groups: Optional[List[str]],
    inferred: Tuple[Optional[str], Optional[str], List[str]],
) -> Tuple[str, str, List[str]]:
    """Prefer explicit LLM values; fill gaps from heuristics."""
    inf_lob, inf_domain, inf_groups = inferred
    out_lob = (lob or "").strip() or (inf_lob or "")
    out_domain = (domain or "").strip() or (inf_domain or "")
    out_groups = [g for g in (user_groups or []) if g]
    for g in inf_groups:
        if g not in out_groups:
            out_groups.append(g)
    return out_lob, out_domain, out_groups


def _normalize_group_name(group: str) -> str:
    cleaned = (group or "").strip()
    for suffix in (" Department", " Team", " Group"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
    return cleaned


def pick_primary_lob(
    lob: Optional[str],
    purpose: Optional[str] = None,
    workbook_name: Optional[str] = None,
) -> Optional[str]:
    """Return a single suggested LOB for a workbook."""
    value = (lob or "").strip()
    if not value:
        value = infer_business_metadata(purpose, workbook_name)[0] or ""
    if not value:
        return None
    lower = value.lower()
    if "insurance" in lower and "worksite" not in lower:
        return "Insurance"
    return value


def pick_primary_business_group(
    groups: Optional[List[str]],
    purpose: Optional[str] = None,
    workbook_name: Optional[str] = None,
) -> Optional[str]:
    """Return a single suggested business group for a workbook."""
    normalized = [_normalize_group_name(g) for g in (groups or []) if _normalize_group_name(g)]
    if not normalized:
        inferred = infer_business_metadata(purpose, workbook_name)[2]
        normalized = [_normalize_group_name(g) for g in inferred if _normalize_group_name(g)]

    if not normalized:
        return None

    lower_map = {g.lower(): g for g in normalized}
    for preferred in _PRIMARY_BUSINESS_ORDER:
        if preferred.lower() in lower_map:
            return lower_map[preferred.lower()]
    return normalized[0]
