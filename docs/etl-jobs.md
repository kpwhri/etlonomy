# Write and run an ETL job

An ETL function should say how to change data. It should not decide where the data lives or how to find a password. The
`@etlonomy.etl` decorator lists the logical data the function needs.

## List the job inputs

```python
import polars as pl

import etlonomy
from claims_demo.datasets import Datasets


@etlonomy.etl(
    name='cohort.build',
    inputs={
        # listing the read here lets Etlonomy show the dependency before a run
        'claims': etlonomy.read(
            Datasets.CLAIMS.CLAIM_LINE,
            # asking only for columns used below keeps the physical read small
            'person_id',
            'diagnosis_code',
        ),
    },
    # outputs tell lineage which logical dataset this job creates
    outputs=(Datasets.COHORT.STUDY_POPULATION,),
)
def build_cohort(claims: pl.LazyFrame) -> pl.LazyFrame:
    """Keep people whose claim contains a diagnosis code."""
    return claims.filter(pl.col('diagnosis_code').is_not_null())
```

The key `claims` must match the function parameter `claims`. Etlonomy checks this during import, so a typo fails before
the job starts.

Job names use dotted lowercase form, such as `cohort.build`. They must be unique in the registry. The registry also
records the function and its source location, which helps inspection and lineage tools.

## Import the job module

Decorators register functions when Python imports their module:

```python
from claims_demo import jobs  # noqa: F401
```

The import registers `cohort.build` with Etlonomy. Import every job module when the application starts, before asking
the runtime to run a job by name.

## Create the provider and runtime

```python
from datetime import date
from pathlib import Path

import etlonomy

# the provider uses the catalog to find and read each source
provider = etlonomy.CatalogDatasetProvider(
    catalog=etlonomy.SQLiteCatalog(Path('.etlonomy/catalog.db')),
)

# one date is used for every dataset read in this run
runtime = etlonomy.Runtime(
    provider=provider,
    context=etlonomy.ExecutionContext(
        as_of=date(2026, 8, 20),
    ),
)
```

## Run the job by name

```python
result = runtime.run('cohort.build')

# collection is explicit because ETL transformations normally remain lazy
cohort = result.collect()
print(cohort)
```

The runtime:

1. Finds the registered job
2. Asks the provider to load every declared read
3. Passes the returned frames to matching function parameters
4. Calls the Python function and returns its result

It also records the reads used during execution. Later, the lineage engine can include dependencies introduced by
reusable helpers.

## Other useful patterns

- A job may have several named inputs
- A job may have no dataset inputs if it genuinely needs none
- A job may return any Python object, though `pl.LazyFrame` is the common case
- An explicitly passed argument replaces automatic loading for that argument
- A helper with its own dataset dependency should use
  [`@etlonomy.requires`](requires.md), not a second `@etl` decorator.

Previous: [environment settings](environments.md) · Next:
[test the ETL without production access](testing.md)
