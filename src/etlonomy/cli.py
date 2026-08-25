"""Command-line tools for catalogs, code generation, and lineage inspection."""

import argparse
import importlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import date
from pathlib import Path
from typing import cast

from etlonomy.catalog import ResolvedDataset, SQLiteCatalog, build_catalog
from etlonomy.codegen import generate_datasets
from etlonomy.environment import (
    EnvironmentDefinition,
    load_environment,
    validate_environment_references,
)
from etlonomy.exceptions import ETLonomyError
from etlonomy.lineage import LineageGraph
from etlonomy.manifest import load_manifest_directory
from etlonomy.models import DatasetId, ExternalDatasetId, ExternalRead, Read
from etlonomy.registry import registry


def _dataset(value: str) -> DatasetId:
    try:
        return DatasetId.parse(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='etlonomy')
    commands = parser.add_subparsers(dest='command', required=True)
    catalog = commands.add_parser('catalog')
    catalog_commands = catalog.add_subparsers(dest='catalog_command', required=True)
    for name in ('build', 'validate'):
        command = catalog_commands.add_parser(name)
        command.add_argument('--manifest-dir', type=Path, required=True)
        command.add_argument('--environment-config', type=Path)
        if name == 'build':
            command.add_argument('--database', type=Path, required=True)
    for name in ('show', 'history', 'resolve'):
        command = catalog_commands.add_parser(name)
        command.add_argument('--database', type=Path, required=True)
        if name != 'show':
            command.add_argument('dataset', type=_dataset)
        if name == 'resolve':
            command.add_argument('--as-of', type=date.fromisoformat)
            command.add_argument('--version', type=int)
    diff = catalog_commands.add_parser('diff')
    diff.add_argument('left', type=Path)
    diff.add_argument('right', type=Path)

    codegen = commands.add_parser('codegen')
    codegen_commands = codegen.add_subparsers(dest='codegen_command', required=True)
    datasets = codegen_commands.add_parser('datasets')
    datasets.add_argument('--database', type=Path, required=True)
    datasets.add_argument('--output', type=Path, required=True)

    registry_parser = commands.add_parser('registry')
    registry_command = registry_parser.add_subparsers(
        dest='registry_command', required=True
    ).add_parser('validate')
    registry_command.add_argument('--module', action='append', default=[])
    for name in ('deps', 'uses', 'lineage', 'graph'):
        command = commands.add_parser(name)
        command.add_argument('name')
        command.add_argument('--module', action='append', default=[])
        command.add_argument('--database', type=Path)
        command.add_argument('--as-of', type=date.fromisoformat)
        command.add_argument(
            '--format', choices=('text', 'json', 'mermaid', 'dot'), default='text'
        )
    return parser


def _catalog_command(args: argparse.Namespace) -> None:
    if args.catalog_command == 'build':
        print(
            build_catalog(
                args.manifest_dir,
                args.database,
                environment_config=args.environment_config,
            )
        )
        return
    if args.catalog_command == 'validate':
        manifest = load_manifest_directory(args.manifest_dir)
        environment = (
            load_environment(args.environment_config)
            if args.environment_config is not None
            else EnvironmentDefinition()
        )
        validate_environment_references(manifest, environment)
        print(f'valid: {len(manifest.datasets)} datasets')
        return
    if args.catalog_command == 'diff':
        left = _catalog_snapshot(SQLiteCatalog(args.left))
        right = _catalog_snapshot(SQLiteCatalog(args.right))
        print(json.dumps({
            'added': sorted(right.keys() - left.keys()),
            'removed': sorted(left.keys() - right.keys()),
            'changed': sorted(
                name
                for name in left.keys() & right.keys()
                if left[name] != right[name]
            ),
            'environment_changed': (
                    SQLiteCatalog(args.left).get_environment()
                    != SQLiteCatalog(args.right).get_environment()
            ),
            'roots_changed': (
                    SQLiteCatalog(args.left).list_roots()
                    != SQLiteCatalog(args.right).list_roots()
            ),
            'connections_changed': (
                    SQLiteCatalog(args.left).list_connections()
                    != SQLiteCatalog(args.right).list_connections()
            ),
        }))
        return
    catalog = SQLiteCatalog(args.database)
    if args.catalog_command == 'show':
        for dataset in catalog.list_datasets():
            print(dataset)
    elif args.catalog_command == 'history':
        for version in catalog.get_versions(args.dataset):
            print(
                f'{version.version}: {version.valid_from} to '
                f'{version.valid_to or "open-ended"}'
            )
    else:
        resolved = catalog.resolve_dataset(args.dataset, args.as_of, args.version)
        print(json.dumps(_json_record(resolved), sort_keys=True))


def _json_record(value: ResolvedDataset) -> dict[str, object]:
    record = _json_value(value)
    return cast(dict[str, object], json.loads(json.dumps(record, default=str)))


