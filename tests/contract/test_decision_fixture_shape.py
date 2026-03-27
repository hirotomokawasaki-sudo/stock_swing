import json
from pathlib import Path


def test_decision_fixture_has_required_keys() -> None:
    path = Path(__file__).resolve().parents[1] / "fixtures" / "decisions" / "decision_sample.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"decision_id", "mode", "strategy_id", "symbol", "action", "risk_state"}
    assert required.issubset(payload.keys())
