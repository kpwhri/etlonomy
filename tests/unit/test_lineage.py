"""Tests for deterministic lineage graph traversal."""

import pytest

from etlonomy.exceptions import DependencyCycleError
from etlonomy.lineage import LineageGraph
from etlonomy.models import DatasetId, ExternalDatasetId, external_read, read
from etlonomy.registry import EtlDefinition, Registry, RequirementDefinition


def dataset(name: str) -> DatasetId:
    return DatasetId('AREA', name)


def test_lineage_supports_diamond_graph_and_symmetric_traversal():
    graph = LineageGraph()
    a, b, c, d = (dataset(name) for name in ('A', 'B', 'C', 'D'))
    graph.add_dependency(b, [a])
    graph.add_dependency(c, [a])
    graph.add_dependency(d, [b, c])

    assert graph.parents(d) == (b, c)
    assert graph.children(a) == (b, c)
    assert graph.ancestors(d) == (a, b, c)
    assert graph.descendants(a) == (b, c, d)
    assert a in graph.ancestors(d)
    assert d in graph.descendants(a)


def test_lineage_handles_leaf_root_and_multiple_roots():
    graph = LineageGraph()
    first, second, result = (dataset(name) for name in ('FIRST', 'SECOND', 'RESULT'))
    graph.add_dependency(result, [second, first])

    assert graph.parents(first) == ()
    assert graph.children(result) == ()
    assert graph.ancestors(result) == (first, second)


def test_lineage_rejects_self_and_indirect_cycles_without_mutating_graph():
    graph = LineageGraph()
    a, b, c = (dataset(name) for name in ('A', 'B', 'C'))
    with pytest.raises(DependencyCycleError, match='itself'):
        graph.add_dependency(a, [a])
    graph.add_dependency(b, [a])
    graph.add_dependency(c, [b])

    with pytest.raises(DependencyCycleError, match='cycle'):
        graph.add_dependency(a, [c])

    assert graph.parents(a) == ()
    assert graph.descendants(a) == (b, c)


def test_lineage_returns_direct_etl_consumers_in_job_name_order():
    source = dataset('SOURCE')
    unrelated = dataset('OTHER')
    job_registry = Registry()
    job_registry.register_etl(
        EtlDefinition(
            'z.consume', lambda frame: frame, {'frame': read(source, 'id')}, (), None, None,
        )
    )
    job_registry.register_etl(
        EtlDefinition(
            'a.consume', lambda frame: frame, {'frame': read(source, 'name')}, (), None, None,
        )
    )
    job_registry.register_etl(
        EtlDefinition(
            'm.other', lambda frame: frame, {'frame': read(unrelated, 'id')}, (), None, None,
        )
    )

    assert LineageGraph().consumers(source, job_registry) == ('a.consume', 'z.consume')


def test_lineage_adds_job_outputs_from_runtime_read_trace():
    source = dataset('SOURCE')
    reference = dataset('REFERENCE')
    output = dataset('OUTPUT')
    graph = LineageGraph()

    graph.add_job_dependencies(
        [output], [read(source, 'id'), read(reference, 'code'), read(source, 'name')]
    )

    assert graph.parents(output) == (reference, source)


def test_runtime_trace_reports_job_uses_and_required_dataset_consumers():
    direct = dataset('DIRECT')
    required = dataset('REQUIRED')
    output = dataset('OUTPUT')
    graph = LineageGraph()

    graph.add_runtime_trace(
        'area.build', [output], [read(direct, 'id'), read(required, 'code')]
    )

    assert graph.uses('area.build') == (direct, required)
    assert graph.uses('missing.job') == ()
    assert graph.consumers(required, Registry()) == ('area.build',)
    assert graph.parents(output) == (direct, required)


def test_lineage_loads_catalog_dependencies_and_reusable_consumers():
    source = dataset('SOURCE')
    output = dataset('OUTPUT')

    class Resolved:
        dataset_version_id = 7

    class Catalog:
        def list_datasets(self):
            return (output,)

        def resolve_dataset(self, requested, as_of=None, version=None):
            assert requested == output
            return Resolved()

        def get_dependencies(self, dataset_version_id):
            assert dataset_version_id == 7
            return (source,)

    def helper(frame):
        return frame

    job_registry = Registry()
    job_registry.register_requirement(
        RequirementDefinition(helper, {'frame': read(source, 'id')}, None, None)
    )
    graph = LineageGraph()
    graph.add_catalog(Catalog())

    assert graph.parents(output) == (source,)
    assert graph.requirement_consumers(source, job_registry) == (helper.__qualname__,)


