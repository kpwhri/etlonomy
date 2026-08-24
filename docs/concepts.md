# How Etlonomy thinks about data

Etlonomy solves one main problem: ETL code should not need to change just because data moved.

Imagine that an analyst writes a cohort job using a claims table. Today the table is a CSV file. Next semester it
becomes Parquet. Later, the organization moves it to SQL Server. The analyst's business rule—“keep claims with a
diagnosis code”—did not change, so the Python transformation should not change either.

To do this, Etlonomy keeps two ideas separate:

- the **logical dataset** says what the data means
- the **source version** says where the data lived during a period of time

## A logical dataset is a stable name

```python
claim_line = etlonomy.DatasetId('CLAIMS', 'CLAIM_LINE')
```

This produces the logical name `CLAIMS.CLAIM_LINE`. It does not mention a file, table, password, or server. The job asks
for claims data, while the catalog handles where that data lives.

In normal application code, use a generated identifier:

```python
from claims_demo.datasets import Datasets

# we use the generated name so a spelling mistake is caught by Python immediately
claim_line = Datasets.CLAIMS.CLAIM_LINE
```

See [logical datasets and generated names](datasets.md) for the generation step.

## A read asks for specific columns

A read combines a logical dataset with the logical columns a function needs:

```python
request = etlonomy.read(
    Datasets.CLAIMS.CLAIM_LINE,
    # requesting only useful columns reduces file I/O and database work
    'person_id',
    'service_date',
)
```

Etlonomy rejects empty reads and duplicate column names. When the source supports it, Etlonomy asks the source for only
these columns instead of loading everything first.

You may pin a source version with `version=1`, but the usual choice is to let an execution date select the correct
version.

## The execution context selects a date and environment

```python
from datetime import date

context = etlonomy.ExecutionContext(
    # this date makes a historical rerun choose the same source version
    as_of=date(2026, 8, 20),
)
```

`as_of` selects the source version for that date. Leave it out to use today's version. If all versions have ended,
Etlonomy uses the one that started most recently. `environment` is optional too. Supply it when you want Etlonomy to
confirm that you opened the catalog for the expected environment.

## A provider loads the requested data

There are two main providers:

- `CatalogDatasetProvider` finds production-style files and databases
- `TestDatasetProvider` exposes only frames supplied by the test

They stay separate for safety. If test data is missing, the test provider raises an error. It never tries a production
catalog.

## Decorators say which data code uses

`@etlonomy.etl` marks a top-level job and lists its direct inputs and outputs.
`@etlonomy.requires` is for reusable helpers that need an additional dataset. The runtime resolves those declarations,
calls the functions, and records what was read.

The full process looks like this:

```text
logical name + requested columns + execution date
                         |
                         v
                dated source version
                         |
                         v
             projected polars LazyFrame
```

TOML describes the sources. The catalog stores that information. A provider loads the selected source. The ETL function
can then focus on changing the data.

Previous: [getting started](getting-started.md) · Next:
[define logical datasets](datasets.md)
