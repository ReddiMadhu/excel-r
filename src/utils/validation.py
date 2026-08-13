"""
Validation — Validate extracted JSON for schema compliance and extraction quality.

Removed hardcoded table count expectations per file name.
Added generic structural checks and formula resolution quality checks.
"""
import os
import re

# KPI-comparable types (checks excluded — they are VALIDATION, not KPIs)
_COMPARABLE_TYPES = frozenset({"formula_based", "pivot_value", "total"})
_FULL_TYPES = frozenset({
    "SUMIFS", "COUNTIFS", "SUM_RANGE", "ARITHMETIC",
    "PASS_THROUGH", "MULTI_AGG", "RATIO", "CONSTANT",
})
_COL_FALLBACK_RE = re.compile(r"^Col_[A-Z]+$", re.I)


def _source_is_resolved(src: str) -> bool:
    """False for Col_D / empty / unresolved placeholders."""
    if not src or not str(src).strip():
        return False
    s = str(src).strip()
    # "SQL_data :: Col_D" or bare "Col_D"
    col_part = s.split("::")[-1].strip() if "::" in s else s
    if _COL_FALLBACK_RE.match(col_part):
        return False
    if col_part.lower().startswith("column_"):
        return False
    return True


def _fingerprint_is_usable(fingerprint: str, computation_type: str) -> bool:
    """Fingerprint must encode a real measure for SUMIFS-family types."""
    if not fingerprint:
        return False
    fp = fingerprint.lower()
    if computation_type in ("SUMIFS", "MULTI_AGG", "SUM_RANGE"):
        if "sum:" not in fp:
            return False
        if "sum:col_" in fp:
            return False
    return True


