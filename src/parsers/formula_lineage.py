"""
Formula Lineage System
======================
Provides structured formula dependency tracking for rationalization.

Covers all formula archetypes:
  SUMIFS, COUNTIFS, SUM_RANGE, ARITHMETIC, RATIO,
  MULTI_AGG, PASS_THROUGH, CONDITIONAL, CONSTANT, LOOKUP, UNKNOWN
"""
import re
from openpyxl.utils import column_index_from_string


# ── Reference already imported from formula_parser when called from there ──
# We import parse_sheet_cell_ref lazily to avoid circular imports
def _get_parse_fn():
    from src.parsers.formula_parser import parse_sheet_cell_ref, extract_function_calls
    return parse_sheet_cell_ref, extract_function_calls


# ─────────────────────────────────────────────────────────────────
# Reference Classification
# ─────────────────────────────────────────────────────────────────

def classify_criteria_ref(ref_str, current_row=None):
    """
    Classify a SUMIFS/COUNTIFS criteria value reference.

    Returns one of:
      'group_by_key' | 'static_filter' | 'parameter_filter' | 'period_or_header_filter'

    $ anchoring is a HINT, not the sole decision:
      - string literal / concatenated operator criteria → static_filter
      - same-row relative ref (A6 with formula on row 6) → group_by_key
      - row-absolute header/title refs (J$5, $A$2) → static_filter (caller may refine)
    """
    if not ref_str:
        return 'static_filter'
    ref = str(ref_str).lstrip('=').strip()

    # String literal
    if ref.startswith('"') or ref.startswith("'"):
        return 'static_filter'

    # Concatenated criteria: ">"&A1, "<="&$B$1, "<>"&C2
    if '&' in ref or re.match(r'^"[<>=!]+"', ref):
        return 'static_filter'

    # Operator-prefixed literal without quotes (rare but possible)
    if re.match(r'^[<>=]', ref) and not re.match(r'^\$?[A-Z]+', ref, re.I):
        return 'static_filter'

    cell_part = ref.split('!')[-1] if '!' in ref else ref
    row_is_absolute = bool(re.search(r'(?<=[A-Za-z])\$\d', cell_part))
    row_match = re.search(r'(\d+)', cell_part.replace('$', ''))
    row_num = int(row_match.group(1)) if row_match else None

    if row_is_absolute:
        # Absolute row: typically a fixed filter / header / parameter
        return 'static_filter'

    # Relative row matching the formula row → grouping key
    if current_row is not None and row_num is not None and row_num == int(current_row):
        return 'group_by_key'

    # Relative row without current_row context — default to group_by (Excel fill pattern)
    return 'group_by_key'


def _parse_concat_criteria(ref):
    """
    Parse concatenated criteria like '">"&A1' or '"<="&$B$2'.
    Returns (operator, remainder_ref) or (None, None).
    """
    ref = str(ref).strip()
    m = re.match(r'^"([<>=!]+)"\s*&\s*(.+)$', ref)
    if m:
        return m.group(1), m.group(2).strip()
    m = re.match(r"^'([<>=!]+)'\s*&\s*(.+)$", ref)
    if m:
        return m.group(1), m.group(2).strip()
    # Unquoted: ">"&A1 already handled; also "<>Closed" style literals
    m = re.match(r'^"([<>=!]{1,2})(.+)"$', ref)
    if m and m.group(2):
        return m.group(1), f'"{m.group(2)}"'
    return None, None


