"""
Structural formula pattern keys (R1C1-like).

Preserves:
  - absolute vs relative vs mixed anchors
  - ranges
  - sheet identity
  - functions and operators
  - structured table refs / named ranges as opaque unsupported tokens

Does NOT treat formula string equality as semantics.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

# A1-style cell ref with optional sheet and $ anchors
_CELL_REF = re.compile(
    r"(?:(?P<sheet>'[^']+'|[A-Za-z0-9_\-]+)!)?"
    r"(?P<col_abs>\$)?(?P<col>[A-Za-z]+)"
    r"(?P<row_abs>\$)?(?P<row>\d+)"
)

_COL_RANGE = re.compile(
    r"(?:(?P<sheet>'[^']+'|[A-Za-z0-9_\-]+)!)?"
    r"(?P<a_abs>\$)?(?P<a>[A-Za-z]+):"
    r"(?P<b_abs>\$)?(?P<b>[A-Za-z]+)"
    r"(?!\d)"
)

_STRUCTURED_REF = re.compile(
    r"(?:\b[A-Za-z_][\w]*\s*)?\[[^\]]+\]|\[@[^\]]+\]|\[#[^\]]+\]"
)

_EXTERNAL_REF = re.compile(r"\[[^\]]+\.[Xx][Ll][Ss][Xx]?[MmBb]?\]")

_ERROR_TOKENS = ("#REF!", "#NAME?", "#VALUE!", "#DIV/0!", "#N/A", "#NULL!", "#NUM!")

_UNSUPPORTED_FUNCS = (
    "XLOOKUP", "XMATCH", "FILTER", "SORT", "UNIQUE", "LAMBDA", "LET",
    "SEQUENCE", "HSTACK", "VSTACK", "MAP", "REDUCE", "SCAN",
)


def col_letters_to_index(col: str) -> int:
    n = 0
    for ch in col.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def _sheet_token(sheet: Optional[str]) -> str:
    if not sheet:
        return "."
    return sheet.strip("'").replace(" ", "_")


def cell_to_r1c1(col: str, row: int, col_abs: bool, row_abs: bool,
                 base_row: int, base_col: int) -> str:
    """Convert A1 component to R1C1 relative to base cell."""
    c_idx = col_letters_to_index(col)
    if col_abs:
        c_part = f"C{c_idx}"
    else:
        dc = c_idx - base_col
        c_part = "C" if dc == 0 else f"C[{dc}]"
    if row_abs:
        r_part = f"R{row}"
    else:
        dr = row - base_row
        r_part = "R" if dr == 0 else f"R[{dr}]"
    return f"{r_part}{c_part}"


def detect_unsupported_features(formula: str) -> list:
    """Return list of unsupported feature tags found in a formula."""
    if not formula:
        return []
    fu = str(formula).upper()
    found = []
    for err in _ERROR_TOKENS:
        if err in fu or err.rstrip("!") in formula:
            found.append(f"error:{err}")
    if _EXTERNAL_REF.search(formula):
        found.append("external_workbook_ref")
    if _STRUCTURED_REF.search(formula):
        found.append("structured_table_ref")
    for fn in _UNSUPPORTED_FUNCS:
        if f"{fn}(" in fu:
            found.append(f"unsupported_func:{fn}")
    # Bare named-range heuristic: identifier that is not a function call and not A1
    # Handled separately when defined_names are provided.
    return found


def structural_pattern_key(
    formula: str,
    base_row: int,
    base_col: int,
) -> Tuple[str, list]:
    """
    Build a structural pattern key for a formula at (base_row, base_col).

    Returns (pattern_key, unsupported_tags).
    """
    if not formula:
        return ("", [])
    f = str(formula).strip()
    unsupported = detect_unsupported_features(f)

    # Mark structured refs as opaque tokens before A1 rewriting
    work = f
    work = _STRUCTURED_REF.sub("STRUCT_REF", work)

    def _repl_col_range(m: re.Match) -> str:
        sheet = _sheet_token(m.group("sheet"))
        a = m.group("a")
        b = m.group("b")
        a_abs = bool(m.group("a_abs"))
        b_abs = bool(m.group("b_abs"))
        # Column-only ranges: keep absolute column indices when $ present
        a_tok = f"C{col_letters_to_index(a)}" if a_abs else f"C[{col_letters_to_index(a) - base_col}]"
        b_tok = f"C{col_letters_to_index(b)}" if b_abs else f"C[{col_letters_to_index(b) - base_col}]"
        return f"{sheet}!{a_tok}:{b_tok}"

    # Replace column ranges first (avoid partial cell matches)
    work = _COL_RANGE.sub(_repl_col_range, work)

    def _repl_cell(m: re.Match) -> str:
        sheet = _sheet_token(m.group("sheet"))
        col = m.group("col")
        row = int(m.group("row"))
        col_abs = bool(m.group("col_abs"))
        row_abs = bool(m.group("row_abs"))
        r1c1 = cell_to_r1c1(col, row, col_abs, row_abs, base_row, base_col)
        return f"{sheet}!{r1c1}" if m.group("sheet") else r1c1

    work = _CELL_REF.sub(_repl_cell, work)
    # Normalize whitespace; preserve operators and function names
    work = re.sub(r"\s+", "", work)
    return work.upper(), unsupported


def is_formula(value) -> bool:
    return isinstance(value, str) and value.startswith("=")


def is_error_value(value) -> bool:
    if value is None:
        return False
    s = str(value).upper()
    return any(err in s for err in _ERROR_TOKENS)


def is_constant_nonblank(value) -> bool:
    if value is None or value == "":
        return False
    if is_formula(value):
        return False
    return True
