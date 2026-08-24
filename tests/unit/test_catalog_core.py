import sqlite3
from contextlib import closing
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pytest

from etlonomy.catalog import SQLiteCatalog, build_catalog
from etlonomy.catalog.migrations import apply_migrations, discover_migrations
from etlonomy.exceptions import (
    CatalogError,
    DependencyCycleError,
    ETLonomyError,
    ManifestError,
)
from etlonomy.manifest import load_manifest, load_manifest_directory, parse_manifest
from etlonomy.models import DatasetId, ExecutionContext, Read, read


def test_domain_errors_are_catchable_through_public_base_error():
    with pytest.raises(ETLonomyError, match='broken'):
        raise ManifestError('broken manifest')


def test_dataset_id_is_canonical_hashable_and_immutable():
    dataset = DatasetId('CLAIMS', 'CLAIM_LINE')
    assert dataset.canonical_name == 'CLAIMS.CLAIM_LINE'
    assert DatasetId.parse(str(dataset)) == dataset
    assert {dataset: 'value'}[dataset] == 'value'
    with pytest.raises(FrozenInstanceError):
        dataset.name = 'OTHER'


def test_dataset_id_rejects_invalid_name_component_after_valid_subject():
    with pytest.raises(ValueError, match='dataset name'):
        DatasetId('CLAIMS', 'claim_line')


@pytest.mark.parametrize('canonical_name', ['claims.CLAIM_LINE', 'CLAIMS', 'A.B.C'])
def test_dataset_id_rejects_noncanonical_names(canonical_name):
    with pytest.raises(ValueError):
        DatasetId.parse(canonical_name)


def test_read_validates_columns_and_version():
    dataset = DatasetId('CLAIMS', 'CLAIM_LINE')
    assert read(dataset, 'person_id', version=2) == Read(dataset, ('person_id',), 2)
    for columns, version in [((), None), (('a', 'a'), None), (('a',), 0)]:
        with pytest.raises(ValueError):
            Read(dataset, columns, version)

    with pytest.raises(ValueError, match='must not be empty'):
        Read(dataset, ('person_id', ''))


def test_execution_context_rejects_empty_environment():
    assert ExecutionContext('prod', date(2026, 1, 1)).environment == 'prod'
    assert ExecutionContext('prod').as_of is None
    with pytest.raises(ValueError):
        ExecutionContext(' ', date(2026, 1, 1))
    with pytest.raises(ValueError, match='surrounding whitespace'):
        ExecutionContext(' prod ', date(2026, 1, 1))


def test_manifest_parses_toml_sorts_versions_and_preserves_optional_metadata():
    manifest = parse_manifest(b"""etlonomy_manifest = 1
[[datasets]]
canonical_name = 'CLAIMS.CLAIM_LINE'
description = 'Claims'
[[datasets.versions]]
version = 2
valid_from = 2026-09-01
source_type = 'sql_table'
source_uri = 'connection://claims'
query = 'dbo.claim_line'
[datasets.versions.columns.person_id]
source = 'member_id'
nullable = false
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
valid_to = 2026-09-01
source_type = 'parquet'
source_uri = '/claims.parquet'
""")
    dataset = manifest.datasets[0]
    assert [version.version for version in dataset.versions] == [1, 2]
    assert dataset.versions[1].columns[0].source_name == 'member_id'


@pytest.mark.parametrize('text, message', [
    ('', 'etlonomy_manifest'),
    ('etlonomy_manifest = 2', 'etlonomy_manifest'),
    ("etlonomy_manifest = 1\ndatasets = 'bad'", 'datasets'),
    ("etlonomy_manifest = 1\n[[datasets]]\ncanonical_name = 'bad'", 'canonical'),
])
def test_manifest_rejects_invalid_documents(text, message):
    with pytest.raises(ManifestError, match=message):
        parse_manifest(text.encode())


def test_manifest_rejects_overlapping_versions():
    document = b"""etlonomy_manifest = 1
[[datasets]]
canonical_name = 'A.B'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
source_type = 'csv'
source_uri = 'a.csv'
[[datasets.versions]]
version = 2
valid_from = 2026-01-01
source_type = 'csv'
source_uri = 'b.csv'
"""
    with pytest.raises(ManifestError, match='overlap'):
        parse_manifest(document)