def extract_filter_value(crit_val_ref, crit_val_repr, summary_ws_val=None, return_operator=False):
    """
    Extract a clean, human-readable filter value from a static criteria reference.

    When return_operator=True, returns (value, operator) tuple. Operator defaults to '='.
    """
    ref = str(crit_val_ref).strip()
    operator = "="

    # Concatenated / operator criteria
    op, remainder = _parse_concat_criteria(ref)
    if op is not None:
        operator = op
        if remainder.startswith('"') or remainder.startswith("'"):
            value = remainder.strip('"\'')
            return (value, operator) if return_operator else value
        # Resolve the cell portion
        crit_val_ref = remainder
        ref = remainder

    # Leading operator in literal: ">=100", "<>Closed"
    lit_op = re.match(r'^"([<>=!]{1,2})(.+)"$', ref)
    if lit_op:
        operator = lit_op.group(1)
        value = lit_op.group(2)
        return (value, operator) if return_operator else value

    # 1. String literal in formula
    if ref.startswith('"'):
        value = ref.strip('"')
        return (value, operator) if return_operator else value

    # 2. Value embedded in repr e.g. "Summary!K5 ('Flexible')"
    match = re.search(r"\(['\"](.+?)['\"]\)", str(crit_val_repr or ""))
    if match:
        value = f"'{match.group(1)}'"
        return (value, operator) if return_operator else value

    # 3. Read actual cell from worksheet
    if summary_ws_val:
        try:
            parse_fn, _ = _get_parse_fn()
            sheet_name, col_letter, row_num, _ = parse_fn(ref)
            if row_num and col_letter:
                col_idx = column_index_from_string(col_letter)
                ws = summary_ws_val
                if sheet_name and summary_ws_val.parent:
                    wb = summary_ws_val.parent
                    if sheet_name in wb.sheetnames:
                        ws = wb[sheet_name]
                val = ws.cell(row=row_num, column=col_idx).value
                if val is not None:
                    value = f"'{val}'" if isinstance(val, str) else str(val)
                    return (value, operator) if return_operator else value
        except Exception:
            pass

    value = str(crit_val_repr or ref).strip("\"'")
    return (value, operator) if return_operator else value


# ─────────────────────────────────────────────────────────────────
# Wrapper Stripping
# ─────────────────────────────────────────────────────────────────

def strip_formula_wrapper(formula_str):
    """
    Strip IFERROR/IFNA/IF wrappers to get the core formula.
    Returns (inner_formula_str, wrapper_type_or_None).
    """
    if not formula_str:
        return formula_str, None
    f = str(formula_str).strip()
    fu = f.upper()
    for wrapper in ["IFERROR", "IFNA", "ISERROR"]:
        prefix = f"={wrapper}("
        if fu.startswith(prefix):
            inner = _extract_first_arg_str(f[len(prefix):])
            return ('=' + inner if not inner.startswith('=') else inner), wrapper
    if fu.startswith("=IF("):
        try:
            _, extract_fn = _get_parse_fn()
            calls = extract_fn(f, "IF")
            if calls and len(calls[0]["args"]) >= 2:
                then_branch = calls[0]["args"][1].strip()
                return ('=' + then_branch if not then_branch.startswith('=') else then_branch), "IF"
        except Exception:
            pass
    return f, None


def _extract_first_arg_str(args_str):
    """Extract first comma-separated argument respecting nesting."""
    paren_count = 0
    in_quote = False
    for i, char in enumerate(args_str):
        if char == '"':
            in_quote = not in_quote
        elif not in_quote:
            if char == '(':
                paren_count += 1
            elif char == ')':
                if paren_count == 0:
                    return args_str[:i]
                paren_count -= 1
            elif char == ',' and paren_count == 0:
                return args_str[:i]
    return args_str


# ─────────────────────────────────────────────────────────────────
# Computation Type Detection
# ─────────────────────────────────────────────────────────────────

