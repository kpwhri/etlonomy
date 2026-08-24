# Optional extension B: move SQLite to a remote SQL database

Tutorial 7 moved claims into SQLite. A team might later move the same logical table to SQL Server, Oracle, Databricks,
or another database with a sqlalchemy driver. Etlonomy uses the same `sql_table` and `sql_query` source types for all of
them.

## Step 1: define the shared connection

Choose the URL that matches the driver your team installs. For example, an environment file might contain one of these:

```toml
[connections.claims_database]
# SQL Server is one possible destination
sqlalchemy_url = 'mssql+pyodbc://warehouse.example/analytics?driver=ODBC+Driver+18+for+SQL+Server'
credential_ref = 'env://?username=WAREHOUSE_USER&password=WAREHOUSE_PASSWORD'
```

```toml
[connections.claims_database]
# Oracle uses the same catalog-owned connection pattern
sqlalchemy_url = 'oracle+oracledb://oracle.example/analytics'
credential_ref = 'env://?username=ORACLE_USER&password=ORACLE_PASSWORD'
```

```toml
[connections.claims_database]
# a Databricks sqlalchemy driver is another possible destination
sqlalchemy_url = 'databricks://workspace.example/analytics'
credential_ref = 'env://?token=DATABRICKS_TOKEN'
```

These examples show the pattern, not a URL that works for every setup. Check the installed driver's documentation for
the exact URL and login method.

## Step 2: add a new dataset version

The claims manifest selects the shared connection instead of repeating its URL:

```toml
[[datasets.versions]]
version = 4
valid_from = 2028-01-01
source_type = 'sql_table'
connection = 'claims_database'
query = 'clinical.claim_line'
```

The connection name and table stay in TOML. `build_cohort()` still asks for
`Datasets.CLAIMS.CLAIM_LINE` and the same logical columns.

## Step 3: test without making remote access part of normal CI

Run business-rule tests with `TestDatasetProvider`, just as Tutorial 4 did. Add a live integration test only when a
dedicated test database is explicitly configured. This helps separate job problems from driver, credential, server, or
table problems.

The repository's default test suite validates example sqlalchemy URL shapes for SQL Server, Oracle, and Databricks
without connecting to any of them.

Read [sqlalchemy connection examples](../sqlalchemy.md) and [credentials](../credentials.md) before putting protected
URLs into an environment catalog.

---

[← Credentials](08-credentials.md) · [Tutorial home](index.md) · [Back to documentation home](../index.md)
