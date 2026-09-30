import etlonomy


def test_package_exposes_version():
    assert len(etlonomy.__version__.split('.')) == 3
