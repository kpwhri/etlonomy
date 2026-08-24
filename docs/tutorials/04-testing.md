# Tutorial 4: test the example safely

Our first test should answer a business question without depending on the CSV, catalog, or working directory. Import
`claims_demo.jobs` to register `cohort.build`, then give the job a small, clear test frame.

Create `tests/test_jobs.py`. The comments motivate each piece of test setup:

```python
from datetime import date

import polars as pl
import pytest

import etlonomy
from claims_demo import jobs  # noqa: F401
from claims_demo.datasets import Datasets


def test_build_cohort_filters_missing_diagnoses() -> None:
    provider = etlonomy.TestDatasetProvider({
        Datasets.CLAIMS.CLAIM_LINE: pl.DataFrame({
            'person_id': [1001, 1002, 1003],
            'diagnosis_code': ['I10', None, 'E11'],
        }),
    })
    runtime = etlonomy.Runtime(
        provider=provider,
        context=etlonomy.ExecutionContext('test', date(2026, 8, 20)),
    )

    result = runtime.run('cohort.build').collect()

    assert result['person_id'].to_list() == [1001, 1003]
```

Run the test with `src/` on the import path. A passing result proves the job can execute entirely from explicit logical
fixtures:

```console
PYTHONPATH=src python -m pytest
```

A passing test does not prove that missing data fails safely. Add a test that leaves out the dataset and confirms that
Etlonomy refuses to search elsewhere:

```python
def test_missing_fixture_never_falls_back_to_catalog() -> None:
    provider = etlonomy.TestDatasetProvider({})
    request = etlonomy.read(Datasets.CLAIMS.CLAIM_LINE, 'person_id')

    with pytest.raises(etlonomy.MissingTestDatasetError):
        provider.read(
            request,
            etlonomy.ExecutionContext(as_of=date(2026, 8, 20)),
        )
```

## Run production-style code with local data

The documentation E2E test deliberately exercises two different paths:

| Path               | Provider                 | Context              | Data                                                       |
|--------------------|--------------------------|----------------------|------------------------------------------------------------|
| Production wiring  | `CatalogDatasetProvider` | `environment='prod'` | CSV, Parquet, and SQLite sources created under `tmp_path`. |
| Isolated unit test | `TestDatasetProvider`    | `environment='test'` | An explicit in-memory polars frame with different IDs.     |

The temporary files act like production data: they use the real catalog and adapters without touching an actual
production system. The isolated test uses person `9001`, while the local production-style data uses `1001` and `1003`.
The different IDs make it clear which provider supplied the input.

The two paths should produce intentionally different identifiers. These conceptual assertions make it impossible to
confuse fake-production rows with the isolated test fixture:

```python
assert production_result['person_id'].to_list() == [1001, 1003]
assert test_result['person_id'].to_list() == [9001]
```

Both calls execute the registered `cohort.build` function through `Runtime.run()`. The production-wiring path is
repeated after the Parquet and SQLite upgrades, while the ETL source file is checked byte-for-byte to ensure it did not
change.

The repository keeps one main acceptance test in `tests/end_to_end/test_documentation_example.py`. It creates the whole
[first project](01-first-project.md) under `tmp_path`, performs the complete
[three-source upgrade](07-migrating-a-source.md), runs the imported ETL, injects its `@requires` dependency, and
verifies lineage and uses. One shared test prevents several nearly identical tutorial projects from becoming
inconsistent.
---

[← SQLite SQL source](03-sql-dataset.md) · [Tutorial home](index.md) · [Next: reusable functions →](05-reusable-functions.md)
