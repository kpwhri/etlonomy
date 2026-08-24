# Contributing code and documentation

## Work in small, testable steps

Use this loop:

1. Choose one observable behavior
2. Add meaningful tests for that behavior immediately
3. Run the focused tests while feedback is fast
4. Run the complete suite after the subsystem is stable
5. Update documentation whenever public behavior changes
6. Run every quality gate before handing off the work

This keeps several mistakes from piling up before the first test is run.

## Put code in the expected place

```text
src/etlonomy/   # every non-test Python implementation module
tests/unit/     # isolated behavior with no external systems
tests/integration/  # temporary files, SQLite, and mocked connection boundaries
tests/end_to_end/   # complete workflows using only non-production resources
docs/           # the teaching and reference material users actually read
```

Tests must never require a production database, shared drive, credential, or remote workspace. Use temporary
directories, small polars frames, local SQLite databases, and explicit mocks.

## Name tests after behavior

```python
def test_resolve_dataset_uses_version_valid_on_requested_date():
    # dates on both sides of the changeover prove the date rule
    ...
```

A name such as `test_catalog()` does not say what should happen. Name the rule the test protects.

Coverage is a warning tool, not the goal. Add tests that would catch a real problem. Do not add assertions only to run a
line.

## Keep documentation accurate

Documentation should:

- explain the motivation before showing syntax
- use TOML for every manifest example
- state the expected result of each command
- include comments that explain why a design choice matters
- link to prerequisites, related references, and the next lesson
- separate safe defaults from optional production connections
- keep examples consistent with the current public API

## Run the quality gates

```console
# behavior and the required coverage threshold
python -m pytest --cov=etlonomy --cov-branch --cov-fail-under=95

# linting catches correctness and consistency problems without rewriting layout
python -m ruff check .

# strict typing checks contracts that tests may not happen to exercise
python -m mypy src/etlonomy

# strict documentation builds catch missing pages and broken internal links
python -m mkdocs build --strict
```

If one command fails, fix it before moving forward. A clean local run makes review and CI easier.

Previous: [architecture](architecture.md) · Return to:
[documentation home](index.md)
