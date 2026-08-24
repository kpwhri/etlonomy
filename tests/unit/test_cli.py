import json
from pathlib import Path

from etlonomy.cli import main
from etlonomy.models import DatasetId, read
from etlonomy.registry import EtlDefinition, RequirementDefinition, registry

MANIFEST = """etlonomy_manifest = 1

[[datasets]]
canonical_name = 'REFERENCE.ZIP_CODES'

[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
source_uri = 'zip.csv'
"""


def test_catalog_cli_build_show_history_and_resolve(tmp_path: Path, capsys):
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'reference.toml').write_text(MANIFEST, encoding='utf8')
    database = tmp_path / 'catalog.db'
    assert main([
        'catalog',
        'build',
        '--manifest-dir',
        str(manifests),
        '--database',
        str(database),
    ]) == 0
    assert main(['catalog', 'show', '--database', str(database)]) == 0
    assert main([
        'catalog',
        'history',
        '--database',
        str(database),
        'REFERENCE.ZIP_CODES',
    ]) == 0
    assert main([
        'catalog',
        'resolve',
        '--database',
        str(database),
        'REFERENCE.ZIP_CODES',
        '--as-of',
        '2026-08-20',
    ]) == 0
    assert main([
        'catalog',
        'resolve',
        '--database',
        str(database),
        'REFERENCE.ZIP_CODES',
    ]) == 0
    assert 'REFERENCE.ZIP_CODES' in capsys.readouterr().out  # type: ignore[attr-defined]


def test_catalog_validate_reports_manifest_error(tmp_path: Path, capsys):
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'bad.toml').write_text('not toml =', encoding='utf8')

    assert main(['catalog', 'validate', '--manifest-dir', str(manifests)]) == 1
    assert 'error:' in capsys.readouterr().err  # type: ignore[attr-defined]


def test_cli_validates_diffs_and_generates_datasets(tmp_path: Path, capsys):
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'reference.toml').write_text(MANIFEST, encoding='utf8')
    first = tmp_path / 'first.db'
    second = tmp_path / 'second.db'
    for database in (first, second):
        assert main([
            'catalog',
            'build',
            '--manifest-dir',
            str(manifests),
            '--database',
            str(database),
        ]) == 0
    assert main(['catalog', 'validate', '--manifest-dir', str(manifests)]) == 0
    assert main(['catalog', 'diff', str(first), str(second)]) == 0
    output = tmp_path / 'datasets.py'
    assert main([
        'codegen',
        'datasets',
        '--database',
        str(first),
        '--output',
        str(output),
    ]) == 0
    assert 'ZIP_CODES' in output.read_text(encoding='utf8')
    assert '"added": []' in capsys.readouterr().out  # type: ignore[attr-defined]

    (manifests / 'reference.toml').write_text(
        MANIFEST.replace('zip.csv', 'zip-v2.csv'), encoding='utf8'
    )
    assert main([
        'catalog',
        'build',
        '--manifest-dir',
        str(manifests),
        '--database',
        str(second),
    ]) == 0
    assert main(['catalog', 'diff', str(first), str(second)]) == 0
    assert '"changed": ["REFERENCE.ZIP_CODES"]' in capsys.readouterr().out  # type: ignore[attr-defined]


def test_cli_reports_registry_and_lineage_formats(capsys):
    source = DatasetId('CLI', 'SOURCE')
    target = DatasetId('CLI', 'TARGET')
    name = 'cli.coverage_job'
    registry.register_etl(
        EtlDefinition(
            name,
            lambda frame: frame,
            {'frame': read(source, 'id')},
            (target,),
            None,
            None,
        )
    )

    assert main(['registry', 'validate']) == 0
    assert main(['deps', name]) == 0
    assert main(['uses', str(source), '--format', 'json']) == 0
    assert main(['lineage', str(target), '--format', 'json']) == 0
    assert main(['graph', name, '--format', 'dot']) == 0
    assert main(['graph', name, '--format', 'mermaid']) == 0
    assert main(['graph', name, '--format', 'json']) == 0
    assert main(['graph', name]) == 0
    assert main(['registry', 'validate', '--module', 'json']) == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert name in output
    assert 'digraph etlonomy' in output
    assert 'graph LR' in output


