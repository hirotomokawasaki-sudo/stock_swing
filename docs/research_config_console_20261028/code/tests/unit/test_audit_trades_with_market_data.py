from scripts.audit_trades_with_market_data import analyze_tracker_integrity, build_tracker_open_positions


def test_build_tracker_open_positions_aggregates_duplicate_lots():
    trades = [
        {"symbol": "AAPL", "status": "open", "qty": 10, "entry_price": 180.0},
        {"symbol": "AAPL", "status": "open", "qty": 5, "entry_price": 210.0},
        {"symbol": "MSFT", "status": "closed", "qty": 3, "entry_price": 400.0},
    ]

    positions = build_tracker_open_positions(trades)

    assert positions["AAPL"]["qty"] == 15
    assert positions["AAPL"]["trade_count"] == 2
    assert positions["AAPL"]["avg_entry_price"] == 190.0
    assert "MSFT" not in positions


def test_analyze_tracker_integrity_detects_duplicate_and_tracker_only_symbols():
    trades = [
        {"symbol": "AAPL", "status": "open", "qty": 10, "entry_price": 180.0},
        {"symbol": "AAPL", "status": "open", "qty": 10, "entry_price": 180.0},
        {"symbol": "TSLA", "status": "open", "qty": 4, "entry_price": 250.0},
    ]
    broker_positions = [
        {"symbol": "AAPL", "qty": "10", "avg_entry_price": "180.0"},
        {"symbol": "NVDA", "qty": "2", "avg_entry_price": "900.0"},
    ]

    result = analyze_tracker_integrity(trades, broker_positions)

    assert result["multi_lot_symbols"] == [{"symbol": "AAPL", "trade_count": 2, "tracker_qty": 20}]
    assert result["tracker_only"] == ["TSLA"]
    assert result["broker_only"] == ["NVDA"]
    assert result["mismatches"][0]["symbol"] == "AAPL"
    assert result["mismatches"][0]["tracker_qty"] == 20
    assert result["mismatches"][0]["broker_qty"] == 10


def test_analyze_tracker_integrity_returns_clean_result_when_positions_match():
    trades = [
        {"symbol": "AAPL", "status": "open", "qty": 10, "entry_price": 180.0},
    ]
    broker_positions = [
        {"symbol": "AAPL", "qty": "10", "avg_entry_price": "180.0"},
    ]

    result = analyze_tracker_integrity(trades, broker_positions)

    assert result["multi_lot_symbols"] == []
    assert result["mismatches"] == []
    assert result["tracker_only"] == []
    assert result["broker_only"] == []
    assert result["consistent"] == ["AAPL"]


def test_analyze_tracker_integrity_ignores_sub_pct_cost_basis_rounding():
    """Regression test (2026-08-15 fix): weighted-avg cost-basis rounding on
    higher-priced stocks/ETFs produces sub-$1 absolute deltas that are well
    under the 5% relative threshold and must NOT be flagged as mismatches.
    Prior to the fix, an absolute $0.01 threshold flagged nearly every
    multi-lot position above ~$10/share as a false-positive "mismatch",
    causing stock_swing_daily_audit to report ~10-20 spurious integrity
    issues every day for weeks even though qty matched exactly.
    """
    trades = [
        {"symbol": "ANET", "status": "open", "qty": 395, "entry_price": 196.05},
        {"symbol": "AVGO", "status": "open", "qty": 176, "entry_price": 423.98},
        {"symbol": "ASML", "status": "open", "qty": 23, "entry_price": 1838.94},
    ]
    broker_positions = [
        # ANET: $0.11 absolute delta (~0.06%) — rounding noise, not a mismatch
        {"symbol": "ANET", "qty": "395", "avg_entry_price": "196.16"},
        # AVGO: $0.93 absolute delta (~0.22%) — rounding noise, not a mismatch
        {"symbol": "AVGO", "qty": "176", "avg_entry_price": "423.05"},
        # ASML: $0.75 absolute delta (~0.04%) — rounding noise, not a mismatch
        {"symbol": "ASML", "qty": "23", "avg_entry_price": "1838.19"},
    ]

    result = analyze_tracker_integrity(trades, broker_positions)

    assert result["mismatches"] == []
    assert sorted(result["consistent"]) == ["ANET", "ASML", "AVGO"]


def test_analyze_tracker_integrity_still_flags_real_price_mismatch():
    """A genuine >5% cost-basis divergence (e.g. missed corporate action,
    data entry error) must still be caught after the relative-threshold fix.
    """
    trades = [
        {"symbol": "XYZ", "status": "open", "qty": 100, "entry_price": 100.0},
    ]
    broker_positions = [
        {"symbol": "XYZ", "qty": "100", "avg_entry_price": "110.0"},  # 10% delta
    ]

    result = analyze_tracker_integrity(trades, broker_positions)

    assert len(result["mismatches"]) == 1
    assert result["mismatches"][0]["symbol"] == "XYZ"
