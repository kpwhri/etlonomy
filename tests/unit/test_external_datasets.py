"""Tests for external dataset identities, reads, and runtime routing."""

from contextvars import Context
from dataclasses import FrozenInstanceError
from datetime import date

import polars as pl
import pytest

import etlonomy
from etlonomy.exceptions import (
    DatasetProviderError,
    ExternalDatasetProviderNotConfiguredError,
    RegistryError,
)
from etlonomy.models import (
    ExecutionContext,
    ExternalDatasetId,
    ExternalRead,
    external_read,
)
from etlonomy.providers import ExternalProviderBinding, TestDatasetProvider
from etlonomy.registry import EtlDefinition, Registry
from etlonomy.runtime import Runtime, get_active_runtime


class RecordingExternalProvider:
    def __init__(self, value: object):
        self.value = value
        self.calls: list[tuple[ExternalRead, ExecutionContext]] = []

    def read(self, request: ExternalRead, context: ExecutionContext) -> object:
        self.calls.append((request, context))
        return self.value


class SourceViewProvider:
    def __init__(self, source_view: dict[str, object]):
        self.source_view = source_view
        self.calls: list[tuple[ExternalRead, ExecutionContext]] = []

    def read(self, request: ExternalRead, context: ExecutionContext) -> object:
        self.calls.append((request, context))
        return self.source_view[request.dataset.name]


def test_external_dataset_id_has_stable_namespaced_identity():
    dataset = ExternalDatasetId('vdwcore', 'sv.vdw_claims')

    assert dataset.canonical_name == 'vdwcore:sv.vdw_claims'
    assert str(dataset) == 'vdwcore:sv.vdw_claims'
    assert ExternalDatasetId.parse(str(dataset)) == dataset
    assert hash(ExternalDatasetId.parse(str(dataset))) == hash(dataset)


@pytest.mark.parametrize('system', ['', 'VDWCORE', 'vdw core', ' vdwcore'])
def test_external_dataset_id_rejects_invalid_system(system: str):
    with pytest.raises(ValueError, match='external dataset system'):
        ExternalDatasetId(system, 'sv.claims')


@pytest.mark.parametrize(
    'name',
    ['', ' sv.claims', 'sv.claims ', 'sv.\nclaims', 'sv.\x00claims', 'sv.\x7fclaims'],
)
def test_external_dataset_id_rejects_invalid_name(name: str):
    with pytest.raises(ValueError, match='external dataset name'):
        ExternalDatasetId('files', name)


def test_external_dataset_id_parse_requires_namespace_separator():
    with pytest.raises(ValueError, match='canonical external dataset'):
        ExternalDatasetId.parse('sv.claims')


def test_external_dataset_values_are_immutable():
    dataset = ExternalDatasetId('files', 'sv.claims')
    request = external_read(dataset, 'person_id')

    with pytest.raises(FrozenInstanceError):
        dataset.name = 'sv.other'  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        request.columns = ('other',)  # type: ignore[misc]


def test_external_read_records_requested_columns():
    dataset = ExternalDatasetId('files', 'sv.claims')

    request = external_read(dataset, 'person_id', 'service_date')

    assert request == ExternalRead(dataset, ('person_id', 'service_date'))


@pytest.mark.parametrize(
    ('columns', 'message'),
    [
        ((), 'at least one'),
        (('person_id', ''), 'must not be empty'),
        (('person_id', 'person_id'), 'must be unique'),
    ],
)
def test_external_read_rejects_invalid_columns(
        columns: tuple[str, ...], message: str
):
    dataset = ExternalDatasetId('files', 'sv.claims')

    with pytest.raises(ValueError, match=message):
        ExternalRead(dataset, columns)


def test_runtime_routes_external_read_and_records_dependency():
    request = external_read(
        ExternalDatasetId('files', 'sv.claims'),
        'person_id',
    )
    supplied = pl.DataFrame({'person_id': [1], 'extra': ['kept']})
    job_registry = Registry()
    job_registry.register_etl(
        EtlDefinition(
            'external.load',
            lambda claims: claims,
            {'claims': request},
            (),
            None,
            None,
        )
    )
    context = ExecutionContext('test', date(2026, 1, 1))
    external_provider = RecordingExternalProvider(supplied)
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        external_providers={'files': external_provider},
        context=context,
        job_registry=job_registry,
    )

    assert runtime.run('external.load') is supplied
    assert external_provider.calls == [(request, context)]
    assert runtime.last_dependencies == (request,)


