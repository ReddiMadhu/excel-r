lineage_code = '''

# ─────────────────────────────────────────────────────────────────
# Formula Lineage System
# ─────────────────────────────────────────────────────────────────

def classify_criteria_ref(ref_str, current_row):
    """
    Classify a SUMIFS/COUNTIFS criteria value reference.
    Returns: 'group_by_key' or 'static_filter'

    Rules:
      $COLrow  (col fixed, row relative) -> group_by_key  e.g. Summary!$A6
      COL$row  (col relative, row fixed) -> static_filter  e.g. Summary!J$5
      $COL$row (both fixed)              -> static_filter
      COLrow   (both relative)           -> group_by_key  e.g. A6
      "string" (literal)                 -> static_filter
    """
    import re
    if not ref_str:
        return 'static_filter'
    ref = str(ref_str).lstrip('=').strip()
    if ref.startswith('"') or ref.startswith("'"):
        return 'static_filter'
    cell_part = ref.split('!')[-1] if '!' in ref else ref
    row_is_absolute = bool(re.search(r'(?<=[A-Za-z])\\$\\d', cell_part))
    if row_is_absolute:
        return 'static_filter'
    return 'group_by_key'


def _extract_filter_value_str(crit_val_ref, crit_val_repr, summary_ws_val):
    """Extract a clean filter value string from a static criteria reference."""
    import re
    ref = str(crit_val_ref).strip()
    if ref.startswith('"'):
        return ref.strip('"')
    match = re.search(r"\\([\'\\"](.+?)[\'\\"]\\)", crit_val_repr)
    if match:
        return f"\\'{match.group(1)}\\'"
    try:
        _, col_letter, row_num, _ = parse_sheet_cell_ref(ref)
        if row_num and col_letter and summary_ws_val:
            from openpyxl.utils import column_index_from_string
            col_idx = column_index_from_string(col_letter)
            val = summary_ws_val.cell(row=row_num, column=col_idx).value
            if val is not None:
                return f"\\'{val}\\'" if isinstance(val, str) else str(val)
    except Exception:
        pass
    return crit_val_repr.strip("\\"'")


def _strip_formula_wrapper(formula_str):
    """Strip IFERROR/IFNA/IF wrappers. Returns (inner_formula, wrapper_type)."""
    if not formula_str:
        return formula_str, None
    f = str(formula_str).strip()
    fu = f.upper()
    for wrapper in ["IFERROR", "IFNA", "ISERROR"]:
        if fu.startswith(f"={wrapper}("):
            inner = f[len(wrapper) + 2:]
            paren_count = 0
            in_quote = False
            for i, char in enumerate(inner):
                if char == '"':
                    in_quote = not in_quote
                elif not in_quote:
                    if char == '(':
                        paren_count += 1
                    elif char == ')':
                        if paren_count == 0:
                            inner = inner[:i]
                            break
                        paren_count -= 1
                    elif char == ',' and paren_count == 0:
                        inner = inner[:i]
                        break
            return ('=' + inner if not inner.startswith('=') else inner), wrapper
    return f, None


def _detect_computation_type(formula_str):
    """
    Detect the computation archetype.
    Returns one of: SUMIFS, COUNTIFS, SUM_RANGE, ARITHMETIC, RATIO,
                    MULTI_AGG, PASS_THROUGH, CONDITIONAL, CONSTANT, LOOKUP, UNKNOWN
    """
    import re
    if not formula_str:
        return "UNKNOWN"
    f = str(formula_str).strip().lstrip('=').strip()
    fu = f.upper()
    try:
        float(f.replace(',', '').replace('%', ''))
        return "CONSTANT"
    except ValueError:
        pass
    if "VLOOKUP(" in fu or "HLOOKUP(" in fu or ("INDEX(" in fu and "MATCH(" in fu):
        return "LOOKUP"
    sumifs_count = fu.count("SUMIFS(")
    if sumifs_count > 1:
        return "MULTI_AGG"
    if sumifs_count == 1:
        return "SUMIFS"
    if "COUNTIFS(" in fu or "COUNTIF(" in fu:
        return "COUNTIFS"
    if "SUM(" in fu:
        return "SUM_RANGE"
    if re.fullmatch(r"\'?[A-Za-z0-9_ ]*\'?!?\\$?[A-Z]+\\$?\\d+", f):
        return "PASS_THROUGH"
    if re.search(r'/', f) and not re.search(r'SUMIFS|SUM\\(|COUNT', fu):
        return "RATIO"
    if re.search(r'[+\\-*/]', f):
        return "ARITHMETIC"
    return "UNKNOWN"


def _build_direct_inputs(formula_source_details, data_source_sheet, all_column_index):
    """Build direct_inputs list with is_raw lookup and nested_lineage attachment."""
    seen = set()
    direct_inputs = []
    for detail in formula_source_details:
        col_name = detail.get("column_name", "")
        role = detail.get("role", "")
        if not col_name or col_name in seen:
            continue
        seen.add(col_name)
        known = all_column_index.get(col_name)
        is_raw = (known is None) or (known.get("type", "raw") == "raw")
        table = known.get("table_name", data_source_sheet) if known else data_source_sheet
        node = {"column": col_name, "table": table, "is_raw": is_raw, "role": role}
        if "filter_value" in detail:
            node["filter_value"] = detail["filter_value"]
        if not is_raw and known and "formula_lineage" in known:
            node["nested_lineage"] = known["formula_lineage"]
        direct_inputs.append(node)
    return direct_inputs


def _collect_ultimate_sources(direct_inputs):
    """Recursively collect ultimate raw source strings (table :: column)."""
    sources = []
    for inp in direct_inputs:
        if inp.get("is_raw"):
            src = f"{inp['table']} :: {inp['column']}"
            if src not in sources:
                sources.append(src)
        elif "nested_lineage" in inp:
            for src in inp["nested_lineage"].get("ultimate_raw_sources", []):
                if src not in sources:
                    sources.append(src)
    return sources


def _compute_lineage_depth(direct_inputs):
    """Compute maximum lineage depth from direct_inputs."""
    max_depth = 1
    for inp in direct_inputs:
        if "nested_lineage" in inp:
            max_depth = max(max_depth, inp["nested_lineage"].get("lineage_depth", 1) + 1)
    return max_depth


def _normalize_fp(s):
    """Normalize a string for fingerprint comparison."""
    import re
    return re.sub(r'[\\s\\-/]+', '_', str(s).lower().strip()).strip('_')


def build_fingerprint(computation_type, computation_params, ultimate_raw_sources):
    """
    Build a normalized, comparable fingerprint string.
    Equivalent formulas in different files produce identical fingerprints.
    """
    parts = [computation_type]
    if computation_type in ("SUMIFS", "MULTI_AGG"):
        scalar = computation_params.get("scalar", 1)
        sum_col = _normalize_fp(computation_params.get("sum_column") or "")
        group_by = sorted([_normalize_fp(g) for g in computation_params.get("group_by", [])])
        filters = sorted([
            f"{_normalize_fp(flt['column'])}={_normalize_fp(str(flt.get('value', '')))}"
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
        group_by = sorted([_normalize_fp(g) for g in computation_params.get("group_by", [])])
        filters = sorted([
            f"{_normalize_fp(flt['column'])}={_normalize_fp(str(flt.get('value', '')))}"
            for flt in computation_params.get("static_filters", [])
        ])
        if filters:
            parts.append("WHERE:" + "&".join(filters))
        if group_by:
            parts.append("GROUP_BY:" + ",".join(group_by))
    elif computation_type == "ARITHMETIC":
        norm_sources = sorted([_normalize_fp(s) for s in ultimate_raw_sources])
        parts.append("USES:" + ",".join(norm_sources))
    elif computation_type == "PASS_THROUGH":
        parts.append(f"REF:{_normalize_fp(computation_params.get('points_to_column', ''))}")
    elif computation_type == "CONSTANT":
        parts.append(f"VALUE:{computation_params.get('value', '')}")
    return "|".join(parts)


def build_formula_lineage(parsed_result, formula_str, all_column_index):
    """
    Build a complete formula_lineage object for a formula column.

    Parameters:
      parsed_result    -- result from parse_formula()
      formula_str      -- raw Excel formula e.g. '=SUMIFS(...)'
      all_column_index -- {column_name: column_dict} for ALL columns in workbook
                          (built by json_builder in a two-pass approach)

    Returns formula_lineage dict, or None if not a formula.
    """
    if not formula_str or not str(formula_str).startswith('='):
        return None

    inner_formula, wrapper_type = _strip_formula_wrapper(formula_str)
    computation_type = _detect_computation_type(inner_formula)

    formula_source_details = parsed_result.get("formula_source_details", [])
    data_source_sheet = parsed_result.get("data_source_sheet", "")

    computation_params = {}
    if computation_type in ("SUMIFS", "MULTI_AGG"):
        scalar = -1 if str(inner_formula).lstrip('=').strip().startswith('-') else 1
        sum_col = next((d["column_name"] for d in formula_source_details if d["role"] == "sum_range"), None)
        group_by = list(dict.fromkeys(
            d["column_name"] for d in formula_source_details
            if d["role"] in ("group_by_key", "criteria_range")
        ))
        static_filters = [
            {"column": d["column_name"], "operator": "=", "value": d.get("filter_value", "?")}
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
            {"column": d["column_name"], "operator": "=", "value": d.get("filter_value", "?")}
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

    direct_inputs = _build_direct_inputs(formula_source_details, data_source_sheet, all_column_index)
    ultimate_raw_sources = _collect_ultimate_sources(direct_inputs)

    if not ultimate_raw_sources:
        for col in parsed_result.get("data_source_columns", []):
            src = f"{data_source_sheet} :: {col}"
            if src not in ultimate_raw_sources:
                ultimate_raw_sources.append(src)

    depth = _compute_lineage_depth(direct_inputs)
    fingerprint = build_fingerprint(computation_type, computation_params, ultimate_raw_sources)

    lineage = {
        "computation_type": computation_type,
        "computation_params": computation_params,
        "lineage_depth": depth,
        "direct_inputs": direct_inputs,
        "ultimate_raw_sources": ultimate_raw_sources,
        "fingerprint": fingerprint,
    }
    if wrapper_type:
        lineage["wrapper"] = wrapper_type
    return lineage
'''

target = r"c:\Users\madhu\Desktop\excelrationlization\input files\src\parsers\formula_parser.py"
with open(target, 'a', encoding='utf-8') as fh:
    fh.write(lineage_code)
print("Appended lineage system successfully.")
