import importlib.metadata


def test_package_is_installed():
    """CI walking-skeleton check: confirms the extractor package builds and installs
    correctly before any feature modules exist."""
    assert importlib.metadata.version("lab-report-extractor") == "0.1.0"