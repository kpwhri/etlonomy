"""Tests for ETL and reusable-function registration."""

from datetime import date

import polars as pl
import pytest

from etlonomy.decorators import _source, etl, requires
from etlonomy.exceptions import RegistryError
from etlonomy.models import DatasetId, ExecutionContext, read
from etlonomy.providers import ExternalProviderBinding, TestDatasetProvider
from etlonomy.registry import EtlDefinition, Registry, RequirementDefinition
from etlonomy.runtime import Runtime


def test_etl_registers_definition_with_inputs_outputs_and_source_location(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)
    source = DatasetId('CLAIMS', 'LINES')
    output = DatasetId('COHORT', 'RESULT')

    @etl(
        name='cohort.build',
        inputs={'claims': read(source, 'person_id')},
        outputs=(output,),
    )
    def build(claims: pl.LazyFrame) -> pl.LazyFrame:
        return claims

    definition = job_registry.get_etl('cohort.build')
    assert definition.function is build
    assert definition.inputs['claims'].dataset == source
    assert definition.outputs == (output,)
    assert definition.source_file is not None
    assert definition.source_line is not None


def test_etl_rejects_duplicate_job_name(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)

    @etl(name='claims.build', inputs={})
    def first():
        pass

    with pytest.raises(RegistryError, match='already registered'):
        @etl(name='claims.build', inputs={})
        def second():
            pass


@pytest.mark.parametrize('name', [
    '',
    'build',
    'Cohort.Build',
    'cohort..build',
    'cohort.build-more',
    'cohort.build.',
])
def test_etl_rejects_non_dotted_lowercase_names(name: str):
    with pytest.raises(RegistryError, match='dotted lowercase'):
        etl(name=name, inputs={})


def test_decorators_reject_input_without_matching_parameter():
    request = read(DatasetId('CLAIMS', 'LINES'), 'person_id')
    with pytest.raises(RegistryError, match='not function parameters'):
        @etl(name='claims.invalid', inputs={'missing': request})
        def invalid():
            pass

    with pytest.raises(RegistryError, match='not function parameters'):
        @requires(missing=request)
        def helper():
            pass


def test_requires_injects_missing_input_and_preserves_explicit_override(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)
    providers = DatasetId('REFERENCE', 'PROVIDER')

    @requires(providers=read(providers, 'provider_id'))
    def attach(frame: pl.LazyFrame, providers: pl.LazyFrame) -> pl.LazyFrame:
        return frame.join(providers, on='provider_id')

    @etl(
        name='claims.attach',
        inputs={'frame': read(DatasetId('CLAIMS', 'LINES'), 'provider_id')},
    )
    def job(frame: pl.LazyFrame) -> pl.LazyFrame:
        return attach(frame)

    runtime = Runtime(
        provider=TestDatasetProvider({
            DatasetId('CLAIMS', 'LINES'): pl.DataFrame({'provider_id': [1]}),
            providers: pl.DataFrame({'provider_id': [1]}),
        }),
        context=ExecutionContext('test', date(2026, 1, 1)),
        job_registry=job_registry,
    )
    assert runtime.run('claims.attach').collect().height == 1
    assert tuple(request.dataset for request in runtime.last_dependencies) == (
        DatasetId('CLAIMS', 'LINES'),
        providers,
    )

    explicit = pl.DataFrame({'provider_id': [2]}).lazy()
    assert attach(pl.DataFrame({'provider_id': [2]}).lazy(), explicit).collect().height == 1


def test_requires_without_runtime_or_explicit_input_fails_clearly(monkeypatch):
    monkeypatch.setattr('etlonomy.decorators.registry', Registry())

    @requires(extra=read(DatasetId('REFERENCE', 'EXTRA'), 'id'))
    def helper(extra: pl.LazyFrame) -> pl.LazyFrame:
        return extra

    with pytest.raises(RegistryError, match='active Runtime'):
        helper()


def test_registry_reports_missing_entries_and_orders_jobs():
    job_registry = Registry()
    with pytest.raises(RegistryError, match='not registered'):
        job_registry.get_etl('missing.job')
    with pytest.raises(RegistryError, match='no registered requirements'):
        job_registry.get_requirement(
            test_registry_reports_missing_entries_and_orders_jobs
        )
    assert job_registry.etls == ()
    assert job_registry.requirements == ()


