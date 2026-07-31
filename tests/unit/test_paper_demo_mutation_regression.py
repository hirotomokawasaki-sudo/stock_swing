"""Mutation-killing regression tests for 2026-07-31 fixes.

These tests run paper_demo.main() through the real production path and are
designed to FAIL when the bug is reverted (i.e., they kill the mutation).

Fix 1: broker.get_account() → equity variable reuse
  - Verifies that day_start_snapshot.json is written with non-null day_start_equity
    when the broker has ONLY fetch_account() (no get_account()).
  - KILLS mutation: if we revert to broker.get_account(), AttributeError is caught
    silently → equity=None → day_start_equity written as null.

Fix 2: position_limit_pct uses alloc_config multiplier not effective_position_notional_pct
  - Verifies that a buy for a symbol with existing position at $42K is NOT blocked
    (new limit ~$78K), using actual paper_demo submit loop.
  - KILLS mutation: if we revert to effective_position_notional_pct(),
    limit = 0.08 * 0.5 * equity ≈ $39K < $42K existing → buy blocked → submitted=0.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# Module-level stubs for heavy optional deps
# ---------------------------------------------------------------------------
massive_stub = types.ModuleType("massive")
massive_stub.RESTClient = object
sys.modules.setdefault("massive", massive_stub)

from stock_swing.cli import paper_demo  # noqa: E402
from stock_swing.cli.cron_summary import CRON_SUMMARY_PREFIX  # noqa: E402
from stock_swing.core.types import CanonicalRecord  # noqa: E402
from stock_swing.feature_engine.base_feature import FeatureResult  # noqa: E402
from stock_swing.strategy_engine.base_strategy import CandidateSignal  # noqa: E402
from stock_swing.risk.entry_filter import EntryFilterResult  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _guardrail_cfg(tmp_path: Path) -> Path:
    cfg = tmp_path / "config" / "guardrails" / "autonomous_stop.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("paper_warning_only: false\nrules: {}\n", encoding="utf-8")
    return cfg


def _set_common_patches(monkeypatch, tmp_path: Path, broker_cls) -> None:
    """Patch paper_demo fixtures shared by both tests."""
    monkeypatch.setattr(paper_demo, "project_root", tmp_path)
    monkeypatch.setattr(paper_demo, "should_skip_non_market_day", lambda: (False, ""))
    monkeypatch.setattr(paper_demo, "read_runtime_mode", lambda root: "paper")
    monkeypatch.setattr(
        paper_demo, "read_ledger_quality_gate",
        lambda root: {"current_status": "VALID", "enforce_invalid_ledger_blocks_live_ready": False},
    )
    monkeypatch.setattr(paper_demo.MarketCalendar, "is_market_open", lambda now=None: (True, "open"))
    monkeypatch.setattr(paper_demo.MarketCalendar, "is_regular_market_hours", lambda now=None: (True, "open"))
    monkeypatch.setenv("BROKER_API_KEY", "key")
    monkeypatch.setenv("BROKER_API_SECRET", "secret")
    monkeypatch.setenv("BROKER_BASE_URL", "https://paper.example")

    class _KillSwitch:
        def __init__(self, state_file): pass
        def check(self): return None

    monkeypatch.setattr(paper_demo, "KillSwitch", _KillSwitch)
    monkeypatch.setattr(paper_demo, "BrokerClient", broker_cls)
    monkeypatch.setattr(paper_demo, "get_permanent_block_summary", lambda **kwargs: [])
    monkeypatch.setattr(paper_demo, "prioritize_buy_signals", lambda s, *a, **kw: s)
    monkeypatch.setattr(paper_demo, "prioritize_buy_signals_v2", lambda s, *a, **kw: s)

    _guardrail_cfg(tmp_path)


def _no_signals(self, *args, **kwargs):
    return []


def _generic_bars_fetcher():
    class _Fetcher:
        def __init__(self, *a, **kw): pass
        def fetch_bars(self, symbol, timeframe="1Day", limit=20):
            rec = CanonicalRecord(
                record_id="r1", schema_version="v1", source="massive", source_type="bars",
                symbol=symbol, event_type="bar", event_time=datetime.now(timezone.utc),
                as_of="2026-07-31", ingested_at=datetime.now(timezone.utc),
                timezone="UTC", payload_version="v1",
                payload={"close": 150.0},
            )
            return [rec], "massive"
    return _Fetcher


def _momentum_result_for(symbol: str):
    def _compute(self, records):
        return [FeatureResult(
            feature_name="price_momentum", symbol=symbol,
            computed_at=datetime.now(timezone.utc),
            values={"momentum": 0.08, "trend": "up", "bars_used": 20, "latest_close": 150.0},
        )]
    return _compute


def _passthrough_filter(self, decisions, *a, **kw):
    """Entry filter stub that passes all decisions through unchanged."""
    return EntryFilterResult(passed=list(decisions), blocked=[])


# ===========================================================================
# TEST 1: broker.get_account() mutation-killer
# ===========================================================================

class _BrokerNoGetAccount:
    """Broker stub intentionally WITHOUT get_account() — mirrors real BrokerClient."""
    def __init__(self, *a, **kw):
        self.base_url = "https://paper.example"

    def fetch_account(self):
        # Real equity value — should be captured into day_start_snapshot
        return SimpleNamespace(payload={
            "status": "ACTIVE",
            "equity": "987573.76",
            "buying_power": "1944159.53",
        })

    def fetch_positions(self):
        return SimpleNamespace(payload=[])


def test_paper_demo_day_start_equity_set_without_get_account(
    monkeypatch, tmp_path, capsys
):
    """Mutation-killer for Fix 1: broker.get_account() → equity variable reuse.

    When the broker has NO get_account() method (matching real BrokerClient),
    day_start_snapshot.json must be written with day_start_equity = 987573.76.

    KILLS mutation: reverting to broker.get_account() causes AttributeError
    → equity captured as None → day_start_equity written as null.
    """
    _set_common_patches(monkeypatch, tmp_path, _BrokerNoGetAccount)

    def _momentum(self, records):
        return [FeatureResult(
            feature_name="price_momentum", symbol="AAPL",
            computed_at=datetime.now(timezone.utc),
            values={"momentum": 0.05, "trend": "up", "bars_used": 20, "latest_close": 150.0},
        )]

    monkeypatch.setattr("stock_swing.sources.hybrid_data_fetcher.HybridDataFetcher", _generic_bars_fetcher())
    monkeypatch.setattr(paper_demo.PriceMomentumFeature, "compute", _momentum)
    monkeypatch.setattr(paper_demo.MacroRegimeFeature, "compute", _no_signals)
    monkeypatch.setattr(paper_demo.BreakoutMomentumStrategy, "generate", _no_signals)
    monkeypatch.setattr(paper_demo.EventSwingStrategy, "generate", _no_signals)
    monkeypatch.setattr(paper_demo.SimpleExitV2Strategy, "generate", _no_signals)
    monkeypatch.setattr(paper_demo.EntryFilterEngine, "filter", _passthrough_filter)

    monkeypatch.setattr(sys, "argv", [
        "paper_demo", "--dry-run", "--cron-summary-json", "--symbols", "AAPL",
    ])

    paper_demo.main()

    # Verify snapshot was written with non-null equity
    snap_path = tmp_path / "data" / "guardrails" / "day_start_snapshot.json"
    assert snap_path.exists(), "day_start_snapshot.json was not written"

    snap = json.loads(snap_path.read_text())
    assert snap["day_start_equity"] is not None, (
        f"day_start_equity is null — broker.get_account() bug was NOT fixed. "
        f"Snapshot: {snap}"
    )
    assert snap["day_start_equity"] == pytest.approx(987573.76), (
        f"day_start_equity={snap['day_start_equity']} expected 987573.76. "
        "Fix may not be wiring fetch_account() equity into snapshot."
    )
    assert snap["source"] == "broker_api", (
        f"source={snap['source']} expected broker_api. "
        "Equity was not obtained from broker — falling back to tracker_estimate."
    )


# ===========================================================================
# TEST 2: allocation position_limit_pct mutation-killer
# ===========================================================================

_EXISTING_MARKET_VALUE = 42_000.0  # above old limit ($39.2K), below new limit ($78.4K)
_EQUITY = 980_000.0
# Old limit: DEFAULT_MAX_POSITION_NOTIONAL_PCT(0.08) * STOCK_MULTIPLIER(0.5) * equity = $39.2K
# New limit: DEFAULT_MAX_POSITION_NOTIONAL_PCT(0.08) * alloc_config.stock_new_buy_multiplier(1.0) * equity = $78.4K


# ---------------------------------------------------------------------------
# TEST 2a: allocation limit formula 直接検証（mutation-killer）
# ---------------------------------------------------------------------------
def test_allocation_limit_formula_new_vs_old():
    """Formula arithmetic validation for Fix 2.

    Verifies that the new position limit formula gives 2× the old formula for
    stocks (correct arithmetic), and that the boundary condition is correctly set:
    - Old formula ($39.2K) would block an existing $42K position
    - New formula ($78.4K) would not block it

    This test validates the correctness of the constants involved.
    Note: mutation in paper_demo.py is killed by test_paper_demo_source_uses_alloc_config_not_effective_pct
    (code-inspection test), not by this arithmetic test.
    """
    from stock_swing.risk.position_sizing import (
        effective_position_notional_pct,
        DEFAULT_MAX_POSITION_NOTIONAL_PCT,
        STOCK_POSITION_SIZE_MULTIPLIER,
    )
    from stock_swing.risk.allocation_config import read_allocation_config
    from pathlib import Path

    yaml_path = Path(__file__).parents[2] / "config" / "strategy" / "portfolio_allocation.yaml"
    alloc_config = read_allocation_config(yaml_path)  # stock_new_buy_multiplier=1.0
    is_etf = False  # AAPL is a stock

    # The OLD (buggy) formula:
    old_pct = effective_position_notional_pct(is_etf)  # False treated as symbol
    old_limit = old_pct * _EQUITY

    # The NEW (fixed) formula:
    base_pct = float(alloc_config.stock_new_buy_multiplier if not is_etf else alloc_config.etf_new_buy_multiplier)
    new_pct = DEFAULT_MAX_POSITION_NOTIONAL_PCT * base_pct
    new_limit = new_pct * _EQUITY

    # Old limit is half of default due to STOCK_POSITION_SIZE_MULTIPLIER=0.5
    assert old_pct == pytest.approx(DEFAULT_MAX_POSITION_NOTIONAL_PCT * STOCK_POSITION_SIZE_MULTIPLIER), (
        f"Old formula gives {old_pct:.4f} — expected "
        f"{DEFAULT_MAX_POSITION_NOTIONAL_PCT} * {STOCK_POSITION_SIZE_MULTIPLIER} = "
        f"{DEFAULT_MAX_POSITION_NOTIONAL_PCT * STOCK_POSITION_SIZE_MULTIPLIER:.4f}"
    )
    # New limit is the full DEFAULT (multiplier=1.0)
    assert new_pct == pytest.approx(DEFAULT_MAX_POSITION_NOTIONAL_PCT), (
        f"New formula gives {new_pct:.4f} — expected {DEFAULT_MAX_POSITION_NOTIONAL_PCT}"
    )
    # New limit must be strictly greater than old limit (2× for stocks)
    assert new_limit > old_limit, (
        f"New limit ${new_limit:,.0f} must exceed old limit ${old_limit:,.0f}"
    )
    # OLD FORMULA WOULD BLOCK: existing $42K > old limit $39.2K
    assert _EXISTING_MARKET_VALUE > old_limit, (
        f"Test invariant: existing ${_EXISTING_MARKET_VALUE:,.0f} must exceed old limit ${old_limit:,.0f}"
    )
    # NEW FORMULA DOES NOT BLOCK: existing $42K < new limit $78.4K
    assert _EXISTING_MARKET_VALUE < new_limit, (
        f"Test invariant: existing ${_EXISTING_MARKET_VALUE:,.0f} must be below new limit ${new_limit:,.0f}"
    )


# ---------------------------------------------------------------------------
# TEST 2b: paper_demo 内の limit 計算が alloc_config 利用をコード檢査で確認
# ---------------------------------------------------------------------------
def test_paper_demo_source_uses_alloc_config_not_effective_pct():
    """Code-inspection mutation-killer: verifies that paper_demo.py contains
    the fixed formula and NOT the old formula at the allocation check site.

    KILLS mutation: if code is reverted to effective_position_notional_pct(is_etf),
    this test fails immediately.
    """
    import pathlib
    src = pathlib.Path(__file__).parents[2] / "src" / "stock_swing" / "cli" / "paper_demo.py"
    code = src.read_text(encoding="utf-8")

    # The fixed line must be present
    fixed_line = "position_limit_pct = DEFAULT_MAX_POSITION_NOTIONAL_PCT * _base_pct"
    assert fixed_line in code, (
        f"Fixed formula not found in paper_demo.py.\n"
        f"Expected: '{fixed_line}'\n"
        f"If the mutation was reverted, effective_position_notional_pct(is_etf) is being used "
        f"(old STOCK_POSITION_SIZE_MULTIPLIER=0.5 halves the limit to ~$39.2K, "
        f"blocking any existing-position BUY above that threshold)."
    )

    # The old (buggy) formula must NOT be present at the allocation check site
    # (allow it in comments/docstrings but not as an assignment)
    import re
    old_formula_assignment = re.compile(
        r"^\s*position_limit_pct\s*=\s*effective_position_notional_pct", re.MULTILINE
    )
    match = old_formula_assignment.search(code)
    assert match is None, (
        f"Old formula found in paper_demo.py at char {match.start()}.\n"
        f"Reverted code: '{match.group()}'\n"
        "This is the allocation bug: STOCK_POSITION_SIZE_MULTIPLIER=0.5 halves "
        "the position limit from $78K to $39K, blocking all BUYs for existing positions."
    )


class _BrokerWithExistingPositionAndOrder:
    """Broker stub with AAPL at $42K. Records submitted order IDs."""
    submitted_orders: list[dict]

    def __init__(self, *a, **kw):
        self.base_url = "https://paper.example"
        _BrokerWithExistingPositionAndOrder.submitted_orders = []

    def fetch_account(self):
        return SimpleNamespace(payload={
            "status": "ACTIVE",
            "equity": str(_EQUITY),
            "buying_power": "1944159.53",
        })

    def fetch_positions(self):
        # AAPL: market_value $42K — above old limit $39.2K, below new limit $78.4K
        return SimpleNamespace(payload=[{
            "symbol": "AAPL",
            "qty": "280",
            "side": "long",
            "market_value": str(_EXISTING_MARKET_VALUE),
            "unrealized_pl": "200.0",
            "current_price": "150.0",
            "avg_entry_price": "148.57",
        }])

    def fetch_latest_quote(self, symbol: str):
        return SimpleNamespace(payload={
            "ap": 150.05,
            "bp": 149.95,
            "t": datetime.now(timezone.utc).isoformat(),
        })

    def submit_order(self, symbol, side, order_type, qty, time_in_force,
                     limit_price=None, extended_hours=False):
        oid = f"order-{symbol}-{side}-{qty}"
        _BrokerWithExistingPositionAndOrder.submitted_orders.append({
            "symbol": symbol, "side": side, "qty": qty, "id": oid,
        })
        return SimpleNamespace(payload={"id": oid, "status": "accepted"})

    def get_order(self, order_id):
        return SimpleNamespace(payload={
            "id": order_id, "status": "accepted", "filled_qty": "0",
        })

    def fetch_orders(self, *a, **kw):
        return SimpleNamespace(payload=[])

    def fetch_position(self, symbol):
        raise Exception("no position")

    def cancel_order(self, order_id):
        return {}


def test_paper_demo_allocation_uses_alloc_config_not_legacy_multiplier(
    monkeypatch, tmp_path, capsys
):
    """Mutation-killer for Fix 2: position_limit_pct uses alloc_config not effective_position_notional_pct.

    Runs through paper_demo WITHOUT --dry-run so the actual submit loop executes.
    Setup: AAPL existing = $42K.
    Old limit: 0.08 * 0.5 * $980K = $39.2K < $42K → buy immediately blocked (allocation_blocked).
    New limit: 0.08 * 1.0 * $980K = $78.4K > $42K → buy may proceed.

    We assert allocation_blocked == 0 (AAPL was not blocked by the position limit).

    KILLS mutation: reverting to effective_position_notional_pct() →
    position limit $39.2K < existing $42K → allocation_blocked=1 → assertion FAILS.
    """
    _set_common_patches(monkeypatch, tmp_path, _BrokerWithExistingPositionAndOrder)

    def _buy_aapl_signal(self, features):
        return [CandidateSignal(
            strategy_id="breakout_momentum_v1",
            symbol="AAPL",
            action="buy",
            signal_strength=0.95,
            generated_at=datetime.now(timezone.utc),
            time_horizon="3d",
            confidence=0.9,
            reasoning="mutation test: allocation limit check",
            metadata={"latest_close": 150.0},
        )]

    monkeypatch.setattr(
        "stock_swing.sources.hybrid_data_fetcher.HybridDataFetcher",
        _generic_bars_fetcher(),
    )
    monkeypatch.setattr(paper_demo.PriceMomentumFeature, "compute",
                        _momentum_result_for("AAPL"))
    monkeypatch.setattr(paper_demo.MacroRegimeFeature, "compute", _no_signals)
    monkeypatch.setattr(paper_demo.BreakoutMomentumStrategy, "generate", _buy_aapl_signal)
    monkeypatch.setattr(paper_demo.EventSwingStrategy, "generate", _no_signals)
    monkeypatch.setattr(paper_demo.SimpleExitV2Strategy, "generate", _no_signals)
    monkeypatch.setattr(paper_demo.EntryFilterEngine, "filter", _passthrough_filter)

    # Mock _calculate_position_size to return 100 shares so the buy passes preflight
    # (real ATR computation would need market data; we bypass that here).
    # 100 shares × $150 = $15K additional → total = $42K + $15K = $57K
    # New limit ($78K) > $57K → NOT blocked (correct)
    # Old limit ($39.2K) < $42K existing → blocked (mutation killed)
    from stock_swing.execution.paper_executor import PaperExecutor
    def _mock_size(self, decision, *, market_regime="neutral", exposure_cap_override=None):
        return 100, {"final_shares": 100, "shares_by_risk": 100, "shares_by_notional": 100,
                     "skip_reason": None, "latest_close": 150.0,
                     "max_position_notional_usd": 78400.0,
                     "current_price": 150.0, "regime_used": "cautious",
                     "asset_class_used": "stock", "applied_constraint": "risk"}
    monkeypatch.setattr(PaperExecutor, "_calculate_position_size", _mock_size)

    # NO --dry-run: the submit loop with allocation check must execute.
    monkeypatch.setattr(sys, "argv", [
        "paper_demo",
        "--cron-summary-json",
        "--symbols", "AAPL",
    ])

    paper_demo.main()

    out = capsys.readouterr().out
    summary_lines = [l for l in out.splitlines() if l.startswith(CRON_SUMMARY_PREFIX)]
    assert summary_lines, f"No cron summary.\nstdout:\n{out[-2000:]}"
    summary = json.loads(summary_lines[-1].split("=", 1)[1])

    allocation_blocked = summary.get("allocation_blocked", 0)
    assert allocation_blocked == 0, (
        f"allocation_blocked={allocation_blocked} — AAPL (existing=${_EXISTING_MARKET_VALUE:,.0f}) "
        f"was blocked by position limit. "
        f"Old limit would be ~${_EQUITY * 0.08 * 0.5:,.0f}; new limit ~${_EQUITY * 0.08:,.0f}. "
        "With fix reverted, existing $42K > old limit $39.2K → blocked (mutation killed). "
        "If this assertion passes with the fix, the position was correctly NOT blocked."
    )
