# Describe data sources in TOML

Manifest files are the main place where you describe datasets. They answer simple questions:

- What logical name should jobs use?
- Where did the data live on a given date?
- Is the source a file, table, or query?
- Do any source column names need to be renamed?
- Which datasets were used to build a derived dataset?

Etlonomy builds the SQLite catalog from these files. Edit the TOML and rebuild the catalog instead of editing the
catalog database by hand.

## Start with a small manifest

Create `manifests/datasets.toml`:

```toml
# this number lets future Etlonomy versions recognize the TOML format
etlonomy_manifest = 1

[[datasets]]
# this logical identity is what Python jobs will keep using over time
canonical_name = 'REFERENCE.ZIP_CODES'
description = 'Postal codes and their state abbreviations.'

[[datasets.versions]]
# versions are positive integers unique within this logical dataset
version = 1
# an unquoted TOML date becomes a real date value during parsing
valid_from = 2026-01-01
source_type = 'csv'
# a relative path is resolved from the process working directory
source_uri = 'data/zip_codes.csv'

[datasets.versions.options]
# these settings belong to this physical CSV implementation
separator = ','
has_header = true
```

The nested `[[...]]` syntax means “add one item to this array.” One
`[[datasets]]` block may contain several `[[datasets.versions]]` blocks.

## Understand the fields

| Field            | Required?        | Why it exists                                                   |
|------------------|------------------|-----------------------------------------------------------------|
| `canonical_name` | yes              | Gives ETL code one stable uppercase `SUBJECT.DATASET` identity. |
| `description`    | no               | Explains the dataset or source version to readers.              |
| `version`        | yes              | Gives the source version a positive number.                     |
| `valid_from`     | yes              | Marks the first date on which the version is valid.             |
| `valid_to`       | no               | Marks the exclusive end; omission means no scheduled end.       |
| `source_type`    | yes              | Selects CSV, Parquet, SAS, or SQL behavior.                     |
| `source_uri`     | source-dependent | Stores a file path or sqlalchemy connection URL.                |
| `source_root`    | no, files only   | Selects a shared file root stored in the catalog.               |
| `connection`     | no, SQL only     | Selects a shared sqlalchemy connection stored in the catalog.   |
| `credential_ref` | no               | Names a runtime secret lookup without storing the secret.       |
| `query`          | SQL              | Stores a table name or ordinary executable SQL.                 |
| `options`        | no               | Supplies source-specific reader settings.                       |
| `columns`        | no               | Maps logical names to physical names and adds metadata.         |
| `dependencies`   | no               | Declares upstream logical datasets for lineage.                 |

## Map only the column names that differ

```toml
[datasets.versions.columns.person_id]
# the ETL asks for person_id, but this version physically stores member_id
source = 'member_id'
data_type = 'Int64'
nullable = false
description = 'Stable identifier for one person.'
```

Column mappings are optional and **partial by default**. If a logical column has a mapping, Etlonomy reads the source
name and changes it back to the logical name. An unmapped column keeps its own name. Add mappings only for names that
actually differ.

No mapping does not mean the column is invalid. The file or database reader still reports a column that is truly
missing.

## List the inputs to derived data

```toml
[[datasets]]
canonical_name = 'CLAIMS.ENRICHED_CLAIMS'

[[datasets.versions]]
version = 1
valid_from = 2026-09-01
source_type = 'sql_query'
source_uri = 'postgresql+psycopg://warehouse.example/analytics'
query = '''
SELECT
    member_id AS person_id,
    service_dt AS service_date
FROM analytics.claim_line
'''
# Etlonomy does not guess lineage from SQL, so list the input dataset
dependencies = ['CLAIMS.CLAIM_LINE']
```

## Check the TOML before building

```console
etlonomy catalog validate --manifest-dir manifests
```

Validation catches broken TOML, unsupported source types, duplicate names or versions, overlapping dates, unknown
dependencies, missing SQL, and unknown Etlonomy fields. A typo such as `dependecies` produces an error instead of
quietly losing lineage. Keys inside `options` remain open because each reader may accept different settings.

Dependency cycles are checked by date. Validation fails if `A.ONE` depends on `B.TWO` while `B.TWO` depends on `A.ONE`
at the same time. The directions may be reversed in separate date ranges because those versions are never active
together.

Shared roots, connections, and optional environment identity are described in
[environment settings](environments.md).

For date boundaries, continue to [versioning](versioning.md). For complete physical examples, see [files](files.md)
and [SQL](sql.md).

Previous: [logical datasets](datasets.md) · Next:
[understand version resolution](versioning.md)
