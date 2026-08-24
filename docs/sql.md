# Read database tables and queries

Put the database location on the **dataset version**, not inside the Python function. If the data moves, update the TOML
and rebuild the catalog. The ETL job does not change.

## Put a sqlalchemy URL in the TOML

```toml
[[datasets]]
canonical_name = 'REFERENCE.REGION'

[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'sql_table'
source_uri = 'sqlite:///data/reference.sqlite'
query = 'regions'
```

`source_uri` is a normal sqlalchemy URL. For `sql_table`, `query` is the table or view name.

## Create the normal catalog provider

There is no SQLite executor to write:

```python
from pathlib import Path

import etlonomy

provider = etlonomy.CatalogDatasetProvider(
    catalog=etlonomy.SQLiteCatalog(Path('.etlonomy/catalog.db')),
)
```

Etlonomy opens this URL only when the dataset is read. Reading CSV or Parquet does not create a database engine.

## Ask for logical columns

```python
request = etlonomy.read(
    Datasets.REFERENCE.REGION,
    'region_id',
    'region_name',
)
```

Etlonomy sends SQL that selects only those columns:

```sql
SELECT [region_id], [region_name] FROM [regions]
```

## Store a query in the dataset version

Use `sql_query` for joins, filters, or aliases. Etlonomy wraps the stored SQL with another query that selects the
requested columns. List dependencies in TOML because Etlonomy does not guess lineage from SQL.

If SQLite later moves to SQL Server, add a new version:

```toml
[[datasets.versions]]
version = 2
valid_from = 2027-07-01
source_type = 'sql_table'
source_uri = 'mssql+pyodbc://warehouse.example/analytics?driver=ODBC+Driver+18+for+SQL+Server'
query = 'reference.regions'
credential_ref = 'env://?username=WAREHOUSE_USER&password=WAREHOUSE_PASSWORD'
```

The URL and credential reference changed in one catalog-controlled place. The ETL still asks for `REFERENCE.REGION`.

## Share a connection between datasets

When several datasets use the same database, define the sqlalchemy URL once in the optional environment TOML:

```toml
[connections.analytics]
sqlalchemy_url = 'mssql+pyodbc://warehouse.example/analytics'
credential_ref = 'env://?username=WAREHOUSE_USER&password=WAREHOUSE_PASSWORD'
```

Then select it from a dataset version:

```toml
source_type = 'sql_table'
connection = 'analytics'
query = 'reference.regions'
```

Use either a direct `source_uri` or a shared `connection`, never both. Etlonomy stores the connection location and the
credential reference in the catalog. It does not store the username, password, or token returned by the credential
provider. Application code still creates only `CatalogDatasetProvider(catalog=...)`.

A URL may contain `username:password@host`. Etlonomy stores and may display that URL exactly as written. Use integrated
security or `credential_ref` when the TOML, catalog, command output, or logs should not contain the secret. See the
[credential guide](credentials.md) for lookup examples.

If your database uses integrated security, omit `credential_ref`. If it needs runtime secrets,
read [credential references](credentials.md).

Next: [build the SQLite tutorial source](tutorials/03-sql-dataset.md).
