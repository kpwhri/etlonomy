"""Domain exceptions raised by ETLonomy."""


class ETLonomyError(Exception):
    """Base class for all expected ETLonomy failures."""


class ManifestError(ETLonomyError):
    """Indicate that manifest input is malformed or inconsistent."""


class CatalogError(ETLonomyError):
    """Indicate that a catalog cannot be built, migrated, or queried."""


class DatasetNotFoundError(CatalogError):
    """Indicate that a logical dataset is absent from a catalog."""


class DatasetVersionNotFoundError(CatalogError):
    """Indicate that no requested or temporally valid dataset version exists."""


class VersionOverlapError(ManifestError):
    """Indicate that validity intervals overlap for one logical dataset."""


class RegistryError(ETLonomyError):
    """Indicate invalid registry metadata or registry access."""


class MissingTestDatasetError(ETLonomyError):
    """Indicate that a test provider was not given a requested dataset."""


class MissingTestColumnError(ETLonomyError):
    """Indicate that a test dataset lacks a requested logical column."""


class DatasetProviderError(ETLonomyError):
    """Indicate that a dataset provider could not satisfy a read."""


class CatalogEnvironmentMismatchError(DatasetProviderError):
    """Indicate that an explicit execution environment conflicts with a catalog."""


class CredentialError(ETLonomyError):
    """Indicate that a credential reference could not be resolved safely."""


class CredentialProviderNotConfiguredError(CredentialError):
    """Indicate that a dataset needs credentials but no provider was configured."""


class CredentialSchemeNotFoundError(CredentialError):
    """Indicate that no credential provider handles a reference scheme."""


class CredentialNotFoundError(CredentialError):
    """Indicate that referenced credential material is unavailable."""


class DependencyCycleError(ETLonomyError):
    """Indicate a cycle in declared dataset dependencies."""
