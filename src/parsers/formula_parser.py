"""
Formula Parser — Hybrid formula parsing using `formulas` library + custom fallback.

Primary: Uses the `formulas` library to compile the workbook into a dependency graph,
supporting all 500+ Excel functions automatically.

Fallback: If `formulas` fails on a specific cell, falls back to the existing custom
parsing logic for SUMIFS, COUNTIFS, SUM, and arithmetic formulas.
"""
import re
import traceback
import openpyxl
from openpyxl.utils import get_column_letter, column_index_from_string


# ─────────────────────────────────────────────────────────────────
# formulas library integration
# ─────────────────────────────────────────────────────────────────

_node_lookup = None


def compile_workbook(file_path):
    """
    Compile an entire workbook using the `formulas` library.
    Returns the ExcelModel or None if compilation fails.
    """
    try:
        import formulas
        xl_model = formulas.ExcelModel().loads(file_path).finish()
        return xl_model
    except Exception as e:
        print(f"Warning: formulas library compilation failed: {e}")
        return None


def get_cell_dependencies(xl_model, sheet_name, cell_ref):
    """
    Get all cells that a given cell depends on (predecessors) using the
    formulas library dependency graph.
    
    Returns a list of cell reference strings like "'[wb]Sheet!A1'".
    """
    global _node_lookup
    if xl_model is None:
        return []
    
    try:
        dsp = xl_model.dsp
        
        # Build lookup if not cached or model changed
        if _node_lookup is None or _node_lookup.get("dsp_id") != id(dsp):
            lookup = {}
            for node in dsp.nodes:
                node_str = str(node)
                if '!' in node_str:
                    parts = node_str.split('!')
                    sheet_part = parts[0].strip("'\"[]")
                    cell_part = parts[1].strip("'\"$")
                    
                    # Extract sheet name (remove workbook prefix)
                    if ']' in sheet_part:
                        s_name = sheet_part.split(']')[-1]
                    else:
                        s_name = sheet_part
                    
                    key = (s_name.upper(), cell_part.upper())
                    lookup[key] = node
            _node_lookup = {
                "dsp_id": id(dsp),
                "lookup": lookup
            }
            
        cell_upper = cell_ref.upper().replace('$', '')
        target_key = _node_lookup["lookup"].get((sheet_name.upper(), cell_upper))
        
        if target_key is None:
            return []
        
        # Get all predecessors (cells this cell depends on)
        predecessors = []
        try:
            preds = list(dsp.predecessors(target_key))
            predecessors = [str(p) for p in preds]
        except Exception:
            pass
        
        return predecessors
    except Exception:
        return []


def resolve_dependency_to_column(dep_ref, raw_column_maps):
    """
    Translate a formulas-library dependency reference back to a human-readable
    column name using the raw column maps.
    
    dep_ref format: "'[workbook.xlsx]SheetName'!A1" or similar
    """
    try:
        # Extract sheet name and cell ref
        if '!' in dep_ref:
            parts = dep_ref.split('!')
            sheet_part = parts[0].strip("'\"[]")
            cell_part = parts[1].strip("'\"")
            
            # Extract just the sheet name (remove workbook name)
            if ']' in sheet_part:
                sheet_name = sheet_part.split(']')[-1]
            else:
                sheet_name = sheet_part
            
            # Get column letter from cell reference
            col_letter = ''.join(filter(str.isalpha, cell_part)).upper()
            
            # Look up in raw column maps
            if sheet_name in raw_column_maps:
                header = raw_column_maps[sheet_name].get(col_letter)
                if header:
                    return {
                        "sheet": sheet_name,
                        "column": col_letter,
                        "header": header,
                    }
            
            return {
                "sheet": sheet_name,
                "column": col_letter,
                "header": None,
            }
    except Exception:
        pass
    
    return None


