"""
Rationalization Engine — Main orchestrator for the pipeline.

Phase 0: Risk detection + Complexity scoring
Phase 1: KPI Canonicalization (lexical + LLM)
Phase 2: Overlap Scoring (5-signal: KPI + DS + FP + Structural + Semantic)
Phase 3: Cluster Formation (graph edges + bridge guard + connected components)
Phase 4: LLM Stage 1 — Cluster Membership Validation
Phase 5: Intra-Cluster Role Assignment
Phase 6: LLM Stage 2 — Per-Workbook Justification
Phase 7: Write governance_recommendations (cluster-aware)
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from src.server.models.database import Database
from src.rationalization.kpi_canonicalizer import run_kpi_canonicalization
from src.rationalization.overlap_scorer import (
    compute_pairwise_overlaps,
    compute_uniqueness_scores,
)
from src.rationalization.complexity_scorer import compute_complexity_scores
from src.rationalization.recommender import Recommender
from src.rationalization.risk_detector import detect_workbook_risks
from src.rationalization.prompts import (
    INTELLIGENCE_METADATA_PROMPT,
    CLUSTER_VALIDATION_PROMPT,
    CLUSTER_JUSTIFICATION_PROMPT,
)
from src.rationalization.cluster_builder import build_clusters
from src.rationalization.cluster_recommender import run_cluster_recommendations

logger = logging.getLogger(__name__)


def _parse_user_groups(val) -> List[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(g).strip() for g in val if str(g).strip()]
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return [str(g).strip() for g in parsed if str(g).strip()]
        except (json.JSONDecodeError, TypeError):
            pass
        return [s.strip() for s in val.split(",") if s.strip()]
    return []


class LLMCaller:
    """Wraps llm_client with retry logic for rationalization."""

    def __init__(self):
        self.max_retries = int(os.getenv("LLM_RETRY_COUNT", "3"))
        self.retry_interval = int(os.getenv("LLM_RETRY_INTERVAL_SECONDS", "60"))
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            try:
                from src.utils.llm_client import get_resilient_llm
                self._llm = get_resilient_llm(temperature=0.3, json_mode=True)
            except Exception as e:
                logger.warning("Could not initialize LLM: %s", e)
        return self._llm

    def __call__(self, prompt: str) -> Optional[Any]:
        llm = self._get_llm()
        if llm is None:
            logger.warning("No LLM available — returning None")
            return None

        for attempt in range(self.max_retries):
            try:
                response = llm.invoke(prompt)
                from src.utils.llm_client import stringify_chat_content
                text = stringify_chat_content(response.content).strip()
                if text.startswith("```json"):
                    text = text[7:]
                elif text.startswith("```"):
                    text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
                return json.loads(text)
            except Exception as e:
                if attempt < self.max_retries - 1:
                    logger.warning(
                        "LLM call failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1, self.max_retries, self.retry_interval, e
                    )
                    time.sleep(self.retry_interval)
                else:
                    logger.error("LLM call failed after %d attempts: %s", self.max_retries, e)
                    return None


class RationalizationEngine:
    """Main orchestrator for the rationalization pipeline."""

    def __init__(self, db: Database, use_llm: bool = True):
        self.db = db
        self.use_llm = use_llm
        self._llm_caller = LLMCaller() if use_llm else None

    def _workbook_count(self, workbook_ids: Optional[List[int]] = None) -> int:
        if workbook_ids:
            placeholders = ",".join("?" * len(workbook_ids))
            row = self.db.query_one(
                f"SELECT COUNT(*) as cnt FROM workbooks WHERE id IN ({placeholders})",
                tuple(workbook_ids),
            )
        else:
            row = self.db.query_one("SELECT COUNT(*) as cnt FROM workbooks")
        return row["cnt"] if row else 0

    def _set_phase(self, phase: str) -> None:
        """Update the most recent scan record's phase field (for UI polling)."""
        try:
            row = self.db.query_one("SELECT id FROM scans ORDER BY id DESC LIMIT 1")
            if row:
                self.db.update("scans", {"phase": phase}, "id = ?", (row["id"],))
        except Exception:
            pass  # Non-critical

    def _clear_cluster_data(self) -> None:
        """Atomically clear all cluster + recommendation data before re-run."""
        conn = self.db._get_connection()
        with self.db._write_lock:
            try:
                conn.execute("DELETE FROM governance_recommendations")
                conn.execute("DELETE FROM workbook_cluster_members")
                conn.execute("DELETE FROM workbook_clusters")
                # pairwise_overlap_cache is NOT cleared — it's hash-keyed and persists across runs
                conn.commit()
                logger.info("Cleared cluster + recommendation data for fresh re-run")
            except Exception:
                conn.rollback()
                raise

    def run_intelligence(self, workbook_ids: Optional[List[int]] = None) -> dict:
        """
        BI Intelligence agent — complexity scoring + KPI canonicalization.
        """
        count = self._workbook_count(workbook_ids)
        if count == 0:
            logger.info("No workbooks in scope — skipping intelligence")
            return {"status": "skipped", "reason": "no workbooks", "agent": "intelligence"}

        logger.info("Starting Intelligence pipeline (%d workbook(s))", count)
        summary = {
            "status": "completed",
            "agent": "intelligence",
            "workbooks": count,
            "workbook_ids": workbook_ids,
        }

        logger.info("── Complexity Scoring ──")
        try:
            scores = compute_complexity_scores(self.db)
            summary["complexity_scores"] = len(scores)
        except Exception as e:
            logger.exception("Complexity scoring failed: %s", e)
            summary["complexity_error"] = str(e)

        logger.info("── KPI Canonicalization ──")
        try:
            clusters = run_kpi_canonicalization(
                self.db, self._llm_caller, workbook_ids=workbook_ids
            )
            summary["kpi_clusters"] = len(clusters)
        except Exception as e:
            logger.exception("KPI canonicalization failed: %s", e)
            summary["kpi_error"] = str(e)

        logger.info("── Dashboard Metadata Enrichment ──")
        try:
            enriched = self._enrich_dashboard_metadata(workbook_ids=workbook_ids)
            summary["dashboard_metadata_enriched"] = enriched
        except Exception as e:
            logger.exception("Dashboard metadata enrichment failed: %s", e)
            summary["metadata_error"] = str(e)

        return summary

    def _enrich_dashboard_metadata(self, workbook_ids: Optional[List[int]] = None) -> int:
        """Populate LOB, domain, and user_groups on summary dashboards via LLM."""
        if not self._llm_caller:
            return 0

        if workbook_ids:
            placeholders = ",".join("?" * len(workbook_ids))
            workbooks = self.db.query(
                f"SELECT id, name, purpose FROM workbooks WHERE id IN ({placeholders})",
                tuple(workbook_ids),
            )
        else:
            workbooks = self.db.query("SELECT id, name, purpose FROM workbooks")

        updated = 0
        for wb in workbooks:
            dashboards = self.db.query(
                "SELECT id, name, sheet_type, line_of_business, domain_classification, user_groups "
                "FROM dashboards WHERE workbook_id = ?",
                (wb["id"],),
            )
            summary_dashes = [
                d for d in dashboards
                if d.get("sheet_type") == "summary_report"
                and (
                    not (d.get("line_of_business") or d.get("domain_classification"))
                    or not _parse_user_groups(d.get("user_groups"))
                )
            ]
            if not summary_dashes:
                continue

            kpi_rows = self.db.query(
                "SELECT DISTINCT name FROM calculated_fields WHERE workbook_id = ? LIMIT 15",
                (wb["id"],),
            )
            kpis = [r["name"] for r in kpi_rows]
            sheet_names = [d["name"] for d in dashboards]

            prompt = INTELLIGENCE_METADATA_PROMPT.format(
                workbook_name=wb.get("name", ""),
                purpose=wb.get("purpose") or "N/A",
                sheet_names=", ".join(sheet_names) or "N/A",
                kpis=", ".join(kpis) or "N/A",
            )

            try:
                response = self._llm_caller(prompt)
            except Exception as e:
                logger.warning("Metadata LLM failed for workbook %s: %s", wb["id"], e)
                continue

            if not response or not isinstance(response, dict):
                continue

            domain = response.get("domain_classification", "")
            lob = response.get("line_of_business", "")
            user_groups = response.get("user_groups") or []
            ai_summary = response.get("ai_summary", "")

            if not (domain or lob or user_groups or ai_summary):
                continue

            for dash in summary_dashes:
                patch = {"is_real_ai": True}
                if ai_summary:
                    patch["ai_summary"] = ai_summary
                if domain:
                    patch["domain_classification"] = domain
                if lob:
                    patch["line_of_business"] = lob
                if user_groups:
                    patch["user_groups"] = user_groups
                self.db.update("dashboards", patch, "id = ?", (dash["id"],))
            updated += 1

        return updated

    def run_rationalization(self, workbook_ids: Optional[List[int]] = None) -> dict:
        """
        BI Rationalization agent — Phases 0–7.
        """
        count = self._workbook_count(workbook_ids)
        if count == 0:
            logger.info("No workbooks in scope — skipping rationalization")
            return {"status": "skipped", "reason": "no workbooks", "agent": "rationalization"}

        logger.info("Starting Rationalization pipeline (%d workbook(s))", count)
        summary: Dict[str, Any] = {
            "status": "completed",
            "agent": "rationalization",
            "workbooks": count,
            "workbook_ids": workbook_ids,
        }

        # ── Atomic truncation before re-run ───────────────────
        self._clear_cluster_data()

        # ── Phase 0: Risk Detection ───────────────────────────
        self._set_phase("risk_detection")
        logger.info("── Phase 0: Risk Detection ──")
        try:
            risks = detect_workbook_risks(self.db, workbook_ids)
            summary["risks_detected"] = len(risks)
        except Exception as e:
            logger.exception("Risk detection failed: %s", e)
            summary["risk_error"] = str(e)

        if count == 1:
            logger.info("Only 1 workbook — singleton cluster, 'keep' recommendation")
            wb = (self.db.query_one(
                "SELECT id, name FROM workbooks WHERE id = ?", (workbook_ids[0],)
            ) if workbook_ids else self.db.query_one("SELECT id, name FROM workbooks"))
            if wb:
                cluster_id = self.db.insert("workbook_clusters", {
                    "cluster_name": wb["name"],
                    "cluster_size": 1,
                    "cohesion_score": 1.0,
                    "canonical_target_id": wb["id"],
                    "cluster_action_summary": "Keep (unique)",
                })
                self.db.insert("workbook_cluster_members", {
                    "cluster_id": cluster_id, "workbook_id": wb["id"]
                })
                self.db.insert("governance_recommendations", {
                    "workbook_id": wb["id"],
                    "action": "keep",
                    "cluster_id": cluster_id,
                    "cluster_role": "keep",
                    "canonical_target_id": wb["id"],
                    "reasons": json.dumps(["Only workbook in portfolio — no redundancy possible."]),
                    "uniqueness_score": 1.0,
                    "kpi_overlap_score": 0.0,
                    "datasource_overlap_score": 0.0,
                })
            summary["recommendations"] = 1
            self._set_phase("completed")
            return summary

        # ── Phase 2: Overlap Scoring ──────────────────────────
        self._set_phase("overlap_scoring")
        logger.info("── Phase 2: Overlap Scoring (5-signal + cache) ──")
        pairwise: Dict[Tuple[int, int], Dict[str, Any]] = {}
        uniqueness: Dict[int, float] = {}
        try:
            pairwise = compute_pairwise_overlaps(self.db, workbook_ids=workbook_ids)
            summary["pairwise_comparisons"] = len(pairwise)
            alpha = float(os.getenv("OVERLAP_WEIGHT_KPI", "0.35"))
            beta = float(os.getenv("OVERLAP_WEIGHT_DS", "0.25"))
            gamma = float(os.getenv("OVERLAP_WEIGHT_FINGERPRINT", "0.25"))
            delta = float(os.getenv("OVERLAP_WEIGHT_STRUCTURAL", "0.15"))
            uniqueness = compute_uniqueness_scores(
                self.db, pairwise, alpha, beta, gamma, delta, workbook_ids=workbook_ids,
            )
            summary["uniqueness_scores"] = len(uniqueness)
        except Exception as e:
            logger.exception("Overlap scoring failed: %s", e)
            summary["overlap_error"] = str(e)

        # ── Phase 3: Cluster Formation ─────────────────────────
        self._set_phase("cluster_formation")
        logger.info("── Phase 3: Cluster Formation ──")
        clusters: List[Dict[str, Any]] = []
        try:
            clusters = build_clusters(
                self.db, pairwise, workbook_ids=workbook_ids
            )
            summary["clusters_formed"] = len(clusters)
            summary["singleton_clusters"] = sum(1 for c in clusters if c["cluster_size"] == 1)
        except Exception as e:
            logger.exception("Cluster formation failed: %s", e)
            summary["cluster_error"] = str(e)

        # ── Phase 4: LLM Stage 1 — Cluster Validation ─────────
        self._set_phase("llm_cluster_validation")
        logger.info("── Phase 4: LLM Stage 1 — Cluster Validation ──")
        if self.use_llm and self._llm_caller:
            try:
                clusters = self._run_llm_stage1(clusters, pairwise)
            except Exception as e:
                logger.exception("LLM Stage 1 failed: %s", e)
                summary["llm_stage1_error"] = str(e)
        else:
            logger.info("LLM disabled — skipping Stage 1")

        # ── Phase 5: Role Assignment ───────────────────────────
        self._set_phase("role_assignment")
        logger.info("── Phase 5: Intra-Cluster Role Assignment ──")
        decisions: List[Dict[str, Any]] = []
        try:
            decisions = run_cluster_recommendations(
                self.db, clusters, pairwise, workbook_ids=workbook_ids
            )
            summary["role_assignments"] = len(decisions)
        except Exception as e:
            logger.exception("Role assignment failed: %s", e)
            summary["role_error"] = str(e)

        # ── Phase 6: LLM Stage 2 — Per-Workbook Justification ──
        self._set_phase("llm_justification")
        logger.info("── Phase 6: LLM Stage 2 — Per-Workbook Justification ──")
        if self.use_llm and self._llm_caller:
            try:
                decisions = self._run_llm_stage2(clusters, decisions, pairwise)
            except Exception as e:
                logger.exception("LLM Stage 2 failed: %s", e)
                summary["llm_stage2_error"] = str(e)
        else:
            logger.info("LLM disabled — skipping Stage 2")

        # ── Phase 7: Write governance_recommendations ──────────
        self._set_phase("writing_recommendations")
        logger.info("── Phase 7: Writing Recommendations ──")
        try:
            self._write_recommendations(decisions, clusters, pairwise, uniqueness, workbook_ids)
            summary["recommendations"] = len(decisions)
            summary["actions"] = {
                "keep": sum(1 for d in decisions if d["action"] == "keep"),
                "merge": sum(1 for d in decisions if d["action"] == "merge"),
                "decommission": sum(1 for d in decisions if d["action"] == "decommission"),
                "review": sum(1 for d in decisions if d["action"] == "review"),
            }
        except Exception as e:
            logger.exception("Writing recommendations failed: %s", e)
            summary["write_error"] = str(e)

        self._set_phase("completed")
        return summary

    # ─── LLM Stage 1: Cluster Membership Validation ──────────────────

    def _run_llm_stage1(
        self,
        clusters: List[Dict[str, Any]],
        pairwise: Dict[Tuple[int, int], Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        from src.rationalization.semantic_similarity import check_semantic_data_available
        semantic_available = check_semantic_data_available(self.db)

        for cluster in clusters:
            if cluster["cluster_size"] < 2:
                continue

            member_ids = cluster["member_ids"]
            members_info = []
            for wb_id in member_ids:
                wb = self.db.query_one(
                    "SELECT name, purpose FROM workbooks WHERE id = ?", (wb_id,)
                ) or {}
                kpis = [r["canonical_name"] for r in self.db.query(
                    """
                    SELECT DISTINCT kc.canonical_name
                    FROM calculated_fields cf
                    JOIN kpi_cluster_cache kc ON cf.name = kc.original_name
                    WHERE cf.workbook_id = ? LIMIT 20
                    """, (wb_id,)
                )]
                ds = [r["name"] for r in self.db.query(
                    "SELECT DISTINCT name FROM datasources WHERE workbook_id = ? LIMIT 10",
                    (wb_id,)
                )]
                lob_row = self.db.query_one(
                    "SELECT line_of_business, domain_classification FROM dashboards "
                    "WHERE workbook_id = ? AND sheet_type='summary_report' AND is_real_ai=1 LIMIT 1",
                    (wb_id,)
                ) or {}
                members_info.append({
                    "workbook_name": wb.get("name", str(wb_id)),
                    "purpose": wb.get("purpose") or "N/A",
                    "lob": lob_row.get("line_of_business") or "unknown",
                    "domain": lob_row.get("domain_classification") or "unknown",
                    "canonical_kpis": kpis,
                    "datasources": ds,
                })

            edge_scores = {}
            for i in range(len(member_ids)):
                for j in range(i + 1, len(member_ids)):
                    a, b = member_ids[i], member_ids[j]
                    key = (min(a, b), max(a, b))
                    score = pairwise.get(key, {}).get("cluster_edge_score", 0.0)
                    name_a = (members_info[i]["workbook_name"])[:20]
                    name_b = (members_info[j]["workbook_name"])[:20]
                    edge_scores[f"{name_a}↔{name_b}"] = round(score, 3)

            prompt = CLUSTER_VALIDATION_PROMPT.format(
                cluster_name=cluster["cluster_name"],
                cohesion_score=cluster["cohesion_score"],
                semantic_data_available=str(semantic_available).lower(),
                members=json.dumps(members_info, indent=2),
                pairwise_edge_scores=json.dumps(edge_scores, indent=2),
            )

            result = self._llm_caller(prompt)
            if result and isinstance(result, dict):
                cluster["llm_stage1_reasoning"] = result.get("reasoning", "")
                suspect_edges = result.get("suspect_edges", [])
                cluster["suspect_edges"] = json.dumps(suspect_edges)
                if not result.get("cluster_coherent", True):
                    cluster["cluster_validation_flag"] = "llm_suspect"
                # Persist Stage 1 result
                if cluster.get("id"):
                    self.db.update(
                        "workbook_clusters",
                        {
                            "llm_stage1_reasoning": cluster["llm_stage1_reasoning"],
                            "suspect_edges": cluster["suspect_edges"],
                            "cluster_validation_flag": cluster.get("cluster_validation_flag"),
                            "llm_validation_skipped": 0,
                        },
                        "id = ?",
                        (cluster["id"],),
                    )
            else:
                cluster["llm_validation_skipped"] = 1
                if cluster.get("id"):
                    self.db.update(
                        "workbook_clusters",
                        {"llm_validation_skipped": 1},
                        "id = ?",
                        (cluster["id"],),
                    )

        return clusters

    # ─── LLM Stage 2: Per-Workbook Justification ──────────────────────

    def _run_llm_stage2(
        self,
        clusters: List[Dict[str, Any]],
        decisions: List[Dict[str, Any]],
        pairwise: Dict[Tuple[int, int], Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        # Index decisions by workbook_id
        dec_map: Dict[int, Dict[str, Any]] = {d["workbook_id"]: d for d in decisions}

        for cluster in clusters:
            member_ids = cluster.get("member_ids", [])
            if not member_ids:
                continue

            cluster_decisions = [dec_map[mid] for mid in member_ids if mid in dec_map]
            members_context = []
            for d in cluster_decisions:
                wb_id = d["workbook_id"]
                wb = self.db.query_one("SELECT name, purpose FROM workbooks WHERE id = ?", (wb_id,)) or {}
                members_context.append({
                    "workbook_name": wb.get("name", str(wb_id)),
                    "purpose": wb.get("purpose") or "N/A",
                    "cluster_role": d["cluster_role"],
                    "unique_kpis": d.get("unique_kpis_in_cluster", [])[:10],
                })

            prompt = CLUSTER_JUSTIFICATION_PROMPT.format(
                cluster_name=cluster["cluster_name"],
                cohesion_score=cluster["cohesion_score"],
                stage1_reasoning=cluster.get("llm_stage1_reasoning") or "N/A",
                members=json.dumps(members_context, indent=2),
            )

            results = self._llm_caller(prompt)
            if results and isinstance(results, list):
                name_to_id: Dict[str, int] = {}
                for d in cluster_decisions:
                    wb = self.db.query_one("SELECT name FROM workbooks WHERE id = ?", (d["workbook_id"],))
                    if wb:
                        name_to_id[wb["name"]] = d["workbook_id"]

                for item in results:
                    wb_name = item.get("workbook_name", "")
                    wb_id = name_to_id.get(wb_name)
                    if wb_id and wb_id in dec_map:
                        d = dec_map[wb_id]
                        final_action = item.get("final_action", d["action"])
                        # Enforce override gating
                        if d["cluster_role"] == "canonical_target":
                            final_action = d["action"]  # cannot override
                        d["action"] = final_action
                        d["llm_justification"] = item.get("justification", "")
                        d["llm_override"] = (final_action != d["action"])
                        d["ai_summary"] = item.get("ai_summary", "")
                        d["domain_classification"] = item.get("domain_classification", "")
                        d["line_of_business"] = item.get("line_of_business", "")
                        d["user_groups"] = item.get("user_groups", [])

        return list(dec_map.values())

    # ─── Phase 7: Write governance_recommendations ────────────────────

    def _write_recommendations(
        self,
        decisions: List[Dict[str, Any]],
        clusters: List[Dict[str, Any]],
        pairwise: Dict[Tuple[int, int], Dict[str, Any]],
        uniqueness: Dict[int, float],
        workbook_ids: Optional[List[int]],
    ) -> None:
        # Build cluster_id lookup from workbook_id
        cluster_id_map: Dict[int, int] = {}
        for cluster in clusters:
            for wb_id in cluster.get("member_ids", []):
                cluster_id_map[wb_id] = cluster["id"]

        for d in decisions:
            wb_id = d["workbook_id"]
            cluster_id = cluster_id_map.get(wb_id)
            canonical_id = d.get("canonical_target_id")

            # Resolve merge_with_name (canonical target name)
            merge_with_name: Optional[str] = None
            merge_with_id: Optional[int] = None
            if d["action"] in ("merge", "decommission") and canonical_id and canonical_id != wb_id:
                cw = self.db.query_one("SELECT name FROM workbooks WHERE id = ?", (canonical_id,))
                if cw:
                    merge_with_name = cw["name"]
                    merge_with_id = canonical_id

            # Pairwise score to canonical target
            kpi_overlap_score = 0.0
            ds_overlap_score = 0.0
            if canonical_id and canonical_id != wb_id:
                key = (min(wb_id, canonical_id), max(wb_id, canonical_id))
                pw = pairwise.get(key, {})
                kpi_overlap_score = pw.get("kpi_overlap", 0.0)
                ds_overlap_score = pw.get("ds_overlap", 0.0)

            # Common KPIs / DS / fingerprints from pairwise
            common_kpis: List[str] = []
            common_ds: List[str] = []
            matching_fps: List[str] = []
            if canonical_id and canonical_id != wb_id:
                key = (min(wb_id, canonical_id), max(wb_id, canonical_id))
                pw = pairwise.get(key, {})
                common_kpis = pw.get("common_kpis", [])
                common_ds = pw.get("common_datasources", [])
                matching_fps = pw.get("matching_fingerprints", [])

            from src.rationalization.overlap_scorer import _get_raw_sources_for_workbook
            raw_sources = _get_raw_sources_for_workbook(self.db, wb_id)
            ds_sources_count = len(raw_sources)
            ds_shared_count = len(common_ds)

            self.db.insert("governance_recommendations", {
                "workbook_id": wb_id,
                "action": d["action"],
                "merge_with_name": merge_with_name,
                "merge_with_id": merge_with_id,
                "cluster_id": cluster_id,
                "cluster_role": d.get("cluster_role"),
                "merge_partners": json.dumps(d.get("merge_partners", [])),
                "canonical_target_id": canonical_id,
                "decommission_after_merge": 1 if d.get("decommission_after_merge") else 0,
                "kpi_overlap_score": round(kpi_overlap_score, 4),
                "datasource_overlap_score": round(ds_overlap_score, 4),
                "uniqueness_score": round(uniqueness.get(wb_id, {}).get("uniqueness_score", 1.0), 4),
                "ds_sources_count": ds_sources_count,
                "ds_shared_count": ds_shared_count,
                "common_kpis": json.dumps(common_kpis),
                "common_datasources": json.dumps(common_ds),
                "matching_fingerprints": json.dumps(matching_fps),
                "reasons": json.dumps(d.get("reasons", [])),
                "llm_justification": d.get("llm_justification"),
                "llm_override": 1 if d.get("llm_override") else 0,
            })

            # Update cluster action summary
            if cluster_id:
                actions = self.db.query(
                    """
                    SELECT action, COUNT(*) as cnt
                    FROM governance_recommendations WHERE cluster_id = ?
                    GROUP BY action
                    """,
                    (cluster_id,),
                )
                parts = [f"{r['cnt']} {r['action']}" for r in actions]
                summary_str = " · ".join(parts)
                self.db.update(
                    "workbook_clusters",
                    {"cluster_action_summary": summary_str},
                    "id = ?",
                    (cluster_id,),
                )

    def run(self, workbook_ids: Optional[List[int]] = None) -> dict:
        """
        Run the full pipeline (intelligence + rationalization).

        If workbook_ids is provided, only compares and recommends within that subset.
        """
        logger.info("═" * 60)
        logger.info("Starting Full Pipeline (scope=%s)",
                    f"{len(workbook_ids)} workbooks" if workbook_ids else "all")
        logger.info("═" * 60)

        count = self._workbook_count(workbook_ids)
        if count == 0:
            logger.info("No workbooks in scope — skipping pipeline")
            return {"status": "skipped", "reason": "no workbooks"}

        summary = {"status": "completed", "workbooks": count, "workbook_ids": workbook_ids}
        intel = self.run_intelligence(workbook_ids)
        for key, value in intel.items():
            if key not in ("status", "agent"):
                summary[key] = value
        rat = self.run_rationalization(workbook_ids)
        for key, value in rat.items():
            if key not in ("status", "agent"):
                summary[key] = value

        logger.info("═" * 60)
        logger.info("Full Pipeline Complete")
        logger.info("Summary: %s", json.dumps(summary, indent=2))
        logger.info("═" * 60)

        return summary

    def _delete_scoped_recommendations(self, workbook_ids: List[int]) -> None:
        placeholders = ",".join("?" * len(workbook_ids))
        self.db.execute(
            f"DELETE FROM governance_recommendations WHERE workbook_id IN ({placeholders})",
            tuple(workbook_ids),
        )
