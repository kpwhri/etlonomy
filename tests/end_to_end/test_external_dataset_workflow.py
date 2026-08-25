"""Run a complete ETL with a file-backed external reusable dependency."""

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from etlonomy.decorators import etl, requires
from etlonomy.lineage import LineageGraph
from etlonomy.models import (
    DatasetId,
    ExecutionContext,
    ExternalDatasetId,
    ExternalRead,
    external_read,
    read,
)
from etlonomy.providers import ExternalProviderBinding, TestDatasetProvider
from etlonomy.registry import Registry
from etlonomy.runtime import Runtime


@dataclass(frozen=True)
class ParquetDataset:
    path: Path

    def load(self) -> pl.LazyFrame:
        return pl.scan_parquet(self.path)


@dataclass(frozen=True)
class SourceView:
    claims: ParquetDataset


class FileDatasetProvider:
    def __init__(self, source_view: SourceView):
        self._resources = {'warehouse.claims': source_view.claims}
        self.requests: list[ExternalRead] = []

    def read(
            self, request: ExternalRead, context: ExecutionContext
    ) -> pl.LazyFrame:
        del context
        self.requests.append(request)
        dataset = self._resources[request.dataset.name]
        return dataset.load().select(list(request.columns))


def test_external_required_dataset_runs_and_appears_in_lineage(tmp_path: Path, monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)
    cohort = DatasetId('COHORT', 'MEMBERS')
    output = DatasetId('COHORT', 'CLAIMS')
    external_claims = ExternalDatasetId('files', 'warehouse.claims')
    claims_request = external_read(
        external_claims,
        'person_id',
        'diagnosis_code',
    )
    claims_path = tmp_path / 'claims.parquet'
    pl.DataFrame({
        'person_id': [1, 3],
        'diagnosis_code': ['I10', 'E11'],
        'unused_physical_column': ['old', 'old'],
    }).write_parquet(claims_path)

    @requires(
        external_provider_bindings={
            'files': ExternalProviderBinding('sv', FileDatasetProvider),
        },
        claims=claims_request,
    )
    def attach_claims(
            members: pl.LazyFrame,
            claims: pl.LazyFrame,
            *,
            sv: SourceView | None = None,
    ) -> pl.LazyFrame:
        del sv
        return members.join(claims, on='person_id', how='inner')

    members_request = read(cohort, 'person_id')

    @etl(
        name='cohort.custom_claims',
        inputs={'members': members_request},
        outputs=(output,),
        uses=(attach_claims,),
    )
    def build_cohort_claims(members: pl.LazyFrame) -> pl.LazyFrame:
        return attach_claims(members)

    source_view = SourceView(ParquetDataset(claims_path))
    external_provider = FileDatasetProvider(source_view)
    runtime = Runtime(
        provider=TestDatasetProvider({
            cohort: pl.DataFrame({'person_id': [1, 2]}),
        }),
        external_providers={
            'files': external_provider,
        },
        context=ExecutionContext('test'),
        job_registry=job_registry,
    )

    result = runtime.run('cohort.custom_claims').collect()

    assert result.to_dict(as_series=False) == {
        'person_id': [1],
        'diagnosis_code': ['I10'],
    }
    assert runtime.last_dependencies == (members_request, claims_request)
    assert external_provider.requests == [claims_request]

    portable_result = attach_claims(
        pl.DataFrame({'person_id': [1, 2]}).lazy(),
        sv=source_view,
    ).collect()

    assert portable_result['person_id'].to_list() == [1]
    assert external_provider.requests == [claims_request]

    test_members = pl.DataFrame({'person_id': [10, 20]}).lazy()
    test_claims = pl.DataFrame({
        'person_id': [10, 30],
        'diagnosis_code': ['TEST', 'OTHER'],
        'extra_test_column': ['kept', 'kept'],
    }).lazy()

    direct_result = attach_claims(test_members, claims=test_claims).collect()

    assert direct_result['person_id'].to_list() == [10]
    assert external_provider.requests == [claims_request]

    declared = LineageGraph()
    declared.add_registry(job_registry)
    assert declared.declared_uses('cohort.custom_claims') == (
        cohort,
        external_claims,
    )
    assert declared.declared_external_uses('cohort.custom_claims') == (
        external_claims,
    )
    assert declared.external_consumers(external_claims, job_registry) == (
        'cohort.custom_claims',
    )
    assert declared.external_requirement_consumers(
        external_claims, job_registry
    ) == (attach_claims.__qualname__,)
    assert declared.requirement_consumers(
        external_claims, job_registry
    ) == (attach_claims.__qualname__,)
    assert declared.parents(output) == (cohort, external_claims)
    assert declared.ancestors(output) == (cohort, external_claims)
    assert declared.descendants(external_claims) == (output,)
    assert declared.used_functions('cohort.custom_claims') == (
        attach_claims.__qualname__,
    )
    assert (
               str(external_claims),
               f'function:{attach_claims.__qualname__}',
           ) in declared.declaration_edges('cohort.custom_claims', job_registry)

    traced = LineageGraph()
    traced.add_runtime_trace(
        'cohort.custom_claims',
        (output,),
        runtime.last_dependencies,
    )
    assert traced.uses('cohort.custom_claims') == (cohort, external_claims)
    assert traced.external_uses('cohort.custom_claims') == (external_claims,)
    assert traced.parents(output) == (cohort, external_claims)
