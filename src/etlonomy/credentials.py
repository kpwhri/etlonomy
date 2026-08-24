"""Optional, user-configurable credential reference resolution."""

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import parse_qsl, unquote, urlsplit

from etlonomy.exceptions import (
    CredentialError,
    CredentialNotFoundError,
    CredentialSchemeNotFoundError,
)

_SCHEME = re.compile(r'^[a-z][a-z0-9+.-]*$')


@dataclass(frozen=True, slots=True)
class ResolvedCredential:
    """Hold credential values returned at runtime without exposing them in repr output."""

    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    token: str | None = field(default=None, repr=False)
    options: Mapping[str, object] = field(default_factory=dict, repr=False)


class CredentialProvider(Protocol):
    """Resolve an opaque credential reference into runtime-only values."""

    def resolve(self, reference: str) -> ResolvedCredential:
        """Resolve a complete reference or raise a credential-specific exception."""
        ...


class EnvironmentCredentialProvider:
    """Resolve credential fields from named environment variables."""

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        """Use the supplied mapping, or the process environment when omitted."""
        self._environment = os.environ if environment is None else environment

    def resolve(self, reference: str) -> ResolvedCredential:
        """Resolve an ``env://`` reference whose query values name variables."""
        parsed = urlsplit(reference)
        if parsed.scheme != 'env' or parsed.netloc or parsed.path:
            raise CredentialError('environment references must start with env://?')
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        allowed = {'username', 'password', 'token'}
        names: dict[str, str] = {}
        for key, variable in pairs:
            if key not in allowed:
                raise CredentialError(
                    f'unsupported environment credential field: {key}'
                )
            if key in names:
                raise CredentialError(f'duplicate environment credential field: {key}')
            if not variable:
                raise CredentialError(f'environment variable name for {key} is empty')
            names[key] = variable
        if not names:
            raise CredentialError('environment reference must name at least one field')
        values: dict[str, str] = {}
        for field_name, variable in names.items():
            try:
                values[field_name] = self._environment[variable]
            except KeyError as error:
                raise CredentialNotFoundError(
                    f'environment variable is not set: {variable}'
                ) from error
        return ResolvedCredential(
            username=values.get('username'),
            password=values.get('password'),
            token=values.get('token'),
        )


class MappingCredentialProvider:
    """Resolve exact references from an in-memory mapping, primarily for tests."""

    def __init__(self, credentials: Mapping[str, ResolvedCredential]) -> None:
        """Copy the supplied mapping so later caller mutation cannot change lookups."""
        self._credentials = dict(credentials)

    def resolve(self, reference: str) -> ResolvedCredential:
        """Return the credential registered for an exact reference."""
        try:
            return self._credentials[reference]
        except KeyError as error:
            raise CredentialNotFoundError(
                f'credential reference was not found: {reference}'
            ) from error


class SchemeCredentialProvider:
    """Dispatch references to explicitly registered providers by URI scheme."""

    def __init__(
            self, providers: Mapping[str, CredentialProvider] | None = None
    ) -> None:
        """Register the initial provider mapping after validating scheme names."""
        self._providers: dict[str, CredentialProvider] = {}
        for scheme, provider in (providers or {}).items():
            self.register(scheme, provider)

    def register(self, scheme: str, provider: CredentialProvider) -> None:
        """Register one provider without importing or executing arbitrary classes."""
        normalized = scheme.lower().rstrip(':')
        if not _SCHEME.fullmatch(normalized):
            raise CredentialError(f'invalid credential scheme: {scheme}')
        if normalized in self._providers:
            raise CredentialError(f'credential scheme already registered: {normalized}')
        self._providers[normalized] = provider

    def resolve(self, reference: str) -> ResolvedCredential:
        """Pass the complete opaque reference to its registered provider."""
        scheme = urlsplit(reference).scheme.lower()
        try:
            provider = self._providers[scheme]
        except KeyError as error:
            raise CredentialSchemeNotFoundError(
                f'no credential provider is registered for scheme: {scheme or "<missing>"}'
            ) from error
        return provider.resolve(reference)


@dataclass(frozen=True, slots=True)
class KeePassProfile:
    """Describe how to open one named KeePass database outside a manifest."""

    database_path: Path
    password: str | None = field(default=None, repr=False)
    keyfile_path: Path | None = None


class KeePassEntry(Protocol):
    """Expose the credential fields read from a KeePass entry."""

    username: str | None
    password: str | None


class KeePassDatabase(Protocol):
    """Expose the one PyKeePass lookup used by the built-in provider."""

    def find_entries(self, *, path: str, first: bool) -> KeePassEntry | None:
        """Return the first entry matching a full database path."""
        ...


KeePassFactory = Callable[[Path, str | None, Path | None], KeePassDatabase]


class KeePassCredentialProvider:
    """Resolve ``keepass://profile/group/entry`` references through PyKeePass."""

    def __init__(
            self,
            profiles: Mapping[str, KeePassProfile],
            *,
            factory: KeePassFactory | None = None,
    ) -> None:
        """Store named profiles and optionally inject the KeePass opening boundary."""
        self._profiles = dict(profiles)
        self._factory = factory or _open_keepass

    def resolve(self, reference: str) -> ResolvedCredential:
        """Read one entry by full path while keeping database settings out of manifests."""
        parsed = urlsplit(reference)
        if (
                parsed.scheme != 'keepass'
                or not parsed.netloc
                or not parsed.path.strip('/')
        ):
            raise CredentialError(
                'KeePass references must look like keepass://profile/group/entry'
            )
        try:
            profile = self._profiles[parsed.netloc]
        except KeyError as error:
            raise CredentialNotFoundError(
                f'KeePass profile was not found: {parsed.netloc}'
            ) from error
        entry_path = unquote(parsed.path.lstrip('/'))
        database = self._factory(
            profile.database_path, profile.password, profile.keyfile_path
        )
        entry = database.find_entries(path=entry_path, first=True)
        if entry is None:
            raise CredentialNotFoundError(
                f'KeePass entry was not found in profile {parsed.netloc}: {entry_path}'
            )
        return ResolvedCredential(username=entry.username, password=entry.password)


def _open_keepass(
        database_path: Path, password: str | None, keyfile_path: Path | None
) -> KeePassDatabase:
    try:
        from pykeepass import PyKeePass
    except ImportError as error:
        raise CredentialError(
            'KeePass support requires the optional pykeepass dependency'
        ) from error
    return cast(
        KeePassDatabase,
        PyKeePass(
            str(database_path),
            password=password,
            keyfile=str(keyfile_path) if keyfile_path else None,
        ),
    )
