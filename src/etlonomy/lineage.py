"""Deterministic dataset lineage traversal and ETL-consumer queries."""

from collections.abc import Callable, Iterable
from datetime import date
from typing import Protocol, cast

from etlonomy.exceptions import DependencyCycleError
from etlonomy.models import (
    DatasetId,
    DependencyRead,
    ExternalDatasetId,
    ExternalRead,
    Read,
)
from etlonomy.registry import Registry, registry

LineageDatasetId = DatasetId | ExternalDatasetId


class ResolvedLineageDataset(Protocol):
    """Expose the stable catalog identifier used for dependency lookup."""

    dataset_version_id: int


class CatalogLineageSource(Protocol):
    """Expose the catalog queries needed to construct dataset lineage."""

    def list_datasets(self) -> tuple[DatasetId, ...]:
        """Return the logical datasets available in the catalog."""
        ...

    def resolve_dataset(
            self,
            dataset: DatasetId,
            as_of: date | None = None,
            version: int | None = None,
    ) -> object:
        """Resolve the dataset version used for lineage."""
        ...

    def get_dependencies(self, dataset_version_id: int) -> tuple[DatasetId, ...]:
        """Return the resolved version's declared upstream datasets."""
        ...


class LineageGraph:
    """Represent directed dependencies from upstream to downstream datasets."""

    def __init__(self) -> None:
        """Create an empty directed lineage graph."""
        self._parents: dict[LineageDatasetId, set[LineageDatasetId]] = {}
        self._children: dict[LineageDatasetId, set[LineageDatasetId]] = {}
        self._job_reads: dict[str, set[DatasetId]] = {}
        self._job_declared_reads: dict[str, set[DatasetId]] = {}
        self._job_external_reads: dict[str, set[ExternalDatasetId]] = {}
        self._job_declared_external_reads: dict[
            str, set[ExternalDatasetId]
        ] = {}
        self._job_functions: dict[str, tuple[Callable[..., object], ...]] = {}
        self._function_functions: dict[
            Callable[..., object], tuple[Callable[..., object], ...]
        ] = {}
        self._function_reads: dict[Callable[..., object], set[DatasetId]] = {}
        self._function_external_reads: dict[
            Callable[..., object], set[ExternalDatasetId]
        ] = {}

    def add_dependency(
            self,
            dataset: LineageDatasetId,
            upstream: Iterable[LineageDatasetId],
    ) -> None:
        """Declare direct upstream datasets and reject dependency cycles."""
        parents = set(upstream)
        if dataset in parents:
            raise DependencyCycleError(f'dataset {dataset} depends on itself')
        old_parents = set(self._parents.get(dataset, set()))
        self._parents.setdefault(dataset, set()).update(parents)
        for parent in parents:
            self._children.setdefault(parent, set()).add(dataset)
        try:
            self._assert_acyclic()
        except DependencyCycleError:
            self._parents[dataset] = old_parents
            for parent in parents - old_parents:
                self._children[parent].discard(dataset)
            raise

    def parents(
            self, dataset: LineageDatasetId
    ) -> tuple[LineageDatasetId, ...]:
        """Return direct upstream datasets in canonical-name order."""
        return self._ordered(self._parents.get(dataset, set()))

    def children(
            self, dataset: LineageDatasetId
    ) -> tuple[LineageDatasetId, ...]:
        """Return direct downstream datasets in canonical-name order."""
        return self._ordered(self._children.get(dataset, set()))

    def ancestors(
            self, dataset: LineageDatasetId
    ) -> tuple[LineageDatasetId, ...]:
        """Return every transitive upstream dataset deterministically."""
        return self._walk(dataset, self._parents)

    def descendants(
            self, dataset: LineageDatasetId
    ) -> tuple[LineageDatasetId, ...]:
        """Return every transitive downstream dataset deterministically."""
        return self._walk(dataset, self._children)

    def consumers(
            self,
            dataset: LineageDatasetId,
            job_registry: Registry = registry,
    ) -> tuple[str, ...]:
        """Return ETL jobs that directly or transitively use a dataset."""
        declared = {
            definition.name
            for definition in job_registry.etls
            if any(read.dataset == dataset for read in definition.inputs.values())
        }
        indirect = {
            job_name
            for job_name, datasets in self._declared_reads_by_job().items()
            if dataset in datasets
        }
        traced = {
            job_name
            for job_name, datasets in self._reads_by_job().items()
            if dataset in datasets
        }
        return tuple(sorted(declared | indirect | traced))

    def external_consumers(
            self,
            dataset: ExternalDatasetId,
            job_registry: Registry = registry,
    ) -> tuple[str, ...]:
        """Return ETL jobs that use an externally loaded dataset."""
        return self.consumers(dataset, job_registry)

    def uses(self, job_name: str) -> tuple[LineageDatasetId, ...]:
        """Return datasets observed while executing a named ETL job."""
        return self._ordered(self._reads_by_job().get(job_name, set()))

    def declared_uses(self, job_name: str) -> tuple[LineageDatasetId, ...]:
        """Return direct and transitive datasets declared for an ETL job."""
        return self._ordered(self._declared_reads_by_job().get(job_name, set()))

    def external_uses(self, job_name: str) -> tuple[ExternalDatasetId, ...]:
        """Return external datasets observed while executing an ETL job."""
        return self._ordered_external(self._job_external_reads.get(job_name, set()))

    def declared_external_uses(
            self, job_name: str
    ) -> tuple[ExternalDatasetId, ...]:
        """Return direct and transitive external datasets declared by a job."""
        return self._ordered_external(
            self._job_declared_external_reads.get(job_name, set())
        )

    def used_functions(self, job_name: str) -> tuple[str, ...]:
        """Return reusable functions transitively declared by an ETL job."""
        found: set[Callable[..., object]] = set()
        pending = list(self._job_functions.get(job_name, ()))
        while pending:
            function = pending.pop()
            if function in found:
                continue
            found.add(function)
            pending.extend(self._function_functions.get(function, ()))
        return tuple(sorted(function.__qualname__ for function in found))

    def add_runtime_trace(
            self,
            job_name: str,
            outputs: Iterable[DatasetId],
            reads: Iterable[DependencyRead],
    ) -> None:
        """Record a completed ETL's dataset uses and output lineage."""
        requests = tuple(reads)
        self._job_reads.setdefault(job_name, set()).update(
            request.dataset for request in requests if isinstance(request, Read)
        )
        self._job_external_reads.setdefault(job_name, set()).update(
            request.dataset
            for request in requests
            if isinstance(request, ExternalRead)
        )
        self.add_job_dependencies(outputs, requests)

    def add_job_dependencies(
            self, outputs: Iterable[DatasetId], reads: Iterable[DependencyRead]
    ) -> None:
        """Add lineage observed or declared for one ETL job execution."""
        upstream = {request.dataset for request in reads}
        for output in outputs:
            self.add_dependency(output, upstream)

    def add_registry(self, job_registry: Registry = registry) -> None:
        """Add every registered ETL's declared dataset edges and direct uses."""
        for requirement in job_registry.requirements:
            self._function_functions[requirement.function] = requirement.uses
            self._function_reads[requirement.function] = {
                request.dataset
                for request in requirement.inputs.values()
                if isinstance(request, Read)
            }
            self._function_external_reads[requirement.function] = {
                request.dataset
                for request in requirement.inputs.values()
                if isinstance(request, ExternalRead)
            }
        for definition in job_registry.etls:
            reads = tuple(definition.inputs.values())
            direct = {
                request.dataset for request in reads if isinstance(request, Read)
            }
            direct_external = {
                request.dataset
                for request in reads
                if isinstance(request, ExternalRead)
            }
            self._job_functions[definition.name] = definition.uses
            declared = direct | self._datasets_for_functions(definition.uses)
            declared_external = direct_external | self._external_datasets_for_functions(
                definition.uses
            )
            self._job_declared_reads[definition.name] = declared
            self._job_declared_external_reads[definition.name] = declared_external
            for output in definition.outputs:
                self.add_dependency(output, declared | declared_external)

    def declaration_edges(
            self, job_name: str, job_registry: Registry = registry
    ) -> tuple[tuple[str, str], ...]:
        """Return typed declaration edges for a job and its reusable functions."""
        definition = job_registry.get_etl(job_name)
        edges: set[tuple[str, str]] = set()
        job_node = f'job:{definition.name}'
        for request in definition.inputs.values():
            edges.add((str(request.dataset), job_node))
        for function in definition.uses:
            edges.add((f'function:{function.__qualname__}', job_node))
        for output in definition.outputs:
            edges.add((job_node, str(output)))
        pending = list(definition.uses)
        visited: set[Callable[..., object]] = set()
        while pending:
            function = pending.pop()
            if function in visited:
                continue
            visited.add(function)
            node = f'function:{function.__qualname__}'
            for dataset in self._function_reads.get(function, set()):
                edges.add((str(dataset), node))
            for external_dataset in self._function_external_reads.get(
                    function, set()
            ):
                edges.add((str(external_dataset), node))
            for used in self._function_functions.get(function, ()):
                edges.add((f'function:{used.__qualname__}', node))
                pending.append(used)
        return tuple(sorted(edges))

    def _datasets_for_functions(
            self, functions: Iterable[Callable[..., object]]
    ) -> set[DatasetId]:
        datasets: set[DatasetId] = set()
        visited: set[Callable[..., object]] = set()
        pending = list(functions)
        while pending:
            function = pending.pop()
            if function in visited:
                continue
            visited.add(function)
            datasets.update(self._function_reads.get(function, set()))
            pending.extend(self._function_functions.get(function, ()))
        return datasets

    def _external_datasets_for_functions(
            self, functions: Iterable[Callable[..., object]]
    ) -> set[ExternalDatasetId]:
        datasets: set[ExternalDatasetId] = set()
        visited: set[Callable[..., object]] = set()
        pending = list(functions)
        while pending:
            function = pending.pop()
            if function in visited:
                continue
            visited.add(function)
            datasets.update(self._function_external_reads.get(function, set()))
            pending.extend(self._function_functions.get(function, ()))
        return datasets

    def add_catalog(
            self, catalog: CatalogLineageSource, as_of: date | None = None
    ) -> None:
        """Add manifest-declared dependencies for resolved catalog versions."""
        for dataset in catalog.list_datasets():
            resolved = cast(
                ResolvedLineageDataset, catalog.resolve_dataset(dataset, as_of)
            )
            version_id = resolved.dataset_version_id
            if not isinstance(version_id, int):
                raise TypeError('resolved catalog dataset has no version identifier')
            self.add_dependency(dataset, catalog.get_dependencies(version_id))

    def requirement_consumers(
            self,
            dataset: LineageDatasetId,
            job_registry: Registry = registry,
    ) -> tuple[str, ...]:
        """Return reusable functions that declare a read of the dataset."""
        names = {
            definition.function.__qualname__
            for definition in job_registry.requirements
            if any(read.dataset == dataset for read in definition.inputs.values())
        }
        return tuple(sorted(names))

    def external_requirement_consumers(
            self,
            dataset: ExternalDatasetId,
            job_registry: Registry = registry,
    ) -> tuple[str, ...]:
        """Return reusable functions that declare an external dataset read."""
        return self.requirement_consumers(dataset, job_registry)

    @staticmethod
    def _ordered(
            datasets: Iterable[LineageDatasetId],
    ) -> tuple[LineageDatasetId, ...]:
        return tuple(sorted(datasets, key=lambda item: item.canonical_name))

    @staticmethod
    def _ordered_external(
            datasets: Iterable[ExternalDatasetId],
    ) -> tuple[ExternalDatasetId, ...]:
        return tuple(sorted(datasets, key=lambda item: item.canonical_name))

    def _walk(
            self,
            dataset: LineageDatasetId,
            edges: dict[LineageDatasetId, set[LineageDatasetId]],
    ) -> tuple[LineageDatasetId, ...]:
        found: set[LineageDatasetId] = set()
        pending = list(edges.get(dataset, set()))
        while pending:
            current = pending.pop()
            if current in found:
                continue
            found.add(current)
            pending.extend(edges.get(current, set()))
        return self._ordered(found)

    def _assert_acyclic(self) -> None:
        visiting: set[LineageDatasetId] = set()
        visited: set[LineageDatasetId] = set()

        def visit(dataset: LineageDatasetId) -> None:
            if dataset in visiting:
                raise DependencyCycleError(f'dependency cycle includes {dataset}')
            if dataset in visited:
                return
            visiting.add(dataset)
            for parent in self._parents.get(dataset, set()):
                visit(parent)
            visiting.remove(dataset)
            visited.add(dataset)

        for dataset in self._parents:
            visit(dataset)

    def _reads_by_job(self) -> dict[str, set[LineageDatasetId]]:
        job_names = self._job_reads.keys() | self._job_external_reads.keys()
        return {
            job_name: set(self._job_reads.get(job_name, set()))
            | set(self._job_external_reads.get(job_name, set()))
            for job_name in job_names
        }

    def _declared_reads_by_job(self) -> dict[str, set[LineageDatasetId]]:
        job_names = (
                self._job_declared_reads.keys()
                | self._job_declared_external_reads.keys()
        )
        return {
            job_name: set(self._job_declared_reads.get(job_name, set()))
            | set(self._job_declared_external_reads.get(job_name, set()))
            for job_name in job_names
        }
