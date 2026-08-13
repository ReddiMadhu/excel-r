"""
Hardcoded override / formula inconsistency detection inside formula regions.

Never labels a constant as definite error — emits review findings with evidence.
"""
from __future__ import annotations

from typing import Any, Dict, List

from src.review.pattern_normalizer import is_constant_nonblank
from src.review.region_detector import FormulaRegion


def _confidence_from_evidence(
    neighbor_agree: int,
    region_size: int,
) -> tuple:
    """
    Discrete confidence bands derived from evidence — not fake precision.
    Returns (band, score) where band in low|medium|high.
    """
    if neighbor_agree >= 3 and region_size >= 4:
        return "high", 0.85
    if neighbor_agree >= 2 and region_size >= 3:
        return "medium", 0.7
    if neighbor_agree >= 1:
        return "low", 0.45
    return "low", 0.3


def detect_overrides_in_region(region: FormulaRegion) -> List[Dict[str, Any]]:
    """
    Find cells that break the dominant formula pattern in a region.

    - Constant in an otherwise consistent formula run → HARDCODED_OVERRIDE
    - Different formula pattern among consistent neighbors → FORMULA_INCONSISTENCY
    """
    findings: List[Dict[str, Any]] = []
    dominant = region.dominant_pattern
    if not dominant or dominant == "__CONSTANT__":
        return findings

    matching = [c for c in region.cells if c.pattern_key == dominant]
    if len(matching) < 2:
        return findings

    example = matching[0]
    expected = example.formula or dominant

    for cell in region.cells:
        if cell.pattern_key == dominant:
            continue

        evidence = [
            f"Region on {region.sheet} ({region.axis}={region.fixed_index}, "
            f"{region.start}:{region.end}) has dominant pattern shared by "
            f"{len(matching)} cell(s).",
        ]
        for nb in matching[:4]:
            evidence.append(f"{nb.address} = {nb.formula}")

        if cell.formula is None and is_constant_nonblank(cell.value):
            band, score = _confidence_from_evidence(len(matching), len(region.cells))
            findings.append({
                "finding_type": "HARDCODED_OVERRIDE",
                "sheet": cell.sheet,
                "cell": cell.address,
                "severity": "MEDIUM" if band != "high" else "HIGH",
                "confidence": band,
                "confidence_score": score,
                "actual": str(cell.value),
                "expected_pattern": expected,
                "evidence": evidence + [
                    f"{cell.address} contains a constant instead of a formula.",
                    "Possible intentional override, manual adjustment, or accidental formula replacement.",
                ],
                "dependencies": [],
                "dependents": [],
                "signals": {
                    "neighbor_agree": len(matching),
                    "region_size": len(region.cells),
                    "region_axis": region.axis,
                    "interpretation": "potential_intentional_or_accidental_override",
                },
            })
        elif cell.formula and cell.pattern_key and cell.pattern_key != dominant:
            band, score = _confidence_from_evidence(len(matching), len(region.cells))
            findings.append({
                "finding_type": "FORMULA_INCONSISTENCY",
                "sheet": cell.sheet,
                "cell": cell.address,
                "severity": "HIGH" if band == "high" else "MEDIUM",
                "confidence": band,
                "confidence_score": score,
                "actual": cell.formula,
                "expected_pattern": expected,
                "evidence": evidence + [
                    f"{cell.address} uses a different structural pattern: {cell.pattern_key}",
                ],
                "dependencies": [],
                "dependents": [],
                "signals": {
                    "neighbor_agree": len(matching),
                    "region_size": len(region.cells),
                    "region_axis": region.axis,
                    "actual_pattern": cell.pattern_key,
                    "expected_pattern_key": dominant,
                },
            })
    return findings


def detect_all_overrides(regions: List[FormulaRegion]) -> List[Dict[str, Any]]:
    """Run override detection across all regions; dedupe by (sheet, cell, type)."""
    seen = set()
    out: List[Dict[str, Any]] = []
    for region in regions:
        for finding in detect_overrides_in_region(region):
            key = (finding["sheet"], finding["cell"], finding["finding_type"])
            if key in seen:
                continue
            seen.add(key)
            out.append(finding)
    return out
