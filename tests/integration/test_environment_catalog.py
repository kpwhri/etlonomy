"""Exercise environment-owned file roots and SQL connections through a catalog."""

import sqlite3
from contextlib import closing
from pathlib import Path

import polars as pl
import pytest

import etlonomy
from etlonomy.catalog import SQLiteCatalog, build_catalog
from etlonomy.environment import load_environment, parse_environment
from etlonomy.exceptions import (
    CatalogEnvironmentMismatchError,
    ManifestError,
)
from etlonomy.manifest import parse_manifest


def test_catalog_resolves_shared_file_root_and_validates_environment(tmp_path: Path):
    data_directory = tmp_path / 'shared-data'
    data_directory.mkdir()
    (data_directory / 'claims.csv').write_text('person_id\n1\n2\n', encoding='utf8')
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'claims.toml').write_text(
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'CLAIMS.LINES'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
source_root = 'claims'
source_uri = 'claims.csv'
""",
        encoding='utf8',
    )
    environment = tmp_path / 'prod.toml'
    environment.write_text(
        f"""etlonomy_environment = 1
environment = 'prod'
[roots.claims]
base_uri = '{data_directory.as_posix()}'
""",
        encoding='utf8',
    )
    database = tmp_path / 'catalog.db'
    build_catalog(manifests, database, environment_config=environment)
    catalog = SQLiteCatalog(database)
    provider = etlonomy.CatalogDatasetProvider(catalog)
    request = etlonomy.read(etlonomy.DatasetId('CLAIMS', 'LINES'), 'person_id')

    result = provider.read(request, etlonomy.ExecutionContext('prod')).collect()

    assert result.to_dict(as_series=False) == {'person_id': [1, 2]}
    assert catalog.get_environment() == 'prod'
    assert catalog.get_root('claims') == data_directory.as_posix()
    with pytest.raises(CatalogEnvironmentMismatchError, match='does not match'):
        provider.read(request, etlonomy.ExecutionContext('dev'))
    assert provider.read(request, etlonomy.ExecutionContext()).collect().height == 2


def test_catalog_resolves_shared_sql_connection(tmp_path: Path):
    source_database = tmp_path / 'warehouse.sqlite'
    with closing(sqlite3.connect(source_database)) as connection:
        with connection:
            connection.execute('CREATE TABLE claims (person_id INTEGER)')
            connection.execute('INSERT INTO claims VALUES (7)')
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'claims.toml').write_text(
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'CLAIMS.LINES'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'sql_table'
connection = 'warehouse'
query = 'claims'
""",
        encoding='utf8',
    )
    environment = tmp_path / 'test.toml'
    environment.write_text(
        f"""etlonomy_environment = 1
[connections.warehouse]
sqlalchemy_url = 'sqlite:///{source_database.as_posix()}'
""",
        encoding='utf8',
    )
    database = tmp_path / 'catalog.db'
    build_catalog(manifests, database, environment_config=environment)
    catalog = SQLiteCatalog(database)

    result = etlonomy.CatalogDatasetProvider(catalog).read(
        etlonomy.read(etlonomy.DatasetId('CLAIMS', 'LINES'), 'person_id'),
        etlonomy.ExecutionContext(),
    )

    assert isinstance(result, pl.LazyFrame)
    assert result.collect().to_dict(as_series=False) == {'person_id': [7]}
    assert catalog.get_connection('warehouse') == (
        f'sqlite:///{source_database.as_posix()}',
        None,
    )


