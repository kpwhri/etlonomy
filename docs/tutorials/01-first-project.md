# Tutorial 1: build and run the first project

This tutorial builds a complete Etlonomy project around one small CSV file. The rows are simple so we can focus on the
steps:

1. give a dataset a stable logical name
2. describe its current location in TOML
3. build a catalog from that TOML
4. generate Python references from the catalog
5. declare an ETL using logical data
6. run the ETL with `Runtime`

No database, network, or credentials are needed. By the end, you will have seen the same workflow that a larger
production project uses, only with local data.

## 1. Create the project folders

Start by separating four kinds of files:

- `data/` contains the example source data
- `manifests/` contains logical names, source locations, and dates
- `src/` contains importable application code
- `tests/` checks behavior without using production data

This matters later. Moving from CSV to Parquet should change `data/` and the TOML, but not the ETL under `src/`.

Create this structure:

```text
claims-demo/
├── .etlonomy/             # the generated catalog will be placed here
├── data/                  # local sources used by the tutorial
│   └── claim_line.csv
├── manifests/             # human-maintained dataset definitions
│   └── claims.toml
├── src/
│   └── claims_demo/
│       ├── __init__.py    # makes claims_demo an importable Python package
│       ├── datasets.py    # generated later from the catalog
│       ├── jobs.py        # business transformations
│       └── run.py         # application entry point
└── tests/
    └── test_jobs.py
```

Create the directories and an empty `src/claims_demo/__init__.py`. The empty file does not contain business logic; it
simply makes the directory an importable package.

## 2. Create a small CSV source

Etlonomy does not hold your business rows. It finds and reads data that already exists, so we need a source before we
can describe one.

Create `data/claim_line.csv` with three different rows:

```csv
person_id,provider_id,service_date,diagnosis_code
1001,10,2026-08-01,I10
1002,10,2026-08-02,
1003,20,2026-08-03,E11
```

The second row has no diagnosis code. That gives our future ETL a visible rule to apply: two rows should remain after
filtering. The `provider_id` column is not needed yet, but a later lesson will use it to join provider and region data.
Including it now lets the project grow without rewriting its seed data. Small, purposeful example data is better than a
large realistic file when learning because we can predict the answer before running code.

At this point, Etlonomy knows nothing about the CSV. The TOML will explain what the data means, when this source is
valid, and where it lives.

## 3. Describe the dataset and its first source

Create `manifests/claims.toml`. It connects the stable logical name `CLAIMS.CLAIM_LINE` to the CSV used at the beginning
of the example.

TOML is easy to read and review. Etlonomy can rebuild the SQLite catalog from it, so people do not have to maintain the
same information in two places.

Write:

```toml
# this schema number lets Etlonomy reject incompatible future manifest formats
etlonomy_manifest = 1

[[datasets]]
# ETL code will depend on this stable identity instead of the CSV path
canonical_name = 'CLAIMS.CLAIM_LINE'
description = 'Claim lines used by cohort jobs.'

[[datasets.versions]]
# version 1 is the first known source for this logical dataset
version = 1
# this source is valid on this date and afterward until a valid_to is added
valid_from = 2026-01-01
source_type = 'csv'
# the location belongs to the dataset version, not to the ETL function
source_uri = 'data/claim_line.csv'
```

Notice the two levels:

- `[[datasets]]` describes the stable logical dataset
- `[[datasets.versions]]` describes one replaceable source

Later, we will add Parquet and SQLite versions without renaming
`CLAIMS.CLAIM_LINE`.

## 4. Check the TOML

The TOML may contain a misspelled field, invalid name, overlapping date, or unsupported source type. Check those
mistakes before replacing a working catalog.

Run validation from the `claims-demo/` directory:

```console
etlonomy catalog validate --manifest-dir manifests
```

The expected result is:

```text
valid: 1 datasets
```

This confirms that the TOML is valid. It does not create the SQLite catalog yet.

## 5. Build the catalog

Etlonomy needs a quick way to find dataset names, dates, and source locations while a job runs. It builds that
information into SQLite.

Build the catalog:

```console
etlonomy catalog build --manifest-dir manifests --database .etlonomy/catalog.db
```

The command prints a catalog hash. Unchanged TOML produces the same hash. Etlonomy builds a temporary database first, so
a failed build cannot partly replace the working catalog.

## 6. Inspect what the catalog contains

Before generating code or running a job, check that the catalog contains the logical name we intended.

List the datasets:

```console
etlonomy catalog show --database .etlonomy/catalog.db
```

The listing should contain:

```text
CLAIMS.CLAIM_LINE
```

Now verify the source version selected for the tutorial date. This separates
'the catalog contains the dataset' from 'the catalog selects the expected implementation at a particular point in time'.

Run:

