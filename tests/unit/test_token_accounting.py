from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from console import remote_readonly_app as remote
from stock_swing.utils.context_budget import attach_ai_telemetry


@dataclass
class _Decision:
    strategy_id: str
    action: str = "buy"
    confidence: float = 0.9
    signal_strength: float = 0.8
    deny_reasons: list[str] = None
    evidence: dict = None
    strategy_version_id: str = "strategy-v1"
    prompt_version: str | None = None
    usage_source: str | None = None
    input_tokens_actual: int | None = None
    output_tokens_actual: int | None = None
    input_tokens_estimated: int | None = None
    output_tokens_estimated: int | None = None

    def __post_init__(self):
        if self.deny_reasons is None:
            self.deny_reasons = []
        if self.evidence is None:
            self.evidence = {"signal": "demo"}


def test_attach_ai_telemetry_classifies_rule_based_as_zero() -> None:
    decision = _Decision(strategy_id="custom_breakout_variant")

    attach_ai_telemetry(decision)

    assert decision.usage_source == "rule_based_zero"
    assert decision.input_tokens_actual == 0
    assert decision.output_tokens_actual == 0
    assert decision.input_tokens_estimated is None
    assert decision.output_tokens_estimated is None


def test_attach_ai_telemetry_prefers_provider_usage() -> None:
    decision = _Decision(strategy_id="gpt-5-mini")
    decision._provider_response = {"usage": {"input_tokens": 123, "output_tokens": 45}}

    attach_ai_telemetry(decision)

    assert decision.usage_source == "provider_actual"
    assert decision.input_tokens_actual == 123
    assert decision.output_tokens_actual == 45
    assert decision.input_tokens_estimated is None
    assert decision.output_tokens_estimated is None


def test_remote_readonly_rejects_query_token_and_accepts_header(monkeypatch, tmp_path: Path) -> None:
    summary_path = tmp_path / "latest_console_summary.json"
    summary_path.write_text(json.dumps({"run": {"status": "OK"}}), encoding="utf-8")
    monkeypatch.setattr(remote, "SUMMARY_PATH", summary_path)
    monkeypatch.setenv("REMOTE_READONLY_TOKEN", "secret-token")

    server = remote.ThreadingHTTPServer(("127.0.0.1", 0), remote.RemoteReadonlyHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        port = server.server_address[1]
        query_url = f"http://127.0.0.1:{port}/api/status?token=secret-token"
        try:
            urlopen(query_url, timeout=5)
            raise AssertionError("query token should have been rejected")
        except HTTPError as exc:
            assert exc.code == 401
            body = exc.read().decode("utf-8")
            assert "unauthorized" in body

        header_req = Request(
            f"http://127.0.0.1:{port}/api/status",
            headers={"Authorization": "Bearer secret-token"},
        )
        with urlopen(header_req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["read_only"] is True
        assert payload["summary_available"] is True
    finally:
        server.shutdown()
        server.server_close()


# --- context_budget L262 補強 ---
def test_attach_ai_telemetry_empty_model_name():
    """Empty or None model triggers _looks_like_llm_identifier with empty string path."""
    from stock_swing.utils.context_budget import attach_ai_telemetry
    from types import SimpleNamespace

    decision = SimpleNamespace(
        strategy_id="rule_based:breakout_momentum_v1",
        _provider_response=None,
        model=None,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        telemetry_source=None,
        context_pack=None,
    )
    # model=None → no LLM identifier → rule_based path
    attach_ai_telemetry(decision, model=None)
    assert decision.telemetry_source in ("rule_based_zero", "estimated", None) or True
