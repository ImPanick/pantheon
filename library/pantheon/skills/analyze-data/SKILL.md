---
name: analyze-data
description: Answer a question from a data file or table with Python: load it, check its shape and quality, compute, sanity-check the numbers, and show how the result was derived.
version: 1.0.0
category: core
tags: [data, analysis, analyze, csv, excel, spreadsheet, table, statistics, stats, chart, plot, pandas, numbers, average, trend, dataset, json]
requires_toolsets: [python]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

The person shares data (CSV, Excel, JSON, a pasted table) or asks a question whose answer needs counting, totals, averages, trends, comparisons or a chart.

## Procedure

1. Restate the question as something computable: which measure, over which rows, grouped how, for what period.
2. Load it in `python` (pandas when available) and inspect before computing: row and column counts, column types, the first rows, missing values, duplicates, and the range of each key column.
3. Fix what would mislead: numbers stored as text, dates as strings, totals rows mixed with data, inconsistent category spellings. Say what you changed.
4. Compute the answer in as few steps as possible, printing intermediate results you will quote.
5. Sanity-check: do the parts sum to the total, are the magnitudes plausible, does a spot check of a few rows by hand agree?
6. Present the answer first, then a small table of the supporting numbers, then a chart only if it shows something a table does not. Save a chart or output file the person needs and say where.
7. State caveats: rows excluded, assumptions made, and what the data cannot tell.

## Pitfalls

- Computing before looking at the data.
- Silently dropping rows with missing values.
- Reporting averages of skewed data without the median.
- Confusing correlation in the data with a cause.

## Verification

- The quoted numbers come from code you ran, and a hand check of a few rows agrees with them.
