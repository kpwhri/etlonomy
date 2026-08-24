"""Execute the complete tutorial project and its upgrades in a temp directory."""

import importlib
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import ModuleType

import polars as pl
import pytest

import etlonomy
from etlonomy.cli import main
from etlonomy.registry import Registry

CSV_DATA = """person_id,provider_id,service_date,diagnosis_code
1001,10,2026-08-01,I10
1002,10,2026-08-02,
1003,20,2026-08-03,E11
"""

CLAIMS_HEADER = """etlonomy_manifest = 1

[[datasets]]
canonical_name = 'CLAIMS.CLAIM_LINE'
description = 'Claim lines used by cohort jobs.'
"""

CSV_VERSION = """
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
{valid_to}source_type = 'csv'
source_uri = 'data/claim_line.csv'
"""

PARQUET_VERSION = """
[[datasets.versions]]
version = 2
valid_from = 2026-09-01
{valid_to}source_type = 'parquet'
source_uri = 'data/claim_line.parquet'
"""

SQLITE_VERSION = """
[[datasets.versions]]
version = 3
valid_from = 2027-01-01
source_type = 'sql_table'
source_uri = 'sqlite:///data/claims.sqlite'
query = 'claim_line'
"""

REFERENCE_MANIFEST = """etlonomy_manifest = 1

[[datasets]]
canonical_name = 'REFERENCE.PROVIDER'
description = 'Provider attributes used to enrich claims.'

[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'parquet'
source_uri = 'data/providers.parquet'

[[datasets]]
canonical_name = 'REFERENCE.REGION'
description = 'Region labels stored in a local SQL table.'

[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'sql_table'
source_uri = 'sqlite:///data/reference.sqlite'
query = 'regions'
"""

SIMPLE_JOBS_SOURCE = '''"""Initial ETL job used by the first tutorial lessons."""

import polars as pl

import etlonomy
from claims_demo.datasets import Datasets


@etlonomy.etl(
    name='cohort.build',
    inputs={
        'claims': etlonomy.read(
            Datasets.CLAIMS.CLAIM_LINE,
            'person_id',
            'diagnosis_code',
        ),
    },
)
def build_cohort(claims: pl.LazyFrame) -> pl.LazyFrame:
    """Keep claim rows that contain a diagnosis code."""
    return claims.filter(pl.col('diagnosis_code').is_not_null())
'''

ENRICHED_JOBS_SOURCE = '''"""ETL and reusable helper used by the completed tutorial."""

import polars as pl

import etlonomy
from claims_demo.datasets import Datasets

COHORT_RESULT = etlonomy.DatasetId('COHORT', 'RESULT')


@etlonomy.requires(
    regions=etlonomy.read(
        Datasets.REFERENCE.REGION,
        'region_id',
        'region_name',
    ),
)
def attach_region(
    providers: pl.LazyFrame,
    regions: pl.LazyFrame,
) -> pl.LazyFrame:
    """Attach a logical region name to each provider."""
    return providers.join(regions, on='region_id', how='left')


@etlonomy.etl(
    name='cohort.build',
    inputs={
        'claims': etlonomy.read(
            Datasets.CLAIMS.CLAIM_LINE,
            'person_id',
            'provider_id',
            'diagnosis_code',
        ),
        'providers': etlonomy.read(
            Datasets.REFERENCE.PROVIDER,
            'provider_id',
            'region_id',
        ),
    },
    uses=(attach_region,),
    outputs=(COHORT_RESULT,),
)
def build_cohort(
    claims: pl.LazyFrame,
    providers: pl.LazyFrame,
) -> pl.LazyFrame:
    """Keep diagnosed claims and attach each provider's region."""
    enriched_providers = attach_region(providers)
    return (
        claims.filter(pl.col('diagnosis_code').is_not_null())
        .join(enriched_providers, on='provider_id', how='left')
        .select('person_id', 'diagnosis_code', 'region_name')
    )
'''


@dataclass(frozen=True, slots=True)
class TutorialProject:
    """Hold results and metadata from the canonical temporary tutorial project."""

    module: ModuleType
    registry: Registry
    runtime: etlonomy.Runtime
    production_result: pl.DataFrame
    test_result: pl.DataFrame
    output: etlonomy.DatasetId


def _write_claims_manifest(path: Path, version_count: int):
    csv = CSV_VERSION.format(
        valid_to='valid_to = 2026-09-01\n' if version_count > 1 else ''
    )
    parquet = ''
    if version_count > 1:
        parquet = PARQUET_VERSION.format(
            valid_to='valid_to = 2027-01-01\n' if version_count > 2 else ''
        )
    sqlite = SQLITE_VERSION if version_count > 2 else ''
    path.write_text(CLAIMS_HEADER + csv + parquet + sqlite, encoding='utf8')