def test_runtime_routes_multiple_systems_and_resources_to_matching_providers():
    first = external_read(ExternalDatasetId('files', 'sv.claims'), 'person_id')
    second = external_read(ExternalDatasetId('files', 'sv.providers'), 'provider_id')
    third = external_read(ExternalDatasetId('warehouse', 'reference.regions'), 'region')
    files_provider = RecordingExternalProvider('file value')
    warehouse_provider = RecordingExternalProvider('warehouse value')
    job_registry = Registry()
    job_registry.register_etl(
        EtlDefinition(
            'external.multiple',
            lambda claims, providers, regions: (claims, providers, regions),
            {'claims': first, 'providers': second, 'regions': third},
            (),
            None,
            None,
        )
    )
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        external_providers={
            'files': files_provider,
            'warehouse': warehouse_provider,
        },
        context=ExecutionContext('test'),
        job_registry=job_registry,
    )

    assert runtime.run('external.multiple') == (
        'file value',
        'file value',
        'warehouse value',
    )
    assert [request for request, _ in files_provider.calls] == [first, second]
    assert [request for request, _ in warehouse_provider.calls] == [third]
    assert runtime.last_dependencies == (first, second, third)


def test_runtime_resolves_two_column_requests_for_same_external_dataset():
    dataset = ExternalDatasetId('files', 'sv.claims')
    identifiers = external_read(dataset, 'person_id')
    diagnoses = external_read(dataset, 'diagnosis_code')
    provider = RecordingExternalProvider(object())
    job_registry = Registry()
    job_registry.register_etl(
        EtlDefinition(
            'external.same_dataset',
            lambda ids, codes: (ids, codes),
            {'ids': identifiers, 'codes': diagnoses},
            (),
            None,
            None,
        )
    )
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        external_providers={'files': provider},
        context=ExecutionContext(),
        job_registry=job_registry,
    )

    runtime.run('external.same_dataset')

    assert [request for request, _ in provider.calls] == [identifiers, diagnoses]
    assert runtime.last_dependencies == (identifiers, diagnoses)


def test_runtime_copies_external_provider_mapping_at_construction():
    request = external_read(ExternalDatasetId('files', 'sv.claims'), 'person_id')
    provider = RecordingExternalProvider('claims')
    providers = {'files': provider}
    job_registry = Registry()
    job_registry.register_etl(
        EtlDefinition(
            'external.mapping',
            lambda claims: claims,
            {'claims': request},
            (),
            None,
            None,
        )
    )
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        external_providers=providers,
        context=ExecutionContext(),
        job_registry=job_registry,
    )

    providers.clear()

    assert runtime.run('external.mapping') == 'claims'
    with pytest.raises(TypeError):
        runtime.external_providers['other'] = provider  # type: ignore[index]


def test_explicit_external_etl_argument_skips_provider_and_keeps_columns():
    request = external_read(
        ExternalDatasetId('files', 'sv.claims'),
        'person_id',
    )
    job_registry = Registry()
    job_registry.register_etl(
        EtlDefinition(
            'external.override',
            lambda claims: claims,
            {'claims': request},
            (),
            None,
            None,
        )
    )
    external_provider = RecordingExternalProvider(object())
    supplied = pl.DataFrame({
        'person_id': [1],
        'extra_test_column': ['preserved'],
    })
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        external_providers={'files': external_provider},
        context=ExecutionContext(),
        job_registry=job_registry,
    )

    assert runtime.run('external.override', claims=supplied) is supplied
    assert supplied.columns == ['person_id', 'extra_test_column']
    assert external_provider.calls == []
    assert runtime.last_dependencies == ()