```console
etlonomy catalog resolve --database .etlonomy/catalog.db CLAIMS.CLAIM_LINE --as-of 2026-08-20
```

The JSON output should include:

```json
{
  "version": 1,
  "source_type": "csv",
  "source_uri": "data/claim_line.csv"
}
```

The full output contains more information, but these fields show that the date selects the CSV we just defined.

## 7. Generate Python dataset references

The catalog now contains the logical names. Generate them into Python instead of typing a second list that could become
out of date.

Generate `src/claims_demo/datasets.py`:

```console
etlonomy codegen datasets --database .etlonomy/catalog.db --output src/claims_demo/datasets.py
```

The generated file provides `Datasets.CLAIMS.CLAIM_LINE`. Application code can now use Python attribute lookup instead
of repeatedly constructing
`DatasetId('CLAIMS', 'CLAIM_LINE')`.

Do not edit the generated file manually. When logical datasets are added or removed, rebuild the catalog and run code
generation again. A physical-only change, such as CSV to Parquet, does not change this file because the logical identity
remains the same.

## 8. Write an ETL job using the logical name

We are finally ready to express the business rule. The function should ask for the logical columns it needs and should
not know that those columns currently come from a CSV.

Create `src/claims_demo/jobs.py`:

```python
import polars as pl

import etlonomy
from claims_demo.datasets import Datasets


@etlonomy.etl(
    name='cohort.build',
    inputs={
        # declaring the read makes the job's data dependency visible before execution
        'claims': etlonomy.read(
            Datasets.CLAIMS.CLAIM_LINE,
            # limiting the request lets physical adapters avoid unused columns
            'person_id',
            'diagnosis_code',
        ),
    },
)
def build_cohort(claims: pl.LazyFrame) -> pl.LazyFrame:
    """Keep claim rows that contain a diagnosis code."""
    # the transformation uses logical columns and remains unaware of the CSV path
    return claims.filter(pl.col('diagnosis_code').is_not_null())
```

The input key `claims` matches the function parameter `claims`. During a run, Etlonomy loads the declared data and
passes the resulting `LazyFrame` to that parameter.

## 9. Create and run the application

The ETL job says **what** data it needs. The application chooses the catalog and optional date used to find that data.

Create `src/claims_demo/run.py`:

```python
import argparse
from datetime import date
from pathlib import Path

import etlonomy
from claims_demo import jobs  # noqa: F401

# importing jobs registers cohort.build before the runtime looks it up by name

# the catalog stores all logical datasets and their dated source versions
catalog = etlonomy.SQLiteCatalog(Path('.etlonomy/catalog.db'))

# the catalog-backed provider finds each source and returns a LazyFrame
provider = etlonomy.CatalogDatasetProvider(catalog=catalog)

parser = argparse.ArgumentParser()
parser.add_argument('--as-of', type=date.fromisoformat)
arguments = parser.parse_args()

# no date means current data; an explicit date makes a historical run reproducible
runtime = etlonomy.Runtime(
    provider=provider,
    context=etlonomy.ExecutionContext(
        as_of=arguments.as_of,
    ),
)

# collect after the job has built its lazy transformation
result = runtime.run('cohort.build').collect()
print(result.to_dict(as_series=False))
```

The import of `jobs` is important even though the variable is not used later:
decorators register jobs when their module is imported.

To make `claims_demo` importable without installing this tutorial package, place `src/` on Python's module search path
and run the module:

```console
PYTHONPATH=src python -m claims_demo.run
```

On PowerShell, use:

```powershell
$env:PYTHONPATH = 'src'
python -m claims_demo.run
```

The result should contain people `1001` and `1003`. Person `1002` is removed because the diagnosis code is missing. This
matches the prediction we made when creating the CSV.

The CSV phase needs no SQL connection or credential provider. The provider selects the CSV adapter because the catalog
resolved `source_type = 'csv'`.

## 10. Review what each file does

| File                    | What it does                                                       |
|-------------------------|--------------------------------------------------------------------|
| `data/claim_line.csv`   | Supplies the example rows.                                         |
| `manifests/claims.toml` | Connects a stable logical name to a dated source.                  |
| `.etlonomy/catalog.db`  | Stores names, source versions, dates, and locations.               |
| `datasets.py`           | Gives Python code generated references to catalog identities.      |
| `jobs.py`               | Contains the logical read declaration and business transformation. |
| `run.py`                | Chooses the provider, execution context, and job to run.           |

This separation is the foundation for the next lesson. We will add a Parquet version while leaving `jobs.py` unchanged.

Continue to [Tutorial 2: migrate CSV to Parquet](02-csv-and-parquet.md).

---

[← Tutorial home](index.md) · [Next: CSV and Parquet →](02-csv-and-parquet.md)