def parse_formula_with_library(xl_model, sheet_name, cell_ref, formula_str,
                                current_row, ws_val, raw_column_maps, 
                                table_col_mapping, table_name, ws_form=None,
                                detected_tables=None):
    """
    Parse a formula using the formulas library dependency graph.
    Falls back to custom parsing if the library can't resolve it.
    """
    deps = get_cell_dependencies(xl_model, sheet_name, cell_ref)
    
    if not deps:
        # Fallback to custom parsing
        return parse_formula(
            formula_str, current_row, ws_val, 
            raw_column_maps, table_col_mapping, table_name,
            ws_form,
            detected_tables=detected_tables
        )
    
    # Resolve dependencies to column names
    data_source_sheet = ""
    data_source_columns = set()
    formula_source_details = []
    
    for dep in deps:
        resolved = resolve_dependency_to_column(dep, raw_column_maps)
        if resolved and resolved["header"]:
            data_source_sheet = resolved["sheet"]
            data_source_columns.add(resolved["header"])
            formula_source_details.append({
                "column_name": resolved["header"],
                "role": "dependency",
            })
    
    if data_source_columns:
        # Successfully resolved via library
        # Generate a human-readable formula pattern
        formula_pattern = _generate_pattern_from_formula(
            formula_str, ws_val, current_row, raw_column_maps, table_col_mapping
        )
        
        return {
            "type": "formula_based",
            "formula_pattern": formula_pattern,
            "data_source_sheet": data_source_sheet,
            "data_source_columns": list(data_source_columns),
            "formula_source_details": formula_source_details,
            "formula_count": 1,
            "resolved_by": "formulas_library",
        }
    
    # Library found dependencies but couldn't map to raw columns
    # Fall back to custom parsing
    return parse_formula(
        formula_str, current_row, ws_val,
        raw_column_maps, table_col_mapping, table_name,
        ws_form,
        detected_tables=detected_tables
    )


def _clean_criteria_value(crit_val_repr):
    """
    Extract a clean, human-readable value from a criteria value representation.
    
    Examples:
      "Summary!K5 ('Flexible')" -> "'Flexible'"
      "current RBC C2 Product Category" -> "current row"
      "Col_A" -> "Col_A"
    """
    if "current " in crit_val_repr:
        return "current row"
    # Look for a value in parentheses e.g. ('Flexible') or ("Flexible")
    match = re.search(r"\(['\"](.+?)['\"]\)", crit_val_repr)
    if match:
        return f"'{match.group(1)}'"
    # Fall back to stripping quotes
    return crit_val_repr.strip("\"'")


def _build_sql_pattern(func_name, sum_repr, filters, criterias, is_negative=False):
    """
    Build a standardized SQL-like formula pattern string.
    
    Output format:
      [-1 * ] FUNC(source[column])
      [WHERE [col] = 'value' AND ...]
      [GROUP BY [col1], [col2]]
    """
    pattern = f"{func_name}({sum_repr})"
    if filters:
        where_parts = []
        for f in filters:
            # f is already in format "ColumnName = value"
            where_parts.append(f"[{f}]")
        pattern += " WHERE " + " AND ".join(where_parts)
    if criterias:
        group_parts = [f"[{c}]" for c in criterias]
        pattern += " GROUP BY " + ", ".join(group_parts)
    if is_negative:
        pattern = f"-1 * {pattern}"
    return pattern


def _generate_pattern_from_formula(formula_str, ws_val, current_row,
                                    raw_column_maps, table_col_mapping):
    """
    Generate a human-readable SQL-like formula pattern from a raw formula string.
    Replaces cell references with header names, respecting function structure.
    """
    if not formula_str:
        return ""

    pattern = formula_str.lstrip('=')

    # Replace sheet!column:column references (e.g., SQL_data!D:D)
    sheet_col_refs = re.findall(
        r"'?([A-Za-z_][A-Za-z0-9_ ]*)'?!\$?([A-Z]+):\$?([A-Z]+)", pattern
    )
    for sheet, col1, col2 in sheet_col_refs:
        if sheet in raw_column_maps:
            header = raw_column_maps[sheet].get(col1.upper(), f"Col_{col1}")
            pattern = pattern.replace(f"'{sheet}'!${col1}:${col2}", f"{sheet}[{header}]")
            pattern = pattern.replace(f"'{sheet}'!{col1}:{col2}", f"{sheet}[{header}]")
            pattern = pattern.replace(f"{sheet}!${col1}:${col2}", f"{sheet}[{header}]")
            pattern = pattern.replace(f"{sheet}!{col1}:{col2}", f"{sheet}[{header}]")

    # Replace local cell references (e.g., $A6, B$6, A6)
    cell_refs = re.findall(r'\$?([A-Z]+)\$?(\d+)', pattern)
    for col_letter, row_str in set(cell_refs):
        row_num = int(row_str)
        col_idx = column_index_from_string(col_letter)
        header = table_col_mapping.get(col_idx, f"Col_{col_letter}")
        if row_num == current_row:
            replacement = "current row"
        else:
            val = ws_val.cell(row=row_num, column=col_idx).value
            if val is not None:
                replacement = f"'{val}'"
            else:
                replacement = f"{col_letter}{row_str}"
        pattern = re.sub(
            rf'\$?{col_letter}\$?{row_str}\b',
            replacement,
            pattern
        )

    return pattern


