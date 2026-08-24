# Read data from CSV, Parquet, and SAS7BDAT files

Files are often the easiest way to start. They need no database server or credentials. Etlonomy can still give them
logical names, keep dated versions, select requested columns, and rename source columns.

## Choose a file format

| Format   | A sensible reason to choose it                                       | Important trade-off                                               |
|----------|----------------------------------------------------------------------|-------------------------------------------------------------------|
| CSV      | Humans and many tools can create it easily.                          | Types must be inferred or configured, and large reads are slower. |
| Parquet  | Analytics workloads benefit from columnar storage and typed schemas. | It is not intended for manual editing.                            |
| SAS7BDAT | A legacy SAS workflow already produces it.                           | Reading may be eager and needs an optional dependency.            |

The logical ETL code is the same regardless of this choice.

## Add a CSV source

```toml
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
# keeping the path in the manifest lets a later version move without changing Python
source_uri = 'data/claim_line.csv'

[datasets.versions.options]
# these options document assumptions that otherwise hide inside reader code
separator = ','
has_header = true
```

Etlonomy normally uses `pl.scan_csv()`. If a job asks for two columns, those two columns are selected in the lazy plan.

CSV options can describe a tab separator, a file with no header, or other supported polars scan settings. Keep these
settings on the CSV version because a later Parquet version will not use them.

## Share a folder when several files use it

Direct relative and absolute paths remain valid. If several datasets share a deployment directory, define it once in an
optional environment TOML file:

```toml
[roots.claims]
base_uri = 'D:/production-data/claims'
```

Select it from the dataset version:

```toml
source_type = 'parquet'
source_root = 'claims'
source_uri = 'claim_line.parquet'
```

Etlonomy joins the relative `source_uri` beneath the named root and rejects attempts to escape it with `..`. There is no
default root. When `source_root` is absent, a relative path continues to use the process working directory.

## Add a Parquet source

```toml
[[datasets.versions]]
version = 2
valid_from = 2026-09-01
source_type = 'parquet'
# Parquet can replace CSV while preserving the same logical dataset and columns
source_uri = 'data/claim_line.parquet'
```

Parquet stores data by column, so it can efficiently read the requested columns. Etlonomy returns a `LazyFrame` and does
not collect the whole file during a normal read.

## Rename source columns

Suppose an old file contains `member_id` and `svc_dt`, but application code should use clearer names:

```toml
[datasets.versions.columns.person_id]
# the source column is selected and immediately aliased to the logical name
source = 'member_id'

[datasets.versions.columns.service_date]
source = 'svc_dt'
```

The ETL still writes:

```python
claims.select(
    # the job uses the same names for every source version
    'person_id',
    'service_date',
)
```

A newer version may map `service_date` to `service_dt` instead. Both versions present the same logical output.

Mappings are partial. If only `service_date` has a mapping, `person_id` and `diagnosis_code` keep their own names. Add a
mapping only when a source name differs from the name your jobs use.

## Add a SAS7BDAT source

Install the optional reader:

```console
python -m pip install 'etlonomy[sas]'
```

Then describe the file:

```toml
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
source_type = 'sas7bdat'
source_uri = 'data/claim_line.sas7bdat'

[datasets.versions.columns.person_id]
# map the old source name to the clearer name used by jobs
source = 'MEMBER_ID'
```

SAS reading may be eager. Etlonomy still asks for only the needed source columns when the reader supports it, changes
their names, and returns a polars `LazyFrame` to the job.

## Understand common errors

- A missing path becomes `DatasetProviderError`
- A requested column missing from the source becomes a provider error when the reader checks the columns
- A missing source column found while reading is reported as a provider error
- Relative paths use the process working directory, so production projects should start from a known project folder or
  use absolute paths

Previous: [lineage](lineage.md) · Next: [read SQL datasets](sql.md)
