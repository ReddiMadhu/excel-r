"""
Agent Orchestrator — Decentralized pipelines aligned with sidebar agents.

  BI Discovery      → extraction on upload (scan_manager)
  BI Intelligence   → complexity + KPI canonicalization (on demand)
  BI Rationalization → risks + overlap + recommendations (on demand)
"""
import logging
import threading
from datetime import datetime
from typing import Any, Dict, Optional

from src.server.models.database import Database

logger = logging.getLogger(__name__)

AGENT_IDS = ("discovery", "intelligence", "rationalization")


class AgentOrchestrator:
    """Tracks and runs intelligence / rationalization agent jobs."""

    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()
        self._state: Dict[str, Dict[str, Any]] = {
            "intelligence": self._empty_agent_state(),
            "rationalization": self._empty_agent_state(),
        }
        self._discovery_extracting = False

    @staticmethod
    def _empty_agent_state() -> Dict[str, Any]:
        return {
            "status": "idle",
            "last_run_at": None,
            "workbook_count_at_run": 0,
            "error": None,
            "summary": None,
        }

    def set_discovery_extracting(self, active: bool) -> None:
        with self._lock:
            self._discovery_extracting = active

    def notify_workbooks_changed(self) -> None:
        """Mark downstream agents stale when portfolio changes."""
        count = self._current_workbook_count()
        with self._lock:
            for agent_id in ("intelligence", "rationalization"):
                state = self._state[agent_id]
                if state["status"] == "running":
                    continue
                if count == 0:
                    state.update(self._empty_agent_state())
                elif state["workbook_count_at_run"] != count:
                    if state["status"] == "completed":
                        state["status"] = "stale"
                elif state["status"] == "idle" and count > 0:
                    state["status"] = "pending"

    def _current_workbook_count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) as cnt FROM workbooks")
        return row["cnt"] if row else 0

    def get_status(self) -> Dict[str, Any]:
        count = self._current_workbook_count()
        kpi_row = self.db.query_one("SELECT COUNT(*) as cnt FROM kpi_cluster_cache")
        rec_row = self.db.query_one("SELECT COUNT(*) as cnt FROM governance_recommendations")
        risk_row = self.db.query_one("SELECT COUNT(*) as cnt FROM governance_risks")

        with self._lock:
            discovery_status = "extracting" if self._discovery_extracting else (
                "ready" if count > 0 else "empty"
            )
            return {
                "discovery": {
                    "status": discovery_status,
                    "workbook_count": count,
                    "label": "BI Discovery",
                    "description": "Extract workbook structure, sheets, and datasources",
                },
                "intelligence": {
                    **self._state["intelligence"],
                    "label": "BI Intelligence",
                    "description": "KPI clustering, formula analysis, complexity scoring",
                    "kpi_cluster_count": kpi_row["cnt"] if kpi_row else 0,
                },
                "rationalization": {
                    **self._state["rationalization"],
                    "label": "BI Rationalization",
                    "description": "Overlap scoring, risks, merge/keep recommendations",
                    "recommendation_count": rec_row["cnt"] if rec_row else 0,
                    "risk_count": risk_row["cnt"] if risk_row else 0,
                },
            }

    def run_intelligence_background(self, workbook_ids: Optional[list] = None) -> bool:
        return self._start_background("intelligence", workbook_ids)

    def run_rationalization_background(self, workbook_ids: Optional[list] = None) -> bool:
        return self._start_background("rationalization", workbook_ids)

    def _start_background(self, agent_id: str, workbook_ids: Optional[list]) -> bool:
        with self._lock:
            state = self._state[agent_id]
            if state["status"] == "running":
                return False
            if self._current_workbook_count() == 0:
                return False
            self._launch_thread(agent_id, workbook_ids)
            return True

    def _launch_thread(self, agent_id: str, workbook_ids: Optional[list]) -> None:
        state = self._state[agent_id]
        state["status"] = "running"
        state["error"] = None
        state["summary"] = None
        thread = threading.Thread(
            target=self._run_agent,
            args=(agent_id, workbook_ids),
            daemon=True,
            name=f"agent-{agent_id}",
        )
        thread.start()

    def _run_agent(self, agent_id: str, workbook_ids: Optional[list]) -> None:
        from src.rationalization.engine import RationalizationEngine

        engine = RationalizationEngine(self.db)
        try:
            if agent_id == "rationalization":
                self._ensure_intelligence(engine, workbook_ids)
            if agent_id == "intelligence":
                summary = engine.run_intelligence(workbook_ids)
            else:
                summary = engine.run_rationalization(workbook_ids)
            with self._lock:
                state = self._state[agent_id]
                state["status"] = "completed"
                state["last_run_at"] = datetime.utcnow().isoformat()
                state["workbook_count_at_run"] = self._current_workbook_count()
                state["summary"] = summary
                state["error"] = None
            logger.info("Agent '%s' completed", agent_id)
        except Exception as e:
            logger.exception("Agent '%s' failed: %s", agent_id, e)
            with self._lock:
                state = self._state[agent_id]
                state["status"] = "failed"
                state["error"] = str(e)

    def _ensure_intelligence(self, engine, workbook_ids: Optional[list]) -> None:
        """Run intelligence first if KPI clusters are missing or stale."""
        with self._lock:
            intel = self._state["intelligence"]
            needs_run = intel["status"] in ("idle", "pending", "stale", "failed")
            if intel["status"] == "completed":
                needs_run = intel["workbook_count_at_run"] != self._current_workbook_count()
            if not needs_run:
                return
            if intel["status"] == "running":
                return

        logger.info("Running intelligence as prerequisite for rationalization")
        summary = engine.run_intelligence(workbook_ids)
        with self._lock:
            intel = self._state["intelligence"]
            intel["status"] = "completed"
            intel["last_run_at"] = datetime.utcnow().isoformat()
            intel["workbook_count_at_run"] = self._current_workbook_count()
            intel["summary"] = summary
            intel["error"] = None


_orchestrator: Optional[AgentOrchestrator] = None


def get_agent_orchestrator(db: Optional[Database] = None) -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        from src.server.models.database import get_database
        _orchestrator = AgentOrchestrator(db or get_database())
    return _orchestrator
