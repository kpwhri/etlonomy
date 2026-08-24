# Tutorial 7: migrate CSV to Parquet to SQLite

This tutorial upgrades the [first project](01-first-project.md). The logical name and ETL source remain unchanged.

## 1. Create the Parquet replacement

We need a second source with the same rows and logical columns. Converting the known CSV prevents unrelated data
differences from confusing the example.

```python
import polars as pl

pl.read_csv('data/claim_line.csv').write_parquet('data/claim_line.parquet')
```

## 2. Create the SQLite source database

The third version uses a different kind of source. SQLite lets us test real SQL column selection and connections without
a server or credentials.

```python
import sqlite3
from contextlib import closing

rows = [
    (1001, 10, '2026-08-01', 'I10'),
    (1002, 10, '2026-08-02', None),
    (1003, 20, '2026-08-03', 'E11'),
]
with closing(sqlite3.connect('data/claims.sqlite')) as connection:
    with connection:
        connection.execute(
            'CREATE TABLE claim_line ('
            'person_id INTEGER, provider_id INTEGER, service_date TEXT, '
            'diagnosis_code TEXT)'
        )
        connection.executemany('INSERT INTO claim_line VALUES (?, ?, ?, ?)', rows)
```

The example now contains a CSV file, a Parquet file, and a usable SQLite source database.

## 3. Replace the manifest with three versions

Update `manifests/claims.toml`:

```toml
etlonomy_manifest = 1

[[datasets]]
canonical_name = 'CLAIMS.CLAIM_LINE'
description = 'Claim lines used by cohort jobs.'

[[datasets.versions]]
version = 1
valid_from = 2026-01-01
valid_to = 2026-09-01
source_type = 'csv'
source_uri = 'data/claim_line.csv'

[[datasets.versions]]
version = 2
valid_from = 2026-09-01
valid_to = 2027-01-01
source_type = 'parquet'
source_uri = 'data/claim_line.parquet'

[[datasets.versions]]
version = 3
valid_from = 2027-01-01
source_type = 'sql_table'
source_uri = 'sqlite:///data/claims.sqlite'
query = 'claim_line'
```

The boundaries are exact: August 31 selects CSV, September 1 selects Parquet, and January 1, 2027 selects the SQLite
table.

## 4. Keep the connection URL with the dataset

No connection module is needed. Etlonomy reads the sqlalchemy URL stored on the selected dataset version. The ETL job
remains unchanged.

## 5. Save the old catalog and build the new one

Keep a copy of the old catalog before rebuilding. You can compare it with the new catalog, while validation protects the
working file from bad TOML.

```console
copy .etlonomy/catalog.db .etlonomy/catalog-v1.db
etlonomy catalog validate --manifest-dir manifests
etlonomy catalog build --manifest-dir manifests --database .etlonomy/catalog.db
etlonomy catalog diff .etlonomy/catalog-v1.db .etlonomy/catalog.db
```

The diff reports `CLAIMS.CLAIM_LINE` as changed because its source versions changed while its logical name stayed the
same. Inspect all three dates:

```console
etlonomy catalog resolve --database .etlonomy/catalog.db CLAIMS.CLAIM_LINE --as-of 2026-08-31
etlonomy catalog resolve --database .etlonomy/catalog.db CLAIMS.CLAIM_LINE --as-of 2026-09-01
etlonomy catalog resolve --database .etlonomy/catalog.db CLAIMS.CLAIM_LINE --as-of 2027-01-01
```

The results report `csv`, `parquet`, and `sql_table` respectively.

## 6. Run the same ETL after each upgrade

Reading each source is not enough. We must show that one unchanged ETL produces the same result. Change only the date in
`run.py`:

```python
context = etlonomy.ExecutionContext(as_of=date(2026, 9, 1))
```

Run once for `2026-09-01`, then change only the date to `2027-01-01` and run again. Do not change `jobs.py`, its logical
read, or generated identifier. Both implementations return people `1001` and `1003` with regions `West` and `East`. The
provider and region datasets remain on Parquet and SQLite while only the claims source changes.

## 7. Prove all three implementations in pytest

The main documentation acceptance test is
`tests/end_to_end/test_documentation_example.py`. It creates the complete project under `tmp_path`, creates all three
source types, builds the initial catalog, performs both claims upgrades, imports the application like a user, runs local
production-style and isolated test data, and checks lineage and uses. See [testing](04-testing.md).

For a SAS-to-SQL migration, use the same dated-version approach and add column mappings when source names differ.
Review [files](../files.md), [SQL](../sql.md), and
[versioning](../versioning.md).
---

[← Lineage](06-lineage.md) · [Tutorial home](index.md) · [Next: optional credentials →](08-credentials.md)