def test_catalog_build_rejects_paths_outside_shared_root(tmp_path: Path):
    data_directory = tmp_path / 'shared-data'
    data_directory.mkdir()
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'claims.toml').write_text(
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'CLAIMS.LINES'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
source_root = 'claims'
source_uri = '../outside.csv'
""",
        encoding='utf8',
    )
    environment = tmp_path / 'prod.toml'
    environment.write_text(
        f"""etlonomy_environment = 1
[roots.claims]
base_uri = '{data_directory.as_posix()}'
""",
        encoding='utf8',
    )
    with pytest.raises(ManifestError, match='remain inside'):
        build_catalog(
            manifests,
            tmp_path / 'catalog.db',
            environment_config=environment,
        )


def test_explicit_environment_requires_catalog_identity(tmp_path: Path):
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    source = tmp_path / 'claims.csv'
    source.write_text('person_id\n1\n', encoding='utf8')
    (manifests / 'claims.toml').write_text(
        f"""etlonomy_manifest = 1
[[datasets]]
canonical_name = 'CLAIMS.LINES'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
source_uri = '{source.as_posix()}'
""",
        encoding='utf8',
    )
    database = tmp_path / 'catalog.db'
    build_catalog(manifests, database)
    provider = etlonomy.CatalogDatasetProvider(SQLiteCatalog(database))

    with pytest.raises(CatalogEnvironmentMismatchError, match='no environment'):
        provider.read(
            etlonomy.read(etlonomy.DatasetId('CLAIMS', 'LINES'), 'person_id'),
            etlonomy.ExecutionContext('prod'),
        )


@pytest.mark.parametrize(('manifest_body', 'environment_body', 'message'), [
    (
            "source_type = 'csv'\nsource_uri = 'a.csv'\nsource_root = 'missing'",
            '',
            'unknown source_root',
    ),
    (
            "source_type = 'sql_table'\nconnection = 'missing'\nquery = 'claims'",
            '',
            'unknown connection',
    ),
    (
            "source_type = 'sql_table'\nconnection = 'warehouse'\n"
            "credential_ref = 'env://?password=ONE'\nquery = 'claims'",
            "[connections.warehouse]\nsqlalchemy_url = 'sqlite:///x.db'\n"
            "credential_ref = 'env://?password=TWO'",
            'both on the dataset version and shared connection',
    ),
    (
            "source_type = 'csv'\nsource_uri = 'a.csv'\nconnection = 'warehouse'",
            "[connections.warehouse]\nsqlalchemy_url = 'sqlite:///x.db'",
            'csv source cannot declare connection',
    ),
    (
            "source_type = 'sql_table'\nsource_uri = 'sqlite:///x.db'\n"
            "source_root = 'files'\nquery = 'claims'",
            "[roots.files]\nbase_uri = 'data'",
            'sql_table source cannot declare source_root',
    ),
    (
            "source_type = 'sql_table'\nquery = 'claims'",
            '',
            'requires exactly one',
    ),
    (
            "source_type = 'sql_table'\nsource_uri = 'sqlite:///x.db'\n"
            "connection = 'warehouse'\nquery = 'claims'",
            "[connections.warehouse]\nsqlalchemy_url = 'sqlite:///x.db'",
            'requires exactly one',
    ),
    (
            "source_type = 'csv'\nsource_uri = '../outside.csv'\n"
            "source_root = 'files'",
            "[roots.files]\nbase_uri = 'data'",
            'remain inside',
    ),
])
def test_catalog_build_rejects_invalid_shared_source_references(
        tmp_path: Path, manifest_body: str, environment_body: str, message: str,
):
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'source.toml').write_text(
        "etlonomy_manifest = 1\n[[datasets]]\ncanonical_name = 'A.B'\n"
        '[[datasets.versions]]\nversion = 1\nvalid_from = 2026-01-01\n'
        f'{manifest_body}\n',
        encoding='utf8',
    )
    environment = tmp_path / 'environment.toml'
    environment.write_text(
        f'etlonomy_environment = 1\n{environment_body}\n', encoding='utf8'
    )

    with pytest.raises(ManifestError, match=message):
        build_catalog(
            manifests,
            tmp_path / 'catalog.db',
            environment_config=environment,
        )


@pytest.mark.parametrize(('document', 'message'), [
    (
            b"etlonomy_environment = 1\nenvironmnt = 'prod'",
            "did you mean 'environment'",
    ),
    (
            b"etlonomy_environment = 1\n[roots.data]\nbas_uri = 'x'",
            'unknown root',
    ),
    (
            b"etlonomy_environment = 1\n[connections.db]\nurl = 'x'",
            'unknown connection',
    ),
])
def test_environment_toml_rejects_unknown_keys(document: bytes, message: str):
    with pytest.raises(ManifestError, match=message):
        parse_environment(document)


@pytest.mark.parametrize(('document', 'message'), [
    (b'not valid =', 'invalid TOML'),
    (b'etlonomy_environment = 2', 'must equal 1'),
    (b'etlonomy_environment = 1\nroots = []', 'roots must be a table'),
    (
            b"etlonomy_environment = 1\nroots.data = 'wrong'",
            'roots.data must be a table',
    ),
    (
            b'etlonomy_environment = 1\n[roots.data]',
            'base_uri must be a non-empty string',
    ),
    (
            b'etlonomy_environment = 1\n[connections.db]\nsqlalchemy_url = 1',
            'sqlalchemy_url must be a non-empty string',
    ),
    (
            b"etlonomy_environment = 1\n[connections.db]\n"
            b"sqlalchemy_url = 'not a URL'",
            'valid SQLAlchemy URL',
    ),
    (
            b"etlonomy_environment = 1\nenvironment = ''",
            'environment must be a non-empty string',
    ),
])
def test_environment_toml_rejects_malformed_values(document: bytes, message: str):
    with pytest.raises(ManifestError, match=message):
        parse_environment(document)


def test_environment_file_read_errors_are_translated(tmp_path: Path):
    with pytest.raises(ManifestError, match='cannot read environment configuration'):
        load_environment(tmp_path / 'missing.toml')


@pytest.mark.parametrize(('body', 'message'), [
    ("manfest_note = 'bad'", 'unknown manifest field'),
    ("[[datasets]]\ncanonical_name = 'A.B'\ndescripton = 'bad'", 'unknown dataset field'),
    (
            "[[datasets]]\ncanonical_name = 'A.B'\n[[datasets.versions]]\n"
            "version = 1\nvalid_from = 2026-01-01\nsource_type = 'csv'\n"
            "source_uri = 'a.csv'\ndependecies = []",
            "did you mean 'dependencies'",
    ),
    (
            "[[datasets]]\ncanonical_name = 'A.B'\n[[datasets.versions]]\n"
            "version = 1\nvalid_from = 2026-01-01\nsource_type = 'csv'\n"
            "source_uri = 'a.csv'\n[datasets.versions.columns.id]\n"
            "sorce = 'physical_id'",
            "did you mean 'source'",
    ),
])
def test_dataset_manifest_rejects_unknown_keys(body: str, message: str):
    document = f'etlonomy_manifest = 1\n{body}\n'.encode()
    with pytest.raises(ManifestError, match=message):
        parse_manifest(document)


@pytest.mark.parametrize('sqlalchemy_url', [
    'mssql+pyodbc://server/database',
    'oracle+oracledb://server/database',
    'databricks://token@workspace/database',
])
def test_environment_accepts_sqlalchemy_dialect_urls(sqlalchemy_url: str):
    environment = parse_environment(
        (
            'etlonomy_environment = 1\n[connections.warehouse]\n'
            f"sqlalchemy_url = '{sqlalchemy_url}'\n"
        ).encode()
    )

    assert environment.connections[0].sqlalchemy_url == sqlalchemy_url
