# Load a dataset through your own Python provider

Most datasets can be loaded by Etlonomy's built-in CSV, Parquet, SAS, or sqlalchemy
readers. Sometimes your organization already has a Python library that knows how to
load a dataset. Replacing that library would create extra work and could remove useful
behavior.

An `ExternalDatasetId` lets you keep using that loader. In this name, **external means
external to Etlonomy's built-in readers**. The data can still be an ordinary internal
dataset owned by your organization.

Once it is declared, the dataset behaves like every other dataset in lineage:

- `uses()` reports it
- `consumers()` finds jobs that use it
- `parents()` and `ancestors()` include it when it feeds an output
- `children()` and `descendants()` show what depends on it
- `etlonomy uses` and `etlonomy lineage` accept its name

The only special part is loading. Etlonomy needs your provider because it does not know
how to call the other library.

## Decide whether you need a custom provider

Use a normal `DatasetId` when Etlonomy should read the physical source described in a
TOML manifest. This gives you catalog versions, date-based source selection, shared
roots, and shared sqlalchemy connections.

Use an `ExternalDatasetId` when another Python API should perform the read. For example,
your organization may have an object such as `warehouse.claims` with its own `load()`
method.

```python
import etlonomy

CUSTOM_CLAIMS = etlonomy.ExternalDatasetId(
    # system chooses one provider from Runtime.external_providers
    system='company_data',
    # name identifies the resource inside that provider
    name='warehouse.claims',
)
```

The complete name is `company_data:warehouse.claims`. Use a stable, readable name because
people will see it in logs, command output, and lineage graphs. Do not put a password,
token, or connection string in the name.

## Declare the columns your function needs

Use `external_read()` in the same place where you would normally use `read()`:

```python
@etlonomy.requires(
    claims=etlonomy.external_read(
        CUSTOM_CLAIMS,
        # naming only the needed columns makes the dependency easier to understand
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

During `Runtime.run()`, Etlonomy sends this request to the provider registered as
`company_data`. It also records `company_data:warehouse.claims` as a normal dataset use.

## Write a small provider in your application

Etlonomy supplies the `ExternalDatasetProvider` interface, but your application supplies
the implementation. That class is the bridge between a stable Etlonomy name and the
library that already knows how to read the data.

```python
class CompanyDataProvider:
    """Read the company datasets that this application is allowed to use."""

    def __init__(self, warehouse: CompanyWarehouse) -> None:
        """Use the warehouse object chosen by the application."""
        self._resources = {
            'warehouse.claims': warehouse.claims,
            'warehouse.providers': warehouse.providers,
        }

    def read(
            self,
            request: etlonomy.ExternalRead,
            context: etlonomy.ExecutionContext,
    ) -> pl.LazyFrame:
        """Load one named resource and return the columns that were requested."""
        del context
        resource = self._resources[request.dataset.name]
        return resource.load().select(list(request.columns))
```

The explicit `_resources` dictionary is useful. It documents what the application can
load and prevents a misspelled name from reaching an unrelated Python attribute. It is
safer than passing the name to `eval()` or unrestricted `getattr()`.

## Follow a clear provider contract

The Python interface intentionally returns `object`. Etlonomy does this because another
library may return a polars frame, a lazy query, or its own table object. The freedom is
useful, but your integration still needs a simple agreement.

For each provider, write down and test these decisions:

- **Return one predictable type.** If production returns a `pl.LazyFrame`, tests should
  normally supply a `pl.LazyFrame` too. A test that uses a very different object may miss
  a real compatibility problem.
- **Use the requested columns.** Apply `request.columns` before returning when the source
  supports projection. If the source cannot do that, explain the limitation in the
  provider's documentation.
- **Use an explicit resource list.** Report an unknown resource clearly instead of
  silently choosing another table.
- **Translate confusing errors.** A provider can catch a library-specific lookup or
  connection error and raise `DatasetProviderError` with the stable dataset name.
- **Decide how context works.** The provider receives `ExecutionContext`. It may use the
  environment or date, or it may ignore them. Make that choice clear instead of letting
  it happen by accident.
- **Keep setup outside Etlonomy.** The application may pass a custom source object,
  session, or client into the provider. Etlonomy does not import a default object or open
  a connection on its own.

Etlonomy cannot enforce column projection or the return type because it does not own the
other library. These checks belong in the provider's tests.

## Add the provider to the runtime

The `system` part of the dataset name selects the provider:

```python
runtime = etlonomy.Runtime(
    provider=catalog_provider,
    context=etlonomy.ExecutionContext(environment='prod'),
    external_providers={
        # company_data matches ExternalDatasetId(system='company_data', ...)
        'company_data': CompanyDataProvider(warehouse=my_warehouse),
    },
)
```

You can supply any warehouse object when the application starts. This is how a developer
can use a local or manually configured source without changing the ETL function.

If no provider is configured for `company_data`, Etlonomy raises
`ExternalDatasetProviderNotConfiguredError`. It never guesses which library or production
connection it should use.

## Pass data directly in a focused test

A focused function test usually does not need a runtime. Pass the dependency by position
or keyword just as you would for an ordinary Python function:

```python
claims_df = pl.DataFrame({
    'person_id': [1, 2],
    'diagnosis_code': ['I10', 'E11'],
    'extra_test_column': ['kept', 'kept'],
}).lazy()

result = find_claims(
    cohort_df.lazy(),
    # supplying claims means that no provider is called
    claims=claims_df,
)
```

Etlonomy passes an explicit argument through unchanged. It does not select columns,
rename the object, or check its type. This is deliberate: the caller supplied the value,
so normal Python argument behavior applies.

| How the value arrives       | Who limits the columns?               |
|-----------------------------|---------------------------------------|
| `CatalogDatasetProvider`    | The catalog adapter                   |
| `TestDatasetProvider`       | `TestDatasetProvider`                 |
| `ExternalDatasetProvider`   | Your external provider                |
| Explicit `claims=claims_df` | Nobody; the value is passed unchanged |

For a full runtime test, construct a small provider that reads temporary CSV or Parquet
files. The [custom-provider tutorial](tutorials/11-custom-provider.md) builds that example
one step at a time without using any organization-specific library.

## Ask the same lineage questions

External and catalog-loaded datasets use the same main query methods:

```python
graph = etlonomy.LineageGraph()
graph.add_registry(etlonomy.registry)

print(graph.declared_uses('cohort.build'))
print(graph.consumers(CUSTOM_CLAIMS))
print(graph.requirement_consumers(CUSTOM_CLAIMS))
print(graph.descendants(CUSTOM_CLAIMS))
```

The older `external_uses()`, `external_consumers()`, and related methods remain available
when code wants only `ExternalDatasetId` results. They are compatibility helpers, not a
separate or less complete lineage system.

The command line works the same way:

```console
etlonomy uses company_data:warehouse.claims --module claims_demo.jobs --format json
etlonomy lineage company_data:warehouse.claims --module claims_demo.jobs --format json
```

Previous: [reusable requirements](requires.md) · Next: [trace lineage](lineage.md)