def detect_computation_type(formula_str):
    """
    Detect the computation archetype for a formula string.

    Returns one of:
      SUMIFS, COUNTIFS, SUM_RANGE, ARITHMETIC, RATIO,
      MULTI_AGG, PASS_THROUGH, CONDITIONAL, CONSTANT, LOOKUP,
      UNKNOWN, DYNAMIC, UNSUPPORTED
    """
    if not formula_str:
        return "UNKNOWN"
    f = str(formula_str).strip().lstrip('=').strip()
    fu = f.upper()
    # Constant (pure number)
    try:
        float(f.replace(',', '').replace('%', ''))
        return "CONSTANT"
    except ValueError:
        pass
    # Explicit unsupported modern Excel
    if any(fn in fu for fn in ("XLOOKUP(", "XMATCH(", "FILTER(", "LAMBDA(", "LET(")):
        return "UNSUPPORTED"
    if "[@" in formula_str or re.search(r"\b[A-Za-z_][\w]*\[", formula_str):
        return "UNSUPPORTED"
    if "VLOOKUP(" in fu or "HLOOKUP(" in fu or ("INDEX(" in fu and "MATCH(" in fu):
        return "LOOKUP"
    if "INDIRECT(" in fu or "OFFSET(" in fu:
        return "DYNAMIC"
    sumifs_count = fu.count("SUMIFS(")
    if sumifs_count > 1:
        return "MULTI_AGG"
    if sumifs_count == 1:
        return "SUMIFS"
    if "COUNTIFS(" in fu:
        return "COUNTIFS"
    if "COUNTIF(" in fu:
        return "UNSUPPORTED"  # singular COUNTIF not fully parsed
    if "SUM(" in fu:
        return "SUM_RANGE"
    # Conditional IF whose core is not stripped to another type
    if fu.startswith("IF("):
        return "CONDITIONAL"
    # Pass-through: single cell reference
    if re.fullmatch(r"'?[A-Za-z0-9_ ]*'?!?\$?[A-Z]+\$?\d+", f):
        return "PASS_THROUGH"
    if re.search(r'/', f) and not re.search(r'SUMIFS|SUM\(|COUNT', fu):
        return "RATIO"
    if re.search(r'[+\-*/]', f):
        return "ARITHMETIC"
    return "UNKNOWN"


# ─────────────────────────────────────────────────────────────────
# Lineage Building
# ─────────────────────────────────────────────────────────────────

LINEAGE_SCHEMA_VERSION = "2.0-semantic"


def _index_lookup(all_column_index, sheet, col_name):
    """
    Look up a column in a sheet-qualified index.

    Preferred key: "sheet :: column". Falls back to bare column_name only when
    the sheet is empty/unknown. Never resolves a raw-sheet column to a summary
    column that happens to share the same label.
    """
    if not all_column_index or not col_name:
        return None
    if sheet:
        qualified = f"{sheet} :: {col_name}"
        if qualified in all_column_index:
            return all_column_index[qualified]
        # Do not fall back to bare name when a sheet was specified — that is the
        # Product Subtype hijack that drops raw group-by columns from ultimate sources.
        return None
    return all_column_index.get(col_name)


def build_direct_inputs(formula_source_details, data_source_sheet, all_column_index):
    """
    Build the direct_inputs list with is_raw flag and nested lineage.

    all_column_index: dict keyed by "sheet :: column" (preferred) and optionally
    bare column_name for same-sheet computed refs.
    """
    seen = set()
    direct_inputs = []
    for detail in formula_source_details:
        col_name = detail.get("column_name", "")
        role = detail.get("role", "")
        if not col_name:
            continue
        source_sheet = detail.get("source_sheet") or data_source_sheet or ""
        seen_key = (source_sheet, col_name, role)
        if seen_key in seen:
            continue
        seen.add(seen_key)

        known = _index_lookup(all_column_index, source_sheet, col_name)
        # Raw-sheet references are always raw even if a summary table has the same label
        if source_sheet and known is None:
            is_raw = True
            table = source_sheet
        elif known is None:
            is_raw = True
            table = data_source_sheet or ""
        else:
            is_raw = known.get("type", "raw") == "raw"
            table = known.get("table_name") or known.get("sheet_name") or source_sheet or data_source_sheet

        # Roles that come from raw criteria/sum ranges must stay raw when the
        # source sheet is a data sheet (present in maps but not as a computed col).
        if role in ("sum_range", "group_by_key", "static_filter", "count_range", "criteria_range"):
            if source_sheet and (known is None or known.get("type") in ("raw", "label", None)):
                # Prefer treating as raw source unless the known column is formula-based
                # on the *same* source sheet.
                known_sheet = (known or {}).get("sheet_name") or (known or {}).get("data_source_sheet")
                if known is None or known.get("type") in ("raw", "label") or known_sheet != source_sheet:
                    is_raw = True
                    table = source_sheet
                    known = None

        node = {"column": col_name, "table": table, "is_raw": is_raw, "role": role}
        if source_sheet:
            node["source_sheet"] = source_sheet
        if "filter_value" in detail:
            node["filter_value"] = detail["filter_value"]
        if "operator" in detail:
            node["operator"] = detail["operator"]
        if detail.get("header_resolved") is False:
            node["header_resolved"] = False
        # Attach nested lineage for intermediate computed columns only
        if not is_raw and known and "formula_lineage" in known:
            node["nested_lineage"] = known["formula_lineage"]
        direct_inputs.append(node)
    return direct_inputs


