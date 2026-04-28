"""Integration tests for delegation."""

import pytest


async def test_delegation_manager():
    """Test DelegationManager."""
    from core.delegation.manager import DelegationManager
    manager = DelegationManager()
    assert manager is not None


async def test_worker():
    """Test Worker."""
    from core.delegation.worker import Worker
    assert Worker is not None


async def test_worker_session():
    """Test WorkerSession."""
    from core.delegation.session import WorkerSession
    assert WorkerSession is not None
