import pytest


def pytest_addoption(parser):
    try:
        parser.addoption("--headed", action="store_true", default=False,
                         help="Run browser in headed (visible) mode")
    except Exception:
        pass
