"""Run one unchanged ETL across real SAS and temporary SQLite sources."""
import importlib
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from etlonomy.catalog import SQLiteCatalog, build_catalog
from etlonomy.catalog_provider import CatalogDatasetProvider
from etlonomy.models import DatasetId, ExecutionContext, read
from etlonomy.registry import EtlDefinition, Registry
from etlonomy.runtime import Runtime

FIXTURE_DIRECTORY = Path(__file__).parents[1] / 'fixtures'


def _sas_support_enabled() -> bool:
    return importlib.util.find_spec('pyreadstat') is not None


requires_sas = pytest.mark.skipif(
    not _sas_support_enabled(),
    reason='SAS7BDAT support requires the etlonomy sas extra',
)


@requires_sas
def test_same_etl_runs_before_and_after_real_sas_to_sql_migration(tmp_path: Path):
    sas_path = FIXTURE_DIRECTORY / 'claim_line.sas7bdat'
    assert sas_path.is_file(), f'missing SAS fixture: {sas_path}'
    sql_path = tmp_path / 'claims.sqlite'
    with closing(sqlite3.connect(sql_path)) as connection:
        with connection:
            connection.execute(
                'CREATE TABLE claim_line ('
                'person_id INTEGER, diagnosis_code TEXT)'
            )
            connection.executemany(
                'INSERT INTO claim_line VALUES (?, ?)',
                [(1, 'I10'), (2, ''), (3, 'E11')],
            )

    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'claims.toml').write_text(
        f"""etlonomy_manifest = 1
[[datasets]]
canonical_name = 'CLAIMS.CLAIM_LINE'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
valid_to = 2026-09-01
source_type = 'sas7bdat'
source_uri = '{sas_path.as_posix()}'
[datasets.versions.columns.person_id]
source = 'member_id'
[datasets.versions.columns.diagnosis_code]
source = 'diagnosis_cd'
[[datasets.versions]]
version = 2
valid_from = 2026-09-01
source_type = 'sql_table'
source_uri = 'sqlite:///{sql_path.as_posix()}'
query = 'claim_line'
""",
        encoding='utf8',
    )
    database = tmp_path / 'catalog.db'
    build_catalog(manifests, database)
    provider = CatalogDatasetProvider(SQLiteCatalog(database))
    dataset = DatasetId('CLAIMS', 'CLAIM_LINE')
    request = read(dataset, 'person_id', 'diagnosis_code')

    def cohort(claims: pl.LazyFrame) -> pl.LazyFrame:
        return claims.filter(pl.col('diagnosis_code').str.len_chars() > 0).select(
            pl.col('person_id').cast(pl.Int64)
        )

    job_registry = Registry()
    job_registry.register_etl(
        EtlDefinition('cohort.build', cohort, {'claims': request}, (), None, None)
    )
    results = []
    for as_of in (date(2026, 8, 31), date(2026, 9, 1)):
        runtime = Runtime(
            provider=provider,
            context=ExecutionContext(as_of=as_of),
            job_registry=job_registry,
        )
        result = runtime.run('cohort.build')
        assert isinstance(result, pl.LazyFrame)
        results.append(result.collect()['person_id'].to_list())

    assert results == [[1, 3], [1, 3]]
    assert SQLiteCatalog(database).resolve_dataset(
        dataset, date(2026, 8, 31)
    ).source_type == 'sas7bdat'
    assert SQLiteCatalog(database).resolve_dataset(
        dataset, date(2026, 9, 1)
    ).source_type == 'sql_table'