def collect_ultimate_sources(direct_inputs, _visited=None):
    """
    Recursively collect ultimate raw source strings (table :: column).

    Walks nested_lineage.direct_inputs when ultimate_raw_sources is missing,
    with cycle detection via visited keys.
    """
    if _visited is None:
        _visited = set()
    sources = []
    for inp in direct_inputs or []:
        key = (inp.get("table", ""), inp.get("column", ""))
        if key in _visited:
            continue
        _visited.add(key)

        if inp.get("is_raw"):
            table = inp.get("table") or ""
            col = inp.get("column") or ""
            if table and col:
                src = f"{table} :: {col}"
                if src not in sources:
                    sources.append(src)
            continue

        nested = inp.get("nested_lineage") or {}
        nested_sources = nested.get("ultimate_raw_sources") or []
        if nested_sources:
            for src in nested_sources:
                if src not in sources:
                    sources.append(src)
        else:
            # Walk nested direct_inputs when precomputed ultimates are absent
            for src in collect_ultimate_sources(nested.get("direct_inputs", []), _visited):
                if src not in sources:
                    sources.append(src)
    return sources


def compute_lineage_depth(direct_inputs, _visited=None):
    """Compute maximum lineage depth from direct_inputs with cycle protection."""
    if _visited is None:
        _visited = set()
    max_depth = 1
    for inp in direct_inputs or []:
        key = (inp.get("table", ""), inp.get("column", ""))
        if key in _visited:
            continue
        _visited.add(key)
        if "nested_lineage" in inp:
            nested = inp["nested_lineage"]
            nested_depth = nested.get("lineage_depth")
            if nested_depth is None:
                nested_depth = compute_lineage_depth(nested.get("direct_inputs", []), _visited)
            max_depth = max(max_depth, nested_depth + 1)
    return max_depth


# ─────────────────────────────────────────────────────────────────
# Fingerprint
# ─────────────────────────────────────────────────────────────────

def _nfp(s):
    """Normalize a string for fingerprint comparison."""
    return re.sub(r'[\s\-/]+', '_', str(s).lower().strip()).strip('_')


def build_degraded_fingerprint(
    computation_type,
    computation_params,
    ultimate_raw_sources,
    function_chain=None,
    formula_str=None,
):
    """Build a coarse fingerprint when full lineage is unavailable."""
    parts = [computation_type or "UNKNOWN"]
    chain = function_chain or []
    if not chain and formula_str:
        chain = re.findall(r'\b([A-Z][A-Z0-9_\.]+)\s*\(', str(formula_str).upper())
    if chain:
        parts.append("FUNC_CHAIN:" + ",".join(sorted(set(c.lower() for c in chain))))
    norm_sources = sorted([_nfp(s) for s in (ultimate_raw_sources or [])])
    if norm_sources:
        parts.append("USES:" + ",".join(norm_sources))
    if computation_type == "DYNAMIC":
        dynamic_func = "indirect" if formula_str and "INDIRECT(" in str(formula_str).upper() else "offset"
        ref_count = len(re.findall(r'[A-Z]+\d+', str(formula_str or "")))
        parts.append(f"FUNC:{dynamic_func}")
        parts.append(f"REF_COUNT:{ref_count}")
    elif computation_type == "LOOKUP":
        parts.append("LOOKUP_TYPE:generic")
    return "|".join(parts) if len(parts) > 1 else parts[0]


