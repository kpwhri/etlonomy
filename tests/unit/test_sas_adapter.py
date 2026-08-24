"""Tests for the injectable SAS7BDAT reader boundary."""

import sys
from types import SimpleNamespace

import polars as pl
import pytest

from etlonomy.adapters import AdapterSource, SasAdapter
from etlonomy.exceptions import DatasetProviderError


def test_sas_adapter_requests_only_physical_columns_and_renames(tmp_path):
    path = tmp_path / 'claims.sas7bdat'
    path.write_bytes(b'synthetic fixture boundary')
    calls = []

    def reader(reader_path, columns):
        calls.append((reader_path, columns))
        return pl.DataFrame({'member_id': [7], 'unused': [8]})

    result = SasAdapter(reader).read(
        AdapterSource('sas7bdat', str(path), columns={'person_id': 'member_id'}),
        ('person_id',),
    )

    assert calls == [(path, ('member_id',))]
    assert result.collect().to_dict(as_series=False) == {'person_id': [7]}


def test_sas_adapter_requires_optional_reader_dependency(tmp_path, monkeypatch):
    path = tmp_path / 'claims.sas7bdat'
    path.write_bytes(b'fixture')
    monkeypatch.setitem(sys.modules, 'pyreadstat', None)

    with pytest.raises(DatasetProviderError, match='etlonomy sas extra'):
        SasAdapter().read(AdapterSource('sas7bdat', str(path)), ('id',))


def test_sas_adapter_rejects_missing_file():
    with pytest.raises(DatasetProviderError, match='does not exist'):
        SasAdapter(lambda path, columns: pl.DataFrame()).read(
            AdapterSource('sas7bdat', 'missing.sas7bdat'), ('id',)
        )


def test_sas_adapter_requires_source_uri():
    with pytest.raises(DatasetProviderError, match='requires a source URI'):
        SasAdapter(lambda path, columns: pl.DataFrame()).read(
            AdapterSource('sas7bdat', None), ('id',)
        )


def test_sas_adapter_translates_reader_failure(tmp_path):
    path = tmp_path / 'claims.sas7bdat'
    path.write_bytes(b'fixture')

    def reader(reader_path, columns):
        raise OSError('unreadable fixture')

    with pytest.raises(DatasetProviderError, match='unreadable fixture'):
        SasAdapter(reader).read(AdapterSource('sas7bdat', str(path)), ('id',))


def test_default_sas_reader_converts_selected_dictionary_result(monkeypatch, tmp_path):
    path = tmp_path / 'claims.sas7bdat'
    path.write_bytes(b'fixture')
    calls = []

    def read_sas7bdat(reader_path, *, usecols, output_format):
        calls.append((reader_path, usecols, output_format))
        return {'id': [3]}, object()

    monkeypatch.setitem(
        sys.modules, 'pyreadstat', SimpleNamespace(read_sas7bdat=read_sas7bdat)
    )

    result = SasAdapter().read(AdapterSource('sas7bdat', str(path)), ('id',))

    assert calls == [(path, ['id'], 'dict')]
    assert result.collect().to_dict(as_series=False) == {'id': [3]}