def _create_physical_sources(data_directory: Path):
    csv_path = data_directory / 'claim_line.csv'
    csv_path.write_text(CSV_DATA, encoding='utf8')
    claims = pl.read_csv(csv_path)
    claims.write_parquet(data_directory / 'claim_line.parquet')
    pl.DataFrame({
        'provider_id': [10, 20],
        'region_id': [100, 200],
    }).write_parquet(data_directory / 'providers.parquet')
    with closing(sqlite3.connect(data_directory / 'claims.sqlite')) as connection:
        with connection:
            connection.execute(
                'CREATE TABLE claim_line ('
                'person_id INTEGER, provider_id INTEGER, service_date TEXT, '
                'diagnosis_code TEXT)'
            )
            connection.executemany(
                'INSERT INTO claim_line VALUES (?, ?, ?, ?)', claims.iter_rows()
            )
    with closing(sqlite3.connect(data_directory / 'reference.sqlite')) as connection:
        with connection:
            connection.execute(
                'CREATE TABLE regions (region_id INTEGER, region_name TEXT)'
            )
            connection.executemany(
                'INSERT INTO regions VALUES (?, ?)', [(100, 'West'), (200, 'East')]
            )


def _build_catalog():
    assert main([
        'catalog',
        'build',
        '--manifest-dir',
        'manifests',
        '--database',
        '.etlonomy/catalog.db',
        '--environment-config',
        'environment.toml',
    ]) == 0


def _run_production(
        database: Path,
        job_registry: Registry,
        as_of: date,
) -> tuple[pl.DataFrame, etlonomy.Runtime]:
    runtime = etlonomy.Runtime(
        provider=etlonomy.CatalogDatasetProvider(
            catalog=etlonomy.SQLiteCatalog(database)
        ),
        context=etlonomy.ExecutionContext('prod', as_of),
        job_registry=job_registry,
    )
    result = runtime.run('cohort.build')
    assert isinstance(result, pl.LazyFrame)
    return result.collect(), runtime


