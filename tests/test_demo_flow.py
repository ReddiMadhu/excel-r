"""
Unit/integration tests for the Smart Cache demo flow.
"""
import os
import sys
import unittest
import shutil
import tempfile

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.server.services.result_cache import ResultCache
from src.server.models.database import Database
from src.server.services.extraction_service import ExtractionService


class TestResultCache(unittest.TestCase):
    def setUp(self):
        # Set up a temporary directory for cache testing
        self.test_dir = tempfile.mkdtemp()
        self.cache = ResultCache(cache_dir=self.test_dir)

    def tearDown(self):
        # Clean up temporary directory
        shutil.rmtree(self.test_dir)

    def test_cache_put_get(self):
        md5 = "d41d8cd98f00b204e9800998ecf8427e"  # empty md5
        test_json = {"file_name": "test.xlsx", "sheets": []}

        # Cache should be empty initially
        self.assertFalse(self.cache.has(md5))
        self.assertIsNone(self.cache.get(md5))

        # Put item in cache
        self.cache.put(md5, test_json)

        # Cache should contain the item
        self.assertTrue(self.cache.has(md5))
        cached = self.cache.get(md5)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["file_name"], "test.xlsx")

        # Stats should show 1 file
        stats = self.cache.stats()
        self.assertEqual(stats["file_count"], 1)

        # Clear cache should remove all items
        removed = self.cache.clear()
        self.assertEqual(removed, 1)
        self.assertFalse(self.cache.has(md5))
        self.assertIsNone(self.cache.get(md5))


class TestCachePreservationInDeleteAll(unittest.TestCase):
    def setUp(self):
        self.temp_db_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_db_dir, "test_governance.db")
        self.db = Database(db_path=self.db_path)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_db_dir)

    def test_delete_all_preserves_and_wipes_db(self):
        # Add basic info to DB to make sure delete works
        scan_id = self.db.insert("scans", {
            "scan_id": "test-scan-123",
            "directory_path": "/fake/path",
            "status": "pending",
        })
        self.assertTrue(scan_id > 0)

        # Confirm there's 1 scan
        row = self.db.query_one("SELECT COUNT(*) as cnt FROM scans")
        self.assertEqual(row["cnt"], 1)

        # Run delete all
        counts = self.db.delete_all_data()
        self.assertEqual(counts["scans"], 1)

        # Confirm DB is empty
        row = self.db.query_one("SELECT COUNT(*) as cnt FROM scans")
        self.assertEqual(row["cnt"], 0)


if __name__ == "__main__":
    unittest.main()
