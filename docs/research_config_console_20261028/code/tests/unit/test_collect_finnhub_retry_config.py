"""Tests for collect_finnhub's FinnhubClient retry/timeout configuration.

Regression (2026-08-07): a cron run showed 6/44 symbols
(MSFT/ASML/SMCI/FTNT/NBIS/RBRK) failing as api_error/timeout, dropping
source_sla coverage to 86.4% (required >=99.5%) and tripping the console
self-check's critical 'source_sla' evidence gate even though ledger and
broker/tracker state were fine. The previous RetryConfig
(max_attempts=2, timeout=5.0) was tight for Finnhub's company-news
endpoint. This locks in the more resilient config
(max_attempts=3, timeout=10.0) so a future regression to the old tight
values is caught.
"""
from __future__ import annotations


def test_collect_finnhub_uses_resilient_retry_config(monkeypatch, tmp_path):
    from stock_swing.cli import collect_data as module
    import stock_swing.cli.paper_demo as paper_demo

    monkeypatch.setattr(module, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "_load_env", lambda _path: None)
    monkeypatch.setenv("FINNHUB_API_KEY", "test_key")

    captured: dict = {}

    class _FakeFinnhubClient:
        def __init__(self, api_key, retry_config=None):
            captured["retry_config"] = retry_config

        def fetch_basic_financials(self, symbol):
            raise RuntimeError("not needed for this test")

        def fetch_company_news(self, symbol, from_date, to_date):
            raise RuntimeError("not needed for this test")

    monkeypatch.setattr(module, "FinnhubClient", _FakeFinnhubClient)

    from stock_swing.core.path_manager import PathManager
    from stock_swing.storage.stage_store import StageStore

    module.collect_finnhub(["AAPL"], StageStore(PathManager(tmp_path)))

    retry_config = captured.get("retry_config")
    assert retry_config is not None, "FinnhubClient must be constructed with a retry_config"
    assert retry_config.max_attempts >= 3, (
        f"max_attempts regressed to {retry_config.max_attempts} "
        "(2026-08-07 fix requires >=3 to tolerate transient company-news failures)"
    )
    assert retry_config.timeout >= 10.0, (
        f"timeout regressed to {retry_config.timeout}s "
        "(2026-08-07 fix requires >=10.0s per-attempt timeout)"
    )
