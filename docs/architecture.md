# How the parts fit together

Etlonomy splits its work into small parts. You do not need all of these details to write a job, but they help when you
are debugging or adding support for something new.

```text
dataset + optional environment TOML ───build───> SQLite catalog
                                  |
Read + ExecutionContext ----------+
                                  v
                        CatalogDatasetProvider
                                  |
              +---------+---------+---------+
              v         v         v         v
          CSV/Parquet   SAS      SQL through sqlalchemy
              +---------+---------+---------+
                                  v
                           polars LazyFrame
```

## Models describe a request

`DatasetId`, `Read`, and `ExecutionContext` are small values that describe what to read, when to read it, and which
environment to check. Creating them does not open a file or database.

## TOML describes datasets and shared locations

Dataset TOML describes logical names and source versions. An optional environment file describes shared folders,
database connections, and an environment name. Etlonomy checks all the files before replacing the SQLite catalog. Jobs
then read one catalog instead of many configuration files.

## The catalog chooses a source

The catalog records versions, dates, column mappings, dependencies, and shared locations. It chooses the version for
`as_of`. It does not contain business data or resolved passwords and tokens.

## The provider handles one read

`CatalogDatasetProvider` asks the catalog which source to use, applies any column mappings, and sends the read to the
right adapter. A column without a mapping keeps its own name.

The ETL function never needs its own CSV-versus-SQL switch.

An `ExternalDatasetProvider` handles reads owned by another Python API. A normal runtime
registers those providers by an external system name. A portable `@requires` function can
instead create one from a supplied argument with `ExternalProviderBinding`. Etlonomy
keeps that provider in a call-local scope so nested helpers see it without sharing it
with concurrent calls. See the [external dataset guide](external-datasets.md#bind-a-provider-from-a-function-argument).

## Adapters read each source type

Adapters know the mechanics specific to their technology:

- CSV and Parquet create lazy scans
- SAS uses the optional reader and may read eagerly
- SQL builds a projected query and opens the dataset's sqlalchemy URL
- SQL Server, Oracle, Databricks, and other installed sqlalchemy drivers use the same SQL adapter

All return logical columns in a `pl.LazyFrame`.

## The runtime loads inputs and calls the job

The runtime finds a registered job, loads its declared inputs, supports `@requires`, calls the function, and records the
datasets used. It does not need to know whether an input came from a file or database.

## The test provider cannot reach production

`TestDatasetProvider` is not a mode on the production provider. It is a separate implementation that owns only explicit
frames and has no fallback reference. This makes accidental production access impossible through its normal API.

## Lineage uses declarations and run records

Lineage comes from TOML dependencies, direct job inputs, helper functions listed in `uses`, and reads recorded during a
run. Etlonomy does not try to guess this information from SQL or Python source code.

## Add new behavior in the right place

- A new physical technology belongs behind an adapter
- A new catalog metadata field needs a numbered structural migration
- A new dataset or version belongs in TOML, not a migration
- An organization-specific secret lookup implements `CredentialProvider` and is registered explicitly
- Scheduling, retries, and writing output data belong outside Etlonomy

Structural migrations use an explicit `-- etlonomy:next-statement` marker between statements and apply all pending files
in one transaction. This keeps the schema and `schema_version` history from disagreeing after a partial failure.

Previous: [CLI reference](cli.md) · Next: [contributing](contributing.md)
