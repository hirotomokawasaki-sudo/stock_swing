import json

import pytest

from scripts import check_corporate_actions as corporate_actions


def test_get_tracker_open_uses_quantity_weighted_average_for_multiple_lots(
    tmp_path, monkeypatch
):
    state_path = tmp_path / "pnl_state.json"
    state_path.write_text(
        json.dumps(
            {
                "trades": [
                    {
                        "symbol": "CRWD",
                        "status": "open",
                        "qty": 167,
                        "entry_price": 220.51,
                    },
                    {
                        "symbol": "CRWD",
                        "status": "open",
                        "qty": 123,
                        "entry_price": 246.015,
                    },
                    {
                        "symbol": "CRWD",
                        "status": "closed",
                        "qty": 999,
                        "entry_price": 1.0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(corporate_actions, "PNL_STATE_PATH", state_path)

    positions = corporate_actions._get_tracker_open()

    assert positions["CRWD"]["qty"] == pytest.approx(290)
    assert positions["CRWD"]["entry_price"] == pytest.approx(
        (167 * 220.51 + 123 * 246.015) / 290
    )


def test_detect_anomalies_does_not_flag_multi_lot_weighted_average(monkeypatch):
    monkeypatch.setattr(corporate_actions, "_load_known_actions", lambda: set())
    monkeypatch.setattr(
        corporate_actions,
        "_get_broker_positions",
        lambda: [
            {
                "symbol": "CRWD",
                "qty": "290",
                "avg_entry_price": "232.26",
                "current_price": "245.59",
            }
        ],
    )
    monkeypatch.setattr(
        corporate_actions,
        "_get_tracker_open",
        lambda: {
            "CRWD": {
                "qty": 290,
                "entry_price": (167 * 220.51 + 123 * 246.015) / 290,
            }
        },
    )

    assert corporate_actions.detect_anomalies() == []


def test_detect_anomalies_still_flags_material_weighted_cost_difference(monkeypatch):
    monkeypatch.setattr(corporate_actions, "_load_known_actions", lambda: set())
    monkeypatch.setattr(
        corporate_actions,
        "_get_broker_positions",
        lambda: [
            {
                "symbol": "XYZ",
                "qty": "20",
                "avg_entry_price": "110",
                "current_price": "112",
            }
        ],
    )
    monkeypatch.setattr(
        corporate_actions,
        "_get_tracker_open",
        lambda: {"XYZ": {"qty": 20, "entry_price": 100}},
    )

    anomalies = corporate_actions.detect_anomalies()

    assert len(anomalies) == 1
    assert anomalies[0]["symbol"] == "XYZ"
    assert anomalies[0]["suspected_action"] == "unknown_price_discrepancy"
