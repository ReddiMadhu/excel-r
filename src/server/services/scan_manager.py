"""
Scan Manager — Orchestrates the full scan lifecycle.

Handles: file discovery, background extraction, progress tracking,
and post-extraction rationalization trigger.
"""
import glob
import logging
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.server.models.database import Database
from src.server.services.extraction_service import ExtractionService
from src.utils.timing_log import PipelineTimer

logger = logging.getLogger(__name__)


class ScanManager:
    """Manages scan lifecycle: create, run in background, track progress."""

    def __init__(self, db: Database, output_dir: str):
        self.db = db
        self.output_dir = output_dir
        self._active_scans: Dict[str, Dict[str, Any]] = {}

    def create_scan(self, file_paths: List[str], scan_dir: str) -> str:
        """
        Create a new scan record and return the scan_id.

        Args:
            file_paths: List of .xlsx file paths saved in the scan directory
            scan_dir: Path to the scan's upload directory
        """
        scan_id = str(uuid.uuid4())
        total_files = len(file_paths)

        # Insert scan row in DB
        db_scan_id = self.db.insert("scans", {
            "scan_id": scan_id,
            "directory_path": scan_dir,
            "status": "pending",
            "total_files": total_files,
            "processed_files": 0,
            "current_file": None,
            "phase": "extraction",
            "errors": [],
            "started_at": datetime.utcnow().isoformat(),
        })

        # Track active scan state in memory
        self._active_scans[scan_id] = {
            "db_id": db_scan_id,
            "status": "pending",
            "phase": "extraction",
            "total_files": total_files,
            "processed_files": 0,
            "current_file": None,
            "errors": [],
            "file_paths": file_paths,
            "started_at": datetime.utcnow().isoformat(),
            "completed_at": None,
        }

        return scan_id

    def start_scan_background(self, scan_id: str) -> None:
        """Start the extraction + rationalization pipeline in a background thread."""
        thread = threading.Thread(
            target=self._run_scan_pipeline,
            args=(scan_id,),
            daemon=True,
            name=f"scan-{scan_id[:8]}",
        )
        thread.start()

    def get_scan_progress(self, scan_id: str) -> Optional[Dict[str, Any]]:
        """Get the current progress of a scan."""
        # Try in-memory first (most current)
        if scan_id in self._active_scans:
            state = self._active_scans[scan_id]
            total = state["total_files"]
            processed = state["processed_files"]
            phase = state["phase"]

            # Calculate progress percent (discovery = full scan progress)
            if phase in ("discovery", "extraction"):
                progress = (processed / total * 100) if total > 0 else 0
            elif state["status"] == "completed":
                progress = 100
            else:
                progress = 0

            return {
                "scan_id": scan_id,
                "status": state["status"],
                "phase": phase,
                "total_files": total,
                "processed_files": processed,
                "current_file": state["current_file"],
                "progress_percent": round(progress, 1),
                "started_at": state["started_at"],
                "completed_at": state["completed_at"],
                "errors": state["errors"],
            }

        # Fall back to DB
        row = self.db.query_one(
            "SELECT * FROM scans WHERE scan_id = ?", (scan_id,)
        )
        if not row:
            return None

        import json as json_mod
        errors = row.get("errors", "[]")
        if isinstance(errors, str):
            try:
                errors = json_mod.loads(errors)
            except Exception:
                errors = []

        total = row.get("total_files", 0)
        processed = row.get("processed_files", 0)
        status = row.get("status", "unknown")
        progress = (processed / total * 100) if total > 0 and status == "completed" else 0

        return {
            "scan_id": scan_id,
            "status": status,
            "phase": row.get("phase", "extraction"),
            "total_files": total,
            "processed_files": processed,
            "current_file": row.get("current_file"),
            "progress_percent": round(progress, 1),
            "started_at": row.get("started_at"),
            "completed_at": row.get("completed_at"),
            "errors": errors,
        }

    def _run_scan_pipeline(self, scan_id: str) -> None:
        """Background pipeline: extract all files then rationalize."""
        state = self._active_scans.get(scan_id)
        if not state:
            return

        db_id = state["db_id"]
        file_paths = state["file_paths"]

        # ── Phase 1: Discovery (extraction) ──────────────────
        state["status"] = "extracting"
        state["phase"] = "discovery"
        self.db.update("scans", {"status": "extracting", "phase": "discovery"},
                       "id = ?", (db_id,))

        from src.server.services.agent_orchestrator import get_agent_orchestrator
        get_agent_orchestrator(self.db).set_discovery_extracting(True)

        scan_timer = PipelineTimer("discovery_scan", scan_id=scan_id)
        extraction_svc = ExtractionService(self.db, self.output_dir)
        scan_workbook_ids: List[int] = []

        for i, fp in enumerate(file_paths):
            file_name = os.path.basename(fp)
            state["current_file"] = file_name
            self.db.update("scans", {"current_file": file_name}, "id = ?", (db_id,))

            logger.info("[Scan %s] Processing file %d/%d: %s",
                        scan_id[:8], i + 1, len(file_paths), file_name)

            with scan_timer.step(f"file_{i + 1}_{file_name}"):
                result = extraction_svc.extract_and_store(fp, db_id, scan_id_str=scan_id)

            state["processed_files"] = i + 1
            self.db.update("scans", {"processed_files": i + 1}, "id = ?", (db_id,))

            wb_id = result.get("workbook_id")
            if wb_id and wb_id not in scan_workbook_ids:
                scan_workbook_ids.append(wb_id)

            if result["status"] == "error":
                error_msg = f"Error processing {file_name}: {result.get('error', 'unknown')}"
                state["errors"].append(error_msg)
                logger.error(error_msg)

            logger.info("[Scan %s] File %s: %s",
                        scan_id[:8], file_name, result["status"])

        # ── Complete (Discovery only — intelligence/rationalization on demand) ──
        completed_at = datetime.utcnow().isoformat()
        state["status"] = "completed"
        state["phase"] = "discovery"
        state["completed_at"] = completed_at
        self.db.update("scans", {
            "status": "completed",
            "phase": "discovery",
            "completed_at": completed_at,
            "errors": state["errors"],
        }, "id = ?", (db_id,))

        from src.server.services.agent_orchestrator import get_agent_orchestrator
        orchestrator = get_agent_orchestrator(self.db)
        orchestrator.set_discovery_extracting(False)
        orchestrator.notify_workbooks_changed()

        scan_timer.finish("DISCOVERY_SCAN_TOTAL")

        logger.info(
            "[Scan %s] Discovery complete. %d files, %d errors. "
            "Run Intelligence / Rationalization from sidebar agents.",
            scan_id[:8], len(file_paths), len(state["errors"])
        )
