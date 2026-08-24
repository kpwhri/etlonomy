from pathlib import Path

import pytest

from etlonomy.catalog import SQLiteCatalog, build_catalog
from etlonomy.codegen import generate_datasets
from etlonomy.exceptions import CatalogError

MANIFEST = b"""etlonomy_manifest = 1

[[datasets]]
canonical_name = 'CLAIMS.CLAIM_LINE'

[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
source_uri = 'claims.csv'
"""


def test_generate_datasets_writes_importable_deterministic_namespace(tmp_path: Path):
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'claims.toml').write_bytes(MANIFEST)
    database = tmp_path / 'catalog.db'
    build_catalog(manifests, database)
    output = tmp_path / 'datasets.py'

    generate_datasets(SQLiteCatalog(database), output)
    first = output.read_text(encoding='utf8')
    generate_datasets(SQLiteCatalog(database), output)

    assert output.read_text(encoding='utf8') == first
    assert "CLAIM_LINE = DatasetId('CLAIMS', 'CLAIM_LINE')" in first
    assert 'CLAIMS = _Claims()' in first


def test_generate_datasets_keeps_similar_subject_names_distinct(tmp_path: Path):
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'similar.toml').write_text(
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'A1.ITEM'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
source_uri = 'one.csv'
[[datasets]]
canonical_name = 'A_1.ITEM'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
source_uri = 'two.csv'
""",
        encoding='utf8',
    )
    database = tmp_path / 'catalog.db'
    output = tmp_path / 'datasets.py'
    build_catalog(manifests, database)

    generate_datasets(SQLiteCatalog(database), output)

    generated = output.read_text(encoding='utf8')
    assert 'class _A1:' in generated
    assert 'class _A_1:' in generated
    assert 'A1 = _A1()' in generated
    assert 'A_1 = _A_1()' in generated


def test_generate_datasets_writes_valid_empty_namespace(tmp_path: Path):
    class EmptyCatalog:
        def list_datasets(self):
            return ()

    output = tmp_path / 'datasets.py'
    generate_datasets(EmptyCatalog(), output)  # type: ignore[arg-type]

    assert 'class Datasets:' in output.read_text(encoding='utf8')
    assert '    pass' in output.read_text(encoding='utf8')


def test_generate_datasets_rejects_normalized_name_collision(tmp_path: Path):
    class DatasetLike:
        def __init__(self, subject: str, name: str):
            self.subject = subject
            self.name = name

        def __str__(self) -> str:
            return f'{self.subject}.{self.name}'

    class CollisionCatalog:
        def list_datasets(self):
            return (DatasetLike('AREA', 'A-B'), DatasetLike('AREA', 'A B'))

    output = tmp_path / 'datasets.py'
    with pytest.raises(CatalogError, match='same Python name'):
        generate_datasets(CollisionCatalog(), output)  # type: ignore[arg-type]

    assert not output.exists()