def test_migrations_are_repeatable_and_enable_foreign_keys(tmp_path):
    with closing(sqlite3.connect(tmp_path / 'catalog.db')) as connection:
        apply_migrations(connection)
        apply_migrations(connection)
        assert connection.execute('PRAGMA foreign_keys').fetchone() == (1,)
        assert connection.execute('SELECT COUNT(*) FROM schema_version').fetchone() == (
            3,
        )
        columns = {
            row[1] for row in connection.execute('PRAGMA table_info(dataset_versions)')
        }
        assert {'source_root', 'connection_name'} <= columns
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'roots'"
        ).fetchone() == ('roots',)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'connections'"
        ).fetchone() == ('connections',)


def test_migrations_upgrade_existing_catalog_with_optional_credential_reference(tmp_path):
    migration_directory = Path('src/etlonomy/catalog/migrations')
    with closing(sqlite3.connect(tmp_path / 'catalog.db')) as connection:
        connection.executescript(
            (migration_directory / '001_initial.sql').read_text(encoding='utf8')
        )
        connection.execute(
            'CREATE TABLE schema_version '
            '(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)'
        )
        connection.execute('INSERT INTO schema_version (version) VALUES (1)')
        connection.commit()

        apply_migrations(connection)

        columns = {
            row[1] for row in connection.execute('PRAGMA table_info(dataset_versions)')
        }
        assert 'credential_ref' in columns
        assert connection.execute(
            'SELECT MAX(version) FROM schema_version'
        ).fetchone() == (3,)


def test_migration_discovery_rejects_duplicate_numbers(tmp_path):
    (tmp_path / '001_a.sql').write_text('SELECT 1;', encoding='utf8')
    (tmp_path / '001_b.sql').write_text('SELECT 1;', encoding='utf8')
    with pytest.raises(CatalogError, match='duplicate'):
        discover_migrations(tmp_path)


def test_failed_migration_rolls_back_version_record(tmp_path):
    migrations = tmp_path / 'migrations'
    migrations.mkdir()
    (migrations / '001_bad.sql').write_text(
        'CREATE TABLE temporary_value (value INTEGER); INVALID SQL;', encoding='utf8'
    )
    with closing(sqlite3.connect(tmp_path / 'catalog.db')) as connection:
        with pytest.raises(CatalogError):
            apply_migrations(connection, migrations)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'schema_version'"
        ).fetchone() is None


def test_later_failed_migration_rolls_back_every_pending_migration(tmp_path):
    migrations = tmp_path / 'migrations'
    migrations.mkdir()
    (migrations / '001_add_first.sql').write_text(
        'CREATE TABLE first_value (value INTEGER);', encoding='utf8'
    )
    (migrations / '002_fail.sql').write_text('INVALID SQL', encoding='utf8')

    with closing(sqlite3.connect(tmp_path / 'catalog.db')) as connection:
        with pytest.raises(CatalogError, match='migration failed'):
            apply_migrations(connection, migrations)

        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
        assert 'first_value' not in tables
        assert 'schema_version' not in tables


def test_migration_separator_preserves_semicolon_inside_sql_string(tmp_path):
    migrations = tmp_path / 'migrations'
    migrations.mkdir()
    (migrations / '001_notes.sql').write_text(
        "CREATE TABLE notes (value TEXT);\n"
        '-- etlonomy:next-statement\n'
        "INSERT INTO notes VALUES ('first; second');\n",
        encoding='utf8',
    )

    with closing(sqlite3.connect(tmp_path / 'catalog.db')) as connection:
        apply_migrations(connection, migrations)
        assert connection.execute('SELECT value FROM notes').fetchone() == (
            'first; second',
        )


def test_empty_migration_is_rejected_without_creating_schema_table(tmp_path):
    migrations = tmp_path / 'migrations'
    migrations.mkdir()
    (migrations / '001_empty.sql').write_text('   \n', encoding='utf8')

    with closing(sqlite3.connect(tmp_path / 'catalog.db')) as connection:
        with pytest.raises(CatalogError, match='contains no SQL'):
            apply_migrations(connection, migrations)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'schema_version'"
        ).fetchone() is None