def _json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _json_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _catalog_snapshot(catalog: SQLiteCatalog) -> dict[str, object]:
    snapshot: dict[str, object] = {}
    for dataset in catalog.list_datasets():
        versions = []
        for version in catalog.get_versions(dataset):
            record = _json_record(version)
            record.pop('dataset_version_id')
            record['dependencies'] = list(
                map(str, catalog.get_dependencies(version.dataset_version_id))
            )
            versions.append(record)
        snapshot[str(dataset)] = versions
    return snapshot


def _load_modules(names: Sequence[str]) -> None:
    for name in names:
        importlib.import_module(name)


def _registry_command(modules: Sequence[str]) -> None:
    _load_modules(modules)
    for definition in registry.etls:
        print(definition.name)
    print(f'valid: {len(registry.etls)} ETL jobs')


def _lineage_command(args: argparse.Namespace) -> None:
    _load_modules(args.module)
    graph = LineageGraph()
    graph.add_registry(registry)
    if args.database:
        graph.add_catalog(SQLiteCatalog(args.database), args.as_of)
    if args.command in {'deps', 'graph'}:
        definition = registry.get_etl(args.name)
        direct = {
            request.dataset
            for request in definition.inputs.values()
            if isinstance(request, Read)
        }
        direct_external = {
            request.dataset
            for request in definition.inputs.values()
            if isinstance(request, ExternalRead)
        }
        transitive = set(graph.declared_uses(definition.name)) - direct
        transitive.update(
            ancestor for dataset in direct for ancestor in graph.ancestors(dataset)
        )
        transitive_external = (
                set(graph.declared_external_uses(definition.name)) - direct_external
        )
        record: dict[str, object] = {
            'job': definition.name,
            'direct': sorted(map(str, direct | direct_external)),
            'transitive': sorted(map(str, transitive | transitive_external)),
            'outputs': sorted(map(str, definition.outputs)),
        }
        graph_nodes = set(definition.outputs)
        for output in definition.outputs:
            graph_nodes.update(graph.ancestors(output))
        edges = {
            (str(parent), str(dataset))
            for dataset in graph_nodes
            for parent in graph.parents(dataset)
        }
        edges.update(graph.declaration_edges(definition.name, registry))
        if args.command == 'deps':
            _print_record(record, args.format)
        else:
            _print_graph(edges, args.format, record)
        return
    if ':' in args.name:
        external = ExternalDatasetId.parse(args.name)
        if args.command != 'uses':
            raise ValueError('external datasets support the uses command')
        jobs = graph.external_consumers(external, registry)
        downstream = {
            output
            for definition in registry.etls
            if definition.name in jobs
            for output in definition.outputs
        }
        record = {
            'dataset': str(external),
            'etl_jobs': list(jobs),
            'reusable_functions': list(
                graph.external_requirement_consumers(external, registry)
            ),
            'downstream_datasets': sorted(map(str, downstream)),
        }
        _print_record(record, args.format)
        return
    dataset = DatasetId.parse(args.name)
    if args.command == 'uses':
        record = {
            'dataset': str(dataset),
            'etl_jobs': list(graph.consumers(dataset, registry)),
            'reusable_functions': list(graph.requirement_consumers(dataset, registry)),
            'downstream_datasets': list(map(str, graph.descendants(dataset))),
        }
    else:
        record = {
            'dataset': str(dataset),
            'parents': list(map(str, graph.parents(dataset))),
            'children': list(map(str, graph.children(dataset))),
            'ancestors': list(map(str, graph.ancestors(dataset))),
            'descendants': list(map(str, graph.descendants(dataset))),
        }
    _print_record(record, args.format)


def _print_record(record: dict[str, object], output_format: str) -> None:
    if output_format == 'json':
        print(json.dumps(record, sort_keys=True))
        return
    for label, value in record.items():
        heading = label.replace('_', ' ').title()
        print(f'{heading}:')
        if isinstance(value, list):
            for item in value:
                print(f'    {item}')
        else:
            print(f'    {value}')


def _print_graph(
        edges: set[tuple[str, str]],
        output_format: str,
        record: dict[str, object],
) -> None:
    ordered = sorted(edges)
    if output_format == 'mermaid':
        print('graph LR')
        labels = sorted({node for edge in ordered for node in edge})
        identifiers = {label: f'n{index}' for index, label in enumerate(labels)}
        for source, target in ordered:
            source_label = source.replace('"', '&quot;')
            target_label = target.replace('"', '&quot;')
            print(
                f'    {identifiers[source]}["{source_label}"] --> '
                f'{identifiers[target]}["{target_label}"]'
            )
    elif output_format == 'dot':
        print('digraph etlonomy {')
        for source, target in ordered:
            print(f'    "{source}" -> "{target}";')
        print('}')
    elif output_format == 'json':
        print(json.dumps({'edges': [[a, b] for a, b in ordered]}))
    else:
        _print_record(record, output_format)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ETLonomy CLI and return a process exit status."""
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.command == 'catalog':
            _catalog_command(args)
        elif args.command == 'codegen':
            generate_datasets(SQLiteCatalog(args.database), args.output)
        elif args.command == 'registry':
            _registry_command(args.module)
        else:
            _lineage_command(args)
    except (ETLonomyError, ImportError, OSError, ValueError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
