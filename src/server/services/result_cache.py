"""
Result Cache — Persistent file-based cache for extracted workbook JSON.

Stores JSON output files keyed by MD5 hash in data/cache/extractions/.
This cache survives DELETE /api/data/all so that re-uploading the same
Excel files skips the heavy extraction pipeline entirely.

IMPORTANT: ExtractionService currently does NOT call get() — full re-parse
is always performed. If ResultCache is re-wired into extract, the cache key
MUST include LINEAGE_SCHEMA_VERSION from formula_lineage so stale JSON from
pre-semantic-lineage builds cannot drive rationalization.
"""
import json
import logging
import os
import shutil
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from src.parsers.formula_lineage import LINEAGE_SCHEMA_VERSION
except Exception:
    LINEAGE_SCHEMA_VERSION = "unknown"

# Default cache directory (sibling to data/output)
DEFAULT_CACHE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "cache", "extractions")
)


class ResultCache:
    """File-based cache for extracted workbook JSON, keyed by MD5 hash + lineage schema."""

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = os.path.abspath(cache_dir or DEFAULT_CACHE_DIR)
        os.makedirs(self.cache_dir, exist_ok=True)

    def _path_for(self, md5_hash: str) -> str:
        """Return the cache file path for a given MD5 hash (schema-versioned)."""
        safe_ver = str(LINEAGE_SCHEMA_VERSION).replace("/", "_").replace("\\", "_")
        return os.path.join(self.cache_dir, f"{md5_hash}.{safe_ver}.json")

    def get(self, md5_hash: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached JSON for the given MD5 hash.
        Returns the parsed dict or None if not cached.
        """
        path = self._path_for(md5_hash)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info("Cache HIT for hash %s", md5_hash[:12])
            return data
        except Exception as e:
            logger.warning("Cache read failed for %s: %s", md5_hash[:12], e)
            return None

    def put(self, md5_hash: str, output_json: Dict[str, Any]) -> None:
        """
        Store extracted JSON in the cache, keyed by MD5 hash.
        """
        path = self._path_for(md5_hash)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(output_json, f, indent=2)
            logger.info("Cache STORED for hash %s", md5_hash[:12])
        except Exception as e:
            logger.warning("Cache write failed for %s: %s", md5_hash[:12], e)

    def has(self, md5_hash: str) -> bool:
        """Check if a cache entry exists for the given hash."""
        return os.path.exists(self._path_for(md5_hash))

    def clear(self) -> int:
        """
        Remove all cached entries.
        Returns the number of files removed.
        """
        count = 0
        if os.path.isdir(self.cache_dir):
            for entry in os.listdir(self.cache_dir):
                entry_path = os.path.join(self.cache_dir, entry)
                if os.path.isfile(entry_path) and entry.endswith(".json"):
                    try:
                        os.remove(entry_path)
                        count += 1
                    except OSError as e:
                        logger.warning("Failed to remove cache file %s: %s", entry, e)
        logger.info("Cache cleared: %d files removed", count)
        return count

    def stats(self) -> Dict[str, Any]:
        """
        Return cache statistics: file count and total size.
        """
        file_count = 0
        total_bytes = 0
        if os.path.isdir(self.cache_dir):
            for entry in os.listdir(self.cache_dir):
                entry_path = os.path.join(self.cache_dir, entry)
                if os.path.isfile(entry_path) and entry.endswith(".json"):
                    file_count += 1
                    total_bytes += os.path.getsize(entry_path)
        return {
            "file_count": file_count,
            "total_size_mb": round(total_bytes / (1024 * 1024), 2),
            "cache_dir": self.cache_dir,
        }
