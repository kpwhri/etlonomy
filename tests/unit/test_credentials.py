"""Tests for optional credential reference providers."""

from types import SimpleNamespace

import pytest

from etlonomy.credentials import (
    EnvironmentCredentialProvider,
    KeePassCredentialProvider,
    KeePassProfile,
    MappingCredentialProvider,
    ResolvedCredential,
    SchemeCredentialProvider,
)
from etlonomy.exceptions import (
    CredentialError,
    CredentialNotFoundError,
    CredentialSchemeNotFoundError,
    ManifestError,
)
from etlonomy.manifest import parse_manifest


def test_resolved_credential_repr_never_contains_secret_values():
    credential = ResolvedCredential(
        username='alice', password='secret', token='token', options={'pin': '1234'}
    )

    representation = repr(credential)

    assert representation == 'ResolvedCredential()'
    assert 'secret' not in representation
    assert 'token' not in representation


def test_environment_provider_reads_names_declared_by_reference():
    provider = EnvironmentCredentialProvider(
        {'DB_USER': 'alice', 'DB_PASSWORD': 'correct horse'}
    )

    credential = provider.resolve('env://?username=DB_USER&password=DB_PASSWORD')

    assert credential.username == 'alice'
    assert credential.password == 'correct horse'


@pytest.mark.parametrize(('reference', 'message'), [
    ('env://host?password=PASS', 'must start'),
    ('env://?database=PASS', 'unsupported'),
    ('env://?password=ONE&password=TWO', 'duplicate'),
    ('env://?password=', 'empty'),
    ('env://', 'at least one'),
])
def test_environment_provider_rejects_ambiguous_references(reference, message):
    with pytest.raises(CredentialError, match=message):
        EnvironmentCredentialProvider({}).resolve(reference)


def test_environment_provider_names_missing_variable_without_exposing_values():
    with pytest.raises(CredentialNotFoundError, match='DB_PASSWORD'):
        EnvironmentCredentialProvider({}).resolve('env://?password=DB_PASSWORD')


def test_mapping_provider_requires_an_exact_reference():
    provider = MappingCredentialProvider(
        {'fixture://database': ResolvedCredential(token='abc')}
    )

    assert provider.resolve('fixture://database').token == 'abc'
    with pytest.raises(CredentialNotFoundError):
        provider.resolve('fixture://other')


def test_scheme_provider_passes_complete_reference_to_custom_provider():
    seen = []

    class CustomProvider:
        def resolve(self, reference):
            seen.append(reference)
            return ResolvedCredential(username='custom')

    dispatcher = SchemeCredentialProvider({'vault+team': CustomProvider()})

    credential = dispatcher.resolve('vault+team://analytics/claims?version=2')

    assert credential.username == 'custom'
    assert seen == ['vault+team://analytics/claims?version=2']


def test_scheme_provider_rejects_unknown_duplicate_and_invalid_schemes():
    dispatcher = SchemeCredentialProvider({'env': EnvironmentCredentialProvider({})})
    with pytest.raises(CredentialSchemeNotFoundError):
        dispatcher.resolve('keepass://work/database')
    with pytest.raises(CredentialError, match='already registered'):
        dispatcher.register('ENV:', EnvironmentCredentialProvider({}))
    with pytest.raises(CredentialError, match='invalid'):
        dispatcher.register('not a scheme', EnvironmentCredentialProvider({}))
    with pytest.raises(CredentialError, match='invalid'):
        dispatcher.register('123', EnvironmentCredentialProvider({}))


def test_keepass_provider_uses_named_profile_and_full_entry_path(tmp_path):
    opened = []
    entry = SimpleNamespace(username='alice', password='secret')

    class Database:
        def find_entries(self, *, path, first):
            assert path == 'Databases/Claims Production'
            assert first is True
            return entry

    def factory(database_path, password, keyfile_path):
        opened.append((database_path, password, keyfile_path))
        return Database()

    profile = KeePassProfile(
        tmp_path / 'team.kdbx',
        password='database-password',
        keyfile_path=tmp_path / 'key',
    )
    provider = KeePassCredentialProvider({'work': profile}, factory=factory)

    credential = provider.resolve('keepass://work/Databases/Claims%20Production')

    assert credential.username == 'alice'
    assert credential.password == 'secret'
    assert opened == [(tmp_path / 'team.kdbx', 'database-password', tmp_path / 'key')]


def test_keepass_provider_reports_missing_profile_and_entry(tmp_path):
    provider = KeePassCredentialProvider({}, factory=lambda *args: object())
    with pytest.raises(CredentialNotFoundError, match='profile'):
        provider.resolve('keepass://work/group/entry')

    class EmptyDatabase:
        def find_entries(self, **kwargs):
            return None

    provider = KeePassCredentialProvider(
        {'work': KeePassProfile(tmp_path / 'team.kdbx')},
        factory=lambda *args: EmptyDatabase(),
    )
    with pytest.raises(CredentialNotFoundError, match='entry'):
        provider.resolve('keepass://work/group/entry')


@pytest.mark.parametrize('reference', [
    'keepass://', 'keepass://work', 'env://?password=PASS'
])
def test_keepass_provider_rejects_malformed_reference(reference):
    with pytest.raises(CredentialError):
        KeePassCredentialProvider({}).resolve(reference)


def test_manifest_parses_optional_credential_reference():
    manifest = parse_manifest(
        b"""etlonomy_manifest = 1
[[datasets]]
canonical_name = 'CLAIMS.LINE'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'sql_table'
source_uri = 'postgresql://warehouse/claims'
credential_ref = 'env://?password=CLAIMS_PASSWORD'
query = 'claims.line'
"""
    )

    assert manifest.datasets[0].versions[0].credential_ref == (
        'env://?password=CLAIMS_PASSWORD'
    )


@pytest.mark.parametrize('value', ["''", '123'])
def test_manifest_rejects_invalid_credential_reference(value):
    document = f"""etlonomy_manifest = 1
[[datasets]]
canonical_name = 'CLAIMS.LINE'
[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'sql_table'
source_uri = 'postgresql://warehouse/claims'
credential_ref = {value}
query = 'claims.line'
"""

    with pytest.raises(ManifestError, match='credential_ref'):
        parse_manifest(document.encode())