def test_runtime_reports_missing_external_provider_without_recording_read():
    request = external_read(ExternalDatasetId('missing', 'sv.claims'), 'person_id')
    job_registry = Registry()
    job_registry.register_etl(
        EtlDefinition(
            'external.missing',
            lambda claims: claims,
            {'claims': request},
            (),
            None,
            None,
        )
    )
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        context=ExecutionContext(),
        job_registry=job_registry,
    )

    with pytest.raises(
            ExternalDatasetProviderNotConfiguredError,
            match="system 'missing'",
    ):
        runtime.run('external.missing')

    assert runtime.last_dependencies == ()


def test_explicit_external_argument_is_passed_unchanged(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)
    request = external_read(ExternalDatasetId('files', 'sv.claims'), 'person_id')

    @etlonomy.requires(claims=request)
    def use_claims(claims: pl.DataFrame) -> pl.DataFrame:
        return claims

    supplied = pl.DataFrame({
        'person_id': [1],
        'extra_test_column': ['preserved'],
    })

    result = use_claims(claims=supplied)

    assert result is supplied
    assert result.columns == ['person_id', 'extra_test_column']


def test_positional_external_argument_is_passed_unchanged(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)
    request = external_read(ExternalDatasetId('files', 'sv.claims'), 'person_id')

    @etlonomy.requires(claims=request)
    def use_claims(claims: pl.DataFrame) -> pl.DataFrame:
        return claims

    supplied = pl.DataFrame({
        'person_id': [1],
        'extra_test_column': ['preserved'],
    })

    result = use_claims(supplied)

    assert result is supplied
    assert result.columns == ['person_id', 'extra_test_column']


def test_external_provider_failure_preserves_trace_and_clears_runtime():
    successful = external_read(ExternalDatasetId('files', 'sv.good'), 'person_id')
    failing = external_read(ExternalDatasetId('files', 'sv.bad'), 'person_id')

    class ConditionalProvider:
        def read(self, request: ExternalRead, context: ExecutionContext) -> object:
            del context
            if request == failing:
                raise ValueError('external read failed')
            return object()

    job_registry = Registry()
    job_registry.register_etl(
        EtlDefinition(
            'external.success', lambda frame: frame, {'frame': successful}, (), None, None
        )
    )
    job_registry.register_etl(
        EtlDefinition(
            'external.failure', lambda frame: frame, {'frame': failing}, (), None, None
        )
    )
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        external_providers={'files': ConditionalProvider()},
        context=ExecutionContext(),
        job_registry=job_registry,
    )

    runtime.run('external.success')
    with pytest.raises(ValueError, match='external read failed'):
        runtime.run('external.failure')

    assert runtime.last_dependencies == (successful,)
    with pytest.raises(RegistryError, match='active Runtime'):
        get_active_runtime()


def test_external_traces_are_isolated_between_execution_contexts():
    left = external_read(ExternalDatasetId('files', 'sv.left'), 'value')
    right = external_read(ExternalDatasetId('files', 'sv.right'), 'value')
    job_registry = Registry()
    job_registry.register_etl(
        EtlDefinition('external.left', lambda frame: frame, {'frame': left}, (), None, None)
    )
    job_registry.register_etl(
        EtlDefinition(
            'external.right', lambda frame: frame, {'frame': right}, (), None, None
        )
    )
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        external_providers={'files': RecordingExternalProvider(object())},
        context=ExecutionContext(),
        job_registry=job_registry,
    )
    left_context = Context()
    right_context = Context()

    left_context.run(runtime.run, 'external.left')
    right_context.run(runtime.run, 'external.right')

    assert left_context.run(lambda: runtime.last_dependencies) == (left,)
    assert right_context.run(lambda: runtime.last_dependencies) == (right,)
    assert runtime.last_dependencies == ()


def test_nested_requires_resolves_external_dataset_and_records_trace(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)
    request = external_read(ExternalDatasetId('files', 'sv.claims'), 'person_id')

    @etlonomy.requires(claims=request)
    def attach_claims(seed: str, claims: object) -> tuple[str, object]:
        return seed, claims

    @etlonomy.requires(uses=(attach_claims,))
    def enrich(seed: str) -> tuple[str, object]:
        return attach_claims(seed)

    @etlonomy.etl(
        name='external.nested',
        inputs={},
        uses=(enrich,),
    )
    def build() -> tuple[str, object]:
        return enrich('seed')

    supplied = object()
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        external_providers={'files': RecordingExternalProvider(supplied)},
        context=ExecutionContext(),
        job_registry=job_registry,
    )

    assert runtime.run('external.nested') == ('seed', supplied)
    assert runtime.last_dependencies == (request,)


