"""
Rationalization Audit Logger
============================
Provides structured governance audit logging for rationalization decisions.

Stores every decision in the `rationalization_audit` database table for queryability
and exports an evidence-based human-readable `rationalization_audit.log` file.
"""
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.server.models.database import Database

logger = logging.getLogger(__name__)


def record_rationalization_audit(
    db: Database,
    audit_entries: List[Dict[str, Any]],
    run_id: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> str:
    """
    Record rationalization audit entries into the database and write the
    human-readable rationalization_audit.log file.

    Returns the path to the written log file.
    """
    if not output_dir:
        output_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "data", "output")
        )
    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(output_dir, "rationalization_audit.log")

    now_iso = datetime.now().isoformat()
    log_blocks = []

    for entry in audit_entries:
        wb_id = entry.get("workbook_id")
        wb_name = entry.get("workbook_name") or f"Workbook {wb_id}"
        cluster_name = entry.get("cluster_name") or "N/A"
        cluster_id = entry.get("cluster_id")
        canonical_id = entry.get("canonical_target_id")
        canonical_name = entry.get("canonical_target_name") or (f"Workbook {canonical_id}" if canonical_id else "None")
        role = entry.get("cluster_role", "review")
        action = entry.get("action", "review")
        decomm_after_merge = entry.get("decommission_after_merge", False)
        
        kpi_cont = entry.get("kpi_containment", 0.0)
        ds_cont = entry.get("ds_containment", 0.0)
        ds_ov = entry.get("ds_overlap", 0.0)
        candidate_col_ov = entry.get("candidate_column_overlap", 0.0)
        quality = entry.get("extraction_quality", 0.0)
        comp_mode = entry.get("comparison_mode", "insufficient")
        
        gates = entry.get("safety_gates_summary", {})
        evidence = entry.get("evidence", {})
        reasons = entry.get("reasons", [])

        # 1. Insert into database table
        try:
            db.insert("rationalization_audit", {
                "rationalization_run_id": run_id,
                "cluster_id": cluster_id,
                "cluster_name": cluster_name,
                "workbook_id": wb_id,
                "workbook_name": wb_name,
                "canonical_target_id": canonical_id,
                "canonical_target_name": canonical_name,
                "cluster_role": role,
                "action": action,
                "decommission_after_merge": 1 if decomm_after_merge else 0,
                "kpi_containment": round(kpi_cont, 4),
                "ds_containment": round(ds_cont, 4),
                "ds_overlap": round(ds_ov, 4),
                "candidate_column_overlap": round(candidate_col_ov, 4),
                "extraction_quality": round(quality, 4) if quality is not None else None,
                "comparison_mode": comp_mode,
                "safety_gates_summary": json.dumps(gates),
                "evidence": json.dumps(evidence),
                "reasons": json.dumps(reasons),
            })
        except Exception as e:
            logger.warning("Failed to insert rationalization audit record for WB %s: %s", wb_id, e)

        # 2. Build human-readable audit block
        block = _format_audit_block(now_iso, entry)
        log_blocks.append(block)

    if log_blocks:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n".join(log_blocks) + "\n")
            logger.info("Rationalization audit log written: %s (%d records)", log_path, len(log_blocks))
        except Exception as e:
            logger.warning("Could not write rationalization audit log file: %s", e)

    return log_path


def _format_audit_block(timestamp: str, entry: Dict[str, Any]) -> str:
    """Format a single audit entry into an explainable evidence block."""
    wb_id = entry.get("workbook_id")
    wb_name = entry.get("workbook_name", str(wb_id))
    cluster_name = entry.get("cluster_name", "N/A")
    canonical_id = entry.get("canonical_target_id")
    canonical_name = entry.get("canonical_target_name", str(canonical_id) if canonical_id else "None")
    role = entry.get("cluster_role", "review")
    action = entry.get("action", "review")
    decomm_after_merge = entry.get("decommission_after_merge", False)

    kpi_cont = entry.get("kpi_containment", 0.0)
    ds_cont = entry.get("ds_containment", 0.0)
    ds_ov = entry.get("ds_overlap", 0.0)
    candidate_col_ov = entry.get("candidate_column_overlap", 0.0)
    quality = entry.get("extraction_quality", 0.0)
    comp_mode = entry.get("comparison_mode", "insufficient")
    reasons = entry.get("reasons", [])
    gates = entry.get("safety_gates_summary", {})
    evidence = entry.get("evidence", {})

    lines = [
        "================================================================================",
        f"RATIONALIZATION DECISION AUDIT — {timestamp}",
        f"Workbook: \"{wb_name}\" (ID={wb_id})",
        f"Cluster : \"{cluster_name}\" | Role: {role.upper()} | Action: {action.upper()}" + (" (decommission_after_merge)" if decomm_after_merge else ""),
        f"Canonical Target: \"{canonical_name}\" (ID={canonical_id})" if canonical_id != wb_id else "Canonical Target: Self (retained canonical)",
        "--------------------------------------------------------------------------------",
        "EVIDENCE SUMMARY:",
        f"  • Datasource Exact Overlap    : {ds_ov:.1%}",
        f"  • Datasource Containment (→Target): {ds_cont:.1%}",
        f"  • Candidate Column Overlap    : {candidate_col_ov:.1%} (advisory only — not used in gates)",
        f"  • KPI Containment in Cluster  : {kpi_cont:.1%}",
        f"  • Extraction Quality Score    : {quality:.1%}" if quality is not None else "  • Extraction Quality Score    : None (forced review)",
        f"  • Comparison Readiness Mode   : {comp_mode}",
    ]

    if evidence:
        unique_kpis = evidence.get("unique_kpis", [])
        common_kpis = evidence.get("common_kpis", [])
        fp_matches = evidence.get("fingerprint_matches", 0)
        fp_total = evidence.get("fingerprint_total", 0)
        lines.append(f"  • Formula Fingerprint Matches : {fp_matches}/{fp_total}")
        if unique_kpis:
            lines.append(f"  • Unique KPIs in Cluster      : {len(unique_kpis)} ({', '.join(unique_kpis[:5])})")
        if common_kpis:
            lines.append(f"  • Shared KPIs with Target     : {len(common_kpis)} ({', '.join(common_kpis[:5])})")

    lines.append("\nSAFETY GATES:")
    for gate_name, passed in gates.items():
        icon = "✅ PASS" if passed else "❌ FAIL"
        lines.append(f"  • {gate_name:<32}: {icon}")

    lines.append("\nGOVERNANCE REASONS:")
    for r in reasons:
        lines.append(f"  → {r}")

    lines.append("================================================================================\n")
    return "\n".join(lines)
