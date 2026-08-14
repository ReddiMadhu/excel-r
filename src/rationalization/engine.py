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

# Pipeline execution statuses — never report "completed" after a mandatory-phase failure.
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_COMPLETED_WITH_WARNINGS = "completed_with_warnings"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

# Mandatory when workbook count >= 2. LLM stages are optional (warnings only).
MANDATORY_PHASES_MULTI = ("overlap_scoring", "cluster_formation", "role_assignment", "writing_recommendations")
OPTIONAL_PHASES = ("risk_detection", "llm_cluster_validation", "llm_justification")


def _finalize_pipeline_status(summary: Dict[str, Any], mandatory_failed: List[str], warnings: List[str]) -> Dict[str, Any]:
    """Derive honest terminal status from phase outcomes."""
    summary["phase_errors"] = list(summary.get("phase_errors") or [])
    summary["warnings"] = list(warnings)
    if mandatory_failed:
        summary["mandatory_failures"] = mandatory_failed
        # Partial write happened if we have some recommendations but a later mandatory phase failed
        if summary.get("recommendations") and "writing_recommendations" not in mandatory_failed:
            summary["status"] = STATUS_PARTIAL
        elif "writing_recommendations" in mandatory_failed and summary.get("role_assignments"):
            summary["status"] = STATUS_PARTIAL
        else:
            summary["status"] = STATUS_FAILED
    elif warnings:
        summary["status"] = STATUS_COMPLETED_WITH_WARNINGS
    else:
        summary["status"] = STATUS_COMPLETED
    return summary


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

        Terminal status is never blindly "completed":
          completed | completed_with_warnings | partial | failed | skipped
        Mandatory phases (count>=2): overlap, cluster, role assignment, write.
        LLM stages are optional — failure becomes a warning only.
        """
        count = self._workbook_count(workbook_ids)
        if count == 0:
            logger.info("No workbooks in scope — skipping rationalization")
            return {"status": STATUS_SKIPPED, "reason": "no workbooks", "agent": "rationalization"}

        logger.info("Starting Rationalization pipeline (%d workbook(s))", count)
        summary: Dict[str, Any] = {
            "status": STATUS_RUNNING,
            "agent": "rationalization",
            "workbooks": count,
            "workbook_ids": workbook_ids,
            "phase_errors": [],
            "warnings": [],
        }
        mandatory_failed: List[str] = []
        warnings: List[str] = []

        def _record_error(phase: str, exc: Exception, *, mandatory: bool) -> None:
            msg = f"{phase}: {exc}"
            summary["phase_errors"].append({"phase": phase, "error": str(exc), "mandatory": mandatory})
            legacy_key = {
                "risk_detection": "risk_error",
                "overlap_scoring": "overlap_error",
                "cluster_formation": "cluster_error",
                "llm_cluster_validation": "llm_stage1_error",
                "role_assignment": "role_error",
                "llm_justification": "llm_stage2_error",
                "writing_recommendations": "write_error",
            }.get(phase)
            if legacy_key:
                summary[legacy_key] = str(exc)
            if mandatory:
                mandatory_failed.append(phase)
            else:
                warnings.append(msg)

        # ── Atomic truncation before re-run ───────────────────
        self._clear_cluster_data()

        # ── Phase 0: Risk Detection (optional — warning on failure) ──
        self._set_phase("risk_detection")
        logger.info("── Phase 0: Risk Detection ──")
        try:
            risks = detect_workbook_risks(self.db, workbook_ids)
            summary["risks_detected"] = len(risks)
        except Exception as e:
            logger.exception("Risk detection failed: %s", e)
            _record_error("risk_detection", e, mandatory=False)

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
                    "reasons": json.dumps([
                        "Only workbook in portfolio — no redundancy possible. "
                        "Excel Review (cell/formula inspection) is a separate pipeline."
                    ]),
                    "uniqueness_score": 1.0,
                    "kpi_overlap_score": 0.0,
                    "datasource_overlap_score": 0.0,
                })
            summary["recommendations"] = 1
            summary["actions"] = {"keep": 1, "merge": 0, "decommission": 0, "review": 0}
            _finalize_pipeline_status(summary, mandatory_failed, warnings)
            self._set_phase(summary["status"])
            return summary

        # ── Phase 2: Overlap Scoring (mandatory) ──────────────
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
            _record_error("overlap_scoring", e, mandatory=True)

        # Stop early if overlap failed — empty pairwise would produce false "keep" for all
        if "overlap_scoring" in mandatory_failed:
            _finalize_pipeline_status(summary, mandatory_failed, warnings)
            self._set_phase(summary["status"])
            return summary

        # ── Phase 3: Cluster Formation (mandatory) ─────────────
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
            _record_error("cluster_formation", e, mandatory=True)

        if "cluster_formation" in mandatory_failed:
            _finalize_pipeline_status(summary, mandatory_failed, warnings)
            self._set_phase(summary["status"])
            return summary

        # ── Phase 4: LLM Stage 1 — Cluster Validation (optional) ─
        self._set_phase("llm_cluster_validation")
        logger.info("── Phase 4: LLM Stage 1 — Cluster Validation ──")
        if self.use_llm and self._llm_caller:
            try:
                clusters = self._run_llm_stage1(clusters, pairwise)
            except Exception as e:
                logger.exception("LLM Stage 1 failed: %s", e)
                _record_error("llm_cluster_validation", e, mandatory=False)
        else:
            logger.info("LLM disabled — skipping Stage 1")
            warnings.append("llm_cluster_validation: LLM disabled — skipped")

        # ── Phase 5: Role Assignment (mandatory) ───────────────
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
            _record_error("role_assignment", e, mandatory=True)

        if "role_assignment" in mandatory_failed:
            _finalize_pipeline_status(summary, mandatory_failed, warnings)
            self._set_phase(summary["status"])
            return summary

        # ── Phase 6: LLM Stage 2 — Justification only (optional) ──
        self._set_phase("llm_justification")
        logger.info("── Phase 6: LLM Stage 2 — Per-Workbook Justification ──")
        if self.use_llm and self._llm_caller:
            try:
                decisions = self._run_llm_stage2(clusters, decisions, pairwise)
            except Exception as e:
                logger.exception("LLM Stage 2 failed: %s", e)
                _record_error("llm_justification", e, mandatory=False)
        else:
            logger.info("LLM disabled — skipping Stage 2")
            warnings.append("llm_justification: LLM disabled — skipped")

        # ── Phase 7: Write governance_recommendations (mandatory) ──
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
            _record_error("writing_recommendations", e, mandatory=True)

        _finalize_pipeline_status(summary, mandatory_failed, warnings)
        self._set_phase(summary["status"])

        # Write diagnostic log on every rationalization run
        self._write_diagnostic_log(summary)

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
                        # LLM may JUSTIFY only — never change deterministic action.
                        # Ignoring final_action prevents inventing governance decisions.
                        suggested = item.get("final_action")
                        if suggested and suggested != d["action"]:
                            logger.info(
                                "LLM suggested final_action=%s for %s but deterministic "
                                "action=%s is preserved (no ungated override)",
                                suggested, wb_name, d["action"],
                            )
                        d["llm_justification"] = item.get("justification", "")
                        d["llm_override"] = False
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
            raw_sources, _ds_mode = _get_raw_sources_for_workbook(self.db, wb_id)
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

        # Write diagnostic log for full traceability
        self._write_diagnostic_log(summary)

        return summary

    def _write_diagnostic_log(self, pipeline_summary: Dict[str, Any]) -> None:
        """
        Write a comprehensive diagnostic log file to data/output/.

        Captures per-workbook extraction quality, KPI state, and
        rationalization decision reasoning for full root-cause traceability.
        """
        import os
        from datetime import datetime

        try:
            output_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "data", "output",
            )
            os.makedirs(output_dir, exist_ok=True)
            log_path = os.path.join(output_dir, "rationalization_diagnostic.log")

            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"{'=' * 80}\n")
                f.write(f"RATIONALIZATION DIAGNOSTIC LOG\n")
                f.write(f"Generated: {datetime.utcnow().isoformat()}\n")
                f.write(f"Pipeline Status: {pipeline_summary.get('status', 'unknown')}\n")
                f.write(f"{'=' * 80}\n\n")

                # ── Section 1: Workbook Extraction Quality ──
                workbooks = self.db.query(
                    "SELECT id, name, extraction_quality_score, comparison_mode, "
                    "extraction_complexity, sheet_count FROM workbooks ORDER BY id"
                )
                f.write(f"{'─' * 60}\n")
                f.write(f"SECTION 1: WORKBOOK EXTRACTION QUALITY\n")
                f.write(f"{'─' * 60}\n\n")

                for wb in workbooks:
                    quality = wb.get("extraction_quality_score")
                    mode = wb.get("comparison_mode", "N/A")
                    cf_row = self.db.query_one(
                        "SELECT COUNT(*) as cnt FROM calculated_fields WHERE workbook_id = ?",
                        (wb["id"],),
                    )
                    cf_count = cf_row["cnt"] if cf_row else 0
                    kpi_row = self.db.query_one(
                        """
                        SELECT COUNT(DISTINCT kc.canonical_name) as cnt
                        FROM calculated_fields cf
                        JOIN kpi_cluster_cache kc ON cf.name = kc.original_name COLLATE NOCASE
                        WHERE cf.workbook_id = ?
                          AND cf.column_type IN ('formula_based','pivot_value','total')
                        """,
                        (wb["id"],),
                    )
                    kpi_count = kpi_row["cnt"] if kpi_row else 0

                    quality_str = f"{quality:.2%}" if quality is not None else "MISSING"
                    flag = "⚠" if (quality is not None and quality < 0.6) or mode == "insufficient" else "✓"
                    f.write(
                        f"  {flag} [{wb['id']}] {wb['name']}\n"
                        f"    extraction_quality_score = {quality_str}\n"
                        f"    comparison_mode          = {mode}\n"
                        f"    sheets                   = {wb.get('sheet_count', 0)}\n"
                        f"    calculated_fields        = {cf_count}\n"
                        f"    canonical_kpis           = {kpi_count}\n"
                    )
                    if (quality is not None and quality < 0.6) or mode == "insufficient" or mode == "degraded":
                        f.write(
                            f"    → REVIEW/DEGRADATION DIAGNOSTICS:\n"
                        )
                        # Check json_output_path first for rich column_diagnostics
                        wb_detail = self.db.query_one("SELECT json_output_path FROM workbooks WHERE id = ?", (wb["id"],))
                        jpath = wb_detail.get("json_output_path") if wb_detail else None
                        printed_from_json = False
                        if jpath and os.path.exists(jpath):
                            try:
                                with open(jpath, "r", encoding="utf-8") as jf:
                                    jdata = json.load(jf)
                                read_meta = jdata.get("comparison_readiness", {})
                                diags = read_meta.get("column_diagnostics", [])
                                if diags:
                                    printed_from_json = True
                                    for d in diags[:20]:
                                        f.write(
                                            f"       - Column '{d.get('column')}' [{d.get('table')}/{d.get('sheet')}]: "
                                            f"status={d.get('status')} | Failures: {'; '.join(d.get('failures', []))}\n"
                                        )
                                    if len(diags) > 20:
                                        f.write(f"       - ... and {len(diags) - 20} more non-ready columns\n")
                            except Exception:
                                pass

                        if not printed_from_json:
                            # Fallback to querying columns table
                            bad_cols = self.db.query(
                                """
                                SELECT column_name, table_name, column_type, formula, resolved_by, formula_lineage
                                FROM columns
                                WHERE workbook_id = ? AND column_type IN ('formula_based','pivot_value','total')
                                """,
                                (wb["id"],),
                            )
                            degraded_count = 0
                            for col in bad_cols:
                                lin = col.get("formula_lineage")
                                if isinstance(lin, str):
                                    try:
                                        lin = json.loads(lin)
                                    except Exception:
                                        lin = {}
                                elif not isinstance(lin, dict):
                                    lin = {}
                                
                                srcs = lin.get("ultimate_raw_sources") or []
                                unresolved = [s for s in srcs if str(s).startswith("Col_")]
                                reasons_col = []
                                if unresolved:
                                    reasons_col.append(f"unresolved headers {unresolved[:3]}")
                                if col.get("resolved_by") in ("degraded", "none", "unsupported"):
                                    reasons_col.append(f"parser resolved_by={col.get('resolved_by')}")
                                if not lin.get("fingerprint"):
                                    reasons_col.append("missing computation fingerprint")
                                
                                if reasons_col:
                                    degraded_count += 1
                                    if degraded_count <= 15:
                                        f.write(
                                            f"       - Column '{col.get('column_name')}' in '{col.get('table_name')}': "
                                            f"formula='{col.get('formula')}' | Issues: {'; '.join(reasons_col)}\n"
                                        )
                            if degraded_count > 15:
                                f.write(f"       - ... and {degraded_count - 15} more degraded columns\n")
                    if kpi_count == 0 and cf_count > 0:
                        f.write(
                            f"    → WARNING: Has {cf_count} calculated fields but 0 canonical KPIs. "
                            f"KPI canonicalization may not have matched column names.\n"
                        )
                    f.write("\n")

                # ── Section 2: Recommendations ──
                recs = self.db.query(
                    "SELECT gr.*, w.name as wb_name FROM governance_recommendations gr "
                    "JOIN workbooks w ON gr.workbook_id = w.id ORDER BY gr.action, w.name"
                )
                f.write(f"\n{'─' * 60}\n")
                f.write(f"SECTION 2: RATIONALIZATION DECISIONS\n")
                f.write(f"{'─' * 60}\n\n")

                action_counts = {"keep": 0, "merge": 0, "decommission": 0, "review": 0}
                for rec in recs:
                    action = rec.get("action", "unknown")
                    action_counts[action] = action_counts.get(action, 0) + 1

                    reasons = rec.get("reasons", "[]")
                    if isinstance(reasons, str):
                        try:
                            reasons = json.loads(reasons)
                        except Exception:
                            reasons = [reasons]

                    icon = {"keep": "✓", "merge": "⇄", "decommission": "✕", "review": "⚠"}.get(action, "?")
                    f.write(
                        f"  {icon} [{rec['workbook_id']}] {rec.get('wb_name', '?')} → {action.upper()}\n"
                    )
                    if rec.get("merge_with_name"):
                        f.write(f"    merge_with: {rec['merge_with_name']} (id={rec.get('merge_with_id')})\n")
                    if rec.get("cluster_role"):
                        f.write(f"    cluster_role: {rec['cluster_role']}\n")
                    f.write(
                        f"    kpi_overlap={rec.get('kpi_overlap_score', 0):.2%}  "
                        f"ds_overlap={rec.get('datasource_overlap_score', 0):.2%}  "
                        f"uniqueness={rec.get('uniqueness_score', 0):.2%}\n"
                    )
                    for i, reason in enumerate(reasons, 1):
                        f.write(f"    reason {i}: {reason}\n")
                    f.write("\n")

                f.write(f"\n{'─' * 60}\n")
                f.write(f"SUMMARY: {action_counts}\n")
                f.write(f"{'─' * 60}\n")

                # ── Section 3: Clusters ──
                clusters = self.db.query(
                    "SELECT * FROM workbook_clusters ORDER BY id"
                )
                if clusters:
                    f.write(f"\n{'─' * 60}\n")
                    f.write(f"SECTION 3: CLUSTERS\n")
                    f.write(f"{'─' * 60}\n\n")
                    for cl in clusters:
                        members = self.db.query(
                            "SELECT wcm.workbook_id, w.name FROM workbook_cluster_members wcm "
                            "JOIN workbooks w ON wcm.workbook_id = w.id "
                            "WHERE wcm.cluster_id = ?",
                            (cl["id"],),
                        )
                        f.write(
                            f"  Cluster {cl['id']}: {cl.get('cluster_name', '?')} "
                            f"(size={cl.get('cluster_size')}, cohesion={cl.get('cohesion_score', 0):.3f})\n"
                        )
                        f.write(f"    canonical_target_id: {cl.get('canonical_target_id')}\n")
                        f.write(f"    action_summary: {cl.get('cluster_action_summary', 'N/A')}\n")
                        for m in members:
                            f.write(f"      - [{m['workbook_id']}] {m['name']}\n")
                        f.write("\n")

            logger.info("Diagnostic log written to %s", log_path)

        except Exception as e:
            logger.warning("Failed to write diagnostic log: %s", e)

    def _delete_scoped_recommendations(self, workbook_ids: List[int]) -> None:
        placeholders = ",".join("?" * len(workbook_ids))
        self.db.execute(
            f"DELETE FROM governance_recommendations WHERE workbook_id IN ({placeholders})",
            tuple(workbook_ids),
        )
