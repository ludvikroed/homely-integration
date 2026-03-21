"""Pytest fixtures for Homely tests."""

from __future__ import annotations

import pytest

from tests.common import (
    LOCATION_RESPONSE,
    TOKEN_RESPONSE,
    build_config_entry,
    copy_location_data,
    copy_updated_location_data,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the custom component from this repository."""
    yield


@pytest.fixture
def token_response():
    """Return a standard token response."""
    return dict(TOKEN_RESPONSE)


@pytest.fixture
def location_response():
    """Return available locations for the mocked account."""
    return list(LOCATION_RESPONSE)


@pytest.fixture
def location_data():
    """Return a fresh copy of the default location payload."""
    return copy_location_data()


@pytest.fixture
def updated_location_data():
    """Return a fresh copy of an updated location payload."""
    return copy_updated_location_data()


@pytest.fixture
def mock_config_entry():
    """Return a default Homely config entry."""
    return build_config_entry()
