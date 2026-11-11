"""Shared fixtures: Home Assistant's test harness with this custom integration enabled."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/mdtronix_nivas in every test."""
    yield
