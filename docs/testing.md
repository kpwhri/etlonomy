# Test ETL code without touching production

A good unit test answers a business question such as “does this job remove claims with no diagnosis?” It should not need
a network, production password, shared drive, or current production catalog.

`TestDatasetProvider` enforces this rule in code. It is not just something the team has to remember.

## Give the test only the data it needs

```python
from datetime import date

import polars as pl

import etlonomy
from claims_demo import jobs  # noqa: F401
from claims_demo.datasets import Datasets


def test_build_cohort_keeps_rows_with_a_diagnosis() -> None:
    # these rows are intentionally small enough that the expected behavior is obvious
    claims = pl.DataFrame({
        'person_id': [1001, 1002],
        'diagnosis_code': ['I10', None],
    })

    provider = etlonomy.TestDatasetProvider({
        # the logical identifier matches the job declaration, but no catalog is opened
        Datasets.CLAIMS.CLAIM_LINE: claims,
    })
    runtime = etlonomy.Runtime(
        provider=provider,
        # the context keeps the runtime API consistent even though fixtures have no versions
        context=etlonomy.ExecutionContext('test', date(2026, 8, 20)),
    )

    result = runtime.run('cohort.build').collect()

    # asserting the business result makes this test useful during later source migrations
    assert result['person_id'].to_list() == [1001]
```

Production and tests run the same ETL function. Only the provider changes.

## Stop when test data is missing

If a declared dataset was not supplied, Etlonomy raises
`MissingTestDatasetError` immediately:

```python
# an empty provider must fail instead of searching for a production fallback
provider = etlonomy.TestDatasetProvider({})

with pytest.raises(etlonomy.MissingTestDatasetError):
    provider.read(request, context)
```

If the test frame lacks a requested column, the provider raises `MissingTestColumnError`. These errors usually mean the
test data needs to be updated for a change in the job.

## Know what the test provider blocks

`TestDatasetProvider`:

- accepts explicit `pl.DataFrame` and `pl.LazyFrame` fixtures
- selects only the requested logical columns
- never reads a catalog
- never creates a SQL connection
- never inspects environment variables or credentials
- never delegates to another provider

A missing test frame can never turn a unit test into a production read.

## Pick the right kind of test

- **Unit test:** supply polars frames and verify transformation behavior
- **Adapter integration test:** use a temporary CSV, Parquet file, or SQLite database to check real reading and column
  selection
- **End-to-end test:** create a temporary project, build its catalog, import the job, run it, and check the result
- **Live-system test:** run only when a real remote database is explicitly configured, never in default CI

Mock the sqlalchemy engine or SAS reader only in small tests of those readers. Real SAS integration tests use the files
under `tests/fixtures/`. End-to-end migration tests create their SQL replacement in a temporary directory. Most tests of
business rules should not need to know how either source is opened.

Previous: [ETL jobs](etl-jobs.md) · Next:
[add reusable requirements](requires.md)
