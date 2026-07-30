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
