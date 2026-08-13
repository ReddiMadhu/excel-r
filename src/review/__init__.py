"""
Excel Review — cell/formula inspection for a single workbook.

Distinct from portfolio Governance Review (action=review in rationalization).
"""
from src.review.engine import run_excel_review

__all__ = ["run_excel_review"]
