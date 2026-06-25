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


def _orient_unique_kpis(
    overlap: Dict[str, Any],
    wb_id: int,
    partner_id: int,
) -> Tuple[List[str], List[str]]:
    """Return (unique_to_wb, unique_to_partner) from a pairwise overlap record."""
    pair_a, pair_b = min(wb_id, partner_id), max(wb_id, partner_id)
    unique_a = overlap.get("unique_kpis_a", [])
    unique_b = overlap.get("unique_kpis_b", [])
    if wb_id == pair_a:
        return list(unique_a), list(unique_b)
    return list(unique_b), list(unique_a)


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
                f"SELECT id, name, purpose, extraction_quality_score, comparison_mode, "
                f"extraction_complexity FROM workbooks WHERE id IN ({placeholders})",
                tuple(workbook_ids),
            )
        else:
            workbooks = self.db.query(
                "SELECT id, name, purpose, extraction_quality_score, comparison_mode, "
                "extraction_complexity FROM workbooks"
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
            best_pair_common_kpis = []
            common_ds = []
            matching_fps = []
            if most_similar_id:
                pair_key = (min(wb_id, most_similar_id), max(wb_id, most_similar_id))
                overlap = pairwise.get(pair_key, {})
                best_pair_common_kpis = overlap.get("common_kpis", [])
                common_ds = overlap.get("common_datasources", [])
                matching_fps = overlap.get("matching_fingerprints", [])
                max_fp_ratio = overlap.get("fingerprint_ratio", max_fp_ratio)

            # Aggregate common_kpis from ALL pairwise entries involving this workbook
            all_common_kpis = set(best_pair_common_kpis)
            for (id_a, id_b), pair_overlap in pairwise.items():
                if id_a == wb_id or id_b == wb_id:
                    for kpi in pair_overlap.get("common_kpis", []):
                        all_common_kpis.add(kpi)
            common_kpis = sorted(all_common_kpis)

            # Decision matrix with safety gates
            action = "keep"
            reasons = []
            canonical_keeper = False

            unique_self: List[str] = []
            unique_partner: List[str] = []
            if most_similar_id and overlap:
                unique_self, unique_partner = _orient_unique_kpis(
                    overlap, wb_id, most_similar_id
                )

            has_common = len(best_pair_common_kpis) > 0
            self_is_kpi_subset = (
                has_common and len(unique_self) == 0 and len(unique_partner) > 0
            )
            partner_is_kpi_subset = (
                has_common and len(unique_partner) == 0 and len(unique_self) > 0
            )
            both_have_extras = len(unique_self) > 0 and len(unique_partner) > 0
            kpi_sets_identical = (
                has_common and len(unique_self) == 0 and len(unique_partner) == 0
            )

            if extraction_quality < self.min_extraction_quality:
                action = "review"
                reasons.append(
                    f"Extraction quality {extraction_quality:.0%} is below "
                    f"{self.min_extraction_quality:.0%} — manual review required before decommission."
                )
            elif self_is_kpi_subset and max_ds >= self.merge_ds:
                action = "decommission"
                reasons.append(
                    f"All {len(best_pair_common_kpis)} KPIs in this workbook are already "
                    f"present in '{most_similar_name}' "
                    f"({len(unique_partner)} additional KPIs only in retain target)."
                )
            elif partner_is_kpi_subset:
                action = "keep"
                canonical_keeper = True
                reasons.append(
                    f"Superset of '{most_similar_name}' — covers all of its KPIs plus "
                    f"{len(unique_self)} additional KPIs only in this workbook."
                )
            elif kpi_sets_identical and max_ds >= self.merge_ds:
                action = "decommission"
                reasons.append(
                    f"Identical KPI set to '{most_similar_name}' — duplicate report."
                )
            elif (
                max_kpi >= self.decommission_kpi
                and max_ds >= self.decommission_ds
                and max_fp_ratio >= self.decommission_fp
            ):
                action = "decommission"
                reasons.append(
                    f"High KPI overlap ({max_kpi:.0%}) and datasource overlap ({max_ds:.0%}) "
                    f"with '{most_similar_name}'."
                )
            elif (
                both_have_extras
                and max_kpi >= self.merge_kpi
                and max_ds >= self.merge_ds
            ):
                action = "merge"
                overlap_label = "High" if max_kpi >= 0.80 and max_ds >= 0.80 else "Moderate"
                reasons.append(
                    f"{overlap_label} KPI overlap ({max_kpi:.0%}) and datasource overlap ({max_ds:.0%}) "
                    f"with '{most_similar_name}' — both workbooks add unique KPIs; "
                    f"candidate for consolidation."
                )
            elif uni_score >= self.keep_uniqueness:
                action = "keep"
                reasons.append(
                    f"Uniqueness score of {uni_score:.2f} indicates distinct analysis."
                )
            else:
                action = "keep"
                reasons.append("No strong overlap detected with other workbooks.")

            decisions[wb_id] = {
                "workbook_id": wb_id,
                "workbook_name": wb["name"],
                "action": action,
                "merge_with_name": (
                    most_similar_name
                    if action in ("merge", "decommission")
                    else None
                ),
                "merge_with_id": (
                    most_similar_id
                    if action in ("merge", "decommission")
                    else None
                ),
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
            if canonical_keeper:
                decisions[wb_id]["_canonical_keeper"] = True

        # ── Step 1b: Resolve symmetric decommission conflicts ─
        self._resolve_decommission_conflicts(decisions, wb_map)

        # ── Step 2: LLM for ambiguous pairs (required) ───────
        ambiguous_pairs = self._assess_ambiguous_pairs(pairwise, wb_map, decisions)

        # ── Step 3: LLM per-action-group justifications ──────
        if self.llm_caller:
            self._generate_llm_justifications(decisions, wb_map)

        # ── Step 3b: Reconcile after LLM (overrides must not break pairs) ─
        self._resolve_decommission_conflicts(decisions, wb_map)
        self._normalize_decommission_rows(decisions, wb_map)

        # ── Step 3c: Make merge recommendations symmetric ────
        self._normalize_merge_pairs(decisions, wb_map)

        # ── Step 4: Route unresolved ambiguous pairs to review ─
        for (id_a, id_b) in ambiguous_pairs:
            for wb_id, partner_id in ((id_a, id_b), (id_b, id_a)):
                if not self._should_route_ambiguous_to_review(
                    wb_id, partner_id, decisions, pairwise
                ):
                    continue
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

    def _resolve_decommission_conflicts(
        self,
        decisions: Dict[int, Dict[str, Any]],
        wb_map: Dict[int, Dict],
    ) -> None:
        """When two workbooks both decommission pointing at each other, keep one."""
        seen_pairs: set = set()

        for wb_id, decision in list(decisions.items()):
            if decision.get("action") != "decommission":
                continue

            other_id = decision.get("merge_with_id")
            if not other_id:
                continue

            pair_key = (min(wb_id, other_id), max(wb_id, other_id))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            other_decision = decisions.get(other_id)
            if (
                not other_decision
                or other_decision.get("action") != "decommission"
                or other_decision.get("merge_with_id") != wb_id
            ):
                continue

            def _keeper_score(wid: int) -> tuple:
                dec = decisions[wid]
                wb = wb_map.get(wid, {})
                complexity = wb.get("extraction_complexity")
                if complexity is None:
                    complexity = 999.0
                return (
                    dec.get("uniqueness_score", 0.0),
                    -complexity,
                    -wid,
                )

            keeper_id = wb_id if _keeper_score(wb_id) >= _keeper_score(other_id) else other_id
            decom_id = other_id if keeper_id == wb_id else wb_id
            keeper_name = wb_map.get(keeper_id, {}).get("name", "")
            decom_name = wb_map.get(decom_id, {}).get("name", "")

            decisions[keeper_id]["action"] = "keep"
            decisions[keeper_id]["merge_with_name"] = None
            decisions[keeper_id]["merge_with_id"] = None
            decisions[keeper_id]["_canonical_keeper"] = True
            decisions[keeper_id]["reasons"] = [
                f"Retained as canonical workbook over '{decom_name}'."
            ]

            decisions[decom_id]["action"] = "decommission"
            decisions[decom_id]["merge_with_name"] = keeper_name
            decisions[decom_id]["merge_with_id"] = keeper_id
            decisions[decom_id]["reasons"] = [
                r for r in decisions[decom_id].get("reasons", [])
                if "fingerprint" not in r.lower()
                and "retained workbook" not in r.lower()
            ]

    def _normalize_decommission_rows(
        self,
        decisions: Dict[int, Dict[str, Any]],
        wb_map: Dict[int, Dict],
    ) -> None:
        """Ensure retain targets are keep, and every decommission has a merge target."""
        retain_target_ids = {
            d["merge_with_id"]
            for d in decisions.values()
            if d.get("action") == "decommission" and d.get("merge_with_id")
        }

        for target_id in retain_target_ids:
            target = decisions.get(target_id)
            if not target or target.get("action") != "decommission":
                continue

            decom_names = [
                decisions[wid]["workbook_name"]
                for wid, dec in decisions.items()
                if dec.get("action") == "decommission" and dec.get("merge_with_id") == target_id
            ]
            target["action"] = "keep"
            target["merge_with_name"] = None
            target["merge_with_id"] = None
            target["_canonical_keeper"] = True
            target["reasons"] = [
                f"Retained as canonical workbook over {', '.join(repr(n) for n in decom_names)}."
            ]

        for wb_id, decision in decisions.items():
            if decision.get("action") != "decommission":
                continue
            if decision.get("merge_with_id"):
                continue
            decision["action"] = "review"
            decision["reasons"].append(
                "Decommission requires a retain target — manual review required."
            )

    def _normalize_merge_pairs(
        self,
        decisions: Dict[int, Dict[str, Any]],
        wb_map: Dict[int, Dict],
    ) -> None:
        """
        Ensure merge recommendations are symmetric.

        The Jaccard overlap score is symmetric, so if A qualifies to merge
        with B, B qualifies to merge with A. However, B might independently
        have chosen a different most-similar partner C and be marked 'keep'.

        For every A→merge with B where B says 'keep':
          - Update B to 'merge' pointing back at A, using the same overlap
            scores that triggered A's merge decision.

        For every A→merge with B where B says 'merge with C' (chain case):
          - Leave the chain as-is. The user sees both sides and can resolve.

        Never override canonical-keeper or decommission decisions.
        """
        for wb_id, decision in list(decisions.items()):
            if decision.get("action") != "merge":
                continue
            partner_id = decision.get("merge_with_id")
            if not partner_id:
                continue
            partner = decisions.get(partner_id)
            if not partner:
                continue
            # Never touch canonical keepers or decommission targets
            if partner.get("_canonical_keeper") or partner.get("action") == "decommission":
                continue
            # Only mirror when partner says keep — chains (B→C) are left alone
            if partner.get("action") != "keep":
                continue

            partner["action"] = "merge"
            partner["merge_with_id"] = wb_id
            partner["merge_with_name"] = wb_map.get(wb_id, {}).get("name", "")
            partner["reasons"].append(
                f"Identified as consolidation candidate with '{decision['workbook_name']}' "
                f"(KPI overlap: {decision.get('kpi_overlap_score', 0):.0%}, "
                f"datasource overlap: {decision.get('datasource_overlap_score', 0):.0%})."
            )
            logger.info(
                "Merge pair normalized: '%s' ↔ '%s'",
                decision["workbook_name"],
                partner.get("workbook_name", ""),
            )

    def _should_route_ambiguous_to_review(
        self,
        wb_id: int,
        partner_id: int,
        decisions: Dict[int, Dict[str, Any]],
        pairwise: Dict[Tuple[int, int], Dict[str, Any]],
    ) -> bool:
        """Decide whether an unresolved ambiguous pair should flip keep → review."""
        decision = decisions.get(wb_id)
        if not decision or decision.get("action") != "keep":
            return False

        if decision.get("_canonical_keeper"):
            return False

        pair_key = (min(wb_id, partner_id), max(wb_id, partner_id))
        overlap = pairwise.get(pair_key, {})
        ds_overlap = overlap.get("ds_overlap", 0.0)
        uni_score = decision.get("uniqueness_score", 0.0)

        # Similar KPIs but different datasources with reasonable uniqueness → stay keep.
        if ds_overlap < self.merge_ds and uni_score >= self.keep_uniqueness:
            return False

        return True

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
                        # Require minimum overlap scores even for LLM same_work verdicts —
                        # the ambiguous-pair combined score gate (0.30–0.85) lets through
                        # pairs with very low KPI/DS scores if structural overlap is high.
                        kpi_score = overlap.get("kpi_overlap", 0.0)
                        ds_score = overlap.get("ds_overlap", 0.0)
                        scores_support_merge = (
                            kpi_score >= self.merge_kpi and ds_score >= self.merge_ds
                        )
                        for wb_id in (id_a, id_b):
                            if decisions.get(wb_id, {}).get("_canonical_keeper"):
                                continue
                            other_id = id_b if wb_id == id_a else id_a
                            if decisions.get(wb_id, {}).get("action") in ("keep", "review"):
                                eq = wb_map.get(wb_id, {}).get("extraction_quality_score") or 1.0
                                if eq >= self.min_extraction_quality and scores_support_merge:
                                    decisions[wb_id]["action"] = "merge"
                                    decisions[wb_id]["merge_with_id"] = other_id
                                    decisions[wb_id]["merge_with_name"] = wb_map.get(other_id, {}).get("name", "")
                                    decisions[wb_id]["llm_override"] = True
                                    decisions[wb_id]["reasons"].append(
                                        f"LLM assessment: same work (confidence={confidence:.0%}). "
                                        f"{response.get('reasoning', '')}"
                                    )
                                elif not scores_support_merge:
                                    logger.info(
                                        "LLM same_work verdict rejected for '%s'/'%s': "
                                        "KPI=%.2f DS=%.2f below merge thresholds",
                                        wb_a.get("name"), wb_b.get("name"), kpi_score, ds_score,
                                    )
                                    unresolved.append((id_a, id_b))
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

                                # Handle LLM override (never undo canonical retain decisions)
                                final_action = item.get("final_action", action_group)
                                if final_action != action_group and item.get("override_reason"):
                                    if decisions[wb_id].get("_canonical_keeper"):
                                        decisions[wb_id]["reasons"].append(
                                            f"LLM suggested {final_action} (not applied — canonical retain): "
                                            f"{item['override_reason']}"
                                        )
                                    elif final_action == "merge" and action_group in ("keep", "review"):
                                        # Gate: LLM can only override keep/review → merge if the
                                        # overlap scores actually meet merge criteria. Without this
                                        # guard the LLM hallucinates merges for completely distinct
                                        # workbooks (e.g. 4% KPI, 0% DS → incorrectly "merge").
                                        kpi_ok = decisions[wb_id].get("kpi_overlap_score", 0.0) >= self.merge_kpi
                                        ds_ok = decisions[wb_id].get("datasource_overlap_score", 0.0) >= self.merge_ds
                                        if kpi_ok and ds_ok:
                                            decisions[wb_id]["action"] = final_action
                                            decisions[wb_id]["llm_override"] = True
                                            decisions[wb_id]["reasons"].append(
                                                f"LLM override: {item['override_reason']}"
                                            )
                                        else:
                                            decisions[wb_id]["reasons"].append(
                                                f"LLM suggested merge (not applied — scores too low: "
                                                f"KPI={decisions[wb_id].get('kpi_overlap_score', 0):.0%}, "
                                                f"DS={decisions[wb_id].get('datasource_overlap_score', 0):.0%}): "
                                                f"{item['override_reason']}"
                                            )
                                            logger.info(
                                                "LLM merge override rejected for '%s': KPI=%.2f DS=%.2f "
                                                "(thresholds: KPI>=%.2f, DS>=%.2f)",
                                                wb_map.get(wb_id, {}).get("name", ""),
                                                decisions[wb_id].get("kpi_overlap_score", 0.0),
                                                decisions[wb_id].get("datasource_overlap_score", 0.0),
                                                self.merge_kpi, self.merge_ds,
                                            )
                                    else:
                                        decisions[wb_id]["action"] = final_action
                                        decisions[wb_id]["llm_override"] = True
                                        decisions[wb_id]["reasons"].append(
                                            f"LLM override: {item['override_reason']}"
                                        )

                                # Update AI fields in dashboards
                                ai_summary = item.get("ai_summary", "")
                                domain = item.get("domain_classification", "")
                                lob = item.get("line_of_business", "")
                                user_groups = item.get("user_groups") or []

                                if ai_summary or domain or lob or user_groups:
                                    dashboards = self.db.query(
                                        "SELECT id FROM dashboards WHERE workbook_id = ? AND sheet_type = 'summary_report'",
                                        (wb_id,)
                                    )
                                    for dash in dashboards:
                                        patch = {
                                            "ai_summary": ai_summary,
                                            "domain_classification": domain,
                                            "line_of_business": lob,
                                            "is_real_ai": True,
                                        }
                                        if user_groups:
                                            patch["user_groups"] = user_groups
                                        self.db.update("dashboards", patch, "id = ?", (dash["id"],))

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
