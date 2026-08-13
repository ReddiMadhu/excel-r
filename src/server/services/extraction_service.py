"""
Extraction Service — Wraps existing parsers, writes to DB + JSON.

Always runs full extraction (no DB skip, no MD5 result cache).
"""
import json
import logging
import os
from typing import Optional

from src.server.models.database import Database
from src.server.services import db_loader
from src.utils.timing_log import PipelineTimer

logger = logging.getLogger(__name__)


class ExtractionService:
    """Manages per-file extraction: always full parse + DB insertion."""

    def __init__(self, db: Database, output_dir: str):
        self.db = db
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)

    def extract_and_store(
        self,
        file_path: str,
        scan_id: int,
        *,
        scan_id_str: Optional[str] = None,
    ) -> dict:
        """
        Extract a single workbook and store in both JSON file and DB.

        Always runs the full extraction pipeline (Excel parse + formulas).

        Returns a result dict: {"status": "extracted"|"error", ...}
        """
        file_name = os.path.basename(file_path)
        timer = PipelineTimer(
            "extraction",
            scan_id=scan_id_str,
            file_name=file_name,
        )

        try:
            from src.core.main import process_single_file
            with timer.step("process_single_file"):
                warnings = process_single_file(file_path, self.output_dir)

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

            with timer.step("db_load_workbook_json"):
                workbook_id = db_loader.load_workbook_json(
                    output_json, scan_id, self.db, json_output_path=json_path
                )

            # Excel Review (cell/formula) — independent of portfolio rationalization
            review_summary = None
            try:
                from src.review.engine import run_excel_review
                with timer.step("excel_review"):
                    review_summary = run_excel_review(
                        self.db, workbook_id, file_path=file_path
                    )
            except Exception as e:
                logger.exception("Excel Review failed for '%s'", file_name)
                review_summary = {"status": "failed", "error": str(e), "findings": 0}

            timer.finish("EXTRACTION_TOTAL")
            return {
                "status": "extracted",
                "file": file_name,
                "workbook_id": workbook_id,
                "warnings_count": len(warnings) if warnings else 0,
                "json_path": json_path,
                "excel_review": review_summary,
            }

        except Exception as e:
            timer.finish("EXTRACTION_TOTAL_ERROR")
            logger.exception("Error extracting '%s'", file_name)
            return {
                "status": "error",
                "file": file_name,
                "error": str(e),
            }
