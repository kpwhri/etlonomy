"""Prove one ETL and reusable helper survive a real SAS-to-SQL migration."""
import importlib
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import polars as pl
import pytest

import etlonomy
from etlonomy.catalog import SQLiteCatalog, build_catalog
from etlonomy.registry import Registry

FIXTURE_DIRECTORY = Path(__file__).parents[1] / 'fixtures'


def _sas_support_enabled() -> bool:
    return importlib.util.find_spec('pyreadstat') is not None


requires_sas = pytest.mark.skipif(
    not _sas_support_enabled(),
    reason='SAS7BDAT support requires the etlonomy sas extra',
)


@requires_sas
def test_real_sas_and_sql_versions_run_unchanged_etl_with_requires_and_lineage(tmp_path: Path, monkeypatch):
    claim_path = FIXTURE_DIRECTORY / 'claim_line.sas7bdat'
    provider_path = FIXTURE_DIRECTORY / 'provider.sas7bdat'
    assert claim_path.is_file(), f'missing SAS fixture: {claim_path}'
    assert provider_path.is_file(), f'missing SAS fixture: {provider_path}'

    sql_path = tmp_path / 'claims.sqlite'
    with closing(sqlite3.connect(sql_path)) as connection:
        with connection:
            connection.execute(
                'CREATE TABLE claim_line ('
                'member_id INTEGER, provider_id INTEGER, svc_dt TEXT, '
                'diagnosis_cd TEXT)'
            )
            connection.executemany(
                'INSERT INTO claim_line VALUES (?, ?, ?, ?)',
                [
                    (1, 101, '2026-08-01', 'I10'),
                    (2, 102, '2026-08-02', ''),
                    (3, 103, '2026-08-03', 'E11'),
                ],
            )

    manifest_directory = tmp_path / 'manifests'
    manifest_directory.mkdir()
    (manifest_directory / 'datasets.toml').write_text(
        f"""etlonomy_manifest = 1
[[datasets]]
canonical_name = 'CLAIMS.CLAIM_LINE'
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
valid_to = 2026-09-01
source_type = 'sas7bdat'
source_uri = '{claim_path.as_posix()}'
[datasets.versions.columns.person_id]
source = 'member_id'
[datasets.versions.columns.service_date]
source = 'svc_dt'
[datasets.versions.columns.diagnosis_code]
source = 'diagnosis_cd'
[[datasets.versions]]
version = 2
valid_from = 2026-09-01
source_type = 'sql_table'
source_uri = 'sqlite:///{sql_path.as_posix()}'
query = 'claim_line'
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
    build_catalog(manifest_directory, catalog_path)

    claims = etlonomy.DatasetId('CLAIMS', 'CLAIM_LINE')
    providers = etlonomy.DatasetId('REFERENCE', 'PROVIDER')
    output = etlonomy.DatasetId('CLAIMS', 'ENRICHED_CLAIMS')
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)

    @etlonomy.requires(
        providers=etlonomy.read(providers, 'provider_id', 'specialty'),
    )
    def attach_specialty(
            frame: pl.LazyFrame,
            providers: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Attach specialty through a reusable logical dependency."""
        return frame.with_columns(
            pl.col('provider_id').cast(pl.Int64)
        ).join(
            providers.with_columns(pl.col('provider_id').cast(pl.Int64)),
            on='provider_id',
            how='left',
        )

    @etlonomy.etl(
        name='claims.build_enriched',
        inputs={
            'claims': etlonomy.read(
                claims,
                'person_id',
                'provider_id',
                'diagnosis_code',
            ),
        },
        outputs=(output,),
        uses=(attach_specialty,),
    )
    def build_enriched(claims: pl.LazyFrame) -> pl.LazyFrame:
        """Keep diagnosed claims after adding provider specialty."""
        return (
            attach_specialty(claims)
            .filter(pl.col('diagnosis_code').str.len_chars() > 0)
            .with_columns(
                pl.col('person_id').cast(pl.Int64),
                pl.col('provider_id').cast(pl.Int64),
            )
        )

    provider = etlonomy.CatalogDatasetProvider(SQLiteCatalog(catalog_path))
    results: list[pl.DataFrame] = []
    traces: list[tuple[etlonomy.Read, ...]] = []
    for as_of in (date(2026, 8, 31), date(2026, 9, 1)):
        runtime = etlonomy.Runtime(
            provider=provider,
            context=etlonomy.ExecutionContext(as_of=as_of),
            job_registry=job_registry,
        )
        result = runtime.run('claims.build_enriched')
        assert isinstance(result, pl.LazyFrame)
        results.append(result.collect())
        traces.append(runtime.last_dependencies)

    expected = {
        'person_id': [1, 3],
        'provider_id': [101, 103],
        'diagnosis_code': ['I10', 'E11'],
        'specialty': ['Cardiology', 'Neurology'],
    }
    assert results[0].to_dict(as_series=False) == expected
    assert results[1].to_dict(as_series=False) == expected
    assert tuple(request.dataset for request in traces[0]) == (claims, providers)
    assert tuple(request.dataset for request in traces[1]) == (claims, providers)

    definition = job_registry.get_etl('claims.build_enriched')
    declared = etlonomy.LineageGraph()
    declared.add_registry(job_registry)
    assert declared.declared_uses(definition.name) == (claims, providers)
    assert declared.consumers(providers, job_registry) == (definition.name,)
    assert declared.requirement_consumers(providers, job_registry) == (
        attach_specialty.__qualname__,
    )

    traced = etlonomy.LineageGraph()
    traced.add_runtime_trace(definition.name, definition.outputs, traces[0])
    assert traced.uses(definition.name) == (claims, providers)
    assert traced.parents(output) == (claims, providers)
