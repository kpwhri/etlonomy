# Choose a data source by date

Versions answer one question: **which source should this run use?**

A job rerun for August should not suddenly read a database introduced in September. Etlonomy uses the run's `as_of`
date to choose a source version.

Most runs can leave out `as_of`. Etlonomy then uses today's version. If every version has ended, it uses the version
that started most recently. Supply `as_of` when you need to repeat an old run or check a source changeover.

## Include the start date and exclude the end date

Each interval includes `valid_from` and excludes `valid_to`:

```text
[valid_from, valid_to)
```

Here is a source migration:

```toml
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
# September 1 is not part of version 1
valid_to = 2026-09-01
source_type = 'parquet'
source_uri = 'data/claim_line.parquet'

[[datasets.versions]]
version = 2
# September 1 is the first day of version 2
valid_from = 2026-09-01
source_type = 'sql_table'
source_uri = 'mssql+pyodbc://warehouse.example/analytics'
query = 'analytics.claim_line'
```

This rule gives one clear result on the changeover date:

| Requested `as_of` date | Result           |
|------------------------|------------------|
| 2026-08-31             | version 1        |
| 2026-09-01             | version 2        |
| before 2025-01-01      | no valid version |

An omitted `valid_to` means “there is no planned ending date.” It does not mean the source is guaranteed to exist
forever; a later manifest may add its end.

## Allow gaps but not overlaps

A gap can be meaningful. Perhaps a study feed was unavailable during a month. A date in that gap raises
`DatasetVersionNotFoundError`.

Overlaps are rejected because Etlonomy would have two possible sources for the same date. An end date that is equal to
or earlier than the start date is also rejected.

## Preview the selected source

```console
etlonomy catalog resolve \
  --database .etlonomy/catalog.db \
  CLAIMS.CLAIM_LINE \
  --as-of 2026-09-01
```

Use this before a production rerun to see the selected version, source type, location, query, column mappings, and
non-secret credential reference.

## Pin a version only when you need to

```python
request = etlonomy.read(
    Datasets.CLAIMS.CLAIM_LINE,
    'person_id',
    # pinning reproduces version 1 even if the execution date would select version 2
    version=1,
)
```

Pinning can help with an audit, comparison, or backfill. Normal jobs should usually use dates. A forgotten pin can keep
a job on an old source after a planned move.

## Remember that dates choose the version

The integer gives humans a concise label. The interval determines normal selection. Version numbers do not need to
encode dates, and a higher version is not chosen merely because it is higher.

Previous: [TOML manifests](manifests.md) · Next:
[compile the catalog](catalog.md)
