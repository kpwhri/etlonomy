# Store shared paths and connections in the catalog

Several datasets may share one folder or database. You can repeat that location in every dataset version, but then a
move requires many TOML edits.

An optional environment TOML file defines a shared folder or connection once. Etlonomy copies it into the catalog during
the normal build. Application code still opens only the catalog.

You do not need an environment file when every dataset uses a direct path or direct sqlalchemy URL.

## Optionally name the environment

Create `environments/prod.toml`:

```toml
# this version lets Etlonomy reject incompatible environment-file syntax
etlonomy_environment = 1

# identity is optional; when present, a caller may explicitly validate it
environment = 'prod'
```

Build it together with the manifests:

```console
etlonomy catalog validate \
  --manifest-dir manifests \
  --environment-config environments/prod.toml

etlonomy catalog build \
  --manifest-dir manifests \
  --environment-config environments/prod.toml \
  --database .etlonomy/prod/catalog.db
```

The generated catalog now identifies itself as `prod`. The setting is metadata, not a secret.

## Check the environment name only when requested

Most code can let the selected catalog determine its environment:

```python
context = etlonomy.ExecutionContext()
```

No comparison occurs when `environment` is omitted. If deployment code wants an extra safety check, supply it:

```python
context = etlonomy.ExecutionContext(environment='prod')
```

Etlonomy then requires the catalog to be named `prod`. A `dev` catalog, or a catalog with no name, fails before any
source is opened. Leave the name out when you do not need this extra check.

## Share a folder between file datasets

Suppose several claim files live below the same directory. Add one root:

```toml
[roots.claims]
# a root may be an absolute filesystem path or a file URI
base_uri = 'D:/production-data/claims'
```

Then let a dataset select it:

```toml
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'parquet'
source_root = 'claims'
source_uri = 'claim_line.parquet'
```

The resolved path is:

```text
D:/production-data/claims/claim_line.parquet
```

`source_uri` must be relative when `source_root` is present. Etlonomy rejects `..` paths that would escape the root.

There is no default root. Without `source_root`, an absolute path stays absolute and a relative path remains relative to
the process working directory.

## Share a database connection

Define a shared connection location. This example keeps secrets behind a reference:

```toml
[connections.claims_database]
sqlalchemy_url = 'mssql+pyodbc://claims-server/claims'
credential_ref = 'env://?username=CLAIMS_USER&password=CLAIMS_PASSWORD'
```

Reference it from a SQL dataset:

```toml
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'sql_table'
connection = 'claims_database'
query = 'dbo.claim_line'
```

For SQL, choose exactly one connection form:

- `source_uri` for a direct sqlalchemy URL
- `connection` for a shared entry in the catalog

Do not declare both. If the shared connection contains `credential_ref`, the dataset version must not declare a second
one. Etlonomy rejects both together because it should not have to guess which one wins.

## Know what the catalog stores

The generated SQLite catalog contains plural `roots` and `connections` tables. It stores paths, sqlalchemy URLs, and
credential references. Values resolved through `credential_ref` stay outside it.

Etlonomy also permits a username, password, or token directly inside `sqlalchemy_url`. If you use that form, the catalog
stores and may display the URL exactly as written. Do not assume sqlalchemy's usual redacted object representation will
redact raw Etlonomy metadata. Use an integrated-security URL or `credential_ref` when catalog readers should not see the
secret.

Catalog diff includes changes to the environment name, folders, and connections, even when logical dataset names stay
the same.

The root, connection, environment-validation, and direct-path examples on this page are executed by
`tests/integration/test_environment_catalog.py`.

Previous: [catalog construction](catalog.md) · Next: [declare ETL jobs](etl-jobs.md)
