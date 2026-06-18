# Logical Steps for Excel-to-JSON Extractor

This document explains the extraction logic used by the Python Excel-to-JSON parser to read, scan, and convert reporting/summary sheets into structured JSON.

## 1. Sheet Classification
- **Summary Sheets**: Detected dynamically if the sheet name contains the word "summary" or "report" (case-insensitive).
- **Raw/Data Sheets**: Identified by checking for names like `Synthetic_Data`, `SQL_data`, or `Warehouse Data`. If none of these match, the sheet with the highest row count that contains a structured tabular header is classified as raw data.
- **Helper/Notes Sheets**: Identified as sheets named `Sheet1`, `helper`, or `notes` that have fewer than 100 rows.

## 2. Raw Data Mapping
- The header row is dynamically located on the raw data sheet by scanning the first 20 rows and identifying the first row containing multiple unique text values.
- A mapping is constructed between each column letter (e.g., `D`, `G`, `L`) and its header name (e.g., `Statutory Reserves - Total - General Account`).
- This mapping allows the formula parser to resolve column letters inside functions to their descriptive raw headers.

## 3. Pivot Table Processing
- Since Excel pivot table metadata is not fully exposed by openpyxl, the script opens the `.xlsx` file as a ZIP archive.
- It parses `xl/pivotTables/pivotTable1.xml` and `xl/pivotCache/pivotCacheDefinition1.xml` to extract:
  - Pivot table range (e.g., `A6:I67`).
  - Active Row fields, Column fields, and Page fields (filters).
  - Value/data fields and their aggregations (e.g., `SUM`, `COUNT`).
- A human-readable pivot formula is reconstructed for each value field (e.g., `SUM(Synthetic_Data[GA Stat Reserve]) GROUP BY Business Unit, ...`).
- Page fields (filters) are extracted from cells above the pivot range on the Summary sheet (e.g., `A1:B4` containing filter states) and stored under `filters` at the sheet level.

## 4. Advanced Table boundary Detection
Summary sheets contain plain ranges instead of formal Excel table objects. The parser scans the Summary sheet vertically and horizontally:
- **Vertical Partitioning**: Contiguous rows containing text or formulas separated by blank rows are identified as vertical blocks.
- **Horizontal Slicing**: Within each vertical block, columns that are completely blank in that row range are treated as horizontal separators. This splits rows into horizontal table blocks (e.g., columns `A:G` and columns `I:K` become separate tables).
- **Table Range Classification**:
  - The row range of each table block is partitioned into:
    - **Title Row**: Row at the top with exactly one non-empty string.
    - **Header Row**: Rows with text headers below the title.
    - **Data Rows**: Rows containing numeric values or formulas.
    - **Total/Check Rows**: Rows starting with "Total", "Grand Total", or "Check" are kept within their parent table boundaries.
- **Multi-Header Identification**:
  - If multiple header rows are detected above the data block, the text values are concatenated (e.g., `STAT Reserve` on row 36 and `Net Reserve` on row 37 are combined into `STAT Reserve Net Reserve`) to prevent duplicate header warnings.

## 5. Formula Parsing and Column Lineage
- Formulas are loaded using `data_only=False` to read raw formulas.
- We tokenize and parse `SUMIFS`, `COUNTIFS`, `SUM`, and arithmetic formulas.
- Cell and column letter references are mapped:
  - References like `SQL_data!D:D` are converted to `SQL_data[Statutory Reserves - Total - General Account]`.
  - Local cell references like `$A6` on the same row are replaced with `current Product Subtype`.
  - Local cell references to other rows/values are replaced with their evaluated cell value (e.g., `Summary Date ("12/31/2025")`).
- Calculated pivot values are marked as `type = pivot_value` and mapped to their source columns in the raw data sheet.
- Column definitions are automatically generated based on the formula patterns and lineage metadata.

## 6. Forward-Filling and JSON Assembly
- Parent label fields (such as `Business Unit` or `Statutory Exhibit section`) are forward-filled row-by-row inside `row_label_values` to provide local cell lineage.
- Original cell blanks are preserved in the row `values` dictionary.
- The raw data sheets are excluded from the output `sheets` array and kept only for internal lineage resolution, respecting the strict output scope rule.
