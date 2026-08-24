# Etlonomy

Etlonomy is a Python framework for ETL projects that read from files and databases. You give each dataset one logical
name, describe where it lives in TOML, and declare which datasets each job or helper function uses. Etlonomy then loads
the right source when the job runs.

It is designed for data warehouses that use a mix of CSV, Parquet, SAS7BDAT, and/or SQL data. A job can keep asking for
`CLAIMS.CLAIM_LINE` even when that dataset moves from a file to a database. The job keeps the same logical column names,
so the storage change does not force you to rewrite the transformation.

## What Etlonomy does

- Gives datasets stable `SUBJECT.DATASET` names
- Keeps dated versions so an older run can use the source that was available at that time
- Builds a small SQLite catalog from readable TOML files
- Reads CSV, Parquet, SAS7BDAT, SQL tables, and SQL queries
- Requests only the columns a job asks for when the source supports it
- Maps old physical column names to clear logical names when needed
- Records datasets used by `@etl` jobs and `@requires` helper functions
- Lets tests supply in-memory data without any fallback to production
- Includes commands for building, checking, inspecting, and comparing catalogs

Etlonomy does not schedule jobs. Airflow, Dagster, Prefect, or another scheduler can call Etlonomy jobs when you need
scheduling, retries, or coordination between jobs.

## Installation

Etlonomy prefers Python 3.14 or later (though earlier may still run).

```console
python -m pip install etlonomy
```

Install optional SAS support with:

```console
python -m pip install 'etlonomy[sas]'
```

To work on this repository and run every test, install the development and optional integration dependencies:

```console
python -m pip install -e '.[dev,sas,keepass]'
```

## Build a small project

Create `manifests/claims.toml`:

```toml
etlonomy_manifest = 1

[[datasets]]
canonical_name = 'CLAIMS.CLAIM_LINE'
description = 'Claim lines used by cohort jobs.'

[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'parquet'
source_uri = 'data/claim_line.parquet'
```

Check the TOML, build the catalog, and generate Python names for the datasets:

```console
etlonomy catalog validate --manifest-dir manifests
etlonomy catalog build --manifest-dir manifests --database .etlonomy/catalog.db
etlonomy codegen datasets --database .etlonomy/catalog.db --output src/my_project/datasets.py
```

The job below asks for a logical dataset and two logical columns. It does not need to know that the current source is a
Parquet file:

```python
import polars as pl

import etlonomy
from my_project.datasets import Datasets


@etlonomy.etl(
    name='claims.filter',
    inputs={
        'claims': etlonomy.read(
            Datasets.CLAIMS.CLAIM_LINE,
            'person_id',
            'diagnosis_code',
        ),
    },
)
def filter_claims(claims: pl.LazyFrame) -> pl.LazyFrame:
    """Return claims with a known diagnosis."""
    return claims.filter(pl.col('diagnosis_code').is_not_null())
```

See [Getting started](docs/getting-started.md) for catalog inspection and runtime setup, or follow the
ordered [tutorial path](docs/tutorials/index.md).

## Run with real data and test data

A normal run uses the catalog to find the real file or database. Each environment can have its own catalog. You only
need to supply an environment name or historical date when you want Etlonomy to check or reproduce that choice:

```python
from pathlib import Path

import etlonomy

runtime = etlonomy.Runtime(
    provider=etlonomy.CatalogDatasetProvider(
        catalog=etlonomy.SQLiteCatalog(Path('.etlonomy/catalog.db')),
    ),
    context=etlonomy.ExecutionContext(),
)
result = runtime.run('claims.filter')
```

Tests use data you provide directly. If a required dataset is missing, the test fails instead of trying a real file or
database:

```python
from datetime import date

import polars as pl

import etlonomy
from my_project.datasets import Datasets

provider = etlonomy.TestDatasetProvider({
    Datasets.CLAIMS.CLAIM_LINE: pl.DataFrame({
        'person_id': [1001, 1002],
        'diagnosis_code': ['I10', None],
    }),
})
runtime = etlonomy.Runtime(
    provider=provider,
    context=etlonomy.ExecutionContext('test', date(2026, 8, 20)),
)
assert runtime.run('claims.filter').collect()['person_id'].to_list() == [1001]
```

## Try the complete example

`examples/claims_demo/` contains:

- a CSV seed
- a generated Parquet equivalent
- a usable SQLite source database
- a three-version TOML manifest
- a built catalog and generated dataset module
- a provider and region enrichment implemented with both `@etl` and `@requires`
- one ETL that runs unchanged while claims move across all three implementations

The end-to-end documentation test rebuilds the tutorial project in a temporary directory. It runs the ETL against local
files and SQLite databases that stand in for production, runs it again with isolated test data, and checks lineage and
dataset use. Start with the [first-project tutorial](docs/tutorials/01-first-project.md).

## Connect to SQL and look up credentials

SQL dataset versions store a normal sqlalchemy URL in `source_uri`. The connection stays with the dataset description,
not in every job that reads it. SQLite and connections that use integrated security do not need a credential provider.
SQL Server, Oracle, Databricks, and other installed sqlalchemy dialects all use `sql_table` or `sql_query`.

If several datasets share a folder or database, an optional environment TOML file can define that location once. The
location is copied into the catalog when you build it. See [environment settings](docs/environments.md).

When runtime secrets are required, add a non-secret `credential_ref` such as
`env://?username=WAREHOUSE_USER&password=WAREHOUSE_PASSWORD`. Etlonomy includes environment, KeePass-profile, mapping,
and explicitly registered custom credential providers. See the [credential guide](docs/credentials.md).

Etlonomy also allows credentials inside a sqlalchemy URL. If you do this, the catalog and command output may show the
URL exactly as you wrote it. Use `credential_ref` when that would expose information you need to keep private.

## Use the command line

```text
etlonomy catalog validate
etlonomy catalog build
etlonomy catalog show
etlonomy catalog history
etlonomy catalog resolve
etlonomy catalog diff
etlonomy codegen datasets
etlonomy registry validate
etlonomy deps
etlonomy uses
etlonomy lineage
etlonomy graph
```

See the [CLI reference](docs/cli.md) for complete arguments and examples.

## Learn more

- [Documentation home](docs/index.md)
- [Implementation checklist](docs/implementation-checklist.md)
- [Tutorial home and recommended order](docs/tutorials/index.md)
- [TOML manifest reference](docs/manifests.md)
- [Testing and isolation](docs/testing.md)
- [Architecture](docs/architecture.md)
- [Contributing](docs/contributing.md)

## Work on Etlonomy

```console
python -m pytest --cov=etlonomy --cov-branch --cov-fail-under=95
python -m ruff check .
python -m mypy src/etlonomy
python -m mkdocs build --strict
```

The suite uses temporary files and databases, small polars frames, and the committed SAS fixtures. Remote database
connections are mocked, so the normal test run never needs production access.


## License

Etlonomy is distributed under the [MIT license](LICENSE).
