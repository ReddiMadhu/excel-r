"""
Rationalization Engine — Main orchestrator for the 3-phase pipeline.

Phase 0: Risk detection + Complexity scoring
Phase 1: KPI Canonicalization (lexical + LLM)
Phase 2: Overlap Scoring (Jaccard + fingerprint dedup)
Phase 3: Recommendation Generation (deterministic + LLM justification)
"""
import json
import logging
import os
import time
from typing import Any, List, Optional

from src.server.models.database import Database
from src.rationalization.kpi_canonicalizer import run_kpi_canonicalization
from src.rationalization.overlap_scorer import (
    compute_pairwise_overlaps,
    compute_uniqueness_scores,
)
from src.rationalization.complexity_scorer import compute_complexity_scores
from src.rationalization.recommender import Recommender
from src.rationalization.risk_detector import detect_workbook_risks
from src.rationalization.prompts import INTELLIGENCE_METADATA_PROMPT

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
        BI Rationalization agent — risk detection, overlap scoring, recommendations.
        """
        count = self._workbook_count(workbook_ids)
        if count == 0:
            logger.info("No workbooks in scope — skipping rationalization")
            return {"status": "skipped", "reason": "no workbooks", "agent": "rationalization"}

        logger.info("Starting Rationalization pipeline (%d workbook(s))", count)
        summary = {
            "status": "completed",
            "agent": "rationalization",
            "workbooks": count,
            "workbook_ids": workbook_ids,
        }

        logger.info("── Risk Detection ──")
        try:
            risks = detect_workbook_risks(self.db, workbook_ids)
            summary["risks_detected"] = len(risks)
        except Exception as e:
            logger.exception("Risk detection failed: %s", e)
            summary["risk_error"] = str(e)

        if count == 1:
            logger.info("Only 1 workbook in scope — assigning 'keep' recommendation")
            if workbook_ids:
                wb = self.db.query_one(
                    "SELECT id, name FROM workbooks WHERE id = ?", (workbook_ids[0],)
                )
                self._delete_scoped_recommendations(workbook_ids)
            else:
                wb = self.db.query_one("SELECT id, name FROM workbooks")
                self.db.execute("DELETE FROM governance_recommendations")
            if wb:
                self.db.insert("governance_recommendations", {
                    "workbook_id": wb["id"],
                    "action": "keep",
                    "reasons": ["Only workbook in the portfolio — no redundancy possible."],
                    "uniqueness_score": 1.0,
                    "kpi_overlap_score": 0.0,
                    "datasource_overlap_score": 0.0,
                })
            summary["recommendations"] = 1
            return summary

        logger.info("── Overlap Scoring ──")
        try:
            pairwise = compute_pairwise_overlaps(self.db, workbook_ids=workbook_ids)
            summary["pairwise_comparisons"] = len(pairwise)

            alpha = float(os.getenv("OVERLAP_WEIGHT_KPI", "0.35"))
            beta = float(os.getenv("OVERLAP_WEIGHT_DS", "0.25"))
            gamma = float(os.getenv("OVERLAP_WEIGHT_FINGERPRINT", "0.25"))
            delta = float(os.getenv("OVERLAP_WEIGHT_STRUCTURAL", "0.15"))

            uniqueness = compute_uniqueness_scores(
                self.db, pairwise, alpha, beta, gamma, delta,
                workbook_ids=workbook_ids,
            )
            summary["uniqueness_scores"] = len(uniqueness)
        except Exception as e:
            logger.exception("Overlap scoring failed: %s", e)
            pairwise = {}
            uniqueness = {}
            summary["overlap_error"] = str(e)

        logger.info("── Recommendation Generation ──")
        try:
            recommender = Recommender(self.db, self._llm_caller)
            recommendations = recommender.run(
                pairwise, uniqueness, workbook_ids=workbook_ids
            )
            summary["recommendations"] = len(recommendations)
            summary["actions"] = {
                "keep": sum(1 for r in recommendations if r["action"] == "keep"),
                "merge": sum(1 for r in recommendations if r["action"] == "merge"),
                "decommission": sum(1 for r in recommendations if r["action"] == "decommission"),
                "review": sum(1 for r in recommendations if r["action"] == "review"),
            }
        except Exception as e:
            logger.exception("Recommendation generation failed: %s", e)
            summary["recommendation_error"] = str(e)

        return summary

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
