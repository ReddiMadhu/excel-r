"""
Data Management Routes — DELETE /api/data/all

Provides endpoints for bulk data operations (e.g. wiping all data).
"""
import os
import glob
import shutil
import logging

from fastapi import APIRouter

from src.server.models.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Data Management"])

OUTPUT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "output")
)
SCANS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "scans")
)


@router.delete("/data/all")
async def delete_all_data():
    """
    Delete ALL data from the database and clean up generated files.

    This is a destructive operation that:
    1. Truncates every table in the database
    2. Removes generated JSON output files
    3. Removes uploaded scan directories
    4. Resets agent orchestrator state
    """
    db = get_database()

    # 1. Wipe the database
    counts = db.delete_all_data()

    # 2. Remove output JSON files (but keep the DB and timing.log)
    json_files_removed = 0
    for json_file in glob.glob(os.path.join(OUTPUT_DIR, "*.json")):
        try:
            os.remove(json_file)
            json_files_removed += 1
        except OSError as e:
            logger.warning("Failed to remove %s: %s", json_file, e)

    # 3. Remove scan directories
    scan_dirs_removed = 0
    if os.path.isdir(SCANS_DIR):
        for entry in os.listdir(SCANS_DIR):
            entry_path = os.path.join(SCANS_DIR, entry)
            if os.path.isdir(entry_path):
                try:
                    shutil.rmtree(entry_path)
                    scan_dirs_removed += 1
                except OSError as e:
                    logger.warning("Failed to remove scan dir %s: %s", entry_path, e)

    # 4. Reset agent orchestrator state
    try:
        from src.server.services.agent_orchestrator import get_agent_orchestrator
        orchestrator = get_agent_orchestrator(db)
        orchestrator.notify_workbooks_changed()
    except Exception as e:
        logger.warning("Failed to reset agent orchestrator: %s", e)

    total_rows = sum(counts.values())
    logger.info(
        "Delete all: %d DB rows, %d JSON files, %d scan dirs removed",
        total_rows, json_files_removed, scan_dirs_removed,
    )

    return {
        "message": "All data deleted successfully.",
        "deleted_rows": total_rows,
        "table_counts": counts,
        "json_files_removed": json_files_removed,
        "scan_dirs_removed": scan_dirs_removed,
    }
