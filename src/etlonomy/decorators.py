"""Decorators for declaring ETL jobs and reusable dataset requirements."""

import inspect
import re
from functools import wraps
from pathlib import Path
from typing import Callable, cast, Mapping, ParamSpec, TypeVar

from etlonomy.exceptions import RegistryError
from etlonomy.models import DatasetId, DependencyRead, ExternalDatasetId
from etlonomy.providers import ExternalProviderBinding
from etlonomy.registry import EtlDefinition, RequirementDefinition, registry

_ETL_NAME = re.compile(r'^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$')

P = ParamSpec('P')
R = TypeVar('R')


def _source(function: Callable) -> tuple[Path | None, int | None]:
    try:
        path = inspect.getsourcefile(function)
        _, line = inspect.getsourcelines(function)
    except (OSError, TypeError):
        return None, None
    return Path(path) if path else None, line


def _validate_inputs(function: Callable, inputs: Mapping[str, DependencyRead]):
    parameters = inspect.signature(function).parameters
    missing = sorted(set(inputs) - set(parameters))
    if missing:
        names = ', '.join(missing)
        raise RegistryError(
            f'declared inputs are not function parameters for '
            f'{function.__qualname__}: {names}'
        )


def etl(
        *,
        name: str,
        inputs: Mapping[str, DependencyRead],
        outputs: tuple[DatasetId, ...] = (),
        uses: tuple[Callable, ...] = (),
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Declare and register a top-level ETL job."""
    if not _ETL_NAME.fullmatch(name):
        raise RegistryError('ETL job names must be dotted lowercase names')

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        if getattr(function, '__etlonomy_requirement__', False):
            raise RegistryError('a function cannot use both etl and requires')
        _validate_inputs(function, inputs)
        source_file, source_line = _source(function)
        definition = EtlDefinition(
            name=name,
            function=cast(Callable, function),
            inputs=dict(inputs),
            outputs=tuple(outputs),
            source_file=source_file,
            source_line=source_line,
            uses=tuple(uses),
        )
        registry.register_etl(definition)
        object.__setattr__(function, '__etlonomy_etl__', True)
        return function

    return decorate


def requires(
        *,
        uses: tuple[Callable, ...] = (),
        external_provider_bindings: Mapping[str, ExternalProviderBinding] | None = None,
        **inputs: DependencyRead,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Declare datasets injected into a reusable function.

    Explicit non-None inputs take precedence over call-bound and runtime providers.
    An external provider binding can resolve its system without an active runtime.
    """
    bindings = dict(external_provider_bindings or {})
    for system, binding in bindings.items():
        if not isinstance(system, str):
            raise RegistryError('external provider binding systems must be strings')
        try:
            ExternalDatasetId(system, 'binding-validation')
        except ValueError as error:
            raise RegistryError(
                f'invalid external provider binding system: {system!r}'
            ) from error
        if not isinstance(binding, ExternalProviderBinding):
            raise RegistryError(
                'external provider bindings must be ExternalProviderBinding values'
            )

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        if getattr(function, '__etlonomy_etl__', False):
            raise RegistryError('a function cannot use both etl and requires')
        _validate_inputs(function, inputs)
        signature = inspect.signature(function)
        parameters = signature.parameters
        missing_arguments = sorted({
            binding.argument
            for binding in bindings.values()
            if binding.argument not in parameters
        })
        if missing_arguments:
            names = ', '.join(missing_arguments)
            raise RegistryError(
                f'external provider binding arguments are not function parameters '
                f'for {function.__qualname__}: {names}'
            )
        conflicting_arguments = sorted(
            {binding.argument for binding in bindings.values()} & set(inputs)
        )
        if conflicting_arguments:
            names = ', '.join(conflicting_arguments)
            raise RegistryError(
                f'external provider binding arguments cannot also be declared '
                f'inputs for {function.__qualname__}: {names}'
            )

        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            bound = signature.bind_partial(*args, **kwargs)
            unresolved = {
                name: request
                for name, request in inputs.items()
                if name not in bound.arguments or bound.arguments[name] is None
            }
            providers = {
                system: binding.create(bound.arguments[binding.argument])
                for system, binding in bindings.items()
                if (
                        binding.argument in bound.arguments
                        and bound.arguments[binding.argument] is not None
                )
            }
            from etlonomy.runtime import _external_provider_scope, _resolve_requirement_inputs

            with _external_provider_scope(providers):
                if unresolved:
                    bound.arguments.update(_resolve_requirement_inputs(unresolved))
                return function(*bound.args, **bound.kwargs)

        object.__setattr__(wrapped, '__etlonomy_requirement__', True)
        source_file, source_line = _source(function)
        registry.register_requirement(
            RequirementDefinition(
                function=cast(Callable, wrapped),
                inputs=dict(inputs),
                source_file=source_file,
                source_line=source_line,
                uses=tuple(uses),
                external_provider_bindings=bindings,
            )
        )
        return wrapped

    return decorate