def test_requires_builds_external_provider_from_function_argument(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)
    claims = external_read(ExternalDatasetId('vdwcore', 'sv.claims'), 'person_id')
    other = external_read(ExternalDatasetId('vdwcore', 'sv.other'), 'code')
    created: list[SourceViewProvider] = []

    def provider_factory(source_view: dict[str, object]) -> SourceViewProvider:
        provider = SourceViewProvider(source_view)
        created.append(provider)
        return provider

    @etlonomy.requires(
        external_provider_bindings={
            'vdwcore': ExternalProviderBinding('sv', provider_factory),
        },
        claims=claims,
        other=other,
    )
    def combine(
            *,
            claims: object,
            other: object,
            sv: dict[str, object] | None = None,
    ) -> tuple[object, object]:
        del sv
        return claims, other

    source_view = {'sv.claims': 'claims', 'sv.other': 'other'}

    assert combine(sv=source_view) == ('claims', 'other')
    assert len(created) == 1
    assert created[0].calls == [
        (claims, ExecutionContext()),
        (other, ExecutionContext()),
    ]
    definition = job_registry.get_requirement(combine)
    assert definition.external_provider_bindings['vdwcore'].argument == 'sv'


def test_call_bound_provider_is_inherited_by_nested_requires(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)
    request = external_read(ExternalDatasetId('vdwcore', 'sv.claims'), 'person_id')

    @etlonomy.requires(claims=request)
    def inner(*, claims: object) -> object:
        return claims

    @etlonomy.requires(
        uses=(inner,),
        external_provider_bindings={
            'vdwcore': ExternalProviderBinding('sv', SourceViewProvider),
        },
    )
    def outer(*, sv: dict[str, object] | None = None) -> object:
        del sv
        return inner()

    assert outer(sv={'sv.claims': 'nested claims'}) == 'nested claims'


def test_call_bound_provider_overrides_runtime_and_records_dependency(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)
    request = external_read(ExternalDatasetId('vdwcore', 'sv.claims'), 'person_id')

    created: list[SourceViewProvider] = []

    def provider_factory(source_view: dict[str, object]) -> SourceViewProvider:
        provider = SourceViewProvider(source_view)
        created.append(provider)
        return provider

    @etlonomy.requires(
        external_provider_bindings={
            'vdwcore': ExternalProviderBinding('sv', provider_factory),
        },
        claims=request,
    )
    def helper(
            *, claims: object, sv: dict[str, object] | None = None
    ) -> object:
        del sv
        return claims

    @etlonomy.etl(name='external.bound', inputs={}, uses=(helper,))
    def job() -> object:
        return helper(sv={'sv.claims': 'call-bound claims'})

    runtime_provider = RecordingExternalProvider('runtime claims')
    context = ExecutionContext('test', date(2026, 1, 1))
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        external_providers={'vdwcore': runtime_provider},
        context=context,
        job_registry=job_registry,
    )

    assert runtime.run('external.bound') == 'call-bound claims'
    assert runtime_provider.calls == []
    assert created[0].calls == [(request, context)]
    assert runtime.last_dependencies == (request,)


def test_binding_omitted_falls_back_to_active_runtime(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)
    request = external_read(ExternalDatasetId('vdwcore', 'sv.claims'), 'person_id')

    @etlonomy.requires(
        external_provider_bindings={
            'vdwcore': ExternalProviderBinding('sv', SourceViewProvider),
        },
        claims=request,
    )
    def helper(
            *, claims: object, sv: dict[str, object] | None = None
    ) -> object:
        del sv
        return claims

    @etlonomy.etl(name='external.fallback', inputs={}, uses=(helper,))
    def job() -> object:
        return helper()

    runtime_provider = RecordingExternalProvider('runtime claims')
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        external_providers={'vdwcore': runtime_provider},
        context=ExecutionContext('test'),
        job_registry=job_registry,
    )

    assert runtime.run('external.fallback') == 'runtime claims'
    assert [call[0] for call in runtime_provider.calls] == [request]


