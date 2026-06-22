"""
Source Normalizer — Stable identifiers for raw data sources across workbooks.

Normalizes ultimate_raw_sources, datasource headers, and primary_inputs
into comparable tokens for overlap scoring.
"""
import json
import re
from typing import Any, Iterable, List, Optional, Set

# Configurable abbreviation map (extend via env or config file in v2)
_ABBREVIATIONS = {
    "stat": "statutory_reserves",
    "ga": "general_account",
    "nb": "new_business",
    "res": "reserves",
    "reserve": "reserves",
}


def _strip_punctuation(s: str) -> str:
    return re.sub(r'[^a-z0-9\s_\[\]]', '', str(s).lower().strip())


def _expand_abbreviations(text: str) -> str:
    """Expand known abbreviations in a normalized token."""
    parts = text.split("_")
    expanded = []
    for part in parts:
        expanded.append(_ABBREVIATIONS.get(part, part))
    return "_".join(p for p in expanded if p)


def normalize_source_token(source: str) -> str:
    """
    Normalize a single source string to a stable ID.

    Examples:
      "SQL_data :: Statutory Reserves" -> "sql_data[statutory_reserves]"
      "Synthetic_Data" -> "synthetic_data"
    """
    if not source:
        return ""
    s = str(source).strip()
    if "::" in s:
        sheet_part, col_part = s.split("::", 1)
        sheet_norm = _strip_punctuation(sheet_part).replace(" ", "_")
        col_norm = _strip_punctuation(col_part).replace(" ", "_")
        col_norm = _expand_abbreviations(col_norm)
        return f"{sheet_norm}[{col_norm}]" if col_norm else sheet_norm
    norm = _strip_punctuation(s).replace(" ", "_")
    norm = _expand_abbreviations(norm)
    return norm


def normalize_source_set(sources: Iterable[str]) -> Set[str]:
    """Normalize a collection of source strings, dropping empties."""
    result = set()
    for src in sources:
        norm = normalize_source_token(src)
        if norm:
            result.add(norm)
    return result


def parse_json_list(value: Any) -> List[str]:
    """Parse a JSON list field from DB or JSON output."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (json.JSONDecodeError, TypeError):
            return [value] if value else []
    return []


def normalize_datasource_headers(sheet_name: str, headers: Iterable[str]) -> Set[str]:
    """Build normalized source IDs from raw sheet column headers."""
    sheet_norm = _strip_punctuation(sheet_name).replace(" ", "_")
    return {
        normalize_source_token(f"{sheet_name} :: {h}")
        for h in headers
        if h
    } or {sheet_norm}