# ─────────────────────────────────────────────────────────────────
# Custom formula parsing (fallback)
# These are kept from the original code as a reliable fallback.
# ─────────────────────────────────────────────────────────────────

def is_value_cell(cell_val, cell_formula):
    """Determine if a cell represents a value or formula (as opposed to metadata/labels)."""
    if cell_val is None:
        return False
    if str(cell_formula).startswith('='):
        return True
    if isinstance(cell_val, (int, float)):
        return True
    return False


def extract_function_calls(formula_str, func_name):
    """
    Find all occurrences of a function call (like SUMIFS, COUNTIFS, SUM) 
    in the formula and extract their arguments, respecting nested parentheses.
    """
    calls = []
    idx = 0
    formula_upper = formula_str.upper()
    func_pattern = func_name.upper() + "("
    
    while True:
        pos = formula_upper.find(func_pattern, idx)
        if pos == -1:
            break
            
        start_arg = pos + len(func_pattern)
        paren_count = 1
        curr = start_arg
        
        while curr < len(formula_str) and paren_count > 0:
            char = formula_str[curr]
            if char == '(':
                paren_count += 1
            elif char == ')':
                paren_count -= 1
            curr += 1
            
        if paren_count == 0:
            call_str = formula_str[pos:curr]
            args_str = formula_str[start_arg:curr-1]
            
            # Split arguments by comma, respecting nested parens and quotes
            args = []
            current_arg = []
            inner_paren = 0
            in_quote = False
            
            for char in args_str:
                if char == '"':
                    in_quote = not in_quote
                    current_arg.append(char)
                elif char == ',' and not in_quote and inner_paren == 0:
                    args.append("".join(current_arg).strip())
                    current_arg = []
                else:
                    if char == '(':
                        inner_paren += 1
                    elif char == ')':
                        inner_paren -= 1
                    current_arg.append(char)
            if current_arg:
                args.append("".join(current_arg).strip())
                
            calls.append({
                "full_call": call_str,
                "args": args
            })
            idx = curr
        else:
            idx = pos + len(func_pattern)
            
    return calls


def parse_sheet_cell_ref(ref_str):
    """
    Parse a reference string like SQL_data!D:D or 'Warehouse Data'!$C:$C or Summary!$A$2 or B6.
    Returns (sheet, col_letter, row_num, is_range) or (None, None, None, False).
    """
    # Remove absolute signs
    clean_ref = ref_str.replace('$', '')
    
    sheet_name = None
    cell_part = clean_ref
    
    if '!' in clean_ref:
        parts = clean_ref.split('!')
        sheet_name = parts[0].strip("'")
        cell_part = parts[1]
        
    # Check if it is a column range e.g. D:D or C:C
    if ':' in cell_part:
        sub_parts = cell_part.split(':')
        if sub_parts[0].isalpha() and sub_parts[1].isalpha():
            return sheet_name, sub_parts[0].upper(), None, True
        else:
            # Row range or mixed range, let's extract column letter of first cell
            col_letter = "".join(filter(str.isalpha, sub_parts[0]))
            return sheet_name, col_letter.upper(), None, True
            
    # Single cell ref e.g. A2 or B6
    col_letter = "".join(filter(str.isalpha, cell_part))
    row_num_str = "".join(filter(str.isdigit, cell_part))
    row_num = int(row_num_str) if row_num_str else None
    
    return sheet_name, col_letter.upper(), row_num, False