def compute_comparison_readiness(json_data):
    """
    Compute per-workbook comparison readiness metrics.

    Returns dict with:
      extraction_quality_score (0-1): share of comparable KPI columns with
        usable fingerprint + resolved (non-Col_*) sources
      comparison_mode: full | degraded | insufficient
      comparable_columns, ready_columns, degraded_columns, missing_columns

    Rules:
      FULL        = >=80% ready AND no critical failures (externals, mixed lineage,
                    Col_* sources dominating, parser degraded)
      DEGRADED    = score >= 0.4 or some recoverable issues
      INSUFFICIENT = majority of KPI columns lack usable lineage
    """
    sheets = json_data.get("sheets", [])
    comparable = 0
    ready = 0
    degraded = 0
    missing = 0
    critical_flags = []
    has_external = False
    has_mixed = False
    has_parser_degraded = False
    unresolved_header_count = 0

    # Workbook-level external links
    meta = json_data.get("workbook_metadata") or {}
    if meta.get("external_links"):
        has_external = True
        critical_flags.append("external_links")

    for sheet in sheets:
        if sheet.get("sheet_type") not in ("summary_report",):
            continue
        for table in sheet.get("tables", []):
            for col in table.get("columns", []):
                col_type = col.get("type", "")
                # Checks are validation — never count as KPI readiness
                if col_type == "check":
                    continue
                if col_type not in _COMPARABLE_TYPES:
                    continue
                comparable += 1
                lineage = col.get("formula_lineage") or {}
                if not isinstance(lineage, dict):
                    lineage = {}
                fingerprint = lineage.get("fingerprint", "") or ""
                sources = lineage.get("ultimate_raw_sources", []) or []
                comp_type = lineage.get("computation_type", "") or ""
                resolved_by = lineage.get("resolved_by", "") or col.get("resolved_by", "")

                if col.get("lineage_is_mixed") or lineage.get("lineage_is_mixed"):
                    has_mixed = True
                if col.get("references_external") or lineage.get("references_external"):
                    has_external = True
                if resolved_by in ("degraded", "none"):
                    has_parser_degraded = True

                resolved_sources = [s for s in sources if _source_is_resolved(s)]
                has_unresolved = any(not _source_is_resolved(s) for s in sources) if sources else False
                if has_unresolved:
                    unresolved_header_count += 1

                has_fp = _fingerprint_is_usable(fingerprint, comp_type)
                has_sources = bool(resolved_sources)
                roles_ok = True
                if comp_type in ("SUMIFS", "MULTI_AGG"):
                    params = lineage.get("computation_params") or {}
                    if not params.get("sum_column") or str(params.get("sum_column", "")).startswith("Col_"):
                        roles_ok = False

                if (
                    has_fp
                    and has_sources
                    and roles_ok
                    and comp_type in _FULL_TYPES
                    and not col.get("lineage_is_mixed")
                    and resolved_by not in ("degraded", "none")
                ):
                    ready += 1
                elif has_fp or has_sources:
                    degraded += 1
                else:
                    missing += 1

    if has_external:
        critical_flags.append("external_refs")
    if has_mixed:
        critical_flags.append("mixed_lineage")
    if has_parser_degraded:
        critical_flags.append("parser_degraded")
    if unresolved_header_count > 0:
        critical_flags.append("unresolved_headers")

    if comparable == 0:
        score = 0.0
        mode = "insufficient"
    else:
        score = round((ready + degraded * 0.5) / comparable, 4)
        full_ratio = ready / comparable
        # Never allow full when critical lineage issues exist
        if critical_flags or has_external or has_mixed:
            if score >= 0.4:
                mode = "degraded"
            else:
                mode = "insufficient"
        elif full_ratio >= 0.8 and unresolved_header_count == 0:
            mode = "full"
        elif score >= 0.4:
            mode = "degraded"
        else:
            mode = "insufficient"

    # Invalid combination guard: full + empty usable sources on any ready claim
    if mode == "full" and ready == 0:
        mode = "insufficient"
        score = 0.0

    return {
        "extraction_quality_score": score,
        "comparison_mode": mode,
        "comparable_columns": comparable,
        "ready_columns": ready,
        "degraded_columns": degraded,
        "missing_columns": missing,
        "critical_flags": critical_flags,
        "unresolved_header_count": unresolved_header_count,
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

    if len(sheets) == 0:
        warnings.append("No sheets found in the JSON output.")
        return warnings

    summary_sheets = [s for s in sheets if s.get("sheet_type") == "summary_report"]

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

            formula_based_count = 0
            unresolved_count = 0
            library_resolved_count = 0
            custom_resolved_count = 0

            for col in t.get("columns", []):
                col_name = col.get("column_name", "")
                col_type = col.get("type", "")
                resolved_by = col.get("resolved_by", "")
                lineage = col.get("formula_lineage") or {}
                if isinstance(lineage, dict) and lineage.get("resolved_by"):
                    resolved_by = lineage.get("resolved_by")

                if resolved_by == "formulas_library":
                    library_resolved_count += 1
                elif resolved_by == "custom_parser":
                    custom_resolved_count += 1

                if col_type == "formula_based":
                    formula_based_count += 1
                    if col.get("formula_count", 0) == 0:
                        warnings.append(
                            f"Column '{col_name}' in table '{t_name}' is formula_based but has 0 formula_count."
                        )
                    if is_rationalized:
                        if "formula_lineage" not in col:
                            unresolved_count += 1
                            warnings.append(
                                f"Column '{col_name}' in table '{t_name}' is formula_based but formula_lineage is missing."
                            )
                        else:
                            sources = lineage.get("ultimate_raw_sources") or []
                            if not sources or not any(_source_is_resolved(s) for s in sources):
                                unresolved_count += 1
                                warnings.append(
                                    f"Column '{col_name}' in table '{t_name}' has unresolved/empty ultimate_raw_sources."
                                )
                    else:
                        if not col.get("data_source_columns"):
                            unresolved_count += 1
                            warnings.append(
                                f"Column '{col_name}' in table '{t_name}' is formula_based but raw data source column could not be mapped."
                            )
                elif col_type == "pivot_value":
                    if not is_rationalized:
                        if not col.get("data_source_columns"):
                            warnings.append(
                                f"Column '{col_name}' in table '{t_name}' is pivot_value but source column could not be resolved from pivot cache."
                            )
                if col.get("lineage_is_mixed"):
                    warnings.append(
                        f"Column '{col_name}' in table '{t_name}' has mixed formula variants — lineage is not uniform."
                    )
                if col.get("references_external") or (isinstance(lineage, dict) and lineage.get("references_external")):
                    warnings.append(
                        f"Column '{col_name}' in table '{t_name}' references an external workbook."
                    )

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
    if readiness.get("critical_flags"):
        warnings.append(
            f"Comparison readiness critical flags: {', '.join(readiness['critical_flags'])}."
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
