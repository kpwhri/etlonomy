# Etlonomy implementation checklist

Use this page when you already understand Etlonomy and need a quick reminder of the setup order. Each item links to a
guide or tutorial with the full explanation.

## Plan the datasets

- [ ] List the datasets your jobs read and write
- [ ] Give each dataset a stable `SUBJECT.DATASET` name that does not mention CSV, Parquet, SAS, or a database product
- [ ] Choose logical column names that make sense to the jobs that use them
- [ ] Identify helper functions that need their own data

Read [logical dataset names](datasets.md) and [how etlonomy thinks about data](concepts.md) if these choices are not yet
clear.

## Describe the sources

- [ ] Create one or more TOML files under `manifests/`
- [ ] Add each logical dataset and its current source version
- [ ] Add `valid_from` and optional `valid_to` dates
- [ ] Map only the source column names that differ from the logical names
- [ ] List the input datasets for a derived dataset under `dependencies`
- [ ] Add a new dated version instead of replacing history when a source moves

Use the [TOML guide](manifests.md), [date rules](versioning.md), [file sources](files.md), and [SQL sources](sql.md) for
details.

## Add shared settings only when useful

- [ ] Use direct file paths or sqlalchemy URLs when a source does not share a location
- [ ] Add `source_root` when several file datasets share a folder
- [ ] Add a named `connection` when several SQL datasets share a database
- [ ] Add an environment name only when runtime code should check that it opened the expected catalog
- [ ] Add `credential_ref` only when the selected database needs a secret lookup

Read [shared paths and connections](environments.md), [sqlalchemy connections](sqlalchemy.md), and
[credentials](credentials.md).

## Build the catalog and Python names

- [ ] Check the TOML before building
- [ ] Build one catalog for the environment
- [ ] Inspect the logical datasets and dated versions
- [ ] Preview an important date with `catalog resolve`
- [ ] Generate `datasets.py` after adding or removing logical dataset names

```console
etlonomy catalog validate --manifest-dir manifests
etlonomy catalog build --manifest-dir manifests --database .etlonomy/catalog.db
etlonomy catalog show --database .etlonomy/catalog.db
etlonomy catalog resolve --database .etlonomy/catalog.db CLAIMS.CLAIM_LINE --as-of 2026-08-20
etlonomy codegen datasets --database .etlonomy/catalog.db --output src/my_project/datasets.py
```

See [catalog commands](catalog.md), the [CLI reference](cli.md), and
[Tutorial 1](tutorials/01-first-project.md).

## Write and run the ETL code

- [ ] Use `@etlonomy.etl` on each top-level named job
- [ ] Request only the logical columns the job uses
- [ ] List logical outputs when the job creates a known dataset
- [ ] Use `@etlonomy.requires` on reusable helpers that need more data
- [ ] Add helpers to `uses` when a job or another helper may call them
- [ ] Use `ExternalDatasetId` only when another Python library owns resolution
- [ ] Keep each external provider in application code or a separate integration package
- [ ] Pass external dependency arguments directly in focused unit tests
- [ ] Confirm custom providers return a predictable type and apply requested columns
- [ ] Check custom-loaded datasets with the ordinary `uses` and lineage methods
- [ ] Import job modules before calling `Runtime.run()`
- [ ] Create `CatalogDatasetProvider` from the catalog and run the job by name

Read [ETL jobs](etl-jobs.md), [reusable helpers](requires.md),
[external datasets](external-datasets.md), and
[Tutorial 5](tutorials/05-reusable-functions.md). If another Python library loads a
dataset, follow the [custom-provider tutorial](tutorials/11-custom-provider.md).

## Test the project

- [ ] Test business rules with `TestDatasetProvider`
- [ ] Add a test that proves missing test data cannot fall back to production
- [ ] Test file and SQL readers with temporary sources
- [ ] Run the complete project in a temporary directory
- [ ] Run the same unchanged job before and after each source migration
- [ ] Check declared uses, actual runtime reads, and dataset lineage

The repository's main documentation test performs this full sequence. Read [safe testing](testing.md),
[lineage](lineage.md), and the [complete migration tutorial](tutorials/07-migrating-a-source.md).

## Check the project before release

- [ ] Compare the old and new catalogs
- [ ] Run pytest with line and branch coverage
- [ ] Run ruff as a lint check without autoformatting the hand-formatted examples
- [ ] Run mypy
- [ ] Build the documentation with strict checks
- [ ] Confirm that manifests, migrations, tests, documentation, and required fixtures are included in Git

```console
python -m pytest --cov=etlonomy --cov-branch --cov-fail-under=95
python -m ruff check .
python -m mypy src/etlonomy
python -m mkdocs build --strict
```

Return to the [documentation home](index.md) or follow the complete [tutorial course](tutorials/index.md).
