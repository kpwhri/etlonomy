# Tutorial 5: let a helper function request data

We now have three logical datasets:

- claims connect a person to a provider
- providers connect a provider to a region
- regions give each region its readable name

Our job will read claims and providers directly. A helper will add region names. This is a good use of
`@etlonomy.requires` because the helper needs another dataset and future jobs may reuse it.

Etlonomy does not inspect Python to discover every helper call. List `uses=(attach_region,)` on the job so lineage can
show the relationship before a run. Etlonomy separately records the reads from each actual run.

## Step 1: update `jobs.py`

Open `src/claims_demo/jobs.py`. Keep the existing job name, then add provider data and the reusable helper.

```python
import polars as pl

import etlonomy
from claims_demo.datasets import Datasets

# this logical output gives lineage a result to connect to the inputs
COHORT_RESULT = etlonomy.DatasetId('COHORT', 'RESULT')


@etlonomy.requires(
    regions=etlonomy.read(
        # this read belongs to the helper because the helper performs the region join
        Datasets.REFERENCE.REGION,
        'region_id',
        'region_name',
    ),
)
def attach_region(
    providers: pl.LazyFrame,
    regions: pl.LazyFrame,
) -> pl.LazyFrame:
    """Attach a logical region name to each provider."""
    return providers.join(regions, on='region_id', how='left')


@etlonomy.etl(
    name='cohort.build',
    inputs={
        'claims': etlonomy.read(
            Datasets.CLAIMS.CLAIM_LINE,
            'person_id',
            'provider_id',
            'diagnosis_code',
        ),
        'providers': etlonomy.read(
            Datasets.REFERENCE.PROVIDER,
            'provider_id',
            'region_id',
        ),
    },
    # this declaration connects the job to the helper before either one runs
    uses=(attach_region,),
    outputs=(COHORT_RESULT,),
)
def build_cohort(
    claims: pl.LazyFrame,
    providers: pl.LazyFrame,
) -> pl.LazyFrame:
    """Keep diagnosed claims and attach each provider's region."""
    # regions is omitted deliberately; the active Runtime injects that requirement
    enriched_providers = attach_region(providers)
    return (
        claims.filter(pl.col('diagnosis_code').is_not_null())
        .join(enriched_providers, on='provider_id', how='left')
        .select('person_id', 'diagnosis_code', 'region_name')
    )
```

Notice what is absent: no function contains `data/providers.parquet`, `reference.sqlite`, or a connection string. Those
details remain with dataset versions in the catalog.

## Step 2: run the normal application

Importing `claims_demo.jobs` registers both declarations. The `run.py` created in Tutorial 1 can still execute the same
job name:

```console
PYTHONPATH=src python -m claims_demo.run --as-of 2026-08-20
```

The result should be:

```python
{
    'person_id': [1001, 1003],
    'diagnosis_code': ['I10', 'E11'],
    'region_name': ['West', 'East'],
}
```

This run reads CSV, Parquet, and SQLite. The runtime passes claims and providers to the job, then passes regions to
`attach_region()` when the helper is called.

## Step 3: pass helper data directly in a test

A small helper test does not need a runtime. Pass `regions` directly and Etlonomy will not open the catalog.

```python
providers = pl.DataFrame({
    'provider_id': [10],
    'region_id': [100],
}).lazy()
regions = pl.DataFrame({
    'region_id': [100],
    'region_name': ['West'],
}).lazy()

# the explicit regions frame keeps this test small and independent of files or databases
result = attach_region(providers, regions=regions).collect()

assert result['region_name'].to_list() == ['West']
```

## Step 4: inspect the recorded reads

After `Runtime.run('cohort.build')` succeeds, `runtime.last_dependencies` contains all three reads: claims, providers,
and regions. A failed run does not erase the last successful record. Separate execution contexts do not overwrite one
another.

The runtime record describes one run. The `uses` declaration says what the job may call. The next lesson looks at both.

---

[← Testing](04-testing.md) · [Tutorial home](index.md) · [Next: lineage →](06-lineage.md)
