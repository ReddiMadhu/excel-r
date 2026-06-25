"""
Scan Routes — POST /api/scans, GET /api/scans/{scan_id}

Handles file upload and scan progress polling.
"""
import os
import logging
import time
from typing import List

from fastapi import APIRouter, File, UploadFile, HTTPException

from src.server.models.schemas import ScanCreateResponse, ScanProgress
from src.server.models.database import get_database
from src.server.services.scan_manager import ScanManager
from src.utils.timing_log import PipelineTimer, log_step

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Scans"])

# Lazy-initialized scan manager
_scan_manager = None

OUTPUT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "output")
)
SCANS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "scans")
)


def _get_scan_manager() -> ScanManager:
    global _scan_manager
    if _scan_manager is None:
        db = get_database()
        _scan_manager = ScanManager(db, OUTPUT_DIR)
    return _scan_manager


@router.post("/scans", response_model=ScanCreateResponse)
async def create_scan(files: List[UploadFile] = File(...)):
    """
    Upload Excel files and start extraction + rationalization.

    Accepts one or more .xlsx files via multipart/form-data.
    Returns a scan_id for progress polling.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    # Validate file extensions
    xlsx_files = []
    for f in files:
        if not f.filename:
            continue
        if f.filename.startswith("~$"):
            continue  # skip temp/autosave files
        if not f.filename.lower().endswith(".xlsx"):
            raise HTTPException(
                status_code=400,
                detail=f"Only .xlsx files are accepted. Got: {f.filename}"
            )
        xlsx_files.append(f)

    if not xlsx_files:
        raise HTTPException(status_code=400, detail="No valid .xlsx files found")

    mgr = _get_scan_manager()

    # Create scan and save files
    import uuid
    scan_uuid = str(uuid.uuid4())
    scan_dir = os.path.join(SCANS_DIR, scan_uuid)
    os.makedirs(scan_dir, exist_ok=True)

    upload_timer = PipelineTimer("upload", scan_id=scan_uuid)
    saved_paths = []
    with upload_timer.step("validate_files", count=len(xlsx_files)):
        pass

    for f in xlsx_files:
        dest = os.path.join(scan_dir, f.filename)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        t0 = time.perf_counter()
        contents = await f.read()
        read_sec = time.perf_counter() - t0
        t1 = time.perf_counter()
        with open(dest, "wb") as out:
            out.write(contents)
        write_sec = time.perf_counter() - t1
        saved_paths.append(dest)
        size_mb = len(contents) / (1024 * 1024)
        log_step(
            "upload",
            "save_file",
            read_sec + write_sec,
            scan_id=scan_uuid,
            file_name=f.filename,
            size_mb=f"{size_mb:.2f}",
            read_ms=f"{read_sec * 1000:.0f}",
            write_ms=f"{write_sec * 1000:.0f}",
        )
        logger.info("Saved uploaded file: %s (%.2f MB)", dest, size_mb)

    # Create scan record
    with upload_timer.step("create_scan_record"):
        scan_id = mgr.create_scan(saved_paths, scan_dir)

    # Start background processing
    with upload_timer.step("start_background_thread"):
        mgr.start_scan_background(scan_id)

    upload_timer.finish("UPLOAD_HTTP_TOTAL")

    return ScanCreateResponse(
        scan_id=scan_id,
        status="pending",
        total_files=len(saved_paths),
        message=f"Scan created with {len(saved_paths)} file(s). Discovery extraction will begin shortly."
    )


@router.get("/scans/{scan_id}", response_model=ScanProgress)
async def get_scan_status(scan_id: str):
    """Get the current progress of a scan."""
    mgr = _get_scan_manager()
    progress = mgr.get_scan_progress(scan_id)

    if progress is None:
        raise HTTPException(status_code=404, detail=f"Scan not found: {scan_id}")

    return ScanProgress(**progress)
