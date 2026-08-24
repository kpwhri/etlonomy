CREATE TABLE datasets
(
    dataset_id     INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    description    TEXT
);

-- etlonomy:next-statement

CREATE TABLE dataset_versions
(
    dataset_version_id INTEGER PRIMARY KEY,
    dataset_id         INTEGER NOT NULL,
    version            INTEGER NOT NULL,
    valid_from         TEXT    NOT NULL,
    valid_to           TEXT,
    source_type        TEXT    NOT NULL,
    source_uri         TEXT,
    query              TEXT,
    options_json       TEXT,
    description        TEXT,
    FOREIGN KEY (dataset_id) REFERENCES datasets (dataset_id),
    UNIQUE (dataset_id, version)
);

-- etlonomy:next-statement

CREATE TABLE dataset_dependencies
(
    dataset_version_id  INTEGER NOT NULL,
    upstream_dataset_id INTEGER NOT NULL,
    PRIMARY KEY (dataset_version_id, upstream_dataset_id),
    FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions (dataset_version_id),
    FOREIGN KEY (upstream_dataset_id) REFERENCES datasets (dataset_id)
);

-- etlonomy:next-statement

CREATE TABLE dataset_columns
(
    dataset_version_id INTEGER NOT NULL,
    logical_name       TEXT    NOT NULL,
    source_name        TEXT,
    data_type          TEXT,
    nullable           INTEGER,
    description        TEXT,
    PRIMARY KEY (dataset_version_id, logical_name),
    FOREIGN KEY (dataset_version_id) REFERENCES dataset_versions (dataset_version_id)
);

-- etlonomy:next-statement

CREATE TABLE catalog_metadata
(
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
