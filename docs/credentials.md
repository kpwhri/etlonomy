# Add credentials when a database needs them

Many sources need no credential provider. Local files and SQLite work without one. A database that uses integrated
security may also need only its sqlalchemy URL.

When a database needs a username, password, or token, separate the location from the secret:

1. `source_uri` says **where and how to connect**
2. `credential_ref` says **where your application may look up secrets**

The TOML stores the reference. The credential provider returns the secret only when the source is read.

You may put a username, password, or token directly in `source_uri` or `sqlalchemy_url`. This can be useful for a small
internal workflow, but Etlonomy may show the URL exactly as written. Only do this when everyone who can read the TOML,
catalog, command output, and logs is allowed to see the secret.

## Read credentials from environment variables

Put variable names—not their values—in TOML:

```toml
source_uri = 'postgresql+psycopg://warehouse.example/analytics'
credential_ref = 'env://?username=WAREHOUSE_USER&password=WAREHOUSE_PASSWORD'
```

Then configure the allowed lookup method when your application starts:

```python
import etlonomy

credentials = etlonomy.SchemeCredentialProvider({
    # explicit registration limits manifests to lookup methods our application trusts
    'env': etlonomy.EnvironmentCredentialProvider(),
})
provider = etlonomy.CatalogDatasetProvider(
    catalog=catalog,
    # this provider is consulted only when the selected version declares credential_ref
    credential_provider=credentials,
)
```

The variables are read only when this dataset is selected. A missing variable produces a clear error. Printed credential
objects hide the secret values.

## Read credentials from KeePass

A KDBX file may need its own password and key file. Put those opening details in one local profile instead of repeating
them for every dataset:

```python
from pathlib import Path

import etlonomy

keepass = etlonomy.KeePassCredentialProvider({
    'work': etlonomy.KeePassProfile(
        # the profile keeps database-opening details out of every dataset version
        database_path=Path('C:/secure/team.kdbx'),
        password=None,
        keyfile_path=Path('C:/secure/team.key'),
    ),
})
credentials = etlonomy.SchemeCredentialProvider({'keepass': keepass})
```

The manifest can refer to one entry:

```toml
credential_ref = 'keepass://work/Databases/Claims%20Production'
```

`work` selects the profile. The remainder is the full PyKeePass entry path. Install the preset with
`pip install etlonomy[keepass]`. In a real application, read the KDBX password during startup from an environment
variable, prompt, or operating-system secret store.

## Add your own credential provider

Your provider may interpret any reference string. Your application must register it directly. Etlonomy never imports a
class named by TOML.

```python
class TeamVaultProvider:
    """Resolve references using the organization's approved vault client."""

    def __init__(self, client: object) -> None:
        """Store the already-configured vault client."""
        self._client = client

    def resolve(self, reference: str) -> etlonomy.ResolvedCredential:
        """Turn one opaque vault reference into database credentials."""
        # passing the complete string lets the organization define its own reference grammar
        record = self._client.fetch(reference)
        return etlonomy.ResolvedCredential(
            username=record.username,
            password=record.password,
        )


credentials = etlonomy.SchemeCredentialProvider({
    'team-vault': TeamVaultProvider(vault_client),
})
```

A manifest may now use `team-vault://analytics/claims`. Your provider receives the complete string, so your organization
owns its meaning.

Use `MappingCredentialProvider` when testing SQL credential lookup. Use `TestDatasetProvider` for normal ETL tests so no
catalog or credential provider is contacted.

Next: [walk through the credential tutorial](tutorials/08-credentials.md).
