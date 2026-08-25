# Extension C: load a dataset with your own provider

Etlonomy already knows how to read common files and SQL databases. This lesson handles a different situation: another
Python object knows how to load the dataset, but Etlonomy does not know how to call that object.

We will build a tiny file-backed source object so the example works on any computer. The same shape can wrap an internal
warehouse library, a source-view object, or another approved data API.

By the end, we will:

1. give the custom-loaded dataset a stable name
2. write a provider that understands that name
3. request it from a reusable function
4. run a normal ETL job
5. bypass the provider in a focused test
6. inspect the dataset with ordinary lineage methods

The complete flow is exercised by
`tests/end_to_end/test_external_dataset_workflow.py` in the Etlonomy repository.

## 1. Create a small source file

We first need data that our custom Python object can load. Parquet is convenient here because polars can scan it lazily.
In a real project, the object might call a private library instead.

```python
from pathlib import Path

import polars as pl

data_directory = Path('data')
data_directory.mkdir(exist_ok=True)

pl.DataFrame({
    'person_id': [1, 3],
    'diagnosis_code': ['I10', 'E11'],
    'unused_physical_column': ['old', 'old'],
}).write_parquet(data_directory / 'claims.parquet')
```

The unused column is intentional. Later, it will help us prove that the provider returns only the columns requested by
the ETL code.

## 2. Give the dataset a stable name

The file path should not appear in the ETL function. If another library replaces this file later, the ETL should keep
asking for the same logical dataset.

Add this to `src/claims_demo/external_sources.py`:

```python
import etlonomy

CUSTOM_CLAIMS = etlonomy.ExternalDatasetId('files', 'warehouse.claims')
```

`files` is the routing name. `warehouse.claims` is the dataset name shown in lineage. Together they form
`files:warehouse.claims`.

## 3. Wrap the loader in a provider

Etlonomy cannot know what methods another Python library provides. We therefore write a small adapter that converts an
`ExternalRead` into the operation understood by our source object.

Continue `src/claims_demo/external_sources.py`:

```python
from dataclasses import dataclass
from pathlib import Path

import polars as pl


@dataclass(frozen=True)
class ParquetDataset:
    path: Path

    def load(self) -> pl.LazyFrame:
        """Build a lazy query for this Parquet dataset."""
        return pl.scan_parquet(self.path)


class FileDatasetProvider:
    def __init__(self, claims: ParquetDataset) -> None:
        """Expose the small, approved set of resources used by this project."""
        self._resources = {'warehouse.claims': claims}

    def read(
            self,
            request: etlonomy.ExternalRead,
            context: etlonomy.ExecutionContext,
    ) -> pl.LazyFrame:
        """Load one named dataset and keep only its requested columns."""
        del context
        dataset = self._resources[request.dataset.name]
        return dataset.load().select(list(request.columns))
```

The provider contains an explicit resource dictionary. That keeps routing easy to read and prevents arbitrary names from
becoming arbitrary Python attribute access.

## 4. Request the dataset from a reusable function

The business function should describe the data it needs, not how the provider finds it. Add this to
`src/claims_demo/jobs.py`:

```python
import polars as pl

import etlonomy
from claims_demo.external_sources import CUSTOM_CLAIMS

MEMBERS = etlonomy.DatasetId('COHORT', 'MEMBERS')
RESULT = etlonomy.DatasetId('COHORT', 'RESULT')


@etlonomy.requires(
    claims=etlonomy.external_read(
        CUSTOM_CLAIMS,
        'person_id',
        'diagnosis_code',
    ),
)
def attach_claims(
        members: pl.LazyFrame,
        claims: pl.LazyFrame,
) -> pl.LazyFrame:
    """Keep claims belonging to cohort members."""
    return members.join(claims, on='person_id', how='inner')


@etlonomy.etl(
    name='cohort.custom_claims',
    inputs={'members': etlonomy.read(MEMBERS, 'person_id')},
    outputs=(RESULT,),
    uses=(attach_claims,),
)
def build_cohort(members: pl.LazyFrame) -> pl.LazyFrame:
    """Build diagnosed claims for cohort members."""
    return attach_claims(members)
```

The job lists `attach_claims` in `uses`. This lets Etlonomy see the claims dependency before the job runs as well as
during the actual run.

## 5. Build the runtime and run the job

The application chooses both providers. The regular test provider supplies members; our custom provider supplies claims.
A production application would normally use a catalog provider for `MEMBERS`.

```python
from pathlib import Path

import polars as pl

import etlonomy
from claims_demo.external_sources import FileDatasetProvider, ParquetDataset
from claims_demo.jobs import MEMBERS

runtime = etlonomy.Runtime(
    provider=etlonomy.TestDatasetProvider({
        MEMBERS: pl.DataFrame({'person_id': [1, 2]}),
    }),
    external_providers={
        # files matches ExternalDatasetId('files', 'warehouse.claims')
        'files': FileDatasetProvider(
            ParquetDataset(Path('data/claims.parquet'))
        ),
    },
    context=etlonomy.ExecutionContext(environment='local'),
)

result = runtime.run('cohort.custom_claims').collect()

assert result.to_dict(as_series=False) == {
    'person_id': [1],
    'diagnosis_code': ['I10'],
}
```

The result does not contain `unused_physical_column`. The provider applied the requested projection before returning the
lazy frame.

## 6. Test the function without calling the provider

Most business-rule tests should be smaller than the full runtime test. Supply `claims`
directly so the custom provider cannot be contacted:

```python
test_members = pl.DataFrame({'person_id': [10, 20]}).lazy()
test_claims = pl.DataFrame({
    'person_id': [10, 30],
    'diagnosis_code': ['TEST', 'OTHER'],
    'extra_test_column': ['kept', 'kept'],
}).lazy()

result = attach_claims(test_members, claims=test_claims).collect()

assert result['person_id'].to_list() == [10]
```

The explicit value is passed unchanged. That is why the extra test column is allowed. If matching production projection
matters to this test, select the desired columns in the fixture itself.

## 7. Inspect normal lineage

A custom-loaded dataset is still a dataset. Use the same methods used for catalog data:

```python
graph = etlonomy.LineageGraph()
graph.add_registry(etlonomy.registry)

assert CUSTOM_CLAIMS in graph.declared_uses('cohort.custom_claims')
assert graph.consumers(CUSTOM_CLAIMS) == ('cohort.custom_claims',)
assert graph.parents(RESULT) == (MEMBERS, CUSTOM_CLAIMS)
assert graph.descendants(CUSTOM_CLAIMS) == (RESULT,)
```

You can ask the same questions from the command line after importing the job module:

```console
etlonomy uses files:warehouse.claims --module claims_demo.jobs --format json
etlonomy lineage files:warehouse.claims --module claims_demo.jobs --format json
etlonomy graph cohort.custom_claims --module claims_demo.jobs --format mermaid
```

The provider changes how the data is loaded. It does not make the dataset less visible or less important in the
dependency graph.

Previous: [remote SQL database extension](10-sql-databases.md) · Return to the
[tutorial home](index.md)
