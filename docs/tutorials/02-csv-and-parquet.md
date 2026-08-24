# Tutorial 2: migrate the first dataset from CSV to Parquet

In the first tutorial, `CLAIMS.CLAIM_LINE` came from CSV. We will create a Parquet copy, add a dated version, and prove
that the same logical request works on both sides of the migration date.

The important lesson is not the file conversion. It is that the ETL job does not change when storage changes.

## Step 1: create the Parquet source

Save this as `scripts/create_parquet.py`:

```python
import polars as pl

# reading the known CSV gives both formats identical rows for a fair comparison
claims = pl.read_csv('data/claim_line.csv')

# Parquet preserves types and supports efficient column projection
claims.write_parquet('data/claim_line.parquet')
```

Run:

```console
python scripts/create_parquet.py
```

## Step 2: check the columns before changing TOML

The Parquet file must provide the same logical columns as the CSV. Compare the names before adding the new version so a
bad conversion is easy to find.

```python
import polars as pl

expected = ['person_id', 'provider_id', 'service_date', 'diagnosis_code']

# check the column names before adding the new source version
assert pl.read_csv('data/claim_line.csv').columns == expected
assert pl.read_parquet('data/claim_line.parquet').columns == expected
```

If the physical names differ, do not rename columns throughout the ETL. Add manifest column mappings instead.

## Step 3: close the CSV interval

Update the existing version:

```toml
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
# the old source remains correct for every date before September 1
valid_to = 2026-09-01
source_type = 'csv'
source_uri = 'data/claim_line.csv'
```

## Step 4: add the Parquet interval

Add the replacement as another version of the same logical dataset. Matching dates ensure that September 1 has exactly
one source.

```toml
[[datasets.versions]]
version = 2
# matching the old valid_to leaves no gap or overlap
valid_from = 2026-09-01
source_type = 'parquet'
source_uri = 'data/claim_line.parquet'
```

## Step 5: rebuild and inspect

The runtime reads the catalog, so rebuild it and check the dates before using the new source.

```console
etlonomy catalog validate --manifest-dir manifests
etlonomy catalog build --manifest-dir manifests --database .etlonomy/catalog.db

# this date should still select the CSV version
etlonomy catalog resolve --database .etlonomy/catalog.db CLAIMS.CLAIM_LINE --as-of 2026-08-31

# this date should select Parquet
etlonomy catalog resolve --database .etlonomy/catalog.db CLAIMS.CLAIM_LINE --as-of 2026-09-01
```

## Step 6: run the unchanged job twice

Catalog inspection shows which source is selected. Running the job also proves that both sources give the expected
result. Change only the date so any difference points to the source move.

```console
PYTHONPATH=src python -m claims_demo.run --as-of 2026-08-31
PYTHONPATH=src python -m claims_demo.run --as-of 2026-09-01
```

Both runs should keep people `1001` and `1003`. The runtime selects different adapters, but `jobs.py` remains
byte-for-byte unchanged.

## What you have proved

- historical dates still use the old source
- the changeover date selects the new source exactly
- both formats provide the same logical columns
- column selection remains lazy
- the ETL does not know which format was chosen

Continue by adding a third physical technology in
[Tutorial 3: SQLite](03-sql-dataset.md).

---

[← Tutorial 1](01-first-project.md) · [Tutorial home](index.md) · [Next: SQLite →](03-sql-dataset.md)
