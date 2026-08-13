"""
Reference / unsupported-feature auditor for Excel Review findings.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from src.review.pattern_normalizer import (
    _ERROR_TOKENS,
    detect_unsupported_features,
    is_formula,
)
from src.review.region_detector import CellInfo

_NAMED_TOKEN = re.compile(r"(?<![A-Za-z0-9_'!\$])([A-Za-z_][A-Za-z0-9_\.]*)(?!\s*\()")
_EXCEL_BUILTINS = {
    "TRUE", "FALSE", "NULL", "IF", "IFERROR", "IFNA", "ISERROR", "ISNA",
    "SUM", "SUMIF", "SUMIFS", "COUNT", "COUNTIF", "COUNTIFS", "AVERAGE",
    "AVERAGEIF", "AVERAGEIFS", "MIN", "MAX", "ABS", "ROUND", "ROUNDUP",
    "ROUNDDOWN", "INT", "MOD", "POWER", "SQRT", "AND", "OR", "NOT",
    "VLOOKUP", "HLOOKUP", "INDEX", "MATCH", "XLOOKUP", "XMATCH",
    "LEFT", "RIGHT", "MID", "LEN", "TRIM", "UPPER", "LOWER", "TEXT",
    "VALUE", "DATE", "YEAR", "MONTH", "DAY", "TODAY", "NOW",
    "INDIRECT", "OFFSET", "CHOOSE", "IFNA", "NA", "N", "T",
    "SUMPRODUCT", "PRODUCT", "DIVIDE", "LET", "LAMBDA", "FILTER",
}


def audit_cell(
    cell: CellInfo,
    defined_names: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Produce findings for broken refs, external deps, unsupported constructs."""
    findings: List[Dict[str, Any]] = []
    formula = cell.formula
    if not formula:
        # Cached error values without formula (e.g. #REF! left as value)
        if cell.value is not None:
            s = str(cell.value).upper()
            for err in _ERROR_TOKENS:
                if err in s:
                    findings.append({
                        "finding_type": "BROKEN_REF",
                        "sheet": cell.sheet,
                        "cell": cell.address,
                        "severity": "HIGH",
                        "confidence": "high",
                        "confidence_score": 0.95,
                        "actual": str(cell.value),
                        "expected_pattern": None,
                        "evidence": [f"Cell value is Excel error {err}."],
                        "dependencies": [],
                        "dependents": [],
                        "signals": {"error_type": err},
                    })
                    break
        return findings

    unsupported = list(cell.unsupported) or detect_unsupported_features(formula)
    fu = formula.upper()

    for err in _ERROR_TOKENS:
        if err in fu or err in str(cell.value or "").upper():
            findings.append({
                "finding_type": "BROKEN_REF",
                "sheet": cell.sheet,
                "cell": cell.address,
                "severity": "HIGH",
                "confidence": "high",
                "confidence_score": 0.98,
                "actual": formula,
                "expected_pattern": None,
                "evidence": [
                    f"Formula contains Excel error token {err}.",
                    "Impact: dependents of this cell may also fail.",
                ],
                "dependencies": [],
                "dependents": [],
                "signals": {"error_type": err},
            })

    if "external_workbook_ref" in unsupported:
        findings.append({
            "finding_type": "EXTERNAL_DEPENDENCY",
            "sheet": cell.sheet,
            "cell": cell.address,
            "severity": "MEDIUM",
            "confidence": "high",
            "confidence_score": 0.9,
            "actual": formula,
            "expected_pattern": None,
            "evidence": [
                "Formula references an external workbook.",
                "Breaking or relocating the external file will break this cell.",
            ],
            "dependencies": [],
            "dependents": [],
            "signals": {"feature": "external_workbook_ref"},
        })

    struct_or_func = [
        t for t in unsupported
        if t.startswith("structured_table_ref") or t.startswith("unsupported_func")
    ]
    if struct_or_func:
        findings.append({
            "finding_type": "UNSUPPORTED_FEATURE",
            "sheet": cell.sheet,
            "cell": cell.address,
            "severity": "LOW",
            "confidence": "high",
            "confidence_score": 0.9,
            "actual": formula,
            "expected_pattern": None,
            "evidence": [
                "Formula uses Excel features not fully supported by the extractor.",
                f"Tags: {', '.join(struct_or_func)}",
                "Do not interpret absence of other findings as 'safe'.",
            ],
            "dependencies": [],
            "dependents": [],
            "signals": {
                "unsupported_tags": struct_or_func,
                "status": "unsupported_feature",
            },
        })

    # Named ranges: identifiers that are not builtins / A1 refs
    if defined_names is not None:
        tokens = _NAMED_TOKEN.findall(formula)
        for tok in tokens:
            if tok.upper() in _EXCEL_BUILTINS:
                continue
            if re.fullmatch(r"[A-Za-z]+\d+", tok):
                continue  # A1-looking
            if tok not in defined_names and tok.upper() not in {n.upper() for n in defined_names}:
                # Could be sheet name or table name — only flag if it looks like a name use
                # and defined_names is non-empty (workbook has names but this isn't one)
                if defined_names and tok[0].isalpha():
                    # Soft: unresolved name only if workbook defines other names
                    pass
            elif tok in defined_names or tok.upper() in {n.upper() for n in defined_names}:
                # Resolved named range — informational only, no finding
                pass

        # Unresolved: token not a builtin, not A1, not in defined_names, and not STRUCT_REF
        for tok in tokens:
            up = tok.upper()
            if up in _EXCEL_BUILTINS:
                continue
            if re.fullmatch(r"[A-Za-z]{1,3}\d{1,7}", tok):
                continue
            if defined_names and tok not in defined_names and up not in {n.upper() for n in defined_names}:
                # Only emit if formula has no cell refs and looks name-driven, or token
                # appears as a bare name operand (heuristic: surrounded by operators)
                if re.search(rf"(?<![A-Za-z0-9_]){re.escape(tok)}(?![A-Za-z0-9_\(])", formula):
                    # Skip common sheet-like tokens already handled by A1 with !
                    if f"{tok}!" in formula or f"'{tok}'!" in formula:
                        continue
                    findings.append({
                        "finding_type": "UNSUPPORTED_FEATURE",
                        "sheet": cell.sheet,
                        "cell": cell.address,
                        "severity": "LOW",
                        "confidence": "medium",
                        "confidence_score": 0.55,
                        "actual": formula,
                        "expected_pattern": None,
                        "evidence": [
                            f"Token '{tok}' looks like a named range but is not in workbook defined names.",
                            "Treated as unsupported / unresolved — confidence reduced.",
                        ],
                        "dependencies": [],
                        "dependents": [],
                        "signals": {
                            "unresolved_name": tok,
                            "status": "unsupported_feature",
                        },
                    })
                    break

    return findings


def audit_all_cells(
    cells: List[CellInfo],
    defined_names: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for cell in cells:
        for finding in audit_cell(cell, defined_names=defined_names):
            key = (finding["sheet"], finding["cell"], finding["finding_type"], finding.get("actual"))
            if key in seen:
                continue
            seen.add(key)
            out.append(finding)
    return out
