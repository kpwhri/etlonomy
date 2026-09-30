from datetime import date

import pytest

from etlonomy import (
    DatasetId,
    ExecutionContext,
    MissingTestDatasetError,
    TestDatasetProvider,
    read,
)


def test_missing_test_fixture_cannot_fall_back_to_production() :
    provider = TestDatasetProvider({})
    request = read(DatasetId('CLAIMS', 'CLAIM_LINE'), 'person_id')

    with pytest.raises(MissingTestDatasetError):
        provider.read(request, ExecutionContext('prod', date(2026, 8, 20)))
