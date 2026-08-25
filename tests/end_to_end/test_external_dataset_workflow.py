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
from etlonomy.providers import TestDatasetProvider
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


class SourceViewProvider:
    def __init__(self, source_view: SourceView):
        self.source_view = source_view

    def read(
            self, request: ExternalRead, context: ExecutionContext
    ) -> pl.LazyFrame:
        del context
        assert request.dataset.name == 'sv.claims'
        return self.source_view.claims.load().select(request.columns)


def test_external_required_dataset_runs_and_appears_in_lineage(tmp_path: Path, monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)
    cohort = DatasetId('COHORT', 'MEMBERS')
    output = DatasetId('COHORT', 'CLAIMS')
    external_claims = ExternalDatasetId('files', 'sv.claims')
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

    @requires(claims=claims_request)
    def attach_claims(
            members: pl.LazyFrame,
            claims: pl.LazyFrame,
    ) -> pl.LazyFrame:
        return members.join(claims, on='person_id', how='inner')

    members_request = read(cohort, 'person_id')

    @etl(
        name='cohort.external_claims',
        inputs={'members': members_request},
        outputs=(output,),
        uses=(attach_claims,),
    )
    def build_cohort_claims(members: pl.LazyFrame) -> pl.LazyFrame:
        return attach_claims(members)

    runtime = Runtime(
        provider=TestDatasetProvider({
            cohort: pl.DataFrame({'person_id': [1, 2]}),
        }),
        external_providers={
            'files': SourceViewProvider(
                SourceView(claims=ParquetDataset(claims_path))
            ),
        },
        context=ExecutionContext('test'),
        job_registry=job_registry,
    )

    result = runtime.run('cohort.external_claims').collect()

    assert result.to_dict(as_series=False) == {
        'person_id': [1],
        'diagnosis_code': ['I10'],
    }
    assert runtime.last_dependencies == (members_request, claims_request)

    declared = LineageGraph()
    declared.add_registry(job_registry)
    assert declared.declared_uses('cohort.external_claims') == (cohort,)
    assert declared.declared_external_uses('cohort.external_claims') == (
        external_claims,
    )
    assert declared.external_consumers(external_claims, job_registry) == (
        'cohort.external_claims',
    )
    assert declared.external_requirement_consumers(
        external_claims, job_registry
    ) == (attach_claims.__qualname__,)
    assert (
               str(external_claims),
               f'function:{attach_claims.__qualname__}',
           ) in declared.declaration_edges('cohort.external_claims', job_registry)

    traced = LineageGraph()
    traced.add_runtime_trace(
        'cohort.external_claims',
        (output,),
        runtime.last_dependencies,
    )
    assert traced.uses('cohort.external_claims') == (cohort,)
    assert traced.external_uses('cohort.external_claims') == (external_claims,)