def test_registry_rejects_duplicate_requirement_function():
    job_registry = Registry()

    def helper():
        pass

    definition = RequirementDefinition(helper, {}, None, None)
    job_registry.register_requirement(definition)

    with pytest.raises(RegistryError, match='already has requirements'):
        job_registry.register_requirement(definition)


def test_decorators_reject_combining_etl_and_requires(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)

    @requires()
    def reusable():
        pass

    with pytest.raises(RegistryError, match='both etl and requires'):
        etl(name='area.reusable', inputs={})(reusable)

    @etl(name='area.job', inputs={})
    def job():
        pass

    with pytest.raises(RegistryError, match='both etl and requires'):
        requires()(job)


def test_source_metadata_falls_back_when_inspection_is_unavailable(monkeypatch):
    def helper():
        pass

    def unavailable(function) -> str:
        del function
        raise OSError('source unavailable')

    monkeypatch.setattr('etlonomy.decorators.inspect.getsourcefile', unavailable)

    assert _source(helper) == (None, None)


def test_etl_and_requires_register_transitive_uses(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)

    @requires(providers=read(DatasetId('REFERENCE', 'PROVIDER'), 'provider_id'))
    def attach_provider(providers: pl.LazyFrame) -> pl.LazyFrame:
        return providers

    @requires(
        uses=(attach_provider,),
        diagnoses=read(DatasetId('REFERENCE', 'DIAGNOSIS'), 'diagnosis_code'),
    )
    def enrich(
            diagnoses: pl.LazyFrame,
    ) -> pl.LazyFrame:
        return diagnoses

    @etl(name='claims.enrich', inputs={}, uses=(enrich,))
    def job():
        pass

    assert job_registry.get_etl('claims.enrich').uses == (enrich,)
    assert job_registry.get_requirement(enrich).uses == (attach_provider,)


def test_registry_rejects_invalid_duplicate_and_unregistered_uses():
    job_registry = Registry()

    def helper():
        pass

    with pytest.raises(RegistryError, match='not registered with requires'):
        job_registry.register_etl(
            EtlDefinition('area.job', helper, {}, (), None, None, (helper,))
        )

    job_registry.register_requirement(
        RequirementDefinition(helper, {}, None, None)
    )
    with pytest.raises(RegistryError, match='duplicate uses'):
        job_registry.register_etl(
            EtlDefinition('area.job', helper, {}, (), None, None, (helper, helper))
        )

    with pytest.raises(RegistryError, match='not callable'):
        job_registry.register_etl(
            EtlDefinition('area.job', helper, {}, (), None, None, (object(),))  # type: ignore[arg-type]
        )

    with pytest.raises(RegistryError, match='cannot use itself'):
        Registry().register_requirement(
            RequirementDefinition(helper, {}, None, None, (helper,))
        )


def test_registry_definitions_copy_and_protect_declared_metadata():
    request = read(DatasetId('AREA', 'SOURCE'), 'value')
    original_inputs = {'frame': request}

    def job(frame: pl.LazyFrame) -> pl.LazyFrame:
        return frame

    definition = EtlDefinition(
        'area.job', job, original_inputs, (), None, None
    )
    original_inputs.clear()

    assert definition.inputs == {'frame': request}
    with pytest.raises(TypeError):
        definition.inputs['other'] = request  # type: ignore[index]

    requirement_inputs = {'frame': request}
    requirement = RequirementDefinition(job, requirement_inputs, None, None)
    requirement_inputs.clear()

    assert requirement.inputs == {'frame': request}
    with pytest.raises(TypeError):
        requirement.inputs['other'] = request  # type: ignore[index]

    binding = ExternalProviderBinding('sv', lambda source: source)  # type: ignore[arg-type,return-value]
    original_bindings = {'files': binding}
    bound_requirement = RequirementDefinition(
        job,
        {'frame': request},
        None,
        None,
        external_provider_bindings=original_bindings,
    )
    original_bindings.clear()

    assert bound_requirement.external_provider_bindings == {'files': binding}
    with pytest.raises(TypeError):
        bound_requirement.external_provider_bindings['other'] = binding  # type: ignore[index]