def build_fingerprint(computation_type, computation_params, ultimate_raw_sources,
                      function_chain=None, formula_str=None):
    """
    Build a normalized, comparable fingerprint string.
    Two formulas doing the same business logic produce identical fingerprints.
    """
    parts = [computation_type]
    if computation_type in ("SUMIFS", "MULTI_AGG"):
        scalar = computation_params.get("scalar", 1)
        sum_col = _nfp(computation_params.get("sum_column") or "")
        group_by = sorted([_nfp(g) for g in computation_params.get("group_by", [])])
        filters = sorted([
            f"{_nfp(flt['column'])}{flt.get('operator', '=')}{_nfp(str(flt.get('value', '')))}"
            for flt in computation_params.get("static_filters", [])
        ])
        parts.append(f"scalar:{scalar}")
        if sum_col:
            parts.append(f"SUM:{sum_col}")
        if filters:
            parts.append("WHERE:" + "&".join(filters))
        if group_by:
            parts.append("GROUP_BY:" + ",".join(group_by))
    elif computation_type == "COUNTIFS":
        group_by = sorted([_nfp(g) for g in computation_params.get("group_by", [])])
        filters = sorted([
            f"{_nfp(flt['column'])}{flt.get('operator', '=')}{_nfp(str(flt.get('value', '')))}"
            for flt in computation_params.get("static_filters", [])
        ])
        if filters:
            parts.append("WHERE:" + "&".join(filters))
        if group_by:
            parts.append("GROUP_BY:" + ",".join(group_by))
    elif computation_type == "ARITHMETIC":
        # Operator/function skeleton so =B2*C2 and =B2+C2 do not collide
        skeleton = ""
        if formula_str:
            skeleton = re.sub(
                r"(?:'[^']+'|[A-Za-z0-9_\-]+!)?"
                r"\$?[A-Z]+\$?\d+(?::\$?[A-Z]+\$?\d+)?",
                "REF",
                str(formula_str).upper(),
            )
            skeleton = re.sub(r"\s+", "", skeleton)
            skeleton = re.sub(r"REF", "R", skeleton)
        norm_sources = sorted([_nfp(s) for s in ultimate_raw_sources])
        if skeleton:
            parts.append("EXPR:" + skeleton[:120])
        parts.append("USES:" + ",".join(norm_sources))
    elif computation_type == "PASS_THROUGH":
        parts.append(f"REF:{_nfp(computation_params.get('points_to_column', ''))}")
    elif computation_type == "CONSTANT":
        parts.append(f"VALUE:{computation_params.get('value', '')}")
    elif computation_type == "SUM_RANGE":
        sum_col = _nfp(computation_params.get("sum_column") or "")
        if sum_col:
            parts.append(f"SUM:{sum_col}")
    elif computation_type == "RATIO":
        norm_sources = sorted([_nfp(s) for s in ultimate_raw_sources])
        parts.append("USES:" + ",".join(norm_sources))
    elif computation_type in ("LOOKUP", "UNKNOWN", "DYNAMIC", "CONDITIONAL", "UNSUPPORTED"):
        return build_degraded_fingerprint(
            computation_type, computation_params, ultimate_raw_sources,
            function_chain=function_chain, formula_str=formula_str,
        )

    result = "|".join(parts)
    if result == computation_type or len(parts) <= 1:
        return build_degraded_fingerprint(
            computation_type, computation_params, ultimate_raw_sources,
            function_chain=function_chain, formula_str=formula_str,
        )
    return result


# ─────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────