def test_explicit_input_still_wins_when_provider_argument_is_supplied(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)
    request = external_read(ExternalDatasetId('vdwcore', 'sv.claims'), 'person_id')
    created: list[SourceViewProvider] = []

    def provider_factory(source_view: dict[str, object]) -> SourceViewProvider:
        provider = SourceViewProvider(source_view)
        created.append(provider)
        return provider

    @etlonomy.requires(
        external_provider_bindings={
            'vdwcore': ExternalProviderBinding('sv', provider_factory),
        },
        claims=request,
    )
    def helper(
            *, claims: object, sv: dict[str, object] | None = None
    ) -> object:
        del sv
        return claims

    explicit = object()

    assert helper(sv={'sv.claims': object()}, claims=explicit) is explicit
    assert len(created) == 1
    assert created[0].calls == []


def test_call_bound_provider_scope_is_cleared_after_failure(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)
    request = external_read(ExternalDatasetId('vdwcore', 'sv.claims'), 'person_id')

    @etlonomy.requires(claims=request)
    def inner(*, claims: object) -> object:
        return claims

    @etlonomy.requires(
        uses=(inner,),
        external_provider_bindings={
            'vdwcore': ExternalProviderBinding('sv', SourceViewProvider),
        },
    )
    def fail(*, sv: dict[str, object] | None = None) -> None:
        del sv
        inner()
        raise ValueError('function failed')

    with pytest.raises(ValueError, match='function failed'):
        fail(sv={'sv.claims': 'claims'})
    with pytest.raises(RegistryError, match='bound external provider'):
        inner()


@pytest.mark.parametrize(('binding', 'message'), [
    ({1: ExternalProviderBinding('sv', SourceViewProvider)}, 'must be strings'),
    (
            {'INVALID': ExternalProviderBinding('sv', SourceViewProvider)},
            'invalid external provider binding system',
    ),
    ({'vdwcore': object()}, 'must be ExternalProviderBinding'),
])
def test_requires_rejects_invalid_external_provider_bindings(
        monkeypatch, binding: object, message: str
):
    monkeypatch.setattr('etlonomy.decorators.registry', Registry())

    with pytest.raises(RegistryError, match=message):
        etlonomy.requires(
            external_provider_bindings=binding,  # type: ignore[arg-type]
        )


def test_requires_validates_binding_argument_against_function_signature(monkeypatch):
    monkeypatch.setattr('etlonomy.decorators.registry', Registry())
    binding = {
        'vdwcore': ExternalProviderBinding('sv', SourceViewProvider),
    }

    with pytest.raises(RegistryError, match='not function parameters'):
        @etlonomy.requires(external_provider_bindings=binding)
        def missing_argument():
            pass

    request = external_read(ExternalDatasetId('vdwcore', 'sv.claims'), 'person_id')
    with pytest.raises(RegistryError, match='cannot also be declared inputs'):
        @etlonomy.requires(external_provider_bindings=binding, sv=request)
        def conflicting_argument(sv: object):
            del sv


def test_external_provider_binding_validates_configuration_and_factory_result():
    for argument in ('not an argument', 'class', 1):
        with pytest.raises(ValueError, match='Python identifier'):
            ExternalProviderBinding(  # type: ignore[arg-type]
                argument, SourceViewProvider
            )
    with pytest.raises(TypeError, match='must be callable'):
        ExternalProviderBinding('sv', object())  # type: ignore[arg-type]

    binding = ExternalProviderBinding('sv', lambda source_view: object())
    with pytest.raises(DatasetProviderError, match='callable read method'):
        binding.create(object())


def test_package_exports_external_provider_binding():
    assert etlonomy.ExternalProviderBinding is ExternalProviderBinding


def test_package_exports_external_dataset_api():
    assert etlonomy.ExternalDatasetId is ExternalDatasetId
    assert etlonomy.ExternalRead is ExternalRead
    assert etlonomy.external_read is external_read
    assert hasattr(etlonomy, 'ExternalDatasetProvider')
