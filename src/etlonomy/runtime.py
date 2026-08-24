"""Execution runtime for registered ETL jobs and reusable requirements."""

from collections.abc import Mapping
from contextvars import ContextVar, Token

import polars as pl

from etlonomy.exceptions import RegistryError
from etlonomy.models import ExecutionContext, Read
from etlonomy.providers import DatasetProvider
from etlonomy.registry import Registry, registry

_ACTIVE_RUNTIME: ContextVar['Runtime | None'] = ContextVar(
    'etlonomy_active_runtime', default=None
)
_ACTIVE_DEPENDENCIES: ContextVar[list[Read] | None] = ContextVar(
    'etlonomy_active_dependencies', default=None
)


def get_active_runtime() -> 'Runtime':
    """Return the runtime currently executing an ETL.

    Raises:
        RegistryError: If dependency injection is requested outside a run.

    """
    runtime = _ACTIVE_RUNTIME.get()
    if runtime is None:
        raise RegistryError(
            'a requires-decorated function needs an active Runtime or explicit inputs'
        )
    return runtime


class Runtime:
    """Execute registered ETL jobs with a dataset provider and fixed context."""

    def __init__(
            self,
            *,
            provider: DatasetProvider,
            context: ExecutionContext,
            job_registry: Registry = registry,
    ) -> None:
        """Create a runtime bound to a provider, context, and registry."""
        self.provider = provider
        self.context = context
        self.registry = job_registry
        self._last_dependencies: ContextVar[tuple[Read, ...]] = ContextVar(
            'etlonomy_last_dependencies', default=()
        )

    @property
    def last_dependencies(self) -> tuple[Read, ...]:
        """Return reads resolved by the last successful job in this context."""
        return self._last_dependencies.get()

    def resolve_inputs(self, inputs: Mapping[str, Read]) -> dict[str, pl.LazyFrame]:
        """Resolve named read requests through this runtime's provider."""
        resolved: dict[str, pl.LazyFrame] = {}
        for name, request in inputs.items():
            resolved[name] = self.provider.read(request, self.context)
            active_dependencies = _ACTIVE_DEPENDENCIES.get()
            if active_dependencies is not None:
                active_dependencies.append(request)
        return resolved

    def run(self, name: str, **arguments: object) -> object:
        """Execute a registered ETL, injecting any undeclared call arguments.

        Explicit arguments take precedence over declared dataset inputs.
        """
        definition = self.registry.get_etl(name)
        dependencies: list[Read] = []
        previous_dependencies = _ACTIVE_DEPENDENCIES.get()
        dependency_token: Token[list[Read] | None] = _ACTIVE_DEPENDENCIES.set(
            dependencies
        )
        runtime_token: Token[Runtime | None] = _ACTIVE_RUNTIME.set(self)
        successful = False
        try:
            injected: dict[str, object] = dict(
                self.resolve_inputs(
                    {
                        key: request
                        for key, request in definition.inputs.items()
                        if key not in arguments
                    }
                )
            )
            injected.update(arguments)
            result = definition.function(**injected)
            successful = True
            return result
        finally:
            if successful:
                self._last_dependencies.set(tuple(dependencies))
                if previous_dependencies is not None:
                    previous_dependencies.extend(dependencies)
            _ACTIVE_DEPENDENCIES.reset(dependency_token)
            _ACTIVE_RUNTIME.reset(runtime_token)