@pytest.mark.parametrize(('body', 'message'), [
    ('datasets = [1]', 'each dataset'),
    ("[[datasets]]\ncanonical_name = 'A.B'", 'at least one version'),
    ("[[datasets]]\ncanonical_name = 'A.B'\nversions = [1]", 'versions for A.B'),
    (
            "[[datasets]]\ncanonical_name = 'A.B'\n[[datasets.versions]]\n"
            "valid_from = 2025-01-01\nsource_type = 'csv'",
            'missing required version field',
    ),
    (
            "[[datasets]]\ncanonical_name = 'A.B'\n[[datasets.versions]]\nversion = 0\n"
            "valid_from = 2025-01-01\nsource_type = 'csv'",
            'positive integer',
    ),
    (
            "[[datasets]]\ncanonical_name = 'A.B'\n[[datasets.versions]]\nversion = 1\n"
            "valid_from = 2025-01-01\nsource_type = 'unknown'",
            'unsupported source_type',
    ),
    (
            "[[datasets]]\ncanonical_name = 'A.B'\n[[datasets.versions]]\nversion = 1\n"
            "valid_from = 2025-01-02\nvalid_to = 2025-01-01\nsource_type = 'csv'",
            'valid_to must be later',
    ),
    (
            "[[datasets]]\ncanonical_name = 'A.B'\n[[datasets.versions]]\nversion = 1\n"
            "valid_from = 2025-01-01\nsource_type = 'csv'\ndependencies = 'A.B'",
            'dependencies must be an array',
    ),
    (
            "[[datasets]]\ncanonical_name = 'A.B'\n[[datasets.versions]]\nversion = 1\n"
            "valid_from = 2025-01-01\nsource_type = 'sql_query'",
            'requires query',
    ),
    (
            "[[datasets]]\ncanonical_name = 'A.B'\n[[datasets.versions]]\nversion = 1\n"
            "valid_from = 2025-01-01\nsource_type = 'csv'\noptions = 'bad'",
            'options must be a table',
    ),
    (
            "[[datasets]]\ncanonical_name = 'A.B'\n[[datasets.versions]]\nversion = 1\n"
            "valid_from = 2025-01-01\nsource_type = 'csv'\ncolumns = 'bad'",
            'columns must be a table',
    ),
])
def test_manifest_rejects_invalid_dataset_and_version_shapes(body, message):
    with pytest.raises(ManifestError, match=message):
        parse_manifest(f'etlonomy_manifest = 1\n{body}'.encode())


def test_manifest_rejects_invalid_dates_columns_duplicates_and_dependencies():
    templates = [
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'A.B'
[[datasets.versions]]
version = 1
valid_from = 'not-a-date'
source_type = 'csv'
""",
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'A.B'
[[datasets.versions]]
version = 1
valid_from = 7
source_type = 'csv'
""",
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'A.B'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
source_type = 'csv'
[datasets.versions.columns.value]
nullable = 'sometimes'
""",
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'A.B'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
source_type = 'csv'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
""",
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'A.B'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
source_type = 'csv'
dependencies = ['C.D']
""",
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'A.B'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
source_type = 'csv'
dependencies = ['A.B', 'A.B']
""",
    ]
    for template in templates:
        with pytest.raises(ManifestError):
            parse_manifest(template.encode())


def test_manifest_rejects_duplicate_datasets_and_non_string_dependencies():
    duplicate = b"""etlonomy_manifest = 1
[[datasets]]
canonical_name = 'A.B'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
source_type = 'csv'
source_uri = 'a.csv'
[[datasets]]
canonical_name = 'A.B'
[[datasets.versions]]
version = 2
valid_from = 2026-01-01
source_type = 'csv'
source_uri = 'b.csv'
"""
    with pytest.raises(ManifestError, match='duplicate dataset'):
        parse_manifest(duplicate)
    dependency = duplicate.replace(
        b"canonical_name = 'A.B'", b"canonical_name = 'C.D'", 1
    )
    dependency = dependency.replace(
        b"source_type = 'csv'", b"source_type = 'csv'\ndependencies = [1]", 1
    )
    with pytest.raises(ManifestError, match='dependency must be a string'):
        parse_manifest(dependency)


def test_manifest_file_and_directory_errors_are_translated(tmp_path):
    with pytest.raises(ManifestError, match='cannot read manifest'):
        load_manifest(tmp_path / 'missing.toml')
    with pytest.raises(ManifestError, match='no TOML manifests'):
        load_manifest_directory(tmp_path)


def test_manifest_directory_combines_cross_file_dependencies(tmp_path):
    (tmp_path / 'a.toml').write_text(
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'A.B'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
source_type = 'csv'
source_uri = 'a.csv'
dependencies = ['C.D']
""",
        encoding='utf8',
    )
    (tmp_path / 'c.toml').write_text(
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'C.D'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
source_type = 'csv'
source_uri = 'c.csv'
""",
        encoding='utf8',
    )
    manifest = load_manifest_directory(tmp_path)
    assert [str(dataset.dataset) for dataset in manifest.datasets] == ['A.B', 'C.D']


