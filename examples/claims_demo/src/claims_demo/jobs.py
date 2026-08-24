"""ETL and reusable helper for the completed tutorial project."""

import polars as pl

import etlonomy
from claims_demo.datasets import Datasets

COHORT_RESULT = etlonomy.DatasetId('COHORT', 'RESULT')


@etlonomy.requires(
    regions=etlonomy.read(
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
    uses=(attach_region,),
    outputs=(COHORT_RESULT,),
)
def build_cohort(
        claims: pl.LazyFrame,
        providers: pl.LazyFrame,
) -> pl.LazyFrame:
    """Keep diagnosed claims and attach each provider's region."""
    enriched_providers = attach_region(providers)
    return (
        claims.filter(pl.col('diagnosis_code').is_not_null())
        .join(enriched_providers, on='provider_id', how='left')
        .select('person_id', 'diagnosis_code', 'region_name')
    )
