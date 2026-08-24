"""Tests for production-isolated in-memory dataset access."""

from datetime import date

import polars as pl
import pytest

from etlonomy.exceptions import MissingTestColumnError, MissingTestDatasetError
from etlonomy.models import DatasetId, ExecutionContext, read
from etlonomy.providers import TestDatasetProvider

CONTEXT = ExecutionContext('test', date(2026, 8, 20))


@pytest.mark.parametrize('lazy', [False, True])
def test_test_dataset_provider_accepts_dataframes_and_lazyframes(lazy: bool):
    dataset = DatasetId('CLAIMS', 'LINES')
    frame = pl.DataFrame({'person_id': [1], 'ignored': ['x']})
    fixture = frame.lazy() if lazy else frame
    provider = TestDatasetProvider({dataset: fixture})

    result = provider.read(read(dataset, 'person_id'), CONTEXT)

    assert isinstance(result, pl.LazyFrame)
    assert result.collect().to_dict(as_series=False) == {'person_id': [1]}


def test_test_dataset_provider_raises_immediately_when_dataset_not_supplied():
    provider = TestDatasetProvider({})
    request = read(DatasetId('CLAIMS', 'LINES'), 'person_id')

    with pytest.raises(MissingTestDatasetError, match='CLAIMS.LINES'):
        provider.read(request, CONTEXT)


def test_test_dataset_provider_reports_every_missing_requested_column():
    dataset = DatasetId('CLAIMS', 'LINES')
    provider = TestDatasetProvider({dataset: pl.DataFrame({'person_id': [1]})})

    with pytest.raises(MissingTestColumnError, match='service_date, diagnosis_code'):
        provider.read(read(dataset, 'service_date', 'diagnosis_code'), CONTEXT)


def test_test_dataset_provider_has_no_production_fallback_surface():
    provider = TestDatasetProvider({})

    assert not hasattr(provider, 'fallback')
    assert not hasattr(provider, 'catalog')
    assert not hasattr(provider, 'connection_resolver')