def translate_reference(ref_str, current_row, summary_ws_val, raw_column_maps, table_col_mapping, detected_tables=None):
    """
    Translate a single cell/column reference in a formula to its header/value representation.
    """
    sheet_name, col_letter, row_num, is_range = parse_sheet_cell_ref(ref_str)
    
    current_sheet_title = summary_ws_val.title if summary_ws_val else "Summary"
    
    # If referencing a raw data sheet
    if sheet_name and sheet_name in raw_column_maps:
        col_map = raw_column_maps[sheet_name]
        header = col_map.get(col_letter, f"Col_{col_letter}")
        return f"{sheet_name}[{header}]", header, sheet_name
        
    # If referencing the summary sheet or a local reference
    is_summary = (not sheet_name) or ("summary" in sheet_name.lower()) or (sheet_name == current_sheet_title)
    if is_summary and col_letter:
        col_idx = column_index_from_string(col_letter)
        
        # If we have detected_tables, try to map the cell to a specific table's column
        if detected_tables and row_num:
            for tbl in detected_tables:
                if tbl.get("row_start") and tbl.get("row_end") and tbl.get("col_start") and tbl.get("col_end"):
                    if tbl["row_start"] <= row_num <= tbl["row_end"] and tbl["col_start"] <= col_idx <= tbl["col_end"]:
                        col_offset = col_idx - tbl["col_start"]
                        headers = tbl.get("headers", [])
                        if col_offset < len(headers):
                            header_name = headers[col_offset]
                            # Return descriptive TableName[ColumnName] pattern
                            return f"{tbl['table_name']}[{header_name}]", header_name, current_sheet_title
        
        # Fallback to local table col mapping
        # If it refers to the same row as the formula
        if row_num == current_row:
            header = table_col_mapping.get(col_idx, f"Col_{col_letter}")
            return f"current {header}", header, current_sheet_title
            
        # If it refers to a specific cell
        if row_num:
            val = summary_ws_val.cell(row=row_num, column=col_idx).value
            header = table_col_mapping.get(col_idx, f"Col_{col_letter}")
            
            if isinstance(val, (int, float)):
                val_str = str(val)
            else:
                val_str = f"'{val}'" if val is not None else "None"
                
            return f"{current_sheet_title}!{col_letter}{row_num} ({val_str})", header, current_sheet_title
            
    return ref_str, None, None
            
    return ref_str, None, None


