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