def test_cli_returns_error_for_unknown_registered_job(capsys):
    assert main(['deps', 'missing.job']) == 1
    assert 'not registered' in capsys.readouterr().err  # type: ignore[attr-defined]


def test_cli_combines_catalog_and_registry_lineage_and_exports_exact_edges(tmp_path: Path, capsys):
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'lineage.toml').write_text(
        """etlonomy_manifest = 1
[[datasets]]
canonical_name = 'CLI.RAW'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
source_uri = 'raw.csv'
[[datasets]]
canonical_name = 'CLI.CURATED'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'sql_query'
source_uri = 'sqlite:///warehouse.db'
query = 'SELECT id FROM raw'
dependencies = ['CLI.RAW']
""",
        encoding='utf8',
    )
    database = tmp_path / 'catalog.db'
    assert main([
        'catalog',
        'build',
        '--manifest-dir',
        str(manifests),
        '--database',
        str(database),
    ]) == 0
    curated = DatasetId('CLI', 'CURATED')
    output = DatasetId('CLI', 'REPORT')
    name = 'cli.catalog_lineage'
    registry.register_etl(
        EtlDefinition(
            name,
            lambda frame: frame,
            {'frame': read(curated, 'id')},
            (output,),
            None,
            None,
        )
    )

    assert main(['deps', name, '--database', str(database)]) == 0
    deps_output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert 'Direct:\n    CLI.CURATED' in deps_output
    assert 'Transitive:\n    CLI.RAW' in deps_output

    assert main([
        'lineage',
        str(curated),
        '--database',
        str(database),
        '--format',
        'json',
    ]) == 0
    lineage_output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert '"parents": ["CLI.RAW"]' in lineage_output

    for output_format in ('mermaid', 'dot', 'json'):
        assert main([
            'graph',
            name,
            '--database',
            str(database),
            '--format',
            output_format,
        ]) == 0
    graph_output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert '["CLI.RAW"] -->' in graph_output
    assert '["CLI.CURATED"]' in graph_output
    assert '["CLI.REPORT"]' in graph_output
    assert '"CLI.RAW" -> "CLI.CURATED";' in graph_output
    assert '"CLI.CURATED" -> "CLI.REPORT";' in graph_output
    graph_record = json.loads(graph_output.splitlines()[-1])
    assert ['CLI.CURATED', 'CLI.REPORT'] in graph_record['edges']
    assert ['CLI.RAW', 'CLI.CURATED'] in graph_record['edges']
    assert ['CLI.CURATED', 'job:cli.catalog_lineage'] in graph_record['edges']
    assert ['job:cli.catalog_lineage', 'CLI.REPORT'] in graph_record['edges']


def test_cli_traces_declared_reusable_function_uses(capsys):
    providers = DatasetId('CLI', 'PROVIDERS')
    claims = DatasetId('CLI', 'CLAIMS')
    output = DatasetId('CLI', 'ENRICHED')

    def attach_provider():
        pass

    registry.register_requirement(
        RequirementDefinition(
            attach_provider,
            {'providers': read(providers, 'provider_id')},
            None,
            None,
        )
    )
    registry.register_etl(
        EtlDefinition(
            'cli.declared_uses',
            lambda frame: frame,
            {'frame': read(claims, 'provider_id')},
            (output,),
            None,
            None,
            (attach_provider,),
        )
    )

    assert main(['deps', 'cli.declared_uses', '--format', 'json']) == 0
    dependencies = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert dependencies['direct'] == ['CLI.CLAIMS']
    assert dependencies['transitive'] == ['CLI.PROVIDERS']

    assert main(['uses', str(providers), '--format', 'json']) == 0
    consumers = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert consumers['etl_jobs'] == ['cli.declared_uses']
    assert consumers['reusable_functions'] == [attach_provider.__qualname__]

    assert main(['graph', 'cli.declared_uses', '--format', 'json']) == 0
    graph = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert ['CLI.PROVIDERS', f'function:{attach_provider.__qualname__}'] in graph[
        'edges'
    ]
    assert [f'function:{attach_provider.__qualname__}', 'job:cli.declared_uses'] in graph[
        'edges'
    ]
