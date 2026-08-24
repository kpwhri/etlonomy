ALTER TABLE dataset_versions
    ADD COLUMN source_root TEXT;

-- etlonomy:next-statement

ALTER TABLE dataset_versions
    ADD COLUMN connection_name TEXT;

-- etlonomy:next-statement

CREATE TABLE roots
(
    root_name TEXT PRIMARY KEY,
    base_uri  TEXT NOT NULL
);

-- etlonomy:next-statement

CREATE TABLE connections
(
    connection_name TEXT PRIMARY KEY,
    sqlalchemy_url  TEXT NOT NULL,
    credential_ref  TEXT
);
