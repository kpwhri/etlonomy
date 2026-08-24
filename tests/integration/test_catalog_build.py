import sqlite3
from contextlib import closing
from datetime import date

import pytest

from etlonomy.catalog import SQLiteCatalog, build_catalog
from etlonomy.exceptions import (
    DatasetNotFoundError,
    DatasetVersionNotFoundError,
    ManifestError,
)
from etlonomy.models import DatasetId

MANIFEST = """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'REFERENCE.PROVIDER'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
source_type = 'csv'
source_uri = 'providers.csv'

[[datasets]]
canonical_name = 'CLAIMS.CLAIM_LINE'
description = 'Claims'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
valid_to = 2026-09-01
source_type = 'parquet'
source_uri = 'claims.parquet'
[[datasets.versions]]
version = 2
valid_from = 2026-09-01
source_type = 'sql_query'
source_uri = 'postgresql+psycopg://claims.example/warehouse'
credential_ref = 'env://?username=CLAIMS_USER&password=CLAIMS_PASSWORD'
query = 'SELECT member_id AS person_id FROM claims'
dependencies = ['REFERENCE.PROVIDER']
[datasets.versions.options]
engine = 'adbc'
[datasets.versions.columns.person_id]
source = 'member_id'
nullable = false
"""


def test_catalog_build_and_read_api_cover_history_dependencies_and_columns(tmp_path):
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'datasets.toml').write_text(MANIFEST, encoding='utf8')
    database = tmp_path / 'catalog.db'
    first_hash = build_catalog(manifests, database)
    second_hash = build_catalog(manifests, database)
    assert first_hash == second_hash

    catalog = SQLiteCatalog(database)
    claims = DatasetId('CLAIMS', 'CLAIM_LINE')
    historical = catalog.resolve_dataset(claims, date(2026, 8, 31))
    current = catalog.resolve_dataset(claims, date(2026, 9, 1))
    assert (historical.version, current.version) == (1, 2)
    assert catalog.resolve_dataset(claims, date(2000, 1, 1), version=1) == historical
    assert current.options == {'engine': 'adbc'}
    assert current.credential_ref == (
        'env://?username=CLAIMS_USER&password=CLAIMS_PASSWORD'
    )
    assert current.columns[0].logical_name == 'person_id'
    assert catalog.get_dependencies(current.dataset_version_id) == (
        DatasetId('REFERENCE', 'PROVIDER'),
    )


def test_catalog_resolution_reports_unknown_dataset_version_and_date(tmp_path):
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'datasets.toml').write_text(MANIFEST, encoding='utf8')
    database = tmp_path / 'catalog.db'
    build_catalog(manifests, database)
    catalog = SQLiteCatalog(database)
    with pytest.raises(DatasetNotFoundError):
        catalog.get_dataset(DatasetId('UNKNOWN', 'DATASET'))
    with pytest.raises(DatasetVersionNotFoundError):
        catalog.resolve_dataset(DatasetId('CLAIMS', 'CLAIM_LINE'), date(2020, 1, 1))
    with pytest.raises(DatasetVersionNotFoundError):
        catalog.resolve_dataset(
            DatasetId('CLAIMS', 'CLAIM_LINE'), date.today(), version=99
        )


def test_invalid_build_leaves_existing_catalog_unchanged(tmp_path):
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    manifest_path = manifests / 'datasets.toml'
    manifest_path.write_text(MANIFEST, encoding='utf8')
    database = tmp_path / 'catalog.db'
    build_catalog(manifests, database)
    with closing(sqlite3.connect(database)) as connection:
        before = connection.execute('SELECT COUNT(*) FROM datasets').fetchone()
    manifest_path.write_text('not valid =', encoding='utf8')
    with pytest.raises(ManifestError):
        build_catalog(manifests, database)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute('SELECT COUNT(*) FROM datasets').fetchone() == before


def test_catalog_build_removes_temporary_database_when_atomic_replace_fails(
        tmp_path, monkeypatch
):
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'datasets.toml').write_text(MANIFEST, encoding='utf8')
    database = tmp_path / 'catalog.db'

    def fail_replace(source, destination):
        raise OSError(f'cannot replace {destination} with {source}')

    monkeypatch.setattr('etlonomy.catalog.builder.os.replace', fail_replace)
    with pytest.raises(OSError, match='cannot replace'):
        build_catalog(manifests, database)
    assert not database.exists()
    assert list(tmp_path.glob('.catalog.db.*.tmp')) == []


def test_catalog_resolution_without_date_uses_most_recent_historical_version(
        tmp_path,
):
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'history.toml').write_text(
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'HISTORY.RECORDS'
[[datasets.versions]]
version = 1
valid_from = 2000-01-01
valid_to = 2001-01-01
source_type = 'csv'
source_uri = 'old.csv'
[[datasets.versions]]
version = 2
valid_from = 2001-01-01
valid_to = 2002-01-01
source_type = 'parquet'
source_uri = 'newer.parquet'
""",
        encoding='utf8',
    )
    database = tmp_path / 'catalog.db'
    build_catalog(manifests, database)

    resolved = SQLiteCatalog(database).resolve_dataset(
        DatasetId('HISTORY', 'RECORDS')
    )

    assert resolved.version == 2
