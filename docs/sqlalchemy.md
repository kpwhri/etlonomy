# Connect to SQL Server, Oracle, or Databricks

Etlonomy uses sqlalchemy for SQL databases. A dataset uses `sql_table` or `sql_query`, whether the database is SQL
Server, Oracle, Databricks, or another database with an installed sqlalchemy driver. The URL tells sqlalchemy which
driver to use.

If a dataset moves to another database, change its TOML instead of the ETL function. Etlonomy builds the projected SQL
and reports connection errors. The installed driver handles login details and network communication.

## Define shared database connections

When several datasets share a database, give the connection one name. These examples show the pattern. Use the exact URL
required by your installed driver and login method.

```toml
etlonomy_environment = 1
environment = 'prod'

[connections.sql_server_warehouse]
sqlalchemy_url = 'mssql+pyodbc://warehouse.example/analytics?driver=ODBC+Driver+18+for+SQL+Server'
credential_ref = 'env://?username=WAREHOUSE_USER&password=WAREHOUSE_PASSWORD'

[connections.oracle_warehouse]
sqlalchemy_url = 'oracle+oracledb://oracle.example/analytics'
credential_ref = 'env://?username=ORACLE_USER&password=ORACLE_PASSWORD'

[connections.databricks_warehouse]
sqlalchemy_url = 'databricks://workspace.example/analytics'
credential_ref = 'env://?token=DATABRICKS_TOKEN'
```

Etlonomy checks that sqlalchemy can understand the URL. This does not prove the driver is installed or the server can be
reached. Check those separately in a non-production environment.

## Point a dataset to a shared connection

The dataset TOML names the shared connection and table. Application code opens only the catalog:

```toml
etlonomy_manifest = 1

[[datasets]]
canonical_name = 'REFERENCE.REGION'

[[datasets.versions]]
version = 2
valid_from = 2027-07-01
source_type = 'sql_table'
# this name points to one catalog-owned environment connection
connection = 'sql_server_warehouse'
query = 'reference.region'
```

A later version may change `connection` to `oracle_warehouse` or `databricks_warehouse` while preserving
`REFERENCE.REGION` and its logical columns.

## Store an ordinary SQL query

The database product does not change Etlonomy's `sql_query` model:

```toml
source_type = 'sql_query'
connection = 'databricks_warehouse'
query = '''
SELECT
    member_id AS person_id,
    service_dt AS service_date
FROM clinical.claim_line
WHERE is_deleted = false
'''
dependencies = ['CLAIMS.CLAIM_LINE']
```

Aliases provide the logical output names. List the input datasets in `dependencies` because Etlonomy does not try to
understand every SQL dialect well enough to guess lineage.

## Add credentials only when needed

Integrated security, managed identity, driver profiles, and local SQLite often need no credential provider. When a
selected connection has `credential_ref`, register only the lookup schemes your application trusts:

```python
credentials = etlonomy.SchemeCredentialProvider({
    # the environment preset receives the complete env:// reference from the catalog
    'env': etlonomy.EnvironmentCredentialProvider(),
})
provider = etlonomy.CatalogDatasetProvider(
    catalog=catalog,
    credential_provider=credentials,
)
```

Most job tests should still use `TestDatasetProvider`.

## Troubleshoot the connection

- If URL validation fails, correct the catalog TOML first
- If `sqlalchemy` reports an unknown dialect, install the matching driver package
- If credential lookup fails, verify the registered scheme and its non-secret reference
- If a connection or query fails, Etlonomy reports `DatasetProviderError`

Read [SQL datasets](sql.md) to learn how columns and queries are handled. Read [credentials](credentials.md) for lookup
options and the warning about secrets written directly in URLs.

Previous: [credentials](credentials.md) · Next: [CLI reference](cli.md)
