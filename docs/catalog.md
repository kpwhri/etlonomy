# Build and inspect the SQLite catalog

People edit the TOML files. Etlonomy builds them into a small SQLite database that is quick to read while a job runs.

The catalog stores dataset names, dates, and locations. It does not copy your data. CSV rows, Parquet files, and
database tables stay where they are.

## Check the TOML files

```console
etlonomy catalog validate --manifest-dir manifests
```

Run this early while editing. A validation failure changes nothing on disk.

## Build the catalog

```console
etlonomy catalog build \
  --manifest-dir manifests \
  --database .etlonomy/catalog.db
```

During a build, Etlonomy:

1. Reads TOML files in a repeatable order
2. Checks names, versions, dates, mappings, and dependencies
3. Creates a temporary SQLite database
4. Applies all pending catalog-schema migrations in one transaction
5. Adds the dataset information
6. Checks foreign keys and SQLite integrity
7. Replaces the old catalog only after every step succeeds

The last step protects the working catalog. A bad TOML change cannot replace it with a half-built database.

## Inspect what the catalog contains

```console
# list logical dataset names so we can confirm they were included
etlonomy catalog show --database .etlonomy/catalog.db

# inspect every source version before scheduling a historical run
etlonomy catalog history \
  --database .etlonomy/catalog.db \
  CLAIMS.CLAIM_LINE

# show which source one date will select
etlonomy catalog resolve \
  --database .etlonomy/catalog.db \
  CLAIMS.CLAIM_LINE \
  --as-of 2026-08-20
```

The date is optional. Leave off `--as-of` for the normal current-data lookup; include it when reproducing history.

Build a separate catalog for each environment. For example, development can build
`.etlonomy/dev/catalog.db` while production compiles approved manifests to `.etlonomy/prod/catalog.db`. Dataset versions
do not carry environment selectors. Instead, an optional single environment identity labels the whole catalog. When an
`ExecutionContext` explicitly supplies an environment, the provider verifies that identity; when it supplies `None`, the
check is intentionally skipped.

When a catalog needs a shared file root, shared SQL connection, or an environment identity, supply the optional TOML
configuration during both validation and build:

```console
etlonomy catalog validate \
  --manifest-dir manifests \
  --environment-config environments/prod.toml

etlonomy catalog build \
  --manifest-dir manifests \
  --environment-config environments/prod.toml \
  --database .etlonomy/prod/catalog.db
```

See [environment settings](environments.md) for the complete file and resolution rules.

## Read catalog information from Python

```python
from datetime import date
from pathlib import Path

from etlonomy import DatasetId, SQLiteCatalog

# direct access is useful for inspection tools and release checks
catalog = SQLiteCatalog(Path('.etlonomy/catalog.db'))
claims = DatasetId('CLAIMS', 'CLAIM_LINE')

for version in catalog.get_versions(claims):
    print(version.version, version.valid_from, version.source_type)

# preview the same source choice that the normal provider will make
resolved = catalog.resolve_dataset(claims, date(2026, 8, 20))
print(resolved.source_uri)
```

ETL jobs normally use `CatalogDatasetProvider` instead of calling the catalog directly. The provider checks the
requested columns and reads the actual source.

## Compare an old and new catalog

```console
etlonomy catalog diff .etlonomy/catalog-old.db .etlonomy/catalog.db
```

The diff reports added, removed, and changed logical datasets. It notices changes to dates, source information, column
mappings, options, credential references, and dependencies. Keep the old catalog during a release so you can compare it
with the new one.

## Know when the catalog schema needs a migration

Adding a dataset or source version requires only a TOML change. Add a numbered SQL migration only when Etlonomy changes
the tables inside its catalog, such as adding a field to every dataset version.

Each migration file may contain several statements separated by an explicit marker:

```sql
CREATE TABLE first_table (
    value TEXT
);

-- etlonomy:next-statement

INSERT INTO first_table (value) VALUES ('a semicolon; inside data is safe');
```

Etlonomy uses the marker because a semicolon may appear inside SQL text. If one pending statement fails, all pending
migrations are rolled back together. Etlonomy opens a finished catalog as read-only and asks you to rebuild when its
schema is too old.

Previous: [versioning](versioning.md) · Next:
[compile optional environment settings](environments.md)
