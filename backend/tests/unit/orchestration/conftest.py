"""Fixtures for the orchestration tests (the shared world lives in tests/support)."""

import pytest
from agent_world import World, build_world


@pytest.fixture
def world() -> World:
    return build_world()
