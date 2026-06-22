"""
Recommender — Phase 3 of the rationalization pipeline.

Deterministic decision matrix → LLM per-action-group justification.
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from src.server.models.database import Database
from src.rationalization.prompts import (
    AMBIGUOUS_PAIR_PROMPT,
    RECOMMENDATION_GROUP_PROMPT,
)

logger = logging.getLogger(__name__)


def _env_float(key: str, default: float) -> float:
    """Read a float from environment with default."""
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


class Recommender:
    """Generates rationalization recommendations using deterministic rules + LLM."""

    def __init__(self, db: Database, llm_caller=None):
        self.db = db
        self.llm_caller = llm_caller

        # Configurable thresholds
        self.decommission_kpi = _env_float("DECOMMISSION_KPI_THRESHOLD", 0.85)
        self.decommission_ds = _env_float("DECOMMISSION_DS_THRESHOLD", 0.85)
        self.decommission_fp = _env_float("DECOMMISSION_FP_THRESHOLD", 0.70)
        self.merge_kpi = _env_float("MERGE_KPI_THRESHOLD", 0.50)
        self.merge_ds = _env_float("MERGE_DS_THRESHOLD", 0.60)
        self.keep_uniqueness = _env_float("KEEP_UNIQUENESS_THRESHOLD", 0.40)
        self.min_extraction_quality = _env_float("MIN_EXTRACTION_QUALITY", 0.60)

    def run(
        self,
        pairwise: Dict[Tuple[int, int], Dict[str, Any]],
        uniqueness: Dict[int, Dict[str, Any]],
        workbook_ids: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate recommendations for all workbooks.

        1. Apply deterministic decision matrix
        2. Send ambiguous pairs to LLM (Phase 2 call)
        3. Generate per-action-group justifications (Phase 3 call)
        4. Write to governance_recommendations table
        """
        if workbook_ids:
            placeholders = ",".join("?" * len(workbook_ids))
            workbooks = self.db.query(
                f"SELECT id, name, purpose, extraction_quality_score, comparison_mode "
                f"FROM workbooks WHERE id IN ({placeholders})",
                tuple(workbook_ids),
            )
        else:
            workbooks = self.db.query(
                "SELECT id, name, purpose, extraction_quality_score, comparison_mode FROM workbooks"
            )
        wb_map = {wb["id"]: wb for wb in workbooks}

        # ── Step 1: Deterministic decisions ──────────────────
        decisions: Dict[int, Dict[str, Any]] = {}

        for wb_id, wb in wb_map.items():
            uni = uniqueness.get(wb_id, {})
            uni_score = uni.get("uniqueness_score", 1.0)
            most_similar_id = uni.get("most_similar_id")
            most_similar_name = uni.get("most_similar_name", "")
            max_kpi = uni.get("max_kpi_overlap", 0.0)
            max_ds = uni.get("max_ds_overlap", 0.0)
            max_fp_ratio = uni.get("max_fingerprint_ratio", 0.0)

            extraction_quality = wb.get("extraction_quality_score")
            if extraction_quality is None:
                extraction_quality = 1.0

            # Get overlap data for the most similar pair
            common_kpis = []
            common_ds = []
            matching_fps = []
            if most_similar_id:
                pair_key = (min(wb_id, most_similar_id), max(wb_id, most_similar_id))
                overlap = pairwise.get(pair_key, {})
                common_kpis = overlap.get("common_kpis", [])
                common_ds = overlap.get("common_datasources", [])
                matching_fps = overlap.get("matching_fingerprints", [])
                max_fp_ratio = overlap.get("fingerprint_ratio", max_fp_ratio)

            # Decision matrix with safety gates
            action = "keep"
            reasons = []

            if extraction_quality < self.min_extraction_quality:
                action = "review"
                reasons.append(
                    f"Extraction quality {extraction_quality:.0%} is below "
                    f"{self.min_extraction_quality:.0%} — manual review required before decommission."
                )
            elif (
                max_kpi >= self.decommission_kpi
                and max_ds >= self.decommission_ds
                and max_fp_ratio >= self.decommission_fp
            ):
                action = "decommission"
                reasons.append(
                    f"High KPI overlap ({max_kpi:.0%}), datasource overlap ({max_ds:.0%}), "
                    f"and fingerprint match ({max_fp_ratio:.0%}) with '{most_similar_name}'."
                )
            elif max_kpi >= self.merge_kpi and max_ds >= self.merge_ds:
                action = "merge"
                reasons.append(
                    f"Moderate KPI overlap ({max_kpi:.0%}) and datasource overlap ({max_ds:.0%}) "
                    f"with '{most_similar_name}' — candidate for consolidation."
                )
            elif uni_score >= self.keep_uniqueness:
                action = "keep"
                reasons.append(
                    f"Uniqueness score of {uni_score:.2f} indicates distinct analysis."
                )
            else:
                action = "keep"
                reasons.append("No strong overlap detected with other workbooks.")

            if matching_fps:
                reasons.append(
                    f"{len(matching_fps)} identical computation fingerprints detected."
                )

            decisions[wb_id] = {
                "workbook_id": wb_id,
                "workbook_name": wb["name"],
                "action": action,
                "merge_with_name": most_similar_name if action in ("merge", "decommission") else None,
                "merge_with_id": most_similar_id if action in ("merge", "decommission") else None,
                "reasons": reasons,
                "common_kpis": common_kpis,
                "common_datasources": common_ds,
                "matching_fingerprints": matching_fps,
                "kpi_overlap_score": max_kpi,
                "datasource_overlap_score": max_ds,
                "uniqueness_score": uni_score,
                "llm_override": False,
                "llm_justification": None,
            }

        # ── Step 2: LLM for ambiguous pairs (required) ───────
        ambiguous_pairs = self._assess_ambiguous_pairs(pairwise, wb_map, decisions)

        # ── Step 3: LLM per-action-group justifications ──────
        if self.llm_caller:
            self._generate_llm_justifications(decisions, wb_map)

        # ── Step 4: Route unresolved ambiguous pairs to review ─
        for (id_a, id_b) in ambiguous_pairs:
            for wb_id in (id_a, id_b):
                if decisions.get(wb_id, {}).get("action") == "keep":
                    decisions[wb_id]["action"] = "review"
                    decisions[wb_id]["reasons"].append(
                        "Ambiguous overlap — LLM assessment inconclusive; manual review required."
                    )

        # ── Step 5: Write to DB ──────────────────────────────
        if workbook_ids:
            placeholders = ",".join("?" * len(workbook_ids))
            self.db.execute(
                f"DELETE FROM governance_recommendations WHERE workbook_id IN ({placeholders})",
                tuple(workbook_ids),
            )
        else:
            self.db.execute("DELETE FROM governance_recommendations")

        for wb_id, decision in decisions.items():
            self.db.insert("governance_recommendations", {
                "workbook_id": wb_id,
                "action": decision["action"],
                "merge_with_name": decision["merge_with_name"],
                "merge_with_id": decision["merge_with_id"],
                "reasons": decision["reasons"],
                "common_kpis": decision["common_kpis"],
                "common_datasources": decision["common_datasources"],
                "matching_fingerprints": decision["matching_fingerprints"],
                "kpi_overlap_score": decision["kpi_overlap_score"],
                "datasource_overlap_score": decision["datasource_overlap_score"],
                "uniqueness_score": decision["uniqueness_score"],
                "llm_override": decision["llm_override"],
                "llm_justification": decision["llm_justification"],
            })

        logger.info(
            "Generated %d recommendations: %d keep, %d merge, %d decommission, %d review",
            len(decisions),
            sum(1 for d in decisions.values() if d["action"] == "keep"),
            sum(1 for d in decisions.values() if d["action"] == "merge"),
            sum(1 for d in decisions.values() if d["action"] == "decommission"),
            sum(1 for d in decisions.values() if d["action"] == "review"),
        )
        return list(decisions.values())

    def _assess_ambiguous_pairs(
        self,
        pairwise: Dict[Tuple[int, int], Dict[str, Any]],
        wb_map: Dict[int, Dict],
        decisions: Dict[int, Dict[str, Any]],
    ) -> List[Tuple[int, int]]:
        """Send ambiguous pairs (combined 0.30-0.85) to LLM. Returns unresolved pairs."""
        unresolved: List[Tuple[int, int]] = []

        for (id_a, id_b), overlap in pairwise.items():
            combined = overlap.get("combined_score")
            if combined is None:
                combined = 0.35 * overlap["kpi_overlap"] + 0.25 * overlap["ds_overlap"]
                fp_total = overlap["fingerprint_total"]
                if fp_total > 0:
                    combined += 0.25 * (overlap["fingerprint_matches"] / fp_total)
                combined += 0.15 * overlap.get("structural_overlap", 0.0)

            if combined < 0.30 or combined > 0.85:
                continue

            wb_a = wb_map.get(id_a, {})
            wb_b = wb_map.get(id_b, {})

            if not self.llm_caller:
                unresolved.append((id_a, id_b))
                continue

            kpis_a = self.db.query("""
                SELECT DISTINCT kc.canonical_name FROM calculated_fields cf
                JOIN kpi_cluster_cache kc ON cf.name = kc.original_name
                WHERE cf.workbook_id = ?
            """, (id_a,))
            kpis_b = self.db.query("""
                SELECT DISTINCT kc.canonical_name FROM calculated_fields cf
                JOIN kpi_cluster_cache kc ON cf.name = kc.original_name
                WHERE cf.workbook_id = ?
            """, (id_b,))

            prompt = AMBIGUOUS_PAIR_PROMPT.format(
                name_a=wb_a.get("name", ""),
                purpose_a=wb_a.get("purpose", "N/A"),
                kpis_a=[r["canonical_name"] for r in kpis_a],
                sources_a=list(overlap.get("common_datasources", [])),
                kpi_score=overlap["kpi_overlap"],
                ds_score=overlap["ds_overlap"],
                name_b=wb_b.get("name", ""),
                purpose_b=wb_b.get("purpose", "N/A"),
                kpis_b=[r["canonical_name"] for r in kpis_b],
                sources_b=list(overlap.get("common_datasources", [])),
            )

            try:
                response = self.llm_caller(prompt)
                if response and isinstance(response, dict):
                    same_work = response.get("same_work", False)
                    confidence = response.get("confidence", 0.0)

                    if same_work and confidence > 0.7:
                        for wb_id in (id_a, id_b):
                            other_id = id_b if wb_id == id_a else id_a
                            if decisions.get(wb_id, {}).get("action") in ("keep", "review"):
                                eq = wb_map.get(wb_id, {}).get("extraction_quality_score") or 1.0
                                if eq >= self.min_extraction_quality:
                                    decisions[wb_id]["action"] = "merge"
                                    decisions[wb_id]["merge_with_id"] = other_id
                                    decisions[wb_id]["merge_with_name"] = wb_map.get(other_id, {}).get("name", "")
                                    decisions[wb_id]["llm_override"] = True
                                    decisions[wb_id]["reasons"].append(
                                        f"LLM assessment: same work (confidence={confidence:.0%}). "
                                        f"{response.get('reasoning', '')}"
                                    )
                        logger.info(
                            "LLM: pair (%s, %s) assessed as same_work=%s (confidence=%.2f)",
                            wb_a.get("name"), wb_b.get("name"), same_work, confidence
                        )
                    else:
                        unresolved.append((id_a, id_b))
                else:
                    unresolved.append((id_a, id_b))
            except Exception as e:
                logger.warning("LLM ambiguous pair assessment failed: %s", e)
                unresolved.append((id_a, id_b))

        return unresolved

    def _generate_llm_justifications(
        self,
        decisions: Dict[int, Dict[str, Any]],
        wb_map: Dict[int, Dict],
    ) -> None:
        """Generate LLM justifications per action group."""
        # Group by action
        groups: Dict[str, List[int]] = {}
        for wb_id, decision in decisions.items():
            action = decision["action"]
            groups.setdefault(action, []).append(wb_id)

        for action_group, wb_ids in groups.items():
            # Build context for this group
            context_lines = []
            for i, wb_id in enumerate(wb_ids, 1):
                dec = decisions[wb_id]
                wb = wb_map.get(wb_id, {})
                ctx = f"""  {i}. "{wb.get('name', '')}"
     Purpose: {wb.get('purpose', 'N/A')}
     KPIs: {dec.get('common_kpis', [])}
     Uniqueness: {dec.get('uniqueness_score', 0):.2f}
     KPI Overlap: {dec.get('kpi_overlap_score', 0):.0%}
     Datasource Overlap: {dec.get('datasource_overlap_score', 0):.0%}"""
                if dec.get("merge_with_name"):
                    ctx += f"\n     Merge with: \"{dec['merge_with_name']}\""
                context_lines.append(ctx)

            prompt = RECOMMENDATION_GROUP_PROMPT.format(
                action_group=action_group,
                workbooks_context="\n\n".join(context_lines),
            )

            try:
                response = self.llm_caller(prompt)
                if response and isinstance(response, list):
                    for item in response:
                        wb_name = item.get("workbook_name", "")
                        # Find matching workbook
                        for wb_id in wb_ids:
                            if wb_map.get(wb_id, {}).get("name") == wb_name:
                                decisions[wb_id]["llm_justification"] = item.get("justification", "")

                                # Handle LLM override
                                final_action = item.get("final_action", action_group)
                                if final_action != action_group and item.get("override_reason"):
                                    decisions[wb_id]["action"] = final_action
                                    decisions[wb_id]["llm_override"] = True
                                    decisions[wb_id]["reasons"].append(
                                        f"LLM override: {item['override_reason']}"
                                    )

                                # Update AI fields in dashboards
                                ai_summary = item.get("ai_summary", "")
                                domain = item.get("domain_classification", "")
                                lob = item.get("line_of_business", "")

                                if ai_summary or domain or lob:
                                    dashboards = self.db.query(
                                        "SELECT id FROM dashboards WHERE workbook_id = ? AND sheet_type = 'summary_report'",
                                        (wb_id,)
                                    )
                                    for dash in dashboards:
                                        self.db.update("dashboards", {
                                            "ai_summary": ai_summary,
                                            "domain_classification": domain,
                                            "line_of_business": lob,
                                            "is_real_ai": True,
                                        }, "id = ?", (dash["id"],))

                                break

                    logger.info(
                        "LLM justifications generated for %s group (%d workbooks)",
                        action_group, len(wb_ids)
                    )
            except Exception as e:
                logger.warning(
                    "LLM justification failed for %s group: %s",
                    action_group, e
                )
