"""Exercise the external provider protocol with temporary file-backed objects."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import pytest

from etlonomy.exceptions import DatasetProviderError
from etlonomy.models import (
    ExecutionContext,
    ExternalDatasetId,
    ExternalRead,
    external_read,
)
from etlonomy.providers import TestDatasetProvider
from etlonomy.registry import EtlDefinition, Registry
from etlonomy.runtime import Runtime


@dataclass(frozen=True)
class FileDataset:
    path: Path
    loader: Callable[[Path], pl.LazyFrame]

    def load(self) -> pl.LazyFrame:
        return self.loader(self.path)


@dataclass(frozen=True)
class FileSourceView:
    claims: FileDataset
    providers: FileDataset


class FileExternalDatasetProvider:
    def __init__(self, source_view: FileSourceView):
        self.source_view = source_view
        self.requests: list[ExternalRead] = []

    def read(
            self, request: ExternalRead, context: ExecutionContext
    ) -> pl.LazyFrame:
        del context
        self.requests.append(request)
        resources = {
            'sv.claims': self.source_view.claims,
            'sv.providers': self.source_view.providers,
        }
        try:
            resource = resources[request.dataset.name]
        except KeyError as error:
            raise DatasetProviderError(
                f'unknown external file dataset: {request.dataset}'
            ) from error
        return resource.load().select(request.columns)


def test_external_provider_reads_csv_and_parquet_with_requested_projection(tmp_path: Path):
    claims_path = tmp_path / 'claims.parquet'
    providers_path = tmp_path / 'providers.csv'
    pl.DataFrame({
        'person_id': [1, 2],
        'provider_id': [10, 20],
        'ignored_claim_value': ['x', 'y'],
    }).write_parquet(claims_path)
    pl.DataFrame({
        'provider_id': [10, 20],
        'specialty': ['cardiology', 'primary care'],
        'ignored_provider_value': [True, False],
    }).write_csv(providers_path)

    source_view = FileSourceView(
        claims=FileDataset(claims_path, pl.scan_parquet),
        providers=FileDataset(providers_path, pl.scan_csv),
    )
    provider = FileExternalDatasetProvider(source_view)
    claims = external_read(
        ExternalDatasetId('files', 'sv.claims'),
        'person_id',
        'provider_id',
    )
    providers = external_read(
        ExternalDatasetId('files', 'sv.providers'),
        'provider_id',
        'specialty',
    )
    job_registry = Registry()

    def join_sources(claims: pl.LazyFrame, providers: pl.LazyFrame) -> pl.LazyFrame:
        return claims.join(providers, on='provider_id', how='left')

    job_registry.register_etl(
        EtlDefinition(
            'external.join_files',
            join_sources,
            {'claims': claims, 'providers': providers},
            (),
            None,
            None,
        )
    )
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        external_providers={'files': provider},
        context=ExecutionContext('test'),
        job_registry=job_registry,
    )

    result = runtime.run('external.join_files').collect()

    assert result.columns == ['person_id', 'provider_id', 'specialty']
    assert result.to_dict(as_series=False) == {
        'person_id': [1, 2],
        'provider_id': [10, 20],
        'specialty': ['cardiology', 'primary care'],
    }
    assert provider.requests == [claims, providers]
    assert runtime.last_dependencies == (claims, providers)


def test_external_provider_reports_unknown_resource(tmp_path: Path):
    path = tmp_path / 'empty.csv'
    pl.DataFrame({'id': [1]}).write_csv(path)
    source_view = FileSourceView(
        claims=FileDataset(path, pl.scan_csv),
        providers=FileDataset(path, pl.scan_csv),
    )
    request = external_read(
        ExternalDatasetId('files', 'sv.unknown'),
        'id',
    )

    with pytest.raises(DatasetProviderError, match='unknown external file dataset'):
        FileExternalDatasetProvider(source_view).read(request, ExecutionContext())