def test_lineage_expands_declared_function_uses_with_typed_edges():
    direct = dataset('DIRECT')
    diagnosis = dataset('DIAGNOSIS')
    provider = dataset('PROVIDER')
    output = dataset('OUTPUT')
    job_registry = Registry()

    def attach_provider():
        pass

    def enrich():
        pass

    job_registry.register_requirement(
        RequirementDefinition(
            attach_provider, {'providers': read(provider, 'provider_id')}, None, None,
        )
    )
    job_registry.register_requirement(
        RequirementDefinition(
            enrich, {'diagnoses': read(diagnosis, 'diagnosis_code')}, None, None, (attach_provider,),
        )
    )
    job_registry.register_etl(
        EtlDefinition(
            'area.build', lambda frame: frame, {'frame': read(direct, 'id')}, (output,), None, None, (enrich,),
        )
    )
    graph = LineageGraph()
    graph.add_registry(job_registry)

    assert graph.declared_uses('area.build') == (diagnosis, direct, provider)
    assert graph.used_functions('area.build') == (
        attach_provider.__qualname__,
        enrich.__qualname__,
    )
    assert graph.parents(output) == (diagnosis, direct, provider)
    assert graph.consumers(provider, job_registry) == ('area.build',)
    assert graph.declaration_edges('area.build', job_registry) == (
        (str(diagnosis), f'function:{enrich.__qualname__}'),
        (str(direct), 'job:area.build'),
        (str(provider), f'function:{attach_provider.__qualname__}'),
        (
            f'function:{attach_provider.__qualname__}',
            f'function:{enrich.__qualname__}',
        ),
        (f'function:{enrich.__qualname__}', 'job:area.build'),
        ('job:area.build', str(output)),
    )


def test_external_dataset_participates_in_normal_lineage_traversal():
    external = ExternalDatasetId('files', 'sv.claims')
    intermediate = dataset('INTERMEDIATE')
    output = dataset('OUTPUT')
    graph = LineageGraph()

    graph.add_job_dependencies([intermediate], [external_read(external, 'person_id')])
    graph.add_dependency(output, [intermediate])

    assert graph.parents(intermediate) == (external,)
    assert graph.children(external) == (intermediate,)
    assert graph.ancestors(output) == (intermediate, external)
    assert graph.descendants(external) == (intermediate, output)


def test_lineage_rejects_cycle_between_catalog_and_external_datasets():
    external = ExternalDatasetId('files', 'sv.claims')
    output = dataset('OUTPUT')
    graph = LineageGraph()
    graph.add_dependency(output, [external])

    with pytest.raises(DependencyCycleError, match='cycle'):
        graph.add_dependency(external, [output])

    assert graph.parents(external) == ()
    assert graph.children(external) == (output,)


def test_normal_uses_queries_include_direct_and_required_external_datasets():
    direct = ExternalDatasetId('files', 'sv.claims')
    required = ExternalDatasetId('warehouse', 'reference.providers')
    output = dataset('OUTPUT')
    job_registry = Registry()

    def attach_provider():
        pass

    job_registry.register_requirement(
        RequirementDefinition(
            attach_provider, {'providers': external_read(required, 'provider_id')}, None, None,
        )
    )
    job_registry.register_etl(
        EtlDefinition(
            'area.external', lambda claims: claims, {'claims': external_read(direct, 'person_id')}, (output,),
            None, None, (attach_provider,),
        )
    )
    graph = LineageGraph()
    graph.add_registry(job_registry)

    assert graph.declared_uses('area.external') == (direct, required)
    assert graph.parents(output) == (direct, required)
    assert graph.consumers(direct, job_registry) == ('area.external',)
    assert graph.consumers(required, job_registry) == ('area.external',)
    assert graph.requirement_consumers(required, job_registry) == (attach_provider.__qualname__,)
    assert graph.external_consumers(required, job_registry) == graph.consumers(required, job_registry)
    assert graph.external_requirement_consumers(required, job_registry) == graph.requirement_consumers(required,
                                                                                                       job_registry)


def test_runtime_uses_and_consumers_include_observed_external_dataset():
    external = ExternalDatasetId('files', 'sv.claims')
    internal = dataset('MEMBERS')
    output = dataset('OUTPUT')
    graph = LineageGraph()

    graph.add_runtime_trace(
        'area.observed',
        [output],
        [read(internal, 'person_id'), external_read(external, 'person_id')],
    )

    assert graph.uses('area.observed') == (internal, external)
    assert graph.external_uses('area.observed') == (external,)
    assert graph.consumers(external, Registry()) == ('area.observed',)
    assert graph.parents(output) == (internal, external)
