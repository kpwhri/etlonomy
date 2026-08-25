# Let a helper function request data

Several jobs may use the same helper to add provider specialties. Passing the provider data through every function can
be awkward. Opening a database inside the helper hides what it uses and makes tests risky.

`@etlonomy.requires` lists the helper's data clearly. During a normal run, Etlonomy can load that data and pass it to
the helper automatically.

## List the helper's data

```python
import polars as pl

import etlonomy
from claims_demo.datasets import Datasets


@etlonomy.requires(
    # the argument name must match the providers parameter below
    providers=etlonomy.read(
        Datasets.REFERENCE.PROVIDER,
        'provider_id',
        'specialty',
    ),
)
def attach_specialty(
        claims: pl.LazyFrame,
        providers: pl.LazyFrame,
) -> pl.LazyFrame:
    """Attach the canonical provider specialty to each claim."""
    return claims.join(providers, on='provider_id', how='left')
```

When an ETL calls `attach_specialty(claims)` during `Runtime.run()`, Etlonomy sees that `providers` was not supplied. It
loads the dataset with the active provider and records the read.

## Tell Etlonomy which helper a job calls

Etlonomy does not inspect Python code to guess which helpers may run. When a job calls a helper that requests data, list
that helper in `uses`:

```python
@etlonomy.etl(
    name='claims.build',
    inputs={
        'claims': etlonomy.read(
            Datasets.CLAIMS.CLAIM_LINE,
            'person_id',
            'provider_id',
        ),
    },
    # this declaration makes the helper and its provider dataset visible before a run
    uses=(attach_specialty,),
)
def build_claims(claims: pl.LazyFrame) -> pl.LazyFrame:
    """Build claims enriched with provider information."""
    return attach_specialty(claims)
```

A reusable helper can use another `@requires` helper in the same way:

```python
@etlonomy.requires(
    uses=(attach_specialty,),
    diagnoses=etlonomy.read(
        Datasets.REFERENCE.DIAGNOSIS,
        'diagnosis_code',
        'description',
    ),
)
def enrich_claims(
    claims: pl.LazyFrame,
    diagnoses: pl.LazyFrame,
) -> pl.LazyFrame:
    """Attach specialty and diagnosis descriptions."""
    return attach_specialty(claims).join(
        diagnoses,
        on='diagnosis_code',
        how='left',
    )
```

Only functions decorated with `@requires` belong in `uses`. A helper that only changes arguments it receives adds no new
dataset to record. Etlonomy reports duplicate or invalid functions instead of building an incomplete graph.

`uses` says what the code may call. A runtime record says what one run actually read. The results can differ when a
helper runs only under certain conditions or a test supplies its data directly.

## Supply the helper data directly in a test

```python
# a tiny frame keeps this test about join behavior, not catalog configuration
test_providers = pl.DataFrame({
    'provider_id': [10],
    'specialty': ['cardiology'],
}).lazy()

result = attach_specialty(
    test_claims,
    # an explicit value wins, so no provider, file, or database is contacted
    providers=test_providers,
)
```

Passing `providers` directly skips catalog lookup. This makes the helper easy to test and lets other Python code call it
without a running Etlonomy job.

An explicit value is passed through unchanged. Etlonomy does not remove extra columns from it. In contrast,
`TestDatasetProvider` and catalog providers select the columns named by the `Read` request.

If another Python library owns the requested dataset, use an external read instead of importing that library inside the
helper. The [external dataset guide](external-datasets.md) shows how `claims=claims_df` still bypasses the external
provider during a test.

## Accept an external site's source view

Sometimes a reusable function is distributed to a site that has a source-view object but
does not construct an Etlonomy runtime. An `ExternalProviderBinding` can build the
function's external provider from an ordinary argument such as `sv`:

```python
@etlonomy.requires(
    external_provider_bindings={
        'company_data': etlonomy.ExternalProviderBinding(
            argument='sv',
            factory=CompanyDataProvider,
        ),
    },
    claims=etlonomy.external_read(CUSTOM_CLAIMS, 'person_id'),
)
def attach_external_claims(
        cohort: pl.LazyFrame,
        claims: pl.LazyFrame,
        *,
        sv: CompanyWarehouse | None = None,
) -> pl.LazyFrame:
    del sv
    return claims.join(cohort, on='person_id', how='inner')


result = attach_external_claims(cohort, sv=site_source_view)
```

The call-bound provider is inherited by nested `@requires` helpers. Explicit dataset
arguments still take precedence, and omitting `sv` still allows an active runtime to
supply its registered provider. See [external provider bindings](external-datasets.md#bind-a-provider-from-a-function-argument)
for the complete provider contract and resolution order.

## Choose the right decorator

- Use `@etlonomy.etl` for a top-level named job with declared outputs
- Use `@etlonomy.requires` for a reusable helper that needs extra logical data
- Use no decorator for a pure helper that only transforms arguments it receives

Do not put both decorators on one function. A function is either a named job or a reusable helper.

Calling a `@requires` helper without its data and outside an active runtime raises `RegistryError`. Etlonomy does not
silently find a production provider.

Previous: [safe testing](testing.md) · Next:
[use an external dataset](external-datasets.md)
