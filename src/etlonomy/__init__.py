"""Public API for logical, versioned ETL dataset resolution."""

from etlonomy.catalog import ResolvedDataset, SQLiteCatalog, build_catalog
from etlonomy.catalog_provider import CatalogDatasetProvider
from etlonomy.credentials import (
    CredentialProvider,
    EnvironmentCredentialProvider,
    KeePassCredentialProvider,
    KeePassProfile,
    MappingCredentialProvider,
    ResolvedCredential,
    SchemeCredentialProvider,
)
from etlonomy.decorators import etl, requires
from etlonomy.environment import (
    ConnectionDefinition,
    EnvironmentDefinition,
    RootDefinition,
    load_environment,
    parse_environment,
)
from etlonomy.exceptions import (
    CatalogEnvironmentMismatchError,
    CatalogError,
    CredentialError,
    CredentialNotFoundError,
    CredentialProviderNotConfiguredError,
    CredentialSchemeNotFoundError,
    DatasetNotFoundError,
    DatasetProviderError,
    DatasetVersionNotFoundError,
    DependencyCycleError,
    ETLonomyError,
    ExternalDatasetProviderNotConfiguredError,
    ManifestError,
    MissingTestColumnError,
    MissingTestDatasetError,
    RegistryError,
    VersionOverlapError,
)
from etlonomy.lineage import LineageGraph
from etlonomy.models import (
    DatasetId,
    DependencyRead,
    ExecutionContext,
    ExternalDatasetId,
    ExternalRead,
    Read,
    external_read,
    read,
)
from etlonomy.providers import (
    DatasetProvider,
    ExternalDatasetProvider,
    TestDatasetProvider,
)
from etlonomy.registry import EtlDefinition, Registry, RequirementDefinition, registry
from etlonomy.runtime import Runtime

__version__ = '0.1.0'

__all__ = [
    'CatalogDatasetProvider',
    'CatalogEnvironmentMismatchError',
    'CatalogError',
    'CredentialError',
    'CredentialNotFoundError',
    'CredentialProvider',
    'CredentialProviderNotConfiguredError',
    'CredentialSchemeNotFoundError',
    'ConnectionDefinition',
    'DatasetId',
    'DatasetNotFoundError',
    'DatasetProvider',
    'DatasetProviderError',
    'DatasetVersionNotFoundError',
    'DependencyRead',
    'DependencyCycleError',
    'ETLonomyError',
    'EnvironmentCredentialProvider',
    'EnvironmentDefinition',
    'EtlDefinition',
    'ExecutionContext',
    'ExternalDatasetId',
    'ExternalDatasetProvider',
    'ExternalDatasetProviderNotConfiguredError',
    'ExternalRead',
    'LineageGraph',
    'KeePassCredentialProvider',
    'KeePassProfile',
    'ManifestError',
    'MappingCredentialProvider',
    'MissingTestColumnError',
    'MissingTestDatasetError',
    'Read',
    'Registry',
    'RegistryError',
    'RequirementDefinition',
    'ResolvedDataset',
    'ResolvedCredential',
    'RootDefinition',
    'Runtime',
    'SchemeCredentialProvider',
    'SQLiteCatalog',
    'TestDatasetProvider',
    'VersionOverlapError',
    '__version__',
    'build_catalog',
    'etl',
    'external_read',
    'load_environment',
    'parse_environment',
    'read',
    'registry',
    'requires',
]
