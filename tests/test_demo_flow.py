"""
Unit/integration tests for the Smart Cache demo flow.
"""
import os
import sys
import unittest
import shutil
import tempfile
import json

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.server.services.result_cache import ResultCache, DEFAULT_CACHE_DIR
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


class TestEndToEndCaching(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_governance.db")
        self.db = Database(db_path=self.db_path)
        self.output_dir = os.path.join(self.temp_dir, "output")
        self.cache_dir = os.path.join(self.temp_dir, "cache")
        
        # Override the cache dir dynamically for the test run
        self.patch_cache_dir(self.cache_dir)
        
        self.extractor = ExtractionService(self.db, self.output_dir)

    def tearDown(self):
        self.db.close()
        self.patch_cache_dir(None)  # reset
        shutil.rmtree(self.temp_dir)

    def patch_cache_dir(self, value):
        from src.server.services import result_cache
        if value:
            result_cache.DEFAULT_CACHE_DIR = value
        else:
            result_cache.DEFAULT_CACHE_DIR = DEFAULT_CACHE_DIR

    def get_db_counts(self):
        counts = {}
        for table in ["workbooks", "dashboards", "datasources", "worksheets", "columns", "calculated_fields"]:
            row = self.db.query_one(f"SELECT COUNT(*) as cnt FROM {table}")
            counts[table] = row["cnt"] if row else 0
        return counts

    def test_cache_hit_populates_db_identically(self):
        # We'll use 4.xlsx since it's the smallest (252KB)
        file_path = os.path.join(PROJECT_ROOT, "data", "input", "4.xlsx")
        self.assertTrue(os.path.exists(file_path), f"Test file not found: {file_path}")

        # Ensure database starts empty
        self.get_db_counts()
        
        # Create a mock scan record
        scan_db_id = self.db.insert("scans", {
            "scan_id": "test-scan-id-1",
            "directory_path": "/fake/path",
            "status": "extracting",
        })

        # --- 1st run: Cache Miss (run full extraction) ---
        print("\nRunning first extraction (Cache Miss)...")
        res1 = self.extractor.extract_and_store(file_path, scan_db_id, scan_id_str="test-scan-id-1")
        self.assertEqual(res1["status"], "extracted")
        workbook_id_1 = res1["workbook_id"]
        self.assertTrue(workbook_id_1 > 0)
        
        # Get DB counts after full run
        counts_miss = self.get_db_counts()
        print("Database counts (Cache Miss):", counts_miss)
        self.assertGreater(counts_miss["workbooks"], 0)
        self.assertGreater(counts_miss["dashboards"], 0)

        # --- Reset DB (simulate App Service reset / Delete All) ---
        print("Resetting database...")
        self.db.delete_all_data()
        counts_after_reset = self.get_db_counts()
        for tbl, cnt in counts_after_reset.items():
            self.assertEqual(cnt, 0, f"Table {tbl} was not cleared: {cnt} rows remain")

        # Create a new scan record for the second upload
        scan_db_id_2 = self.db.insert("scans", {
            "scan_id": "test-scan-id-2",
            "directory_path": "/fake/path",
            "status": "extracting",
        })

        # --- 2nd run: Cache Hit (load from cache) ---
        print("Running second extraction (Cache Hit)...")
        res2 = self.extractor.extract_and_store(file_path, scan_db_id_2, scan_id_str="test-scan-id-2")
        self.assertEqual(res2["status"], "cached")
        workbook_id_2 = res2["workbook_id"]
        self.assertTrue(workbook_id_2 > 0)

        # Get DB counts after cache hit run
        counts_hit = self.get_db_counts()
        print("Database counts (Cache Hit):", counts_hit)

        # Compare both counts to make sure cache hit populated the DB identically!
        for tbl in counts_miss:
            self.assertEqual(counts_miss[tbl], counts_hit[tbl], f"Mismatch in table {tbl} count!")

        print("Verification successful: DB populated identically from cache!")


if __name__ == "__main__":
    unittest.main()
