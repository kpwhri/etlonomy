"""Validate navigation and example coverage in the Markdown documentation."""

import re
from pathlib import Path

DOCS_DIRECTORY = Path(__file__).parents[2] / 'docs'
PROJECT_DIRECTORY = DOCS_DIRECTORY.parent
MARKDOWN_LINK = re.compile(r'\[[^]]+\]\(([^)]+\.md)(?:#[^)]+)?\)')


def test_every_documentation_page_links_to_related_guidance():
    for page in DOCS_DIRECTORY.rglob('*.md'):
        content = page.read_text(encoding='utf8')
        assert MARKDOWN_LINK.search(content), f'{page} has no cross-document links'


def test_every_documentation_page_contains_a_copyable_example():
    for page in DOCS_DIRECTORY.rglob('*.md'):
        content = page.read_text(encoding='utf8')
        assert '```' in content, f'{page} has no code or file example'


def test_all_relative_markdown_links_resolve_to_existing_files():
    broken: list[str] = []
    for page in DOCS_DIRECTORY.rglob('*.md'):
        content = page.read_text(encoding='utf8')
        for target in MARKDOWN_LINK.findall(content):
            if not (page.parent / target).resolve().is_file():
                broken.append(f'{page.relative_to(DOCS_DIRECTORY)} -> {target}')
    assert not broken, 'broken documentation links:\n' + '\n'.join(broken)


def test_documented_declared_uses_matches_the_executable_api():
    content = (DOCS_DIRECTORY / 'requires.md').read_text(encoding='utf8')

    assert 'uses=(attach_specialty,)' in content
    assert 'graph.declared_uses' in (
            DOCS_DIRECTORY / 'lineage.md'
    ).read_text(encoding='utf8')


def test_documented_environment_sources_match_executed_integration_examples():
    content = (DOCS_DIRECTORY / 'environments.md').read_text(encoding='utf8')

    assert '[roots.claims]' in content
    assert "source_root = 'claims'" in content
    assert '[connections.claims_database]' in content
    assert "connection = 'claims_database'" in content
    assert "context = etlonomy.ExecutionContext(environment='prod')" in content


def test_external_dataset_guide_matches_the_executable_public_api():
    content = (DOCS_DIRECTORY / 'external-datasets.md').read_text(encoding='utf8')
    workflow = (
        PROJECT_DIRECTORY
        / 'tests'
        / 'end_to_end'
        / 'test_external_dataset_workflow.py'
    ).read_text(encoding='utf8')

    examples = (
        'SV_CLAIMS = etlonomy.ExternalDatasetId(',
        "system='vdwcore'",
        "name='sv.vdw_claims'",
        'claims=etlonomy.external_read(',
        'external_providers={',
        "claims=claims_df",
        "declared_external_uses('cohort.build')",
        'FileExternalDatasetProvider(source_view)',
    )
    for example in examples:
        assert example in content

    assert "ExternalDatasetId('files', 'sv.claims')" in workflow
    assert "external_providers={" in workflow
    assert "declared_external_uses('cohort.external_claims')" in workflow


def test_tutorial_home_indexes_every_tutorial_in_numbered_order():
    tutorial_directory = DOCS_DIRECTORY / 'tutorials'
    index = (tutorial_directory / 'index.md').read_text(encoding='utf8')
    positions = [
        index.index(page.name)
        for page in sorted(tutorial_directory.glob('[0-9][0-9]-*.md'))
    ]

    assert positions == sorted(positions)


def test_implementation_checklist_covers_the_complete_user_workflow():
    content = (DOCS_DIRECTORY / 'implementation-checklist.md').read_text(
        encoding='utf8'
    )

    expected_steps = (
        'Give each dataset a stable `SUBJECT.DATASET` name',
        'Create one or more TOML files',
        'Build one catalog for the environment',
        'Use `@etlonomy.etl`',
        'Use `@etlonomy.requires`',
        'Test business rules with `TestDatasetProvider`',
        'Check declared uses, actual runtime reads, and dataset lineage',
        'Run pytest with line and branch coverage',
    )

    assert content.count('- [ ]') >= 30
    for step in expected_steps:
        assert step in content


def test_canonical_tutorial_fixture_executes_documented_core_examples():
    fixture = (
            PROJECT_DIRECTORY / 'tests' / 'end_to_end' / 'test_documentation_example.py'
    ).read_text(encoding='utf8')
    tutorials = '\n'.join(
        page.read_text(encoding='utf8')
        for page in sorted((DOCS_DIRECTORY / 'tutorials').glob('*.md'))
    )
    shared_examples = (
        'person_id,provider_id,service_date,diagnosis_code',
        "source_uri = 'data/claim_line.csv'",
        "source_uri = 'data/providers.parquet'",
        "source_uri = 'sqlite:///data/reference.sqlite'",
        'uses=(attach_region,)',
        "runtime.run('cohort.build')",
        "graph.declared_uses('cohort.build')",
    )

    for example in shared_examples:
        assert example in fixture
        assert example in tutorials
