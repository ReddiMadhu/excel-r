"""
Validation — Validate extracted JSON for schema compliance and extraction quality.

Removed hardcoded table count expectations per file name.
Added generic structural checks and formula resolution quality checks.
"""
import os

_COMPARABLE_TYPES = frozenset({"formula_based", "pivot_value", "total", "check"})
_FULL_TYPES = frozenset({"SUMIFS", "COUNTIFS", "SUM_RANGE", "ARITHMETIC", "PASS_THROUGH", "MULTI_AGG", "RATIO", "CONSTANT"})


def compute_comparison_readiness(json_data):
    """
    Compute per-workbook comparison readiness metrics.

    Returns dict with:
      extraction_quality_score (0-1): share of comparable columns with fingerprint + sources
      comparison_mode: full | degraded | insufficient
      comparable_columns, ready_columns, degraded_columns, missing_columns
    """
    sheets = json_data.get("sheets", [])
    comparable = 0
    ready = 0
    degraded = 0
    missing = 0

    for sheet in sheets:
        if sheet.get("sheet_type") not in ("summary_report",):
            continue
        for table in sheet.get("tables", []):
            for col in table.get("columns", []):
                col_type = col.get("type", "")
                if col_type not in _COMPARABLE_TYPES:
                    continue
                comparable += 1
                lineage = col.get("formula_lineage") or {}
                fingerprint = lineage.get("fingerprint", "") if isinstance(lineage, dict) else ""
                sources = lineage.get("ultimate_raw_sources", []) if isinstance(lineage, dict) else []
                comp_type = lineage.get("computation_type", "") if isinstance(lineage, dict) else ""

                has_fp = bool(fingerprint)
                has_sources = bool(sources)

                if has_fp and has_sources and comp_type in _FULL_TYPES:
                    ready += 1
                elif has_fp:
                    degraded += 1
                else:
                    missing += 1

    if comparable == 0:
        score = 0.0
        mode = "insufficient"
    else:
        score = round((ready + degraded * 0.5) / comparable, 4)
        full_ratio = ready / comparable
        if full_ratio >= 0.8:
            mode = "full"
        elif score >= 0.4:
            mode = "degraded"
        else:
            mode = "insufficient"

    return {
        "extraction_quality_score": score,
        "comparison_mode": mode,
        "comparable_columns": comparable,
        "ready_columns": ready,
        "degraded_columns": degraded,
        "missing_columns": missing,
    }


def validate_extracted_json(json_data):
    """
    Validate the generated JSON output for schema compliance and extraction quality.
    Returns a list of warnings.
    """
    warnings = []
    
    file_name = json_data.get("file_name", "")
    sheets = json_data.get("sheets", [])
    
    schema_version = json_data.get("schema_version", "")
    is_rationalized = (schema_version == "7.0-rationalized")
    
    # 1. Sheet scope checks
    if len(sheets) == 0:
        warnings.append("No sheets found in the JSON output.")
        return warnings
        
    summary_sheets = [s for s in sheets if s.get("sheet_type") == "summary_report"]
    raw_sheets = [s for s in sheets if s.get("sheet_type") == "raw_data"]
    
    # 2. Table-level checks

    for sheet in summary_sheets:
        tables = sheet.get("tables", [])
        
        if len(tables) == 0:
            warnings.append(f"Sheet '{sheet.get('sheet_name')}' has 0 detected tables.")
        
        for t in tables:
            t_name = t.get("table_name", "")
            t_range = t.get("table_range", "")
            
            if not is_rationalized:
                if not t_range:
                    warnings.append(f"Table '{t_name}' is missing a table_range.")
                if t.get("row_count", 0) == 0:
                    warnings.append(f"Table '{t_name}' ({t_range}) has 0 data rows.")
                if t.get("column_count", 0) == 0:
                    warnings.append(f"Table '{t_name}' ({t_range}) has 0 columns.")
                
            # Column-level checks
            formula_based_count = 0
            unresolved_count = 0
            library_resolved_count = 0
            custom_resolved_count = 0
            
            for col in t.get("columns", []):
                col_name = col.get("column_name", "")
                col_type = col.get("type", "")
                resolved_by = col.get("resolved_by", "")
                
                if resolved_by == "formulas_library":
                    library_resolved_count += 1
                elif resolved_by == "custom_parser":
                    custom_resolved_count += 1
                
                if col_type == "formula_based":
                    formula_based_count += 1
                    if col.get("formula_count", 0) == 0:
                        warnings.append(f"Column '{col_name}' in table '{t_name}' is formula_based but has 0 formula_count.")
                    if is_rationalized:
                        if "formula_lineage" not in col:
                            unresolved_count += 1
                            warnings.append(f"Column '{col_name}' in table '{t_name}' is formula_based but formula_lineage is missing.")
                    else:
                        if not col.get("data_source_columns"):
                            unresolved_count += 1
                            warnings.append(f"Column '{col_name}' in table '{t_name}' is formula_based but raw data source column could not be mapped.")
                elif col_type == "pivot_value":
                    if not is_rationalized:
                        if not col.get("data_source_columns"):
                            warnings.append(f"Column '{col_name}' in table '{t_name}' is pivot_value but source column could not be resolved from pivot cache.")
            
            # Resolution quality summary
            if formula_based_count > 0:
                resolution_rate = ((formula_based_count - unresolved_count) / formula_based_count * 100)
                if resolution_rate < 80:
                    warnings.append(
                        f"Table '{t_name}': Only {resolution_rate:.0f}% of formula columns have resolved data sources "
                        f"({formula_based_count - unresolved_count}/{formula_based_count}). "
                        f"Library resolved: {library_resolved_count}, Custom resolved: {custom_resolved_count}."
                    )

    readiness = compute_comparison_readiness(json_data)
    if readiness["comparable_columns"] > 0 and readiness["extraction_quality_score"] < 0.6:
        warnings.append(
            f"Low comparison readiness: score={readiness['extraction_quality_score']:.0%}, "
            f"mode={readiness['comparison_mode']}, "
            f"missing={readiness['missing_columns']}/{readiness['comparable_columns']} columns."
        )

    return warnings


def generate_validation_report(all_results):
    """
    Generate a collective validation report.
    all_results: dict mapping filename to its warnings list.
    """
    report = {
        "validation_report_version": "6.0",
        "total_files_processed": len(all_results),
        "overall_status": "PASS" if not any(all_results.values()) else "WARNINGS",
        "files": []
    }
    
    for fn, warnings in all_results.items():
        report["files"].append({
            "file_name": fn,
            "status": "PASS" if not warnings else "WARNINGS",
            "warnings_count": len(warnings),
            "warnings": warnings
        })
        
    return report
