# Tutorials: build one project from beginning to end

These tutorials form a small course. Every lesson adds one idea to the same `claims-demo` project.

If you are new to Etlonomy, follow the numbered path in order. The optional extensions make more sense after the
complete migration lesson.

## What you will build

By the end, the project will:

- create CSV, Parquet, and SQLite data locally
- build a SQLite catalog from TOML files
- generate stable Python dataset identifiers
- run one logical ETL unchanged while its claims source moves across formats
- run that same ETL with an isolated test provider
- let a reusable helper request another dataset
- report lineage and dataset uses
- optionally resolve credentials without storing secrets

The main lessons use only local files and need no network access.

The project grows into this shape:

```text
claims-demo/
├── data/                 # local files and databases used by the lessons
├── manifests/            # logical names, source locations, and dates
├── scripts/              # repeatable setup helpers for local example data
├── src/claims_demo/      # generated names, ETL jobs, and the run entry point
└── tests/                # isolated and end-to-end verification
```

## Recommended path

| Lesson | Page                                                              | Why this lesson comes here                                             |
|--------|-------------------------------------------------------------------|------------------------------------------------------------------------|
| 1      | [Build and run the first project](01-first-project.md)            | Create the folders, CSV, TOML, catalog, generated names, and first job |
| 2      | [Migrate CSV to Parquet](02-csv-and-parquet.md)                   | Add a dated Parquet version without changing the job                   |
| 3      | [Add Parquet and SQLite references](03-sql-dataset.md)            | Read three datasets from CSV, Parquet, and SQLite                      |
| 4      | [Test safely](04-testing.md)                                      | Compare local production-style data with fully isolated test data      |
| 5      | [Add a reusable requirement](05-reusable-functions.md)            | Let a helper request another dataset automatically                     |
| 6      | [Inspect lineage and uses](06-lineage.md)                         | Ask which datasets and helpers a job uses                              |
| 7      | [Run the complete source migration](07-migrating-a-source.md)     | Run one unchanged job against CSV, Parquet, and SQLite                 |
| 8      | [Add shared connections and credential lookup](08-credentials.md) | Reuse database locations and look up secrets only when needed          |

## Optional extensions

- [Extension A: SAS7BDAT](09-sas7bdat.md) maps older column names and explains why SAS reading may be eager
- [Extension B: A Remote SQL Database](10-sql-databases.md) compares SQL Server, Oracle, and Databricks-style sqlalchemy
  connections without adding database-specific ETL code.
- [Extension C: A Custom Provider](11-custom-provider.md) loads a normal internal dataset through another Python API
  while keeping the dataset in ordinary uses and lineage results

## How to study each lesson

Do not merely paste the code. At each step:

1. Predict which file or output should change
2. Run the validation or assertion shown
3. Read the failure if your prediction was wrong
4. Confirm which files stayed unchanged—especially the ETL during migrations

This helps you see the main idea: jobs use stable logical names, while files and databases can change.

The checked-in `examples/claims_demo/` project shows the finished version without credentials. The test
`tests/end_to_end/test_documentation_example.py` rebuilds the whole course in a temporary directory and runs it the way
a user would. It checks catalog upgrades, local production-style data, isolated test data, helper requirements, lineage,
and uses.

Before starting, complete [Getting started](../getting-started.md). Then begin with [Tutorial 1](01-first-project.md).
