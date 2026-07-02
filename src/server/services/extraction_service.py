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

        Uses a persistent result cache keyed by MD5 hash:
        - Cache HIT  → skip Excel parsing, load cached JSON into DB (~1-2s)
        - Cache MISS → run full extraction, cache the result for future re-uploads

        Returns a result dict: {"status": "extracted"|"skipped"|"cached"|"error", ...}
        """
        file_name = os.path.basename(file_path)
        timer = PipelineTimer(
            "extraction",
            scan_id=scan_id_str,
            file_name=file_name,
        )

        # 1. Check skip (already in current DB session)
        with timer.step("skip_check"):
            should_skip, existing_id = self.should_skip(file_path)
        if should_skip:
            timer.finish("EXTRACTION_TOTAL_SKIPPED")
            return {"status": "skipped", "file": file_name, "workbook_id": existing_id}

        # 2. Check persistent result cache (survives DELETE /api/data/all)
        from src.server.services.result_cache import ResultCache
        cache = ResultCache()

        with timer.step("cache_check"):
            try:
                file_hash = workbook_loader.compute_md5(file_path)
            except Exception:
                file_hash = None

            cached_json = cache.get(file_hash) if file_hash else None

        if cached_json:
            try:
                # Cache HIT — skip entire extraction pipeline, go straight to DB load
                logger.info("Cache HIT for '%s' (hash=%s) — loading from cache", file_name, file_hash[:12])

                base_name = os.path.splitext(file_name)[0]
                json_path = os.path.join(self.output_dir, f"{base_name}.json")

                # Write cached JSON to output dir (so other code can find it)
                with timer.step("write_cached_json"):
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(cached_json, f, indent=2)

                with timer.step("db_load_from_cache"):
                    workbook_id = db_loader.load_workbook_json(
                        cached_json, scan_id, self.db, json_output_path=json_path
                    )

                timer.finish("EXTRACTION_TOTAL_CACHED")
                return {
                    "status": "cached",
                    "file": file_name,
                    "workbook_id": workbook_id,
                    "json_path": json_path,
                }

            except Exception as e:
                logger.warning("Cache load failed for '%s', falling through to full extraction: %s", file_name, e)

        try:
            # 3. Full extraction pipeline (cache MISS or cache load failed)
            from src.core.main import process_single_file
            with timer.step("process_single_file"):
                warnings = process_single_file(file_path, self.output_dir)

            # 4. Read the JSON output that was just written
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

            # 5. Store in persistent cache for future re-uploads
            with timer.step("cache_store"):
                if file_hash:
                    cache.put(file_hash, output_json)

            # 6. Load into DB
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

