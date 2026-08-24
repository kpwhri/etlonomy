"""Read committed SAS fixtures through real adapter and catalog boundaries."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

import etlonomy
from etlonomy.adapters import AdapterSource, SasAdapter
from etlonomy.catalog import SQLiteCatalog, build_catalog
from etlonomy.exceptions import DatasetProviderError

FIXTURE_DIRECTORY = Path(__file__).parents[1] / 'fixtures'


def test_real_claim_line_sas_fixture_projects_and_renames_columns():
    path = FIXTURE_DIRECTORY / 'claim_line.sas7bdat'
    assert path.is_file(), f'missing SAS fixture: {path}'
    source = AdapterSource(
        source_type='sas7bdat',
        source_uri=str(path),
        columns={
            'person_id': 'member_id',
            'provider_id': 'provider_id',
            'service_date': 'svc_dt',
            'diagnosis_code': 'diagnosis_cd',
        },
    )

    frame = SasAdapter().read(
        source,
        ('person_id', 'provider_id', 'service_date', 'diagnosis_code'),
    )
    result = frame.collect()

    assert isinstance(frame, pl.LazyFrame)
    assert result.columns == [
        'person_id',
        'provider_id',
        'service_date',
        'diagnosis_code',
    ]
    assert result['person_id'].cast(pl.Int64).to_list() == [1, 2, 3]
    assert result['provider_id'].cast(pl.Int64).to_list() == [101, 102, 103]
    assert result['diagnosis_code'].to_list() == ['I10', '', 'E11']
    assert 'ignored_legacy_field' not in result.columns


def test_real_provider_sas_fixture_projects_and_renames_specialty():
    path = FIXTURE_DIRECTORY / 'provider.sas7bdat'
    assert path.is_file(), f'missing SAS fixture: {path}'
    source = AdapterSource(
        source_type='sas7bdat',
        source_uri=str(path),
        columns={
            'provider_id': 'provider_id',
            'specialty': 'specialty_desc',
        },
    )

    frame = SasAdapter().read(source, ('provider_id', 'specialty'))
    result = frame.collect()

    assert isinstance(frame, pl.LazyFrame)
    assert result.columns == ['provider_id', 'specialty']
    assert result['provider_id'].cast(pl.Int64).to_list() == [101, 102, 103]
    assert result['specialty'].to_list() == [
        'Cardiology',
        'Primary Care',
        'Neurology',
    ]
    assert 'inactive_flag' not in result.columns


def test_catalog_provider_reads_real_sas_fixtures_with_partial_mappings(tmp_path: Path):
    claim_path = FIXTURE_DIRECTORY / 'claim_line.sas7bdat'
    provider_path = FIXTURE_DIRECTORY / 'provider.sas7bdat'
    assert claim_path.is_file(), f'missing SAS fixture: {claim_path}'
    assert provider_path.is_file(), f'missing SAS fixture: {provider_path}'
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'sas.toml').write_text(
        f"""etlonomy_manifest = 1
[[datasets]]
canonical_name = 'CLAIMS.CLAIM_LINE'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
source_type = 'sas7bdat'
source_uri = '{claim_path.as_posix()}'
[datasets.versions.columns.person_id]
source = 'member_id'
[datasets.versions.columns.service_date]
source = 'svc_dt'
[datasets.versions.columns.diagnosis_code]
source = 'diagnosis_cd'
[[datasets]]
canonical_name = 'REFERENCE.PROVIDER'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
source_type = 'sas7bdat'
source_uri = '{provider_path.as_posix()}'
[datasets.versions.columns.specialty]
source = 'specialty_desc'
""",
        encoding='utf8',
    )
    catalog_path = tmp_path / 'catalog.db'
    build_catalog(manifests, catalog_path)
    provider = etlonomy.CatalogDatasetProvider(SQLiteCatalog(catalog_path))
    context = etlonomy.ExecutionContext(as_of=date(2026, 8, 31))

    claims = provider.read(
        etlonomy.read(
            etlonomy.DatasetId('CLAIMS', 'CLAIM_LINE'),
            'person_id',
            'provider_id',
            'diagnosis_code',
        ),
        context,
    )
    providers = provider.read(
        etlonomy.read(
            etlonomy.DatasetId('REFERENCE', 'PROVIDER'),
            'provider_id',
            'specialty',
        ),
        context,
    )

    assert isinstance(claims, pl.LazyFrame)
    assert isinstance(providers, pl.LazyFrame)
    assert claims.collect().columns == [
        'person_id',
        'provider_id',
        'diagnosis_code',
    ]
    assert providers.collect().columns == ['provider_id', 'specialty']


def test_real_sas_reader_translates_invalid_file_error(tmp_path: Path):
    invalid = tmp_path / 'invalid.sas7bdat'
    invalid.write_bytes(b'not a SAS data file')

    with pytest.raises(DatasetProviderError, match='Unable to read SAS7BDAT'):
        SasAdapter().read(
            AdapterSource('sas7bdat', str(invalid)), ('person_id',)
        )
