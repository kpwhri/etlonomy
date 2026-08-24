"""Integration tests for local file source adapters."""

import polars as pl
import pytest

from etlonomy.adapters import AdapterSource, CsvAdapter, ParquetAdapter
from etlonomy.exceptions import DatasetProviderError


def test_csv_adapter_projects_and_renames_requested_columns(tmp_path):
    path = tmp_path / 'claims.csv'
    path.write_text('member_id|amount\n1|10\n2|20\n', encoding='utf8')
    source = AdapterSource(
        'csv', str(path), options={'separator': '|'}, columns={'person_id': 'member_id'}
    )

    result = CsvAdapter().read(source, ('person_id',)).collect()

    assert result.to_dict(as_series=False) == {'person_id': [1, 2]}


def test_parquet_adapter_is_lazy_and_projects_requested_columns(tmp_path):
    path = tmp_path / 'claims.parquet'
    pl.DataFrame({'member_id': [1], 'unused': [2]}).write_parquet(path)
    source = AdapterSource('parquet', str(path), columns={'person_id': 'member_id'})

    result = ParquetAdapter().read(source, ('person_id',))

    assert isinstance(result, pl.LazyFrame)
    assert result.collect().columns == ['person_id']
    assert 'unused' not in result.explain()


@pytest.mark.parametrize('adapter', [CsvAdapter(), ParquetAdapter()])
def test_file_adapter_rejects_missing_path(adapter, tmp_path):
    with pytest.raises(DatasetProviderError, match='does not exist'):
        adapter.read(AdapterSource('file', str(tmp_path / 'missing.data')), ('id',))


@pytest.mark.parametrize('adapter', [CsvAdapter(), ParquetAdapter()])
def test_file_adapter_requires_source_uri(adapter):
    with pytest.raises(DatasetProviderError, match='requires a source URI'):
        adapter.read(AdapterSource('file', None), ('id',))


def test_parquet_adapter_translates_missing_requested_column(tmp_path):
    path = tmp_path / 'claims.parquet'
    pl.DataFrame({'id': [1]}).write_parquet(path)

    with pytest.raises(DatasetProviderError, match='missing'):
        ParquetAdapter().read(AdapterSource('parquet', str(path)), ('missing',))


def test_csv_adapter_translates_missing_requested_column(tmp_path):
    path = tmp_path / 'claims.csv'
    path.write_text('id\n1\n', encoding='utf8')

    with pytest.raises(DatasetProviderError, match='missing'):
        CsvAdapter().read(AdapterSource('csv', str(path)), ('missing',)).collect()