@pytest.fixture
def tutorial_project(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
) -> Iterator[TutorialProject]:
    """Run every main tutorial phase against a disposable project."""
    project = tmp_path / 'claims-demo'
    data_directory = project / 'data'
    manifest_directory = project / 'manifests'
    package_directory = project / 'src' / 'claims_demo'
    catalog_directory = project / '.etlonomy'
    for directory in (
            data_directory,
            manifest_directory,
            package_directory,
            catalog_directory,
    ):
        directory.mkdir(parents=True)
    _create_physical_sources(data_directory)
    (package_directory / '__init__.py').write_text('', encoding='utf8')
    (project / 'environment.toml').write_text(
        "etlonomy_environment = 1\nenvironment = 'prod'\n", encoding='utf8'
    )
    for module_name in tuple(sys.modules):
        if module_name == 'claims_demo' or module_name.startswith('claims_demo.'):
            sys.modules.pop(module_name, None)
    monkeypatch.chdir(project)
    monkeypatch.syspath_prepend(str(project / 'src'))

    claims_manifest = manifest_directory / 'claims.toml'
    _write_claims_manifest(claims_manifest, version_count=1)
    assert main([
        'catalog',
        'validate',
        '--manifest-dir',
        'manifests',
        '--environment-config',
        'environment.toml',
    ]) == 0
    _build_catalog()
    assert main(['catalog', 'show', '--database', '.etlonomy/catalog.db']) == 0
    assert main([
        'catalog',
        'resolve',
        '--database',
        '.etlonomy/catalog.db',
        'CLAIMS.CLAIM_LINE',
        '--as-of',
        '2026-08-20',
    ]) == 0
    assert main([
        'codegen',
        'datasets',
        '--database',
        '.etlonomy/catalog.db',
        '--output',
        'src/claims_demo/datasets.py',
    ]) == 0
    (package_directory / 'jobs.py').write_text(SIMPLE_JOBS_SOURCE, encoding='utf8')
    simple_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', simple_registry)
    importlib.import_module('claims_demo.jobs')
    database = catalog_directory / 'catalog.db'
    simple_result, _ = _run_production(
        database, simple_registry, date(2026, 8, 20)
    )
    assert simple_result['person_id'].to_list() == [1001, 1003]

    _write_claims_manifest(claims_manifest, version_count=2)
    _build_catalog()
    parquet_result, _ = _run_production(
        database, simple_registry, date(2026, 9, 1)
    )
    assert parquet_result['person_id'].to_list() == [1001, 1003]

    (manifest_directory / 'reference.toml').write_text(
        REFERENCE_MANIFEST, encoding='utf8'
    )
    _build_catalog()
    assert main([
        'codegen',
        'datasets',
        '--database',
        '.etlonomy/catalog.db',
        '--output',
        'src/claims_demo/datasets.py',
    ]) == 0
    sys.modules.pop('claims_demo.jobs', None)
    sys.modules.pop('claims_demo.datasets', None)
    importlib.invalidate_caches()
    (package_directory / 'jobs.py').write_text(ENRICHED_JOBS_SOURCE, encoding='utf8')
    enriched_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', enriched_registry)
    module = importlib.import_module('claims_demo.jobs')
    unchanged_job = (package_directory / 'jobs.py').read_bytes()

    production_result, runtime = _run_production(
        database, enriched_registry, date(2026, 8, 20)
    )
    test_provider = etlonomy.TestDatasetProvider({
        etlonomy.DatasetId('CLAIMS', 'CLAIM_LINE'): pl.DataFrame({
            'person_id': [9001, 9002],
            'provider_id': [91, 92],
            'diagnosis_code': ['TEST', None],
        }),
        etlonomy.DatasetId('REFERENCE', 'PROVIDER'): pl.DataFrame({
            'provider_id': [91, 92],
            'region_id': [901, 902],
        }),
        etlonomy.DatasetId('REFERENCE', 'REGION'): pl.DataFrame({
            'region_id': [901, 902],
            'region_name': ['Fixture West', 'Fixture East'],
        }),
    })
    test_runtime = etlonomy.Runtime(
        provider=test_provider,
        context=etlonomy.ExecutionContext('test', date(2026, 8, 20)),
        job_registry=enriched_registry,
    )
    test_lazy = test_runtime.run('cohort.build')
    assert isinstance(test_lazy, pl.LazyFrame)
    test_result = test_lazy.collect()

    _write_claims_manifest(claims_manifest, version_count=3)
    _build_catalog()
    sqlite_result, runtime = _run_production(
        database, enriched_registry, date(2027, 1, 1)
    )
    assert sqlite_result.equals(production_result)
    assert (package_directory / 'jobs.py').read_bytes() == unchanged_job
    assert 'CLAIMS.CLAIM_LINE' in capsys.readouterr().out

    yield TutorialProject(
        module=module,
        registry=enriched_registry,
        runtime=runtime,
        production_result=production_result,
        test_result=test_result,
        output=etlonomy.DatasetId('COHORT', 'RESULT'),
    )
    for module_name in tuple(sys.modules):
        if module_name == 'claims_demo' or module_name.startswith('claims_demo.'):
            sys.modules.pop(module_name, None)


def test_canonical_tutorial_runs_csv_parquet_sqlite_and_test_data(tutorial_project: TutorialProject):
    assert tutorial_project.production_result.to_dict(as_series=False) == {
        'person_id': [1001, 1003],
        'diagnosis_code': ['I10', 'E11'],
        'region_name': ['West', 'East'],
    }
    assert tutorial_project.test_result.to_dict(as_series=False) == {
        'person_id': [9001],
        'diagnosis_code': ['TEST'],
        'region_name': ['Fixture West'],
    }


def test_canonical_tutorial_lineage_includes_etl_and_requires_reads(tutorial_project: TutorialProject):
    definition = tutorial_project.registry.get_etl('cohort.build')
    graph = etlonomy.LineageGraph()
    graph.add_runtime_trace(
        definition.name,
        definition.outputs,
        tutorial_project.runtime.last_dependencies,
    )

    assert graph.parents(tutorial_project.output) == (
        etlonomy.DatasetId('CLAIMS', 'CLAIM_LINE'),
        etlonomy.DatasetId('REFERENCE', 'PROVIDER'),
        etlonomy.DatasetId('REFERENCE', 'REGION'),
    )


def test_canonical_tutorial_uses_reports_direct_and_reusable_consumers(tutorial_project: TutorialProject):
    graph = etlonomy.LineageGraph()
    graph.add_registry(tutorial_project.registry)
    regions = etlonomy.DatasetId('REFERENCE', 'REGION')

    assert graph.declared_uses('cohort.build') == (
        etlonomy.DatasetId('CLAIMS', 'CLAIM_LINE'),
        etlonomy.DatasetId('REFERENCE', 'PROVIDER'),
        regions,
    )
    assert graph.consumers(regions, tutorial_project.registry) == ('cohort.build',)
    assert graph.requirement_consumers(regions, tutorial_project.registry) == (
        tutorial_project.module.attach_region.__qualname__,
    )
