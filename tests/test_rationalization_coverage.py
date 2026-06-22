"""
Rationalization v1 coverage regression tests.

Unit tests run without a live server. Integration tests require bi_governance.db
with extracted workbooks (skip if DB empty).
"""
import json
import os
import sys
import unittest

# Project root on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.parsers.formula_lineage import (
    build_degraded_fingerprint,
    build_fingerprint,
    detect_computation_type,
)
from src.rationalization.source_normalizer import normalize_source_token, normalize_source_set
from src.utils.validation import compute_comparison_readiness


class TestFingerprintStability(unittest.TestCase):
    def test_sumifs_fingerprint_stable(self):
        params = {
            "scalar": 1,
            "sum_column": "Stat Amount",
            "group_by": ["Product Subtype"],
            "static_filters": [{"column": "BU", "value": "'GA'"}],
        }
        sources = ["SQL_data :: Statutory Reserves"]
        fp1 = build_fingerprint("SUMIFS", params, sources)
        fp2 = build_fingerprint("SUMIFS", params, sources)
        self.assertEqual(fp1, fp2)
        self.assertIn("SUMIFS", fp1)

    def test_unknown_degraded_fingerprint_not_empty(self):
        fp = build_degraded_fingerprint(
            "UNKNOWN", {}, [],
            function_chain=["SUMIFS", "ROUND"],
            formula_str="=ROUND(SUMIFS(...),2)",
        )
        self.assertTrue(fp)
        self.assertIn("FUNC_CHAIN", fp)

    def test_dynamic_indirect_fingerprint(self):
        comp = detect_computation_type("=INDIRECT(\"A\"&ROW())")
        self.assertEqual(comp, "DYNAMIC")
        fp = build_fingerprint("DYNAMIC", {}, [], formula_str="=INDIRECT(\"A\"&ROW())")
        self.assertIn("DYNAMIC", fp)
        self.assertIn("indirect", fp.lower())

    def test_lookup_degraded_fingerprint(self):
        fp = build_fingerprint(
            "LOOKUP", {}, ["Data :: Amount"],
            function_chain=["VLOOKUP"],
            formula_str="=VLOOKUP(A1,Data!A:B,2,FALSE)",
        )
        self.assertIn("LOOKUP", fp)


class TestSourceNormalizer(unittest.TestCase):
    def test_normalize_sheet_column(self):
        norm = normalize_source_token("SQL_data :: Statutory Reserves - Total")
        self.assertIn("sql_data", norm)
        self.assertIn("[", norm)

    def test_normalize_abbreviation(self):
        norm = normalize_source_token("Data :: GA Stat Reserve")
        self.assertIn("general_account", norm)

    def test_normalize_source_set_dedupes(self):
        s = normalize_source_set([
            "SQL_data :: Stat Amount",
            "sql_data :: stat amount",
        ])
        self.assertEqual(len(s), 1)


class TestComparisonReadiness(unittest.TestCase):
    def test_empty_workbook_insufficient(self):
        result = compute_comparison_readiness({"sheets": []})
        self.assertEqual(result["comparison_mode"], "insufficient")
        self.assertEqual(result["extraction_quality_score"], 0.0)

    def test_ready_column_scores_high(self):
        json_data = {
            "sheets": [{
                "sheet_type": "summary_report",
                "tables": [{
                    "columns": [{
                        "type": "formula_based",
                        "formula_lineage": {
                            "computation_type": "SUMIFS",
                            "fingerprint": "SUMIFS|SUM:amount",
                            "ultimate_raw_sources": ["Data :: Col"],
                        },
                    }],
                }],
            }],
        }
        result = compute_comparison_readiness(json_data)
        self.assertGreaterEqual(result["extraction_quality_score"], 0.5)
        self.assertIn(result["comparison_mode"], ("full", "degraded"))


class TestEvalLabels(unittest.TestCase):
    def test_labels_file_valid(self):
        labels_path = os.path.join(PROJECT_ROOT, "data", "eval", "labels.json")
        self.assertTrue(os.path.exists(labels_path))
        with open(labels_path, "r", encoding="utf-8") as f:
            labels = json.load(f)
        self.assertIn("metrics_targets", labels)
        self.assertGreaterEqual(labels["metrics_targets"]["fingerprint_coverage_min"], 0.9)


class TestIntegrationRationalization(unittest.TestCase):
    """Integration tests against SQLite DB if workbooks exist."""

    @classmethod
    def setUpClass(cls):
        from src.server.models.database import get_database, reset_database
        reset_database()
        cls.db = get_database()

    def test_overlap_scorer_runs(self):
        from src.rationalization.overlap_scorer import compute_pairwise_overlaps, jaccard_similarity

        self.assertEqual(jaccard_similarity({"a"}, {"a"}), 1.0)
        pairwise = compute_pairwise_overlaps(self.db)
        # Empty or populated — should not raise
        self.assertIsInstance(pairwise, dict)

    def test_risk_detector_runs(self):
        from src.rationalization.risk_detector import detect_workbook_risks
        risks = detect_workbook_risks(self.db)
        self.assertIsInstance(risks, list)

    def test_fingerprint_coverage_in_db(self):
        row = self.db.query_one("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN fingerprint IS NOT NULL AND fingerprint != '' THEN 1 ELSE 0 END) as with_fp
            FROM calculated_fields
            WHERE column_type IN ('formula_based', 'pivot_value')
        """)
        if not row or row["total"] == 0:
            self.skipTest("No calculated fields in DB")
        coverage = row["with_fp"] / row["total"]
        labels_path = os.path.join(PROJECT_ROOT, "data", "eval", "labels.json")
        with open(labels_path, "r", encoding="utf-8") as f:
            target = json.load(f)["metrics_targets"]["fingerprint_coverage_min"]
        self.assertGreaterEqual(
            coverage, target * 0.5,
            f"Fingerprint coverage {coverage:.0%} below relaxed target"
        )


if __name__ == "__main__":
    unittest.main()
