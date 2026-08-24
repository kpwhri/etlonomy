# Tutorial 3: add Parquet and SQLite reference datasets

Our project has one logical dataset with CSV and Parquet versions. Real jobs usually combine several datasets. We will
add providers in Parquet and regions in SQLite. At the earlier tutorial date, the project uses three source types at
once: claims in CSV, providers in Parquet, and regions in SQLite.

That distinction is worth slowing down for:

- a **version** is a replacement source for the same logical dataset
- a **different dataset** represents a different business concept

We will eventually join all three datasets, but first we will create and verify each source independently. This makes a
bad file or table much easier to diagnose.

## Step 1: create the provider Parquet file

Provider data is small in this example, but Parquet gives us a typed, columnar source and lets us practice having two
independent file-backed datasets. Save this as `scripts/create_reference_data.py`:

```python
import sqlite3
from pathlib import Path

import polars as pl

data_directory = Path('data')
data_directory.mkdir(exist_ok=True)

# providers connect each claim's provider_id to a region_id
pl.DataFrame({
    'provider_id': [10, 20],
    'region_id': [100, 200],
}).write_parquet(data_directory / 'providers.parquet')

# regions use SQL so the completed job exercises the SQL adapter
with sqlite3.connect(data_directory / 'reference.sqlite') as connection:
    connection.execute(
        'CREATE TABLE regions (region_id INTEGER, region_name TEXT)'
    )
    connection.executemany(
        'INSERT INTO regions VALUES (?, ?)',
        [(100, 'West'), (200, 'East')],
    )
```

Run the script from the project root:

```console
python scripts/create_reference_data.py
```

You should now have `data/providers.parquet` and `data/reference.sqlite`. The script is intentionally repeatable in the
main test fixture, which creates a fresh temporary directory for every run. If you rerun this exact standalone script in
the same directory, remove the old `regions` table or database first.

## Step 2: describe both datasets

Keep the paths and SQL table name in TOML. If regions later move from SQLite to SQL Server, the ETL job should not need
a new connection string or table name.

Create `manifests/reference.toml`:

```toml
# each manifest file is independently versioned and validated
etlonomy_manifest = 1

[[datasets]]
canonical_name = 'REFERENCE.PROVIDER'
description = 'Provider attributes used to enrich claims.'

[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'parquet'
source_uri = 'data/providers.parquet'

[[datasets]]
canonical_name = 'REFERENCE.REGION'
description = 'Region labels stored in a local SQL table.'

[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'sql_table'
# the sqlalchemy URL stays with this dataset version
source_uri = 'sqlite:///data/reference.sqlite'
# for sql_table, query is the table or view name
query = 'regions'
```

There is no `SQLiteExecutor` to construct in user code. Etlonomy reads the selected sqlalchemy URL from the catalog and
opens it only when `REFERENCE.REGION` is requested.

## Step 3: rebuild the catalog and generated names

We added logical names, so rebuild the catalog from both TOML files. Then regenerate `datasets.py` so Python can use the
new names without a second handwritten list.

```console
etlonomy catalog validate --manifest-dir manifests
etlonomy catalog build --manifest-dir manifests --database .etlonomy/catalog.db
etlonomy codegen datasets --database .etlonomy/catalog.db --output src/claims_demo/datasets.py
```

After code generation, these names should exist:

```python
assert Datasets.CLAIMS.CLAIM_LINE.canonical_name == 'CLAIMS.CLAIM_LINE'
assert Datasets.REFERENCE.PROVIDER.canonical_name == 'REFERENCE.PROVIDER'
assert Datasets.REFERENCE.REGION.canonical_name == 'REFERENCE.REGION'
```

## Step 4: verify each source before joining it

A short provider check tells us whether the catalog, paths, sqlalchemy URL, table name, and requested columns agree. If
it fails, fix the source before adding join logic.

```python
from datetime import date
from pathlib import Path

import etlonomy

from claims_demo.datasets import Datasets

provider = etlonomy.CatalogDatasetProvider(
    catalog=etlonomy.SQLiteCatalog(Path('.etlonomy/catalog.db')),
)
context = etlonomy.ExecutionContext(as_of=date(2026, 8, 20))

providers = provider.read(
    etlonomy.read(Datasets.REFERENCE.PROVIDER, 'provider_id', 'region_id'),
    context,
)
regions = provider.read(
    etlonomy.read(Datasets.REFERENCE.REGION, 'region_id', 'region_name'),
    context,
)

assert providers.collect()['provider_id'].to_list() == [10, 20]
assert regions.collect()['region_name'].to_list() == ['West', 'East']
```

The checked-in end-to-end test performs the same operations in a temporary directory. It does not contact a shared
database or reuse files from an earlier test.

Next we will learn how to test the business rule without opening any of these production-like sources.

---

[← CSV and Parquet](02-csv-and-parquet.md) · [Tutorial home](index.md) · [Next: testing →](04-testing.md)
