"""
Source Normalizer — Stable identifiers for raw data sources across workbooks.

Normalizes ultimate_raw_sources, datasource headers, and primary_inputs
into comparable tokens for overlap scoring.
"""
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

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
    text = text.replace("add1_term", "addl_term").replace("addnl_term", "addl_term")
    parts = text.split("_")
    expanded = []
    for part in parts:
        expanded.append(_ABBREVIATIONS.get(part, part))
    return "_".join(p for p in expanded if p)


def normalize_source_token(
    source: str,
    sheet_mapping: Optional[Dict[str, str]] = None,
) -> str:
    """
    Normalize a single source string to a stable canonical ID.

    Examples:
      "SQL_data :: Statutory Reserves" -> "sql_data[statutory_reserves]"
      "Synthetic_Data" -> "synthetic_data"

    If sheet_mapping is provided (e.g. {"data_extract": "ds_canonical_sql_data"}),
    the sheet name is canonicalized based on underlying column schema.
    """
    if not source:
        return ""
    s = str(source).strip()
    if "::" in s:
        sheet_part, col_part = s.split("::", 1)
        sheet_norm = _strip_punctuation(sheet_part).replace(" ", "_")
        col_norm = _strip_punctuation(col_part).replace(" ", "_")
        col_norm = _expand_abbreviations(col_norm)

        # Apply schema-based canonical sheet mapping if available
        if sheet_mapping and sheet_norm in sheet_mapping:
            sheet_norm = sheet_mapping[sheet_norm]

        return f"{sheet_norm}[{col_norm}]" if col_norm else sheet_norm
    norm = _strip_punctuation(s).replace(" ", "_")
    norm = _expand_abbreviations(norm)
    if sheet_mapping and norm in sheet_mapping:
        norm = sheet_mapping[norm]
    return norm


def normalize_source_set(
    sources: Iterable[str],
    sheet_mapping: Optional[Dict[str, str]] = None,
) -> Set[str]:
    """Normalize a collection of source strings, dropping empties."""
    result = set()
    for src in sources:
        norm = normalize_source_token(src, sheet_mapping=sheet_mapping)
        if norm:
            result.add(norm)
    return result


def build_datasource_canonical_mapping(
    db: Any,
    workbook_ids: Optional[List[int]] = None,
    min_jaccard_threshold: float = 0.70,
) -> Dict[int, Dict[str, str]]:
    """
    Build a mapping from {workbook_id: {sheet_name_norm: canonical_ds_name}}.

    If two sheets across workbooks share >= 70% of their column headers (or >= 4 columns and
    >= 80% containment), they represent the SAME underlying enterprise data source, regardless
    of whether the Excel sheet tab was named 'SQL_data', 'Data_Extract', 'Sheet1', or 'Export'.

    Returns:
        {workbook_id: {normalized_sheet_name: canonical_ds_name}}
    """
    if workbook_ids:
        placeholders = ",".join("?" * len(workbook_ids))
        rows = db.query(f"""
            SELECT workbook_id, name, column_headers
            FROM datasources
            WHERE workbook_id IN ({placeholders})
        """, tuple(workbook_ids))
    else:
        rows = db.query("""
            SELECT workbook_id, name, column_headers
            FROM datasources
        """)

    # Group by (workbook_id, sheet_name_norm) -> set of normalized column tokens
    sheet_entries = []
    for r in rows:
        wid = r["workbook_id"]
        raw_name = r["name"] or ""
        norm_sheet = _strip_punctuation(raw_name).replace(" ", "_")
        headers = parse_json_list(r.get("column_headers"))
        col_set = set()
        for h in headers:
            col_norm = _expand_abbreviations(_strip_punctuation(h).replace(" ", "_"))
            if col_norm and len(col_norm) > 2:
                col_set.add(col_norm)
        if col_set:
            sheet_entries.append({
                "workbook_id": wid,
                "sheet_norm": norm_sheet,
                "columns": col_set,
            })

    if not sheet_entries:
        return {}

    # Union-find across sheet entries
    parent = list(range(len(sheet_entries)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for i in range(len(sheet_entries)):
        for j in range(i + 1, len(sheet_entries)):
            cols_a = sheet_entries[i]["columns"]
            cols_b = sheet_entries[j]["columns"]
            intersection = cols_a & cols_b
            union_cols = cols_a | cols_b
            if not union_cols:
                continue
            jaccard = len(intersection) / len(union_cols)
            cont_a = len(intersection) / len(cols_a) if cols_a else 0.0
            cont_b = len(intersection) / len(cols_b) if cols_b else 0.0

            # Match condition: >= 70% Jaccard OR (>= 4 shared columns AND >= 80% containment)
            is_same_schema = (
                jaccard >= min_jaccard_threshold
                or (len(intersection) >= 4 and (cont_a >= 0.80 or cont_b >= 0.80))
            )
            if is_same_schema:
                union(i, j)

    # Group sheet entries by cluster root
    clusters: Dict[int, List[int]] = {}
    for i in range(len(sheet_entries)):
        root = find(i)
        clusters.setdefault(root, []).append(i)

    # Build final mapping: {workbook_id: {sheet_norm: canonical_name}}
    mapping: Dict[int, Dict[str, str]] = {}
    for indices in clusters.values():
        # Pick the most descriptive sheet name in this cluster as canonical
        names = [sheet_entries[idx]["sheet_norm"] for idx in indices]
        # Ignore generic names like 'sheet1', 'data' when picking canonical name if a better name exists
        better_names = [n for n in names if n not in ("sheet1", "sheet2", "sheet3", "data", "raw_data", "table1")]
        canonical_name = max(better_names, key=len) if better_names else max(names, key=len)
        canonical_id = f"ds_{canonical_name}"

        for idx in indices:
            wid = sheet_entries[idx]["workbook_id"]
            sn = sheet_entries[idx]["sheet_norm"]
            mapping.setdefault(wid, {})[sn] = canonical_id

    return mapping


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
