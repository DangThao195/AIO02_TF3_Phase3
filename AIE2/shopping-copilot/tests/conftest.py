# tests/conftest.py — pytest configuration for Shopping Copilot graph tests.
import pytest


def pytest_configure(config):
    """Enable asyncio mode globally."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