def test_manifest_rejects_dependency_cycle_active_on_same_date():
    document = b"""etlonomy_manifest = 1
[[datasets]]
canonical_name = 'A.ONE'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
source_uri = 'a.csv'
dependencies = ['B.TWO']
[[datasets]]
canonical_name = 'B.TWO'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
source_uri = 'b.csv'
dependencies = ['A.ONE']
"""

    with pytest.raises(DependencyCycleError, match='cycle.*2026-01-01'):
        parse_manifest(document)


def test_manifest_allows_opposing_dependencies_that_never_coexist():
    document = b"""etlonomy_manifest = 1
[[datasets]]
canonical_name = 'A.ONE'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
valid_to = 2026-01-01
source_type = 'csv'
source_uri = 'a.csv'
dependencies = ['B.TWO']
[[datasets.versions]]
version = 2
valid_from = 2026-01-01
source_type = 'csv'
source_uri = 'a.csv'
[[datasets]]
canonical_name = 'B.TWO'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
valid_to = 2026-01-01
source_type = 'csv'
source_uri = 'b.csv'
[[datasets.versions]]
version = 2
valid_from = 2026-01-01
source_type = 'csv'
source_uri = 'b.csv'
dependencies = ['A.ONE']
"""

    assert len(parse_manifest(document).datasets) == 2


def test_manifest_options_are_immutable_after_validation():
    manifest = parse_manifest(b"""etlonomy_manifest = 1
[[datasets]]
canonical_name = 'A.B'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
source_uri = 'a.csv'
[datasets.versions.options]
separator = '|'
""")
    options = manifest.datasets[0].versions[0].options

    with pytest.raises(TypeError):
        options['separator'] = ','  # type: ignore[index]


@pytest.mark.parametrize(('body', 'message'), [
    (
            "source_type = 'sql_table'\nsource_uri = 'not a URL'\nquery = 'claims'",
            'valid SQLAlchemy URL',
    ),
    (
            "source_type = 'sql_table'\nsource_uri = 'sqlite:///x.db'\n"
            "query = 'claims; DROP TABLE claims'",
            'invalid SQL table reference',
    ),
])
def test_manifest_rejects_invalid_sql_location_and_table(body, message):
    document = (
        "etlonomy_manifest = 1\n[[datasets]]\ncanonical_name = 'A.B'\n"
        '[[datasets.versions]]\nversion = 1\nvalid_from = 2026-01-01\n'
        f'{body}\n'
    )

    with pytest.raises(ManifestError, match=message):
        parse_manifest(document.encode())


def test_sqlite_catalog_rejects_missing_path_without_creating_a_file(tmp_path):
    catalog_path = tmp_path / 'missing.db'

    with pytest.raises(CatalogError, match='does not exist'):
        SQLiteCatalog(catalog_path).list_datasets()

    assert not catalog_path.exists()


def test_sqlite_catalog_rejects_stale_schema_with_rebuild_guidance(tmp_path):
    catalog_path = tmp_path / 'stale.db'
    with closing(sqlite3.connect(catalog_path)) as connection:
        connection.execute(
            'CREATE TABLE schema_version '
            '(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)'
        )
        connection.execute("INSERT INTO schema_version VALUES (1, 'now')")
        connection.commit()

    with pytest.raises(CatalogError, match='expected 3.*Rebuild'):
        SQLiteCatalog(catalog_path).list_datasets()


def test_sqlite_catalog_translates_corrupt_schema_query_errors(tmp_path):
    catalog_path = tmp_path / 'corrupt.db'
    with closing(sqlite3.connect(catalog_path)) as connection:
        connection.execute(
            'CREATE TABLE schema_version '
            '(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)'
        )
        connection.execute("INSERT INTO schema_version VALUES (3, 'now')")
        connection.commit()

    with pytest.raises(CatalogError, match='cannot query catalog'):
        SQLiteCatalog(catalog_path).list_datasets()


def test_sqlite_catalog_translates_unreadable_database_errors(tmp_path):
    catalog_path = tmp_path / 'not-sqlite.db'
    catalog_path.write_bytes(b'not a sqlite database')

    with pytest.raises(CatalogError, match='cannot open catalog'):
        SQLiteCatalog(catalog_path).list_datasets()


def test_resolved_catalog_options_are_immutable(tmp_path):
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'source.toml').write_text(
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'A.B'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
source_uri = 'a.csv'
[datasets.versions.options]
separator = '|'
""",
        encoding='utf8',
    )
    catalog_path = tmp_path / 'catalog.db'
    build_catalog(manifests, catalog_path)
    options = SQLiteCatalog(catalog_path).resolve_dataset(DatasetId('A', 'B')).options

    with pytest.raises(TypeError):
        options['separator'] = ','  # type: ignore[index]
