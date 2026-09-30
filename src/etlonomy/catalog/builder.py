"""Compile authoritative TOML manifests into deterministic SQLite catalogs."""

import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from pathlib import Path

from etlonomy.catalog.migrations import apply_migrations
from etlonomy.environment import (
    EnvironmentDefinition,
    load_environment,
    validate_environment_references,
)
from etlonomy.exceptions import CatalogError
from etlonomy.manifest import Manifest, load_manifest_directory


def _last_row_id(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise CatalogError('SQLite did not return an inserted row identifier')
    return row_id


def _insert_manifest(
        connection: sqlite3.Connection,
        manifest: Manifest,
        environment: EnvironmentDefinition,
) :
    for root in environment.roots:
        connection.execute(
            'INSERT INTO roots (root_name, base_uri) VALUES (?, ?)',
            (root.name, root.base_uri),
        )
    for definition in environment.connections:
        connection.execute(
            'INSERT INTO connections '
            '(connection_name, sqlalchemy_url, credential_ref) VALUES (?, ?, ?)',
            (
                definition.name,
                definition.sqlalchemy_url,
                definition.credential_ref,
            ),
        )
    dataset_ids: dict[object, int] = {}
    for dataset in manifest.datasets:
        cursor = connection.execute(
            'INSERT INTO datasets (canonical_name, description) VALUES (?, ?)',
            (str(dataset.dataset), dataset.description),
        )
        dataset_ids[dataset.dataset] = _last_row_id(cursor)
    for dataset in manifest.datasets:
        for version in dataset.versions:
            cursor = connection.execute(
                'INSERT INTO dataset_versions '
                '(dataset_id, version, valid_from, valid_to, source_type, source_uri, '
                'source_root, connection_name, credential_ref, query, options_json, '
                'description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    dataset_ids[dataset.dataset],
                    version.version,
                    version.valid_from.isoformat(),
                    version.valid_to.isoformat() if version.valid_to else None,
                    version.source_type,
                    version.source_uri,
                    version.source_root,
                    version.connection,
                    version.credential_ref,
                    version.query,
                    json.dumps(
                        dict(version.options), sort_keys=True, separators=(',', ':')
                    ),
                    version.description,
                ),
            )
            version_id = _last_row_id(cursor)
            for dependency in version.dependencies:
                connection.execute(
                    'INSERT INTO dataset_dependencies VALUES (?, ?)',
                    (version_id, dataset_ids[dependency]),
                )
            for column in version.columns:
                connection.execute(
                    'INSERT INTO dataset_columns VALUES (?, ?, ?, ?, ?, ?)',
                    (
                        version_id,
                        column.logical_name,
                        column.source_name,
                        column.data_type,
                        None if column.nullable is None else int(column.nullable),
                        column.description,
                    ),
                )


def _catalog_hash(
        manifest: Manifest, environment: EnvironmentDefinition
) -> str:
    serializable = json.dumps(
        {
            'manifest': _catalog_value(manifest),
            'environment': _catalog_value(environment),
        },
        sort_keys=True,
        separators=(',', ':'),
        default=str,
    ).encode('utf8')
    return hashlib.sha256(serializable).hexdigest()


def _catalog_value(value) :
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _catalog_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _catalog_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_catalog_value(item) for item in value]
    return value


def build_catalog(
        manifest_dir: Path,
        database: Path,
        *,
        environment_config: Path | None = None,
) -> str:
    """Build a catalog atomically and return its deterministic content hash.

    An invalid manifest or failed integrity check leaves an existing catalog unchanged.
    """
    manifest = load_manifest_directory(manifest_dir)
    environment = (
        load_environment(environment_config)
        if environment_config is not None
        else EnvironmentDefinition()
    )
    validate_environment_references(manifest, environment)
    database.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f'.{database.name}.', suffix='.tmp', dir=database.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    catalog_hash = _catalog_hash(manifest, environment)
    try:
        connection = sqlite3.connect(temporary)
        try:
            apply_migrations(connection)
            with connection:
                _insert_manifest(connection, manifest, environment)
                connection.execute(
                    'INSERT INTO catalog_metadata (key, value) VALUES (?, ?)',
                    ('catalog_hash', catalog_hash),
                )
                if environment.environment is not None:
                    connection.execute(
                        'INSERT INTO catalog_metadata (key, value) VALUES (?, ?)',
                        ('environment', environment.environment),
                    )
            foreign_key_errors = connection.execute(
                'PRAGMA foreign_key_check'
            ).fetchall()
            integrity = connection.execute('PRAGMA integrity_check').fetchone()
            if foreign_key_errors or integrity != ('ok',):
                raise CatalogError('catalog integrity validation failed')
        finally:
            connection.close()
        os.replace(temporary, database)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return catalog_hash
