from datetime import datetime

import pytest

from stock_swing.sources import massive_client as massive_module
from stock_swing.sources.massive_client import MassiveBar, MassiveClient


def test_massive_bar_dataclass_imports_without_sdk():
    bar = MassiveBar(
        timestamp=datetime(2026, 6, 1, 12, 0),
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=100,
    )
    assert bar.close == 1.5


def test_massive_client_raises_clear_import_error_without_sdk(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    monkeypatch.setattr(massive_module, "_MassiveRESTClient", None)

    with pytest.raises(ImportError, match="massive SDK is required"):
        MassiveClient()


def test_massive_client_pool_maxsize_patched(monkeypatch):
    """R7-v2 / H8: MassiveClient patches urllib3 pool maxsize to suppress
    'Connection pool is full' warnings seen in logs (07-08 incident).
    """
    from unittest.mock import MagicMock, patch

    # Simulate _MassiveRESTClient with a urllib3-like pool manager
    fake_pool_kw: dict = {}
    fake_pool_mgr = MagicMock()
    fake_pool_mgr.connection_pool_kw = fake_pool_kw

    fake_sdk_client = MagicMock()
    fake_sdk_client.client = fake_pool_mgr

    fake_rest_client_cls = MagicMock(return_value=fake_sdk_client)

    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    monkeypatch.setattr(massive_module, "_MassiveRESTClient", fake_rest_client_cls)

    client = MassiveClient()

    # After init, maxsize must be ≥ 10
    assert fake_pool_kw.get("maxsize", 0) >= 10, (
        "connection_pool_kw['maxsize'] must be ≥ 10 to avoid pool-full warnings"
    )


def test_massive_client_pool_patch_is_safe_when_no_pool_attr(monkeypatch):
    """Pool patch must not crash when SDK client has no .client attribute."""
    from unittest.mock import MagicMock

    fake_sdk_client = MagicMock(spec=[])  # no attributes

    fake_rest_client_cls = MagicMock(return_value=fake_sdk_client)

    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    monkeypatch.setattr(massive_module, "_MassiveRESTClient", fake_rest_client_cls)

    # Should not raise
    client = MassiveClient()
    assert client is not None