def build_formula_lineage(parsed_result, formula_str, all_column_index):
    """
    Build a complete formula_lineage object for a formula column.

    Parameters:
      parsed_result    -- result from parse_formula() in formula_parser.py
      formula_str      -- raw Excel formula e.g. '=SUMIFS(...)'
      all_column_index -- {column_name: column_dict} for ALL columns in workbook
                          (built by json_builder in a two-pass approach)

    Returns formula_lineage dict, or None if not a formula column.

    Lineage depth:
      depth=1 : formula directly references raw data (SUMIFS, COUNTIFS)
      depth=2 : formula references another computed column (arithmetic combo)
      depth=N : N levels of computed → computed → ... → raw

    Fingerprint:
      A normalized string for cross-file comparison. Two formulas doing the
      same business logic produce identical fingerprints regardless of file name,
      sheet name, or column name capitalization differences.
    """
    if not formula_str or not str(formula_str).startswith('='):
        return None

    # ── 1. Strip wrapper ─────────────────────────────────────────
    inner_formula, wrapper_type = strip_formula_wrapper(formula_str)

    # ── 2. Detect type ───────────────────────────────────────────
    computation_type = detect_computation_type(inner_formula)

    # ── 3. Build computation_params ──────────────────────────────
    formula_source_details = parsed_result.get("formula_source_details", [])
    data_source_sheet = parsed_result.get("data_source_sheet", "")

    computation_params = {}

    if computation_type in ("SUMIFS", "MULTI_AGG"):
        scalar = -1 if str(inner_formula).lstrip('=').strip().startswith('-') else 1
        sum_col = next(
            (d["column_name"] for d in formula_source_details if d["role"] == "sum_range"),
            None
        )
        group_by = list(dict.fromkeys(
            d["column_name"] for d in formula_source_details
            if d["role"] in ("group_by_key", "criteria_range")
        ))
        static_filters = [
            {
                "column": d["column_name"],
                "operator": d.get("operator", "="),
                "value": d.get("filter_value", "?"),
            }
            for d in formula_source_details if d["role"] == "static_filter"
        ]
        computation_params = {
            "agg_function": "SUM", "scalar": scalar,
            "sum_column": sum_col, "group_by": group_by, "static_filters": static_filters,
        }

    elif computation_type == "COUNTIFS":
        group_by = list(dict.fromkeys(
            d["column_name"] for d in formula_source_details
            if d["role"] in ("count_range", "group_by_key")
        ))
        static_filters = [
            {
                "column": d["column_name"],
                "operator": d.get("operator", "="),
                "value": d.get("filter_value", "?"),
            }
            for d in formula_source_details if d["role"] == "static_filter"
        ]
        computation_params = {"group_by": group_by, "static_filters": static_filters}

    elif computation_type == "ARITHMETIC":
        arith_inputs = [d["column_name"] for d in formula_source_details
                        if d["role"] in ("arithmetic_input", "sum_input")]
        computation_params = {
            "inputs": arith_inputs,
            "expression": parsed_result.get("formula_pattern", inner_formula.lstrip('=')),
        }

    elif computation_type == "PASS_THROUGH":
        ref_col = next((d["column_name"] for d in formula_source_details), None)
        computation_params = {"points_to_column": ref_col or ""}

    elif computation_type == "CONSTANT":
        try:
            computation_params = {"value": float(inner_formula.lstrip('=').strip())}
        except ValueError:
            computation_params = {"value": inner_formula.lstrip('=')}

    # ── 4. Build direct_inputs ───────────────────────────────────
    direct_inputs = build_direct_inputs(
        formula_source_details, data_source_sheet, all_column_index
    )

    # ── 5. Collect ultimate raw sources ──────────────────────────
    ultimate_raw_sources = collect_ultimate_sources(direct_inputs)

    # Fallback to parsed data_source_columns if lineage can't resolve
    if not ultimate_raw_sources:
        for col in parsed_result.get("data_source_columns", []):
            src = f"{data_source_sheet} :: {col}"
            if src not in ultimate_raw_sources:
                ultimate_raw_sources.append(src)

    # ── 6. Depth + fingerprint ───────────────────────────────────
    depth = compute_lineage_depth(direct_inputs)
    function_chain = parsed_result.get("function_chain", [])
    fingerprint = build_fingerprint(
        computation_type, computation_params, ultimate_raw_sources,
        function_chain=function_chain, formula_str=formula_str,
    )
    if not fingerprint:
        fingerprint = build_degraded_fingerprint(
            computation_type, computation_params, ultimate_raw_sources,
            function_chain=function_chain, formula_str=formula_str,
        )

    resolved_by = parsed_result.get("resolved_by", "custom_parser")
    if computation_type in ("LOOKUP", "UNKNOWN", "DYNAMIC", "CONDITIONAL"):
        resolved_by = "degraded"
    if computation_type == "UNSUPPORTED" or parsed_result.get("unsupported_features"):
        resolved_by = "unsupported"

    lineage = {
        "computation_type": computation_type,
        "computation_params": computation_params,
        "lineage_depth": depth,
        "direct_inputs": direct_inputs,
        "ultimate_raw_sources": ultimate_raw_sources,
        "fingerprint": fingerprint,
        "resolved_by": resolved_by,
        "lineage_schema_version": LINEAGE_SCHEMA_VERSION,
    }
    if parsed_result.get("unsupported_features"):
        lineage["unsupported_features"] = parsed_result["unsupported_features"]
    if wrapper_type:
        lineage["wrapper"] = wrapper_type
    if parsed_result.get("references_external"):
        lineage["references_external"] = True
    if parsed_result.get("circular_reference"):
        lineage["circular_reference"] = True

    return lineage
