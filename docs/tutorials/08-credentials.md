# Tutorial 8: look up database credentials

You do not need credentials for the SQLite lesson. Use this lesson when a database administrator gives you a server URL
and environment-variable names.

## Step 1: decide whether datasets share a connection

One dataset may keep its full sqlalchemy URL in `source_uri`. When several datasets use the same database, define the
connection once in environment TOML:

```toml
etlonomy_environment = 1
environment = 'prod'

[connections.warehouse]
sqlalchemy_url = 'postgresql+psycopg://warehouse.example/analytics'
credential_ref = 'env://?username=WAREHOUSE_USER&password=WAREHOUSE_PASSWORD'
```

The dataset selects it without repeating the URL:

```toml
source_type = 'sql_table'
connection = 'warehouse'
query = 'reference.regions'
```

Build with `--environment-config environments/prod.toml`. The catalog receives the URL and credential reference, while
the actual username and password remain outside it.

You may put credentials directly in `sqlalchemy_url` for a small internal workflow. Etlonomy may display the URL exactly
as written, so do this only when catalog and command-line users are allowed to see the value.

## Step 2: change only the dataset version

The database location and credential reference both describe the source, so keep them on its version. Moving the source
then requires a TOML change instead of edits across Python modules.

```toml
[[datasets.versions]]
version = 2
valid_from = 2027-01-01
source_type = 'sql_table'
source_uri = 'postgresql+psycopg://warehouse.example/analytics'
query = 'reference.regions'
credential_ref = 'env://?username=WAREHOUSE_USER&password=WAREHOUSE_PASSWORD'
```

The manifest contains variable names, not a username or password value.

## Step 3: allow a credential lookup method

A credential reference is only text until the application registers a provider for its scheme. Register the built-in
environment provider instead of letting TOML load arbitrary Python code.

```python
credentials = etlonomy.SchemeCredentialProvider({
    # only schemes registered by application startup are allowed to resolve secrets
    'env': etlonomy.EnvironmentCredentialProvider(),
})
```

Registration is deliberate. A typo such as `enb://...` fails instead of silently running unknown code.

## Step 4: give the provider to catalog access

The catalog provider opens the database, so give the credential provider to it. ETL functions still receive only logical
`LazyFrame` arguments.

```python
provider = etlonomy.CatalogDatasetProvider(
    catalog=etlonomy.SQLiteCatalog(Path('.etlonomy/catalog.db')),
    # credential-free versions continue to work without consulting this object
    credential_provider=credentials,
)
```

Nothing changes in the ETL function. It still reads
`Datasets.REFERENCE.REGION`.

## Step 5: test without real secrets

Tests of connection construction need predictable credentials, but they should never read a developer's environment or
KeePass database. A mapping provider supplies explicit values under a harmless fixture reference.

```python
credentials = etlonomy.MappingCredentialProvider({
    # a named fixture proves connection construction without touching a real secret store
    'fixture://regions': etlonomy.ResolvedCredential(
        username='student',
        password='safe-test-value',
    ),
})
```

Use this preset to test SQL connection construction. For ETL logic, use
`TestDatasetProvider` and a polars frame, which skip files and databases.

## Step 6: add an organization-specific provider

Many organizations already have a vault client. Implement the small interface that turns your reference string into a
`ResolvedCredential`.

```python
class CampusVaultProvider:
    """Resolve credentials through the campus vault client."""

    def resolve(self, reference: str) -> etlonomy.ResolvedCredential:
        """Return the record identified by the complete reference."""
        # your organization decides how this string maps to a record
        record = campus_vault.read(reference)
        return etlonomy.ResolvedCredential(
            username=record.username,
            password=record.password,
        )
```

Register it under a scheme such as `campus-vault`. Etlonomy passes the whole reference to your class without assuming
what it means.

Read the full [credential guide](../credentials.md) for KeePass profiles and error behavior.

---

[← Source migration](07-migrating-a-source.md) · [Tutorial home](index.md) · [Next extension: SAS7BDAT →](09-sas7bdat.md)