def parse_formula(formula_str, current_row, summary_ws_val, raw_column_maps, table_col_mapping, table_name, summary_ws_form=None, _depth=0, detected_tables=None):
    """
    Parse an Excel formula and extract metadata, lineage and formula patterns.
    
    This is the original custom parser kept as a fallback for when the 
    formulas library can't resolve a specific cell.
    
    _depth: recursion depth for transitive resolution (max 5 to prevent infinite loops).
    """
    if not formula_str or not str(formula_str).startswith('='):
        return {
            "type": "raw",
            "formula_pattern": "",
            "data_source_sheet": "",
            "data_source_columns": [],
            "formula_source_details": [],
            "formula_count": 0,
            "resolved_by": "none",
        }
        
    formula_upper = formula_str.upper()
    
    current_sheet_title = summary_ws_val.title if summary_ws_val else "Summary"
    
    data_source_sheet = ""
    data_source_columns = set()
    formula_source_details = []
    formula_pattern = formula_str
    
    # 1. Parse SUMIFS
    sumifs_calls = extract_function_calls(formula_str, "SUMIFS")
    if sumifs_calls:
        patterns = []
        for call in sumifs_calls:
            args = call["args"]
            if len(args) < 3:
                continue
                
            sum_ref = args[0]
            sum_repr, sum_hdr, sum_sheet = translate_reference(sum_ref, current_row, summary_ws_val, raw_column_maps, table_col_mapping, detected_tables)
            if sum_hdr:
                data_source_columns.add(sum_hdr)
                if sum_sheet:
                    data_source_sheet = sum_sheet
                formula_source_details.append({
                    "column_name": sum_hdr,
                    "role": "sum_range"
                })
                
            criterias = []
            filters = []
            for i in range(1, len(args), 2):
                if i + 1 >= len(args):
                    break
                crit_range_ref = args[i]
                crit_val_ref = args[i+1]

                crit_range_repr, crit_range_hdr, crit_sheet = translate_reference(
                    crit_range_ref, current_row, summary_ws_val,
                    raw_column_maps, table_col_mapping, detected_tables
                )
                crit_val_repr, crit_val_hdr, _ = translate_reference(
                    crit_val_ref, current_row, summary_ws_val,
                    raw_column_maps, table_col_mapping, detected_tables
                )

                if crit_range_hdr:
                    data_source_columns.add(crit_range_hdr)
                    if crit_sheet:
                        data_source_sheet = crit_sheet

                col_label = crit_range_hdr if crit_range_hdr else crit_range_repr

                # Classify using $ pattern — the definitive way to detect GROUP BY vs WHERE
                from src.parsers.formula_lineage import classify_criteria_ref, extract_filter_value
                ref_type = classify_criteria_ref(crit_val_ref, current_row)

                if ref_type == 'group_by_key':
                    criterias.append(col_label)
                    formula_source_details.append({
                        "column_name": col_label,
                        "role": "group_by_key"
                    })
                else:
                    fv = extract_filter_value(crit_val_ref, crit_val_repr, summary_ws_val)
                    filters.append(f"{col_label} = {fv}")
                    formula_source_details.append({
                        "column_name": col_label,
                        "role": "static_filter",
                        "filter_value": fv
                    })

            is_negative = formula_str.strip().startswith('=-1*') or formula_str.strip().startswith('=-')
            pattern = _build_sql_pattern("SUM", sum_repr, filters, criterias)
            formula_pattern = formula_pattern.replace(call["full_call"], pattern)

        clean_pattern = formula_pattern.lstrip('=-1*').lstrip('=-').lstrip('=')

        return {
            "type": "formula_based",
            "formula_pattern": f"-1 * {clean_pattern}" if is_negative else clean_pattern,
            "data_source_sheet": data_source_sheet,
            "data_source_columns": list(data_source_columns),
            "formula_source_details": formula_source_details,
            "formula_count": len(sumifs_calls),
            "resolved_by": "custom_parser",
        }
        
    # 2. Parse COUNTIFS
    countifs_calls = extract_function_calls(formula_str, "COUNTIFS")
    if countifs_calls:
        for call in countifs_calls:
            args = call["args"]
            if len(args) < 2:
                continue

            criterias = []
            filters = []
            for i in range(0, len(args), 2):
                if i + 1 >= len(args):
                    break
                crit_range_ref = args[i]
                crit_val_ref = args[i+1]

                crit_range_repr, crit_range_hdr, crit_sheet = translate_reference(
                    crit_range_ref, current_row, summary_ws_val,
                    raw_column_maps, table_col_mapping, detected_tables
                )
                crit_val_repr, crit_val_hdr, _ = translate_reference(
                    crit_val_ref, current_row, summary_ws_val,
                    raw_column_maps, table_col_mapping, detected_tables
                )

                if crit_range_hdr:
                    data_source_columns.add(crit_range_hdr)
                    if crit_sheet:
                        data_source_sheet = crit_sheet

                col_label = crit_range_hdr if crit_range_hdr else crit_range_repr

                from src.parsers.formula_lineage import classify_criteria_ref, extract_filter_value
                ref_type = classify_criteria_ref(crit_val_ref, current_row)

                if ref_type == 'group_by_key':
                    criterias.append(col_label)
                    formula_source_details.append({
                        "column_name": col_label,
                        "role": "group_by_key"
                    })
                else:
                    fv = extract_filter_value(crit_val_ref, crit_val_repr, summary_ws_val)
                    filters.append(f"{col_label} = {fv}")
                    formula_source_details.append({
                        "column_name": col_label,
                        "role": "static_filter",
                        "filter_value": fv
                    })

            count_source = data_source_sheet if data_source_sheet else "source"
            pattern = _build_sql_pattern("COUNT", count_source, filters, criterias)
            formula_pattern = formula_pattern.replace(call["full_call"], pattern)

        clean_pattern = formula_pattern.lstrip('=')
        return {
            "type": "formula_based",
            "formula_pattern": clean_pattern,
            "data_source_sheet": data_source_sheet,
            "data_source_columns": list(data_source_columns),
            "formula_source_details": formula_source_details,
            "formula_count": len(countifs_calls),
            "resolved_by": "custom_parser",
        }
        
    # 3. Parse SUM totals
    sum_calls = extract_function_calls(formula_str, "SUM")
    if sum_calls:
        sum_data_source_sheet = ""
        sum_data_source_columns = set()
        sum_formula_source_details = []
        
        for call in sum_calls:
            args = call["args"]
            if not args:
                continue
            arg_reprs = []
            for arg in args:
                if ':' in arg:
                    sub_parts = arg.split(':')
                    sheet_name, start_col, start_row_num, _ = parse_sheet_cell_ref(sub_parts[0])
                    _, end_col, end_row_num, _ = parse_sheet_cell_ref(sub_parts[1])
                    if start_col and end_col:
                        start_idx = column_index_from_string(start_col)
                        end_idx = column_index_from_string(end_col)
                        if start_idx > end_idx:
                            start_idx, end_idx = end_idx, start_idx
                            
                        for c_idx in range(start_idx, end_idx + 1):
                            c_letter = get_column_letter(c_idx)
                            header = table_col_mapping.get(c_idx, f"Col_{c_letter}")
                            arg_reprs.append(f"SUM({header})")
                            
                            if not sheet_name or sheet_name == current_sheet_title:
                                sum_data_source_columns.add(header)
                                if not sum_data_source_sheet or sum_data_source_sheet == current_sheet_title:
                                    sum_data_source_sheet = current_sheet_title
                        
                        # Transitive resolution: resolve only the first row in range for efficiency
                        if summary_ws_form and _depth < 5 and start_row_num and (not sheet_name or sheet_name == current_sheet_title):
                            sum_r = start_row_num
                            for c_idx in range(start_idx, end_idx + 1):
                                ref_formula = summary_ws_form.cell(row=sum_r, column=c_idx).value
                                if ref_formula and str(ref_formula).startswith('='):
                                    parsed_ref = parse_formula(
                                        ref_formula, sum_r, summary_ws_val,
                                        raw_column_maps, table_col_mapping, table_name,
                                        summary_ws_form, _depth=_depth + 1,
                                        detected_tables=detected_tables
                                    )
                                    if parsed_ref["data_source_columns"]:
                                        if parsed_ref["data_source_sheet"] and parsed_ref["data_source_sheet"] != current_sheet_title:
                                            if sum_data_source_sheet == current_sheet_title:
                                                sum_data_source_columns = set()
                                            sum_data_source_sheet = parsed_ref["data_source_sheet"]
                                            sum_data_source_columns.update(parsed_ref["data_source_columns"])
                                        else:
                                            if not sum_data_source_sheet or sum_data_source_sheet == current_sheet_title:
                                                sum_data_source_sheet = current_sheet_title
                                                sum_data_source_columns.update(parsed_ref["data_source_columns"])
                else:
                    repr_val, header, ref_sheet = translate_reference(arg, current_row, summary_ws_val, raw_column_maps, table_col_mapping, detected_tables)
                    arg_reprs.append(repr_val)
                    if header:
                        sum_formula_source_details.append({
                            "column_name": header,
                            "role": "sum_input"
                        })
                        if ref_sheet == current_sheet_title:
                            sum_data_source_columns.add(header)
                            if not sum_data_source_sheet or sum_data_source_sheet == current_sheet_title:
                                sum_data_source_sheet = current_sheet_title
                        elif ref_sheet:
                            if sum_data_source_sheet == current_sheet_title:
                                sum_data_source_columns = set()
                            sum_data_source_sheet = ref_sheet
                            sum_data_source_columns.add(header)
                            
            formula_pattern = formula_pattern.replace(call["full_call"], " + ".join(arg_reprs))
            
        clean_pattern = formula_pattern.lstrip('=')
        
        # Translate any remaining cell references (like F7) in the clean pattern
        cell_refs = re.findall(r'\b\$?[A-Z]+\$?[0-9]+\b', clean_pattern)
        for ref in set(cell_refs):
            repr_val, header, ref_sheet = translate_reference(ref, current_row, summary_ws_val, raw_column_maps, table_col_mapping, detected_tables)
            clean_pattern = re.sub(rf'\b{re.escape(ref)}\b', repr_val, clean_pattern)
            if header:
                if ref_sheet == current_sheet_title:
                    sum_data_source_columns.add(header)
                    if not sum_data_source_sheet or sum_data_source_sheet == current_sheet_title:
                        sum_data_source_sheet = current_sheet_title
                elif ref_sheet:
                    if sum_data_source_sheet == current_sheet_title:
                        sum_data_source_columns = set()
                    sum_data_source_sheet = ref_sheet
                    sum_data_source_columns.add(header)
            
        # If we found transitive/calculated data sources, return as formula_based
        if sum_data_source_columns:
            return {
                "type": "formula_based",
                "formula_pattern": clean_pattern,
                "data_source_sheet": sum_data_source_sheet,
                "data_source_columns": list(sum_data_source_columns),
                "formula_source_details": sum_formula_source_details,
                "formula_count": len(sum_calls),
                "resolved_by": "transitive_custom_parser",
            }
        
        return {
            "type": "total",
            "formula_pattern": clean_pattern,
            "data_source_sheet": "",
            "data_source_columns": [],
            "formula_source_details": [],
            "formula_count": len(sum_calls),
            "resolved_by": "custom_parser",
        }
        
    # 4. Parse arithmetic formulas
    arith_pattern = formula_str.lstrip('=')
    
    cell_refs = re.findall(r'\b\$?[A-Z]+\$?[0-9]+\b', arith_pattern)
    for ref in set(cell_refs):
        repr_val, header, ref_sheet = translate_reference(ref, current_row, summary_ws_val, raw_column_maps, table_col_mapping, detected_tables)
        arith_pattern = re.sub(rf'\b{re.escape(ref)}\b', repr_val, arith_pattern)
        if header:
            formula_source_details.append({
                "column_name": header,
                "role": "arithmetic_input"
            })
            if ref_sheet == current_sheet_title:
                data_source_columns.add(header)
                if not data_source_sheet or data_source_sheet == current_sheet_title:
                    data_source_sheet = current_sheet_title
            elif ref_sheet:
                if data_source_sheet == current_sheet_title:
                    data_source_columns = set()
                data_source_sheet = ref_sheet
                data_source_columns.add(header)
            
    # Transitive data sources resolution
    if summary_ws_form and _depth < 5:
        for ref in set(cell_refs):
            sheet_name, col_letter, row_num, is_range = parse_sheet_cell_ref(ref)
            if not sheet_name or sheet_name == current_sheet_title:
                if col_letter and row_num:
                    col_idx = column_index_from_string(col_letter)
                    ref_formula = summary_ws_form.cell(row=row_num, column=col_idx).value
                    if ref_formula and str(ref_formula).startswith('='):
                        # Parse recursively with incremented depth
                        parsed_ref = parse_formula(
                            ref_formula, row_num, summary_ws_val,
                            raw_column_maps, table_col_mapping, table_name,
                            summary_ws_form, _depth=_depth + 1,
                            detected_tables=detected_tables
                        )
                        if parsed_ref["data_source_columns"]:
                            if parsed_ref["data_source_sheet"] and parsed_ref["data_source_sheet"] != current_sheet_title:
                                if data_source_sheet == current_sheet_title:
                                    data_source_columns = set()
                                data_source_sheet = parsed_ref["data_source_sheet"]
                                data_source_columns.update(parsed_ref["data_source_columns"])
                            else:
                                if not data_source_sheet or data_source_sheet == current_sheet_title:
                                    data_source_sheet = current_sheet_title
                                    data_source_columns.update(parsed_ref["data_source_columns"])
            elif sheet_name in raw_column_maps:
                col_map = raw_column_maps[sheet_name]
                header = col_map.get(col_letter)
                if header:
                    if data_source_sheet == current_sheet_title:
                        data_source_columns = set()
                    data_source_columns.add(header)
                    data_source_sheet = sheet_name

    first_cell_val = str(summary_ws_val.cell(row=current_row, column=1).value).strip().lower()
    if "check" in first_cell_val:
        f_type = "check"
    elif "total" in first_cell_val or "grand total" in first_cell_val:
        f_type = "total"
    else:
        f_type = "formula_based"
        
    return {
        "type": f_type,
        "formula_pattern": arith_pattern,
        "data_source_sheet": data_source_sheet,
        "data_source_columns": list(data_source_columns),
        "formula_source_details": formula_source_details,
        "formula_count": 1,
        "resolved_by": "transitive_custom_parser" if data_source_columns else "custom_parser",
    }


def infer_formula_pattern_for_column(formulas_in_column):
    """
    Given a list of formulas in a summary column, return a single generalized formula pattern.
    """
    for f in formulas_in_column:
        if f and str(f).startswith('='):
            return f
    return ""
