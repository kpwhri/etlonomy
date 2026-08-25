# Use data managed by another Python library

Most Etlonomy datasets belong in the catalog. The catalog gives them a stable name, selects the correct dated source,
and returns a polars `LazyFrame`.

Sometimes another Python library already knows how to find and read a dataset. For example, an application might provide
a source-view object with attributes such as `sv.claims`. Rebuilding that library inside Etlonomy would add work without
helping the ETL job.

An external dataset lets the two libraries share the responsibility:

- Etlonomy records which named dataset the function needs
- Your provider knows how to obtain that dataset
- The function receives the data through an ordinary argument
- A test can pass that argument directly and avoid the provider

## Name the external dataset

First, give the external dataset a stable name:

```python
import etlonomy

MY_CLAIMS = etlonomy.ExternalDatasetId(
    # system selects the provider registered with the runtime
    system='vdwcore',
    # name identifies the resource that people should see in lineage
    name='accessor.vdw_claims',
)
```

The complete identity is `vdwcore:accessor.vdw_claims`. The Python object used in production does not have to be stored in a
variable named `accessor`. The name is a stable label for people reading the dependency graph.

Use a normal catalog `DatasetId` when Etlonomy should manage versions and physical locations. Use
`ExternalDatasetId` when another library owns those details and Etlonomy only needs resolution and lineage.

## Request the columns the function needs

Declare the external input with the same argument name used by the function:

```python
@etlonomy.requires(
    claims=etlonomy.external_read(
        MY_CLAIMS,
        # a short column list documents the part of the external table we depend on
        'person_id',
        'diagnosis_code',
    ),
)
def find_claims(
        cohort: pl.LazyFrame,
        claims: pl.LazyFrame,
) -> pl.LazyFrame:
    """Keep claims belonging to people in the cohort."""
    return claims.join(cohort, on='person_id', how='inner')
```

When `find_claims(cohort)` runs inside `Runtime.run()`, Etlonomy asks the `vdwcore` external provider for
`sv.vdw_claims`. The provider receives the requested columns and decides how to apply them.

## Keep the provider in your project

Etlonomy defines the `ExternalDatasetProvider` protocol but does not include an implementation. The provider belongs in
your application or in a separate integration package because it knows how your source object works.

Here is a small provider for an attribute-based source view:

```python
class SourceViewProvider:
    """Read external datasets from an application-owned source view."""

    def __init__(self, source_view: object) -> None:
        """Use the source view supplied by the application."""
        self._source_view = source_view

    def read(
            self,
            request: etlonomy.ExternalRead,
            context: etlonomy.ExecutionContext,
    ) -> pl.LazyFrame:
        """Resolve one external resource and apply its requested projection."""
        del context

        resources = {
            'accessor.vdw_claims': self._source_view.vdw_claims,
        }
        return resources[request.dataset.name].select(request.columns)
```

An explicit resource table is safer than treating every external string as unrestricted Python attribute access. The
provider can also rename columns, translate errors, or collect a remote query into a `polars` object when that is part
of the application's contract.

## Supply any source-view object

The application chooses the real object when it builds the runtime:

```python
from infrastructure import accessor

runtime = etlonomy.Runtime(
    provider=catalog_provider,
    context=execution_context,
    external_providers={
        # this object may be replaced with a site-specific or locally configured sv
        'vdwcore': SourceViewProvider(source_view=accessor),
    },
)
```

To use a custom source view, construct the same provider with another object:

```python
custom_provider = SourceViewProvider(source_view=my_accessor)
```

Etlonomy never imports `infrastructure` or `accessor` on its own. This keeps connection setup in the application and
prevents a unit test from opening a production connection by accident.

## Pass test data directly

For a focused function test, do not construct a runtime or external provider. Supply the named argument:

```python
claims_df = pl.DataFrame({
    'person_id': [1, 2],
    'diagnosis_code': ['I10', 'E11'],
    'extra_test_column': ['kept', 'kept'],
}).lazy()

result = find_claims(
    cohort_df.lazy(),
    # an explicit value prevents all external resolution
    claims=claims_df,
)
```

Etlonomy passes an explicit argument through unchanged. It does not select columns from it, rename it, or validate its
type. This is normal Python argument behavior and lets a test include supporting columns when necessary.

The behavior is different when a provider performs the read:

| How the value arrives       | Who limits the columns?               |
|-----------------------------|---------------------------------------|
| `CatalogDatasetProvider`    | The catalog adapter                   |
| `TestDatasetProvider`       | `TestDatasetProvider`                 |
| `ExternalDatasetProvider`   | The external provider                 |
| Explicit `claims=claims_df` | Nobody; the value is passed unchanged |

If a test needs to reproduce production projection exactly, select the columns in the test before passing the frame.

## Test the complete runtime without the real library

A complete runtime test should exercise external resolution. It can use a tiny test-only source object whose loader
reads a temporary CSV or Parquet file:

```python
source_view = TestSourceView(
    claims=FileDataset(claims_path, pl.scan_parquet),
    providers=FileDataset(providers_path, pl.scan_csv),
)

runtime = etlonomy.Runtime(
    provider=test_provider,
    context=etlonomy.ExecutionContext(environment='test'),
    external_providers={
        'files': FileExternalDatasetProvider(source_view),
    },
)
```

This checks the Etlonomy routing boundary without requiring VDWCore, LazyBear, a network, or credentials.

## Inspect external lineage

External datasets have separate query methods so existing catalog lineage continues to return only `DatasetId`
objects:

```python
graph = etlonomy.LineageGraph()
graph.add_registry(etlonomy.registry)

print(graph.declared_external_uses('cohort.build'))
print(graph.external_consumers(MY_CLAIMS))
print(graph.external_requirement_consumers(MY_CLAIMS))
```

The command line accepts the namespaced identity too:

```console
etlonomy uses vdwcore:accessor.vdw_claims --module claims_demo.jobs --format json
```

The graph shows `vdwcore:accessor.vdw_claims`, the reusable function that requests it, and each ETL job that lists that
function under `uses`.

Previous: [reusable requirements](requires.md) · Next: [trace lineage](lineage.md)
