"""
Extraction Service — Wraps existing parsers, writes to DB + JSON.

Calls process_single_file() from the existing pipeline, then loads
the resulting JSON into the SQLite database.
"""
import json
import logging
import os
from typing import Optional, Tuple

from src.server.models.database import Database
from src.server.services import db_loader
import src.extractors.workbook_loader as workbook_loader
from src.utils.timing_log import PipelineTimer

logger = logging.getLogger(__name__)


class ExtractionService:
    """Manages per-file extraction: skip detection, parsing, DB insertion."""

    def __init__(self, db: Database, output_dir: str):
        self.db = db
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)

    def should_skip(self, file_path: str) -> Tuple[bool, Optional[int]]:
        """
        Check if a file has already been extracted (hash + filename match).
        Returns (True, workbook_id) if skip, else (False, None).
        """
        file_name = os.path.basename(file_path)
        try:
            file_hash = workbook_loader.compute_md5(file_path)
        except Exception as e:
            logger.warning("Could not compute hash for %s: %s", file_name, e)
            return False, None

        existing = self.db.query_one(
            "SELECT id FROM workbooks WHERE source_file = ? AND file_hash_md5 = ?",
            (file_name, file_hash)
        )
        if existing:
            logger.info("Skipping '%s' — already in DB (hash match)", file_name)
            return True, existing["id"]
        return False, None

    def extract_and_store(
        self,
        file_path: str,
        scan_id: int,
        *,
        scan_id_str: Optional[str] = None,
    ) -> dict:
        """
        Extract a single workbook and store in both JSON file and DB.

        Returns a result dict: {"status": "extracted"|"skipped"|"error", ...}
        """
        file_name = os.path.basename(file_path)
        timer = PipelineTimer(
            "extraction",
            scan_id=scan_id_str,
            file_name=file_name,
        )

        # 1. Check skip
        with timer.step("skip_check"):
            should_skip, existing_id = self.should_skip(file_path)
        if should_skip:
            timer.finish("EXTRACTION_TOTAL_SKIPPED")
            return {"status": "skipped", "file": file_name, "workbook_id": existing_id}

        try:
            # 2. Import and run existing extraction pipeline
            from src.core.main import process_single_file
            with timer.step("process_single_file"):
                warnings = process_single_file(file_path, self.output_dir)

            # 3. Read the JSON output that was just written
            base_name = os.path.splitext(file_name)[0]
            json_path = os.path.join(self.output_dir, f"{base_name}.json")

            if not os.path.exists(json_path):
                timer.finish("EXTRACTION_TOTAL_ERROR")
                return {
                    "status": "error",
                    "file": file_name,
                    "error": f"JSON output not found at {json_path}"
                }

            with timer.step("read_json_output"):
                with open(json_path, "r", encoding="utf-8") as f:
                    output_json = json.load(f)

            # 4. Load into DB
            with timer.step("db_load_workbook_json"):
                workbook_id = db_loader.load_workbook_json(
                    output_json, scan_id, self.db, json_output_path=json_path
                )

            timer.finish("EXTRACTION_TOTAL")
            return {
                "status": "extracted",
                "file": file_name,
                "workbook_id": workbook_id,
                "warnings_count": len(warnings) if warnings else 0,
                "json_path": json_path,
            }

        except Exception as e:
            timer.finish("EXTRACTION_TOTAL_ERROR")
            logger.exception("Error extracting '%s'", file_name)
            return {
                "status": "error",
                "file": file_name,
                "error": str(e),
            }
