#!/usr/bin/env python3
"""End-to-end paper trading demo.

Full pipeline:
  broker bars -> normalize -> momentum features -> strategy signals
  -> risk validation -> decision engine -> paper order submission
  -> reconciliation -> audit log -> summary report

Usage:
    python -m stock_swing.cli.paper_demo --dry-run
    python -m stock_swing.cli.paper_demo --allow-outside-hours
    python -m stock_swing.cli.paper_demo --symbols AAPL,MSFT --min-momentum 0.02
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root / "src"))
logger = logging.getLogger(__name__)


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(project_root / ".env")

from stock_swing.core.path_manager import PathManager
from stock_swing.core.run_context import RunContext, attach_run_context
from stock_swing.core.runtime import RuntimeMode, RuntimeModeError, read_runtime_mode, read_ledger_quality_gate, read_circuit_breaker_config
from stock_swing.core.types import CanonicalRecord
from stock_swing.cli.cron_summary import emit_cron_summary
from stock_swing.decision_engine.decision_engine import DecisionEngine, DecisionRecord
from stock_swing.decision_engine.risk_validator import RiskValidator
from stock_swing.execution.paper_executor import OrderSubmission, PaperExecutor
from stock_swing.execution.reconciler import Reconciler
from stock_swing.risk.entry_filter import EntryFilterConfig, EntryFilterEngine, get_permanent_block_summary
from stock_swing.risk.open_shock_cooldown import apply_open_shock_cooldown
from stock_swing.risk.portfolio_allocator import PortfolioAllocator
from stock_swing.risk.allocation_config import (
    get_etf_symbols_from_registry,
    read_allocation_config,
    read_symbol_registry,
)
from stock_swing.risk.position_sizing import DEFAULT_MAX_POSITION_NOTIONAL_PCT
from stock_swing.feature_engine.macro_regime_feature import MacroRegimeFeature
from stock_swing.feature_engine.price_momentum_feature import PriceMomentumFeature
from stock_swing.feature_engine.intraday_momentum_feature import IntradayMomentumFeature
from stock_swing.normalization.broker_normalizer import BrokerNormalizer
from stock_swing.safety.audit_logger import AuditLevel, AuditLogger
from stock_swing.safety.kill_switch import KillSwitch
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.storage.stage_store import StageStore
from stock_swing.strategy_engine.breakout_momentum_strategy import BreakoutMomentumStrategy
from stock_swing.strategy_engine.event_swing_strategy import EventSwingStrategy
from stock_swing.strategy_engine.simple_exit_strategy import SimpleExitStrategy
from stock_swing.strategy_engine.simple_exit_v2_strategy import SimpleExitV2Strategy
from stock_swing.strategy_engine.sector_shock_hold import (
    SectorShockAnalyzer,
    SectorShockHoldConfig,
    get_symbol_sector_returns,
)
from stock_swing.tracking.exit_reason_store import delete_exit_reason, write_exit_reason
from stock_swing.tracking.trade_event_store import TradeEvent
from stock_swing.tracking.pnl_tracker import PnLTracker
from stock_swing.tracking.fill_ledger import FillLedger, FillAlreadyConsumedError, FillQuarantinedError
from stock_swing.guardrails.risk_snapshot import build_risk_snapshot
from stock_swing.reporting.equity_bridge import compute_equity_bridge
from stock_swing.utils.context_budget import (
    TokenUsageRecord,
    TokenUsageTracker,
    attach_ai_telemetry,
    build_ai_metrics_from_decisions,
)
from stock_swing.utils.latency_tracker import LatencyTracker
from stock_swing.utils.market_calendar import MarketCalendar
from stock_swing.utils.market_guard import should_skip_non_market_day
from stock_swing.utils.signal_prioritization import prioritize_buy_signals, prioritize_buy_signals_v2
from stock_swing.utils.stale_price import apply_price_overrides, compute_stale_price_overrides


def _infer_price_based_regime(momentum_results: list) -> str:
    """Infer a simple market regime from current price momentum breadth.

    Uses the monitored universe itself as a lightweight fallback when macro data is
    unavailable. This is intentionally simple and conservative.
    """
    if not momentum_results:
        return "neutral"

    momenta = [float(f.values.get("momentum", 0) or 0) for f in momentum_results]
    bullish = sum(1 for m in momenta if m > 0.02)
    bearish = sum(1 for m in momenta if m < -0.02)
    total = len(momenta)
    avg_momentum = sum(momenta) / total if total else 0.0

    if total and bullish / total >= 0.6 and avg_momentum > 0.01:
        return "bullish"
    if total and bearish / total >= 0.5 and avg_momentum < -0.01:
        return "cautious"
    return "neutral"


def _select_intraday_candidate_symbols(
    breakout_signals: list,
    limit: int | None = None,
) -> list[str]:
    """Select symbols that deserve intraday confirmation.

    The intraday feature only enhances breakout signals today, so we first run
    the cheaper daily pass on the full universe, then fetch intraday bars only
    for the breakout candidates that survived the daily filter.
    """
    ranked = sorted(
        breakout_signals,
        key=lambda signal: (
            float(getattr(signal, "signal_strength", 0.0) or 0.0),
            float(getattr(signal, "confidence", 0.0) or 0.0),
            getattr(signal, "symbol", ""),
        ),
        reverse=True,
    )
    symbols: list[str] = []
    seen: set[str] = set()
    for signal in ranked:
        symbol = str(getattr(signal, "symbol", "") or "").upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
        if limit is not None and limit > 0 and len(symbols) >= limit:
            break
    return symbols


def _filter_buys_outside_regular_hours(
    decisions: list,
    now: "datetime | None" = None,
) -> tuple[list, list]:
    """Block new BUY orders when US market is outside regular hours (9:30–16:00 ET).

    Market orders with extended_hours=False cannot fill during pre-market or
    after-hours sessions.  Submitting them then creates phantom 'accepted'
    orders that carry over to the next session and pollute the PnL tracker
    with fake open trades (ORCL/QCOM batch incident 2026-06-03).

    Sell/exit orders are NEVER blocked — trailing stops and exits are urgent
    and must be processed regardless of session.

    Override: export PAPER_DEMO_ALLOW_OFFHOURS_BUYS=true
    """
    import os

    if os.environ.get("PAPER_DEMO_ALLOW_OFFHOURS_BUYS", "").lower() == "true":
        return decisions, []

    is_regular, status = MarketCalendar.is_regular_market_hours(now)
    if is_regular:
        return decisions, []

    allowed, blocked = [], []
    for d in decisions:
        if d.action == "buy":
            blocked.append((d.symbol, status))
        else:
            allowed.append(d)
    return allowed, blocked


def _extract_return_pct_from_notes(notes_text: str) -> float | None:
    """Extract the primary return percentage from exit notes when present."""
    if not notes_text:
        return None

    match = re.search(r"return\s+([+-]?\d+(?:\.\d+)?)%", notes_text, re.IGNORECASE)
    if match:
        return float(match.group(1)) / 100.0

    match = re.search(r":\s*([+-]?\d+(?:\.\d+)?)%\s*<=", notes_text)
    if match:
        return float(match.group(1)) / 100.0

    return None


def _filter_sells_outside_regular_hours(
    decisions: list,
    now: "datetime | None" = None,
    force_sell_return_pct: float = -0.12,
) -> tuple[list, list[tuple[str, str, float | None]]]:
    """Defer non-catastrophic SELL orders outside regular market hours.

    Market SELL orders submitted outside regular hours become queued day orders and
    can execute at the next regular-session open. That is precisely the behavior we
    want to avoid for moderate exit signals during broad Monday panic conditions.

    We therefore keep only catastrophic exits (default: return <= -12%) actionable
    outside regular hours and defer the rest for re-evaluation in the next session.
    """
    if os.environ.get("PAPER_DEMO_ALLOW_OFFHOURS_SELLS", "").lower() == "true":
        return decisions, []

    is_regular, _ = MarketCalendar.is_regular_market_hours(now)
    if is_regular:
        return decisions, []

    allowed: list = []
    deferred: list[tuple[str, str, float | None]] = []
    for decision in decisions:
        if decision.action != "sell":
            allowed.append(decision)
            continue

        notes = " ".join((decision.evidence or {}).get("notes") or [])
        _exit_trigger, exit_reason = _classify_exit_reason_from_notes(notes)
        return_pct = None
        if isinstance(decision.evidence, dict):
            raw_return = decision.evidence.get("return_pct")
            if raw_return is not None:
                try:
                    return_pct = float(raw_return)
                except (TypeError, ValueError):
                    return_pct = None
        if return_pct is None:
            return_pct = _extract_return_pct_from_notes(notes)

        if return_pct is not None and return_pct <= force_sell_return_pct:
            allowed.append(decision)
            continue

        deferred.append((decision.symbol, exit_reason, return_pct))

    deferred_symbols = {symbol for symbol, _, _ in deferred}
    for decision in decisions:
        if decision.action == "sell" and decision.symbol in deferred_symbols:
            continue
        if decision not in allowed:
            allowed.append(decision)

    return allowed, deferred


def _filter_etf_buys_by_guardrail(
    decisions: list,
    etf_symbols: set,
) -> tuple[list, list]:
    """Block new ETF buy orders unless PAPER_DEMO_ALLOW_ETF_BUYS=true.

    Sell/exit orders for existing ETF positions are never blocked.
    ETF-to-stock PF gap: ETF 0.168 vs Stock 1.731 (2026-05-28 analysis).
    Re-enable: export PAPER_DEMO_ALLOW_ETF_BUYS=true
    """
    import os
    if os.environ.get("PAPER_DEMO_ALLOW_ETF_BUYS", "").lower() == "true":
        return decisions, []

    allowed, blocked = [], []
    for d in decisions:
        if d.action == "buy" and d.symbol in etf_symbols:
            blocked.append(d.symbol)
        else:
            allowed.append(d)
    return allowed, blocked


def _filter_buys_by_risk_budget(
    decisions: list,
    project_root: "Path",
    equity: float,
) -> tuple[list, list[str], dict]:
    """Block all new BUY decisions when portfolio open risk exceeds BLOCK_PCT.

    Open risk = sum of (qty × entry_price × stop_loss_pct) for all open trades.
    Thresholds: WARN=5%, BLOCK=8% of equity.  Sell decisions are never blocked.
    Override: export PAPER_DEMO_SKIP_RISK_BUDGET=true
    """
    import os
    from stock_swing.risk.risk_budget import compute_open_risk

    if os.environ.get("PAPER_DEMO_SKIP_RISK_BUDGET", "").lower() == "true":
        return decisions, [], {}

    risk = compute_open_risk(project_root, equity)

    if risk.get("error"):
        print(f"  ⚠️  Risk budget: could not compute ({risk['error']}) — skipping guard")
        return decisions, [], risk

    pct = risk["pct_of_equity"]
    total = risk["total_open_risk"]

    if risk["is_blocked"]:
        allowed = [d for d in decisions if d.action != "buy"]
        blocked = [d.symbol for d in decisions if d.action == "buy"]
        print(
            f"  🚫 Risk budget BLOCK: open risk ${total:,.0f} = {pct:.1%} of equity "
            f"(limit {risk['block_threshold']:,.0f} / 8%) — "
            f"blocked {len(blocked)} new buy(s): {', '.join(blocked[:5])}"
            + (f" +{len(blocked)-5} more" if len(blocked) > 5 else "")
        )
        return allowed, blocked, risk

    if risk["is_warn"]:
        print(
            f"  ⚠️  Risk budget WARN: open risk ${total:,.0f} = {pct:.1%} of equity "
            f"(warn at 5%, block at 8%) — buys allowed"
        )
    else:
        print(
            f"  ✅ Risk budget OK: open risk ${total:,.0f} = {pct:.1%} of equity "
            f"(warn at 5%, block at 8%)"
        )

    return decisions, [], risk


def _filter_buys_by_cluster_cap(
    decisions: list,
    current_positions_full: dict[str, dict],
    equity: float,
) -> tuple[list, list[tuple[str, str]]]:
    """Block BUY decisions that would exceed a correlation cluster cap (P4-B)."""
    import os
    from stock_swing.risk.correlation_cluster import is_buy_blocked_by_cluster_cap

    if os.environ.get("PAPER_DEMO_SKIP_CLUSTER_CAP", "").lower() == "true":
        return decisions, []

    positions_list = list(current_positions_full.values())
    allowed, blocked = [], []
    for d in decisions:
        if d.action != "buy":
            allowed.append(d)
            continue
        is_blocked, reason = is_buy_blocked_by_cluster_cap(
            d.symbol, positions_list, equity
        )
        if is_blocked:
            blocked.append((d.symbol, reason))
        else:
            allowed.append(d)
    return allowed, blocked


def _classify_exit_reason_from_notes(notes_text: str) -> tuple[str, str]:
    """Derive (exit_trigger, exit_reason) from decision notes text."""
    t = notes_text.lower()
    if "trailing stop" in t:
        return "Trailing stop triggered", "trailing_stop"
    if "breakeven stop" in t:
        return "Breakeven stop triggered", "breakeven_stop"
    if "stop loss" in t:
        return "Stop loss triggered", "stop_loss"
    if "take profit" in t:
        return "Take profit triggered", "take_profit"
    if "max hold" in t:
        return "Max hold period reached", "time_based"
    return "Strategy exit", "strategy_exit"


def _prefilter_actionable_buys_for_submission(
    actionable: list,
    executor: PaperExecutor,
    exposure_cap_override: float | None = None,
) -> tuple[list, dict[str, tuple[int, dict[str, object]]], dict[str, int], list[tuple[str, str]]]:
    """Drop BUY decisions that size to zero before entering broker submission.

    The decision engine does not know account exposure. Without this preflight,
    paper_demo can churn through many BUY attempts that deterministically size to
    zero because the portfolio is already at its exposure cap.
    """
    filtered: list = []
    preview_cache: dict[str, tuple[int, dict[str, object]]] = {}
    skipped_by_reason: dict[str, int] = {}
    skipped_symbols: list[tuple[str, str]] = []

    for decision in actionable:
        order = decision.proposed_order
        if order is None or order.side != "buy":
            filtered.append(decision)
            continue

        market_regime = "neutral"
        if isinstance(decision.evidence, dict):
            market_regime = decision.evidence.get("market_regime") or "neutral"

        preview_qty, preview_sizing = executor._calculate_position_size(
            decision,
            market_regime=market_regime,
            exposure_cap_override=exposure_cap_override,
        )
        preview_cache[decision.decision_id] = (preview_qty, preview_sizing)

        if preview_qty >= 1:
            filtered.append(decision)
            continue

        reason = str(preview_sizing.get("skip_reason") or "final_shares_below_1")
        skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1
        skipped_symbols.append((decision.symbol, reason))

    return filtered, preview_cache, skipped_by_reason, skipped_symbols

# Unified paper-demo / monitoring universe
# Stocks: existing core AI stocks + approved additional normal stocks
# ETFs: approved normal ETFs only (no leveraged / inverse / bear / short / yield-enhanced ETFs)
#
# 2026-05-15 CRITICAL UPDATE:
# Alpaca fetch_bars() stopped updating ALL symbols (stocks + ETFs) on 2026-04-22.
# SOLUTION: Use Massive API for historical bars (provides fresh data for all symbols).
# Hybrid fetcher: Massive primary, Broker fallback.
# See docs/daily_logs/2026-05-15_exit_investigation.md for full analysis.
#
DEFAULT_SYMBOLS = [
    # Large cap tech
    "NVDA", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "AMD", "TSM", "ASML",
    # Semiconductors
    "INTC", "MU", "ARM", "AMAT", "LRCX", "KLAC", "QCOM", "MRVL",
    # Software & Cloud
    "PLTR", "ADBE", "CRM", "ORCL", "NOW", "SNOW", "MDB", "DDOG", "PATH", "FICO",
    # Cybersecurity & Infrastructure
    "SMCI", "PANW", "CRWD", "FTNT", "ANET", "CSCO", "IBM",
    # Hardware & Networking
    "HPE", "DELL", "HPQ", "SNPS", "CDNS", "NBIS", "CRDO", "RBRK", "CIEN",
    # ETFs (re-enabled with Massive API)
    "SOXQ", "SOXX", "SMH", "FTXL", "PTF", "SMHX", "FRWD", "TTEQ",
    "GTOP", "CHPX", "CHPS", "PSCT", "QTEC", "TDIV", "SKYY", "QTUM",
]

# Legacy CLI compatibility: "full" maps to the unified universe as well.
TECH_UNIVERSE_FULL = DEFAULT_SYMBOLS

# ETF symbols for portfolio allocation
# R2-v2 / H5 (2026-07-23): loaded from symbol_registry.yaml via allocation_config.
# Hardcoded fallback retained for safety when registry is unavailable.
_REGISTRY_PATH = project_root / "config" / "reference" / "symbol_registry.yaml"
_ALLOC_CONFIG_PATH = project_root / "config" / "strategy" / "portfolio_allocation.yaml"

_SYMBOL_REGISTRY = read_symbol_registry(_REGISTRY_PATH)
_ALLOC_CONFIG = read_allocation_config(_ALLOC_CONFIG_PATH)

_ETF_SYMBOLS_FROM_REGISTRY: frozenset[str] = get_etf_symbols_from_registry(_SYMBOL_REGISTRY)

# Hardcoded fallback (used only when registry is empty)
_ETF_SYMBOLS_FALLBACK = frozenset({
    'SOXQ', 'SOXX', 'SMH', 'FTXL', 'PTF', 'SMHX', 'FRWD',
    'TTEQ', 'GTOP', 'CHPX', 'CHPS', 'PSCT', 'QTEC', 'TDIV', 'SKYY', 'QTUM',
})

ETF_SYMBOLS: frozenset[str] = _ETF_SYMBOLS_FROM_REGISTRY if _ETF_SYMBOLS_FROM_REGISTRY else _ETF_SYMBOLS_FALLBACK


def main() -> int:  # noqa: C901
    parser = argparse.ArgumentParser(description="stock_swing paper trading demo")
    parser.add_argument("--symbols", type=str, default=",".join(DEFAULT_SYMBOLS),
                        help="Comma-separated symbols (overrides --universe)")
    parser.add_argument("--universe", type=str, choices=["default", "full"], default="default",
                        help="Predefined symbol universe: default (10 tech) / full (14 tech+ETF)")
    parser.add_argument("--timeframe", type=str, default="1Day")
    parser.add_argument("--bar-limit", type=int, default=20)
    # NOTE: These defaults align with BreakoutMomentumStrategy class defaults.
    # Previous values (0.025 / 0.52) were looser and produced different behaviour
    # in interactive use vs cron runs (which passed --min-momentum 0.05 explicitly).
    parser.add_argument("--min-momentum", type=float, default=0.05)
    parser.add_argument("--min-signal-strength", type=float, default=0.60)  # 2026-07-29: raised 0.40→0.60 (decile analysis: 0.4-0.6 range PF<0.05; R4-B lowered too far)
    parser.add_argument("--intraday-candidate-limit", type=int, default=0,
                        help="Max symbols to fetch 5-minute intraday bars for after daily screening (0 = all daily breakout candidates)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-outside-hours", action="store_true")
    parser.add_argument("--telegram", action="store_true", help="Send summary to Telegram")
    parser.add_argument("--silent", action="store_true", help="Send Telegram notification silently")
    parser.add_argument("--cron-summary-json", action="store_true", help="Emit one compact CRON_SUMMARY_JSON line at the end")
    args = parser.parse_args()

    # Configure logging so logger.info() messages (exit_signal_fired, exit_signal_generated,
    # exit_signals_none, exit_check) are captured in the cron log file.
    # Suppress noisy third-party libraries; keep stock_swing at INFO.
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=__import__("sys").stderr,
        force=True,
    )
    logging.getLogger("stock_swing").setLevel(logging.INFO)

    # Resolve symbol universe (--symbols overrides --universe)
    if args.symbols != ",".join(DEFAULT_SYMBOLS):
        # User explicitly passed --symbols
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.universe == "full":
        symbols = TECH_UNIVERSE_FULL
    else:
        symbols = DEFAULT_SYMBOLS

    latency_tracker: LatencyTracker | None = None
    _final_exit_code = 0
    _final_reason: str | None = None
    _buy_halt_reasons: list[str] = []

    def finish(
        exit_code: int,
        decisions: list[DecisionRecord] | None = None,
        submissions: list[OrderSubmission] | None = None,
        equity_value: float = 0.0,
        extra: dict | None = None,
    ) -> int:
        if latency_tracker is not None:
            latency_tracker.flush()
        if args.cron_summary_json:
            emit_cron_summary(
                _build_cron_summary(
                    symbols=symbols,
                    decisions=decisions or [],
                    submissions=submissions or [],
                    equity=equity_value,
                    dry_run=args.dry_run,
                    exit_code=exit_code,
                    extra=extra or {},
                )
            )
        return exit_code

    # R7-v2 / H8: skip on non-market days (weekends / US holidays)
    # Override: export STOCK_SWING_FORCE_MARKET_DAY=true
    if not args.dry_run:
        _skip, _skip_reason = should_skip_non_market_day()
        if _skip:
            print(f"⏭  {_skip_reason} – skipping paper_demo run")
            if args.cron_summary_json:
                emit_cron_summary({"job": "paper_demo", "status": "skipped", "reason": _skip_reason})
            return 0

    _banner("stock_swing Paper Trading Demo")
    run_context = RunContext.create("paper_demo")
    experiment_context = None
    print(f"  Symbols   : {', '.join(symbols)}")
    print(f"  Timeframe : {args.timeframe} x {args.bar_limit} bars")
    print(f"  Dry run   : {args.dry_run}")
    print(f"  Run ID    : {run_context.run_id}")
    print()

    # --- R0-A: ExperimentContext ---
    _section("ExperimentContext")
    try:
        import yaml as _yaml
        from stock_swing.experiments import ExperimentRegistry, build_experiment_context

        _exp_config_path = project_root / "config" / "experiments" / "default_experiment.yaml"
        _exp_raw = _yaml.safe_load(_exp_config_path.read_text(encoding="utf-8")) if _exp_config_path.exists() else {}
        experiment_context = build_experiment_context(
            repo_root=project_root,
            run_id=run_context.run_id,
            strategy_version=str(_exp_raw.get("strategy_version", "swing-v1")),
            prompt_version=str(_exp_raw.get("prompt_version", "prompt-v1")),
            feature_schema_version=str(_exp_raw.get("feature_schema_version", "features-v1")),
            config_payload=_exp_raw,
            mode=str(_exp_raw.get("mode", "paper")),
        )
        _exp_registry = ExperimentRegistry(project_root / "data" / "experiments")
        _exp_registry.register(experiment_context)
        print(f"  experiment_id : {experiment_context.experiment_id}")
        print(f"  config_hash   : {experiment_context.config_hash}")
    except Exception as _exc:
        logger.error("ExperimentContext setup failed — BUYs will be halted: %s", _exc)
        _buy_halt_reasons.append("experiment_context_unavailable")
        _final_exit_code = 1
        _final_reason = _final_reason or "experiment_context_unavailable"
        experiment_context = None
    # --- end R0-A ---

    # 0. Manual Kill Switch Check (GW emergency stop)
    MANUAL_KILL_SWITCH_FILE = project_root / "data" / "kill_switch_manual.txt"
    if MANUAL_KILL_SWITCH_FILE.exists():
        print("\n" + "=" * 60)
        print("🚨 MANUAL KILL SWITCH ACTIVATED")
        print("=" * 60)
        print(f"Kill switch file detected: {MANUAL_KILL_SWITCH_FILE}")
        print("Trading is DISABLED.")
        print(f"To resume trading, remove the file:")
        print(f"  rm {MANUAL_KILL_SWITCH_FILE}")
        print("=" * 60)
        return finish(1)

    # 1. Runtime mode
    _section("1. Runtime Mode")
    try:
        runtime_mode_str = read_runtime_mode(project_root)
    except (FileNotFoundError, RuntimeModeError) as exc:
        print(f"  ERROR: {exc}")
        return finish(1)

    if runtime_mode_str != "paper":
        print(f"  ERROR: Must be 'paper', got '{runtime_mode_str}'")
        return finish(1)

    runtime_mode = RuntimeMode.PAPER
    print(f"  OK: runtime_mode={runtime_mode_str}")

    # R0-v2-A: Ledger quality gate status
    _ledger_gate = read_ledger_quality_gate(project_root)
    _ledger_gate_status = _ledger_gate.get("current_status", "UNKNOWN")
    _enforce_invalid = _ledger_gate.get("enforce_invalid_ledger_blocks_live_ready", True)
    if _ledger_gate_status == "INVALID" and _enforce_invalid:
        print(f"  WARN: ledger_gate=INVALID — PF/WR suppressed in console, live-ready=NO-GO")
    else:
        print(f"  OK: ledger_gate={_ledger_gate_status}")

    # 2. Kill switch
    _section("2. Kill Switch")
    ks_file = project_root / "data" / "audits" / "kill_switch.txt"
    kill_switch = KillSwitch(state_file=ks_file)
    try:
        kill_switch.check()
        print("  OK: Kill switch ACTIVE (execution allowed)")
    except RuntimeError as exc:
        print(f"  ERROR: {exc}")
        return finish(1)

    # --- R0-B: Guardrail startup check ---
    _section("Guardrail")
    _breaker_path = project_root / "data" / "guardrails" / "circuit_breaker.json"
    hard_mode = False
    try:
        import yaml as _gyaml
        from stock_swing.guardrails.rule_engine import GuardrailEngine, load_rules_from_dict
        from stock_swing.guardrails.circuit_breaker import CircuitBreakerStore
        from stock_swing.guardrails.pre_trade_check import check_startup, should_skip_ai, apply_to_buy_candidate, post_run_update

        _guardrail_config_path = project_root / "config" / "guardrails" / "autonomous_stop.yaml"
        _guardrail_raw = _gyaml.safe_load(_guardrail_config_path.read_text(encoding="utf-8")) if _guardrail_config_path.exists() else {}
        _warning_only = bool(_guardrail_raw.get("paper_warning_only", True))
        hard_mode = not _warning_only
        _guardrail_rules = load_rules_from_dict(_guardrail_raw)
        _guard_engine = GuardrailEngine(_guardrail_rules, warning_only=_warning_only)
        _breaker_store = CircuitBreakerStore(_breaker_path)
        _breaker_state = check_startup(_breaker_store)

        if _warning_only:
            print("  OK: Guardrail ACTIVE (warning_only=True — no hard blocks yet)")
        elif _breaker_state.is_halted:
            print(f"  🚨 Guardrail HALTED: {_breaker_state.reason} — buys will be blocked")
        else:
            print(f"  OK: Guardrail status={_breaker_state.status}")
    except Exception as _exc:
        _hard_mode_failed = hard_mode
        logger.warning("Guardrail setup failed (non-fatal): %s", _exc)
        _guard_engine = None
        _breaker_store = None
        _breaker_state = None
        _warning_only = True
        hard_mode = False
        should_skip_ai = None
        apply_to_buy_candidate = None
        post_run_update = None
        if _hard_mode_failed:
            logger.critical("Guardrail setup failed in hard mode — fail-closed, aborting")
            sys.exit(1)
    # --- end R0-B startup ---

    # 3. Market hours
    _section("3. Market Hours")
    now_local = datetime.now()
    is_open, market_status = MarketCalendar.is_market_open(now_local)
    print(f"  {'OK' if is_open else 'WARN'}: {market_status}")
    if not is_open and not args.allow_outside_hours and not args.dry_run:
        print("  Use --allow-outside-hours to queue orders, or --dry-run to preview")

    # 4. Broker connectivity
    _section("4. Broker")
    required_env = ["BROKER_API_KEY", "BROKER_API_SECRET", "BROKER_BASE_URL"]
    missing_env = [v for v in required_env if not os.getenv(v)]
    if missing_env:
        print(f"  ERROR: Missing env vars: {', '.join(missing_env)}")
        return finish(1)

    broker = BrokerClient(
        api_key=os.environ["BROKER_API_KEY"],
        api_secret=os.environ["BROKER_API_SECRET"],
        paper_mode=True,
        base_url=os.environ["BROKER_BASE_URL"],
    )
    latency_tracker = LatencyTracker(
        project_root / "data" / "analysis" / "api_latency.csv"
    )
    # RF-5b: token usage tracker for AI telemetry
    token_tracker = TokenUsageTracker(
        project_root / "data" / "analysis" / "token_usage.csv"
    )
    print(f"  URL: {broker.base_url}")

    latest_quote_cache: dict[str, float] = {}

    def get_mid_price(symbol: str) -> float:
        cached = latest_quote_cache.get(symbol)
        if cached is not None:
            return cached
        try:
            q = broker.fetch_latest_quote(symbol).payload
            quote = q.get("quote", q)
            bid = float(quote.get("bp", 0) or 0)
            ask = float(quote.get("ap", 0) or 0)
            price = round((bid + ask) / 2, 4) if bid and ask else 0.0
        except Exception:
            price = 0.0
        latest_quote_cache[symbol] = price
        return price

    def _normalize_fill_price(raw_price: float, reference_prices: list[float]) -> float:
        """Scale broker fill anomalies back near the live reference price set.

        Alpaca paper data has occasionally returned 10x/100x prices around split
        events. If dividing by 10 or 100 lands near a trusted live reference,
        record the corrected fill instead of the raw broker value.
        """
        if raw_price <= 0:
            return 0.0

        refs = [float(price) for price in reference_prices if price and float(price) > 0]
        if not refs:
            return round(raw_price, 6)

        for factor in (1, 10, 100):
            candidate = raw_price / factor
            if any(abs(candidate - ref) / ref <= 0.12 for ref in refs):
                return round(candidate, 6)

        return round(raw_price, 6)

    def resolve_recorded_entry_price(submission: OrderSubmission, symbol: str, limit_price: float | None) -> float:
        """Prefer broker truth for tracking, then fall back to local estimates.

        Stale-fill guard:
        Alpaca paper bars have been frozen since 2026-04-22, causing
        get_order().filled_avg_price to return the frozen bar price rather
        than the actual market fill price.  When the broker fill deviates
        by more than 20 % from sizing_price (which now comes from Massive
        via decision.evidence["latest_close"]), we treat the fill as stale
        and record sizing_price as the entry price instead.
        This keeps the tracker consistent with the price basis used for
        position sizing, stop-loss, and trailing-stop calculations.
        """
        sizing_price = float((submission.sizing_details or {}).get("current_price") or 0)
        quote_price = get_mid_price(symbol)
        reference_prices = [sizing_price, quote_price, float(limit_price or 0)]

        if submission.broker_order_id:
            try:
                order_resp = broker.get_order(submission.broker_order_id)
                order_payload = order_resp.payload if hasattr(order_resp, "payload") else order_resp
                filled_avg_price = float(order_payload.get("filled_avg_price") or 0)
                if filled_avg_price > 0:
                    normalized = _normalize_fill_price(filled_avg_price, reference_prices)
                    # Stale-fill guard: if the normalised fill still deviates
                    # > 20 % from sizing_price (Massive-backed), the broker
                    # is returning a stale paper fill.  Fall back to
                    # sizing_price, which reflects the real market price.
                    if sizing_price > 0:
                        deviation = abs(normalized - sizing_price) / sizing_price
                        if deviation > 0.15:
                            import logging
                            logging.getLogger(__name__).warning(
                                f"resolve_recorded_entry_price: stale broker fill for {symbol}: "
                                f"fill=${normalized:.4f} deviates {deviation:.1%} from "
                                f"sizing_price=${sizing_price:.4f} — "
                                f"using sizing_price (Massive-backed) as entry"
                            )
                            return round(sizing_price, 6)
                    return normalized
            except Exception:
                pass

        for candidate in (sizing_price, quote_price, float(limit_price or 0)):
            if candidate > 0:
                return round(candidate, 6)

        return 0.0

    try:
        with latency_tracker.track("broker.fetch_account"):
            account_env = broker.fetch_account()
        acct = account_env.payload
        equity = float(acct.get("equity", 100_000))
        buying_power = float(acct.get("buying_power", 100_000))
        print(f"  OK: status={acct.get('status')} equity=${equity:,.2f} bp=${buying_power:,.2f}")
    except Exception as exc:
        print(f"  ERROR: Account fetch failed: {exc}")
        return finish(1)

    # Infrastructure
    paths = PathManager(project_root)
    store = StageStore(paths, allow_raw_overwrite=True)
    ts_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    audit_log = AuditLogger(
        log_file=project_root / "data" / "audits" / f"paper_demo_{datetime.now().strftime('%Y%m%d')}.log",
        min_level=AuditLevel.INFO,
    )
    audit_log.log_system_event("paper_demo_start", details=f"symbols={symbols} dry_run={args.dry_run}")

    # 5. Data collection (hybrid: Massive primary, Broker fallback)
    _section("5. Data Collection (Hybrid: Massive Primary, Broker Fallback)")
    
    # Initialize hybrid fetcher (prefers Massive for all symbols)
    # 2026-05-15: Alpaca fetch_bars() stopped updating ALL symbols on 2026-04-22
    from stock_swing.sources.hybrid_data_fetcher import HybridDataFetcher
    hybrid_fetcher = HybridDataFetcher(
        broker_client=broker,
        etf_symbols=ETF_SYMBOLS,
        massive_api_key=os.environ.get("MASSIVE_API_KEY")
    )
    
    all_records: list[CanonicalRecord] = []
    max_workers = int(os.environ.get("PAPER_DEMO_MAX_WORKERS", "8"))

    def fetch_single_symbol(symbol: str) -> tuple[str, list[CanonicalRecord], int, str | None, str]:
        """Fetch bars for a single symbol. Returns (symbol, records, bar_count, error, source)."""
        try:
            records, source = hybrid_fetcher.fetch_bars(
                symbol,
                timeframe=args.timeframe,
                limit=args.bar_limit
            )
            bar_count = len(records)
            if source == "failed":
                return (symbol, [], 0, "Fetch failed", source)
            return (symbol, records, bar_count, None, source)
        except Exception as exc:
            return (symbol, [], 0, str(exc), "failed")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_single_symbol, symbol): symbol for symbol in symbols}
        source_counts = {"massive": 0, "yahoo": 0, "broker": 0, "failed": 0}
        for future in as_completed(futures):
            symbol, records, bar_count, error, source = future.result()
            source_counts.setdefault(source, 0)
            source_counts[source] += 1
            if error:
                print(f"  WARN: {symbol:<6} fetch failed: {error}")
            else:
                all_records.extend(records)
                source_icon = "📊" if source == "massive" else "🟨" if source == "yahoo" else "📈"
                print(f"  OK: {symbol:<6} {bar_count:3d} bars -> {len(records):3d} records [{source_icon} {source}]")

    if not all_records:
        print("\n  ERROR: No data fetched. Cannot proceed.")
        return finish(1, equity_value=equity if 'equity' in locals() else 0.0)
    print(f"\n  Total records: {len(all_records)}")
    print(
        f"  Sources: Massive={source_counts['massive']}, Yahoo={source_counts['yahoo']}, "
        f"Broker={source_counts['broker']}, Failed={source_counts['failed']}"
    )
    print(f"  Workers: {max_workers} parallel")

    # 6. Features (daily pass on full universe)
    _section("6. Feature Computation")
    momentum_feat = PriceMomentumFeature(period_days=args.bar_limit)
    macro_feat = MacroRegimeFeature()
    momentum_results = momentum_feat.compute(all_records)
    macro_results = macro_feat.compute([])

    detected_regime = macro_results[0].values.get('regime', 'unknown') if macro_results else 'unknown'
    macro_based_regime = 'bullish' if detected_regime == 'expansion' else ('cautious' if detected_regime in {'recession', 'high_volatility'} else 'neutral')
    price_based_regime = _infer_price_based_regime(momentum_results)
    regime_for_sizing = price_based_regime if detected_regime == 'unknown' else macro_based_regime
    daily_features = momentum_results + macro_results

    # Data freshness validation (2026-05-15: prevent stale price data)
    stale_symbols = set()
    for f in momentum_results:
        if "stale_data" in f.quality_flags:
            stale_symbols.add(f.symbol)
            data_age = f.values.get("data_age_days", "unknown")
            print(f"  ⚠️  WARNING: {f.symbol} has stale price data (age: {data_age} days)")
    
    if stale_symbols:
        print(f"\n  ⚠️  CRITICAL: {len(stale_symbols)} symbols with stale data detected.")
        print(f"     Stale symbols: {', '.join(sorted(stale_symbols))}")
        print(f"     These symbols will be EXCLUDED from trading to prevent")
        print(f"     incorrect entry/exit decisions.\n")
        audit_log.log_system_event(
            "stale_data_detected",
            details=f"Excluded {len(stale_symbols)} symbols: {','.join(sorted(stale_symbols))}"
        )
        # Filter out stale symbols from features
        momentum_results = [f for f in momentum_results if f.symbol not in stale_symbols]
        daily_features = momentum_results + macro_results

    print(f"  Macro regime: {detected_regime}")
    print(f"  Price regime: {price_based_regime}")
    print(f"  Sizing regime: {regime_for_sizing}")
    print()
    print(f"  Daily Momentum (fresh data only):")
    print(f"  {'Symbol':<6}  {'Momentum':>10}  {'Trend':<10}  {'Bars':>5}")
    print(f"  {'------':<6}  {'--------':>10}  {'----':>10}  {'----':>5}")
    for f in sorted(momentum_results, key=lambda x: x.values.get("momentum", 0), reverse=True):
        m = f.values.get("momentum", 0)
        t = f.values.get("trend", "?")
        b = f.values.get("bars_used", 0)
        print(f"  {f.symbol:<6}  {m:>+10.2%}  {t:<10}  {b:>5}")

    # 7. Strategy signals
    _section("7. Strategy Signals")

    pnl_tracker = PnLTracker(project_root)
    # FIX-LEDGER-RACE (2026-07-31): exactly-once fill consumption guard for the
    # inline reconciler below. Without this, the same broker sell fill can be
    # partially consumed both here AND by the 15-min reconcile_orders.py cron,
    # with no cross-process coordination (both read/append fill_ledger.jsonl
    # independently). This does not corrupt PnL by itself (FIFO qty accounting
    # in pnl_tracker.record_exit is still correct), but it silently loses the
    # earlier consumption_events entry on the next append, and provides no
    # protection against double-consuming a partial fill under raciness.
    fill_ledger = FillLedger(project_root)

    # First, get current positions for exit strategy
    current_positions_full: dict[str, dict] = {}
    current_positions: dict[str, int] = {}
    try:
        with latency_tracker.track("broker.fetch_positions"):
            pos_env = broker.fetch_positions()
        pos_data = pos_env.payload
        position_prices: dict[str, float] = {}
        if isinstance(pos_data, list):
            for pos in pos_data:
                sym = pos.get("symbol")
                qty = int(float(pos.get("qty", 0)))
                if sym and qty > 0:
                    current_positions[sym] = qty
                    current_positions_full[sym] = dict(pos)
                    current_price = float(pos.get("current_price", 0) or 0)
                    if current_price > 0:
                        position_prices[sym] = current_price

        if current_positions_full:
            try:
                from stock_swing.sources.massive_client import MassiveClient
                massive_client = MassiveClient(api_key=os.environ.get("MASSIVE_API_KEY"))
                runtime_overrides, _, runtime_override_errors = compute_stale_price_overrides(
                    list(current_positions_full.values()),
                    massive_client,
                    min_deviation_pct=5.0,
                )
                overrides_applied = apply_price_overrides(current_positions_full, runtime_overrides)
                if overrides_applied > 0:
                    print(f"  Applied {overrides_applied} runtime fresh-price overrides for exit strategy")
                if runtime_override_errors:
                    print(f"  WARN: runtime fresh-price checks had {len(runtime_override_errors)} error(s)")
            except Exception as exc:
                print(f"  WARN: Could not compute runtime fresh-price overrides: {exc}")
                # Override computation failed. Scan raw broker prices for obvious anomalies
                # (e.g. 10x split glitch) and warn so the operator can investigate.
                for sym, pos in current_positions_full.items():
                    try:
                        broker_cp = float(pos.get("current_price") or 0)
                        broker_ep = float(pos.get("avg_entry_price") or 0)
                        if broker_ep > 0 and broker_cp > broker_ep * 2.5:
                            print(
                                f"  WARN: Possible price anomaly for {sym}: "
                                f"broker current_price=${broker_cp:.2f} is {broker_cp/broker_ep:.1f}x "
                                f"avg_entry_price=${broker_ep:.2f}. "
                                f"Peak update skipped by anomaly guard."
                            )
                    except (TypeError, ValueError):
                        pass

            position_prices = {
                sym: float(pos.get("current_price", 0) or 0)
                for sym, pos in current_positions_full.items()
                if float(pos.get("current_price", 0) or 0) > 0
            }
            pnl_tracker.update_open_trade_peaks(position_prices)
            tracker_position_context = pnl_tracker.get_open_position_context_by_symbol()
            for sym, pos in current_positions_full.items():
                tracker_ctx = tracker_position_context.get(sym)
                if not tracker_ctx:
                    continue
                if tracker_ctx.get("created_at") and not pos.get("created_at"):
                    pos["created_at"] = tracker_ctx["created_at"]
                if tracker_ctx.get("peak_price") is not None and not pos.get("peak_price"):
                    pos["peak_price"] = tracker_ctx["peak_price"]
                if tracker_ctx.get("entry_signal_strength") is not None:
                    pos["entry_signal_strength"] = tracker_ctx["entry_signal_strength"]
    except Exception as exc:
        print(f"  WARN: Could not fetch positions for exit strategy: {exc}")

    # FIX-GUARDRAIL-2: Use day-start snapshot; never fall back to 0 silently.
    _day_start_unrealized: float | None = None
    _day_start_missing_metrics: list[str] = []
    try:
        from stock_swing.guardrails.day_start_snapshot import get_prev_unrealized_for_guardrail
        # Compute current unrealized for capture if no snapshot exists yet today
        _current_unrealized_for_capture: float | None = None
        if current_positions_full:
            try:
                _current_unrealized_for_capture = sum(
                    float(pos.get("unrealized_pl", 0) or 0)
                    for pos in current_positions_full.values()
                )
            except Exception:
                pass
        # FIX: reuse already-fetched equity (broker.get_account() does not exist;
        # the correct method is fetch_account(), already called above at startup).
        _broker_equity_for_capture: float | None = equity if equity and equity > 0 else None
        _day_start_unrealized, _day_start_missing_metrics = get_prev_unrealized_for_guardrail(
            project_root,
            equity=_broker_equity_for_capture,
            unrealized_pnl=_current_unrealized_for_capture,
            source="broker_api" if _broker_equity_for_capture is not None else "tracker_estimate",
        )
        if _day_start_missing_metrics:
            print(
                f"  ERROR [FIX-GUARDRAIL-2]: day-start snapshot missing fields: "
                f"{_day_start_missing_metrics}. BUYs must remain halted.",
                file=sys.stderr,
            )
            _final_exit_code = 1
            _final_reason = _final_reason or "guardrail_missing_day_start"
    except Exception as _dss_exc:
        print(f"  ERROR [FIX-GUARDRAIL-2]: day-start snapshot error: {_dss_exc}", file=sys.stderr)
        _day_start_missing_metrics = ["day_start_unrealized", "day_start_equity", "captured_at", "source"]
        _final_exit_code = 1
        _final_reason = _final_reason or "guardrail_missing_day_start"

    # Entry strategies: first pass on daily features only.
    breakout_strat = BreakoutMomentumStrategy(
        min_momentum=args.min_momentum,
        min_signal_strength=args.min_signal_strength,
        etf_symbols=ETF_SYMBOLS,  # Tag ETF signals with ETF_STRATEGY_ID for PF attribution
    )
    event_strat = EventSwingStrategy()
    breakout_signals = breakout_strat.generate(daily_features)
    event_signals = event_strat.generate(daily_features)
    
    # Filter out stale symbols from entry signals (2026-05-15: prevent stale data trades)
    if stale_symbols:
        breakout_signals = [s for s in breakout_signals if s.symbol not in stale_symbols]
        event_signals = [s for s in event_signals if s.symbol not in stale_symbols]
        print(f"  \u26a0️  Filtered {len(stale_symbols)} stale symbols from entry signals.")
        audit_log.log_system_event(
            "stale_symbols_filtered_from_entry",
            details=f"{','.join(sorted(stale_symbols))}"
        )

    # 7b. Intraday data collection (5-minute bars for breakout candidates only)
    _section("7b. Data Collection (5-Minute Intraday Bars)")
    intraday_records: list[CanonicalRecord] = []
    intraday_results = []

    use_intraday = os.environ.get("PAPER_DEMO_USE_INTRADAY", "true").lower() == "true"
    intraday_candidate_limit = args.intraday_candidate_limit if args.intraday_candidate_limit and args.intraday_candidate_limit > 0 else None
    intraday_candidates = _select_intraday_candidate_symbols(breakout_signals, intraday_candidate_limit)

    if use_intraday and intraday_candidates:
        print(
            f"  Two-stage fetch enabled: {len(symbols)} daily symbols -> "
            f"{len(intraday_candidates)} intraday candidate(s)"
        )

        _intraday_normalizer = BrokerNormalizer()

        def fetch_intraday_bars(symbol: str) -> tuple[str, list[CanonicalRecord], int, str | None]:
            """Fetch 5-minute bars for intraday momentum analysis."""
            try:
                # Fetch ~8 hours of 5-minute bars (100 bars = 500 minutes ≈ 8.3 hours)
                with latency_tracker.track("broker.fetch_bars", symbol=symbol):
                    raw = broker.fetch_bars(symbol, timeframe="5Min", limit=100)
                bar_count = len(raw.payload.get("bars", []))
                records = _intraday_normalizer.normalize(raw)
                return (symbol, records, bar_count, None)
            except Exception as exc:
                return (symbol, [], 0, str(exc))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_intraday_bars, sym): sym for sym in intraday_candidates}
            for future in as_completed(futures):
                symbol, records, bar_count, error = future.result()
                if error:
                    print(f"  WARN: {symbol:<6} intraday fetch failed: {error}")
                else:
                    intraday_records.extend(records)
                    print(f"  OK: {symbol:<6} {bar_count:3d} 5-min bars -> {len(records):3d} records")

        print(f"\n  Total intraday records: {len(intraday_records)}")
        if not intraday_records:
            print("  WARN: No intraday data fetched. Intraday momentum feature will be skipped.")
    elif not use_intraday:
        print("  Intraday feature disabled (set PAPER_DEMO_USE_INTRADAY=true to enable)")
    else:
        print("  No breakout candidates from daily pass. Skipping intraday fetch.")

    # Compute intraday momentum if data available
    if intraday_records:
        # Load optimal parameters from config
        intraday_config_path = project_root / "config" / "features" / "intraday_momentum.yaml"
        if intraday_config_path.exists():
            with open(intraday_config_path) as f:
                intraday_config = yaml.safe_load(f)
            lookback_bars = intraday_config.get('lookback_bars', 25)
            smoothing_window = intraday_config.get('smoothing_window', 5)
            vwap_threshold = intraday_config.get('vwap_threshold', 0.005)
        else:
            # Fallback to optimal defaults
            lookback_bars = 25
            smoothing_window = 5
            vwap_threshold = 0.005

        intraday_feat = IntradayMomentumFeature(
            lookback_bars=lookback_bars,
            smoothing_window=smoothing_window,
            vwap_threshold=vwap_threshold
        )
        intraday_results = intraday_feat.compute(intraday_records)
        print(f"  Intraday momentum computed: {len(intraday_results)} symbols (lookback={lookback_bars})")

    all_features = daily_features + intraday_results

    # Display intraday momentum if available
    if intraday_results:
        print()
        print(f"  Intraday Momentum (5-min bars):")
        print(f"  {'Symbol':<6}  {'Smoothed':>10}  {'VWAP Signal':<12}  {'Vol%':>6}")
        print(f"  {'------':<6}  {'--------':>10}  {'------------':<12}  {'----':>6}")
        for f in sorted(intraday_results, key=lambda x: x.values.get("smoothed_momentum", 0), reverse=True):
            sm = f.values.get("smoothed_momentum", 0)
            vwap_sig = f.values.get("vwap_signal", "unknown")
            iv = f.values.get("intraday_volatility", 0) or 0
            print(f"  {f.symbol:<6}  {sm:>+10.2%}  {vwap_sig:<12}  {iv:>6.2%}")

    # Enhance signals with intraday momentum (Hybrid Strategy)
    if intraday_results:
        # Create intraday lookup by symbol
        intraday_by_symbol = {f.symbol: f for f in intraday_results}

        # Load intraday config for thresholds
        intraday_config_path = project_root / "config" / "features" / "intraday_momentum.yaml"
        if intraday_config_path.exists():
            with open(intraday_config_path) as f:
                intraday_config = yaml.safe_load(f)
            momentum_threshold = intraday_config.get('signal_criteria', {}).get('momentum_threshold', 0.003)
        else:
            momentum_threshold = 0.003  # 0.3% optimal threshold

        enhanced_breakout_signals = []
        for signal in breakout_signals:
            intraday_feat = intraday_by_symbol.get(signal.symbol)

            if intraday_feat:
                smoothed_mom = intraday_feat.values.get('smoothed_momentum', 0)
                vwap_signal = intraday_feat.values.get('vwap_signal', 'neutral')

                # Boost confidence if intraday confirms (both bullish + VWAP favorable)
                if smoothed_mom > momentum_threshold and vwap_signal != 'below_vwap':
                    # High confidence: both daily and intraday bullish
                    boosted_strength = min(signal.signal_strength * 1.2, 1.0)  # +20% boost
                    # Update signal with boosted strength
                    enhanced_signal = replace(
                        signal,
                        signal_strength=boosted_strength,
                        reasoning=f"{signal.reasoning} + Intraday confirmed (smoothed={smoothed_mom:.2%}, VWAP={vwap_signal})",
                        strategy_id=f"{signal.strategy_id}_intraday_enhanced"
                    )
                    enhanced_breakout_signals.append(enhanced_signal)
                else:
                    # Keep original signal but log intraday status
                    enhanced_signal = replace(
                        signal,
                        reasoning=f"{signal.reasoning} (intraday weak: smoothed={smoothed_mom:.2%})"
                    )
                    enhanced_breakout_signals.append(enhanced_signal)
            else:
                # No intraday data, keep original
                enhanced_breakout_signals.append(signal)

        breakout_signals = enhanced_breakout_signals
    
    # Exit strategy for current positions (V2 with trailing stop)
    # Load exit strategy config
    exit_config_path = project_root / "config" / "strategy" / "simple_exit_v2.yaml"
    if exit_config_path.exists():
        with open(exit_config_path) as f:
            exit_config = yaml.safe_load(f)
        exit_strat = SimpleExitV2Strategy(
            stop_loss_pct=exit_config.get('stop_loss_pct', -0.07),
            breakeven_activation_pct=exit_config.get('breakeven_activation_pct', 0.03),
            trailing_activation_pct=exit_config.get('trailing_activation_pct', 0.08),
            trailing_stop_pct=exit_config.get('trailing_stop_pct', 0.04),
            max_hold_days=exit_config.get('max_hold_days', 20),
            staged_trailing_enabled=exit_config.get('staged_trailing_enabled', False),
            staged_trailing_levels=exit_config.get('staged_trailing_levels', []),
            # G9: min_hold guard
            min_hold_days=exit_config.get('min_hold_days', 1),
            min_hold_days_enabled=exit_config.get('min_hold_days_enabled', True),
            emergency_stop_bypass_pct=exit_config.get('emergency_stop_bypass_pct', -0.12),
            # Plan A: tiered min_hold (2026-07-27)
            tiered_min_hold_enabled=exit_config.get('tiered_min_hold_enabled', False),
            tiered_min_hold_levels=exit_config.get('tiered_min_hold_levels', []),
            # broker_recon graduation (改善点1 2026-07-16)
            broker_recon_graduation_days=exit_config.get('broker_recon_graduation_days', 5),
            # Staged breakeven floor (2026-08-05)
            staged_breakeven_enabled=exit_config.get('staged_breakeven_enabled', False),
            staged_breakeven_levels=exit_config.get('staged_breakeven_levels', []),
        )
    else:
        # Fallback to default values
        exit_strat = SimpleExitV2Strategy(
            stop_loss_pct=-0.07,
            breakeven_activation_pct=0.03,
            trailing_activation_pct=0.08,
            trailing_stop_pct=0.04,
            max_hold_days=20,
        )
    exit_signals = exit_strat.generate(all_features, current_positions_full)

    # F7: sector_shock_hold shadow analysis — annotate exit signals with regime context
    _ssh_config = SectorShockHoldConfig.from_env()
    _ssh_analyzer = SectorShockAnalyzer(_ssh_config)
    _ssh_shadow_count = 0
    if _ssh_analyzer.is_enabled() and exit_signals:
        # Fix 1: build symbol → return_1d map from all price_momentum features
        _feat_return_1d: dict[str, float] = {}
        for _feat in all_features:
            _sym_f = getattr(_feat, "symbol", None)
            _vals_f = getattr(_feat, "values", {})
            if _sym_f and isinstance(_vals_f, dict):
                _r1d = _vals_f.get("return_1d")
                if _r1d is not None:
                    try:
                        _feat_return_1d[_sym_f] = float(_r1d)
                    except (TypeError, ValueError):
                        pass

        # Build returns for ALL benchmark symbols used across the entire registry
        # (2026-07-28 fix): previously only global [SMH, SOXX] were fetched, meaning
        # non-semiconductor stocks (ADBE/AMZN/PLTR/META) were always evaluated against
        # semiconductor benchmarks. Per-symbol benchmarks from symbol_registry.yaml
        # were ignored even though they were correctly defined there.
        _all_bm_symbols: set[str] = set(_ssh_config.benchmark_symbols)  # global fallback
        for _reg_info in _SYMBOL_REGISTRY.values():
            for _bm in (_reg_info.get("benchmark_symbols") or []):
                _all_bm_symbols.add(_bm)

        # Sector 1d return: prefer all_features (real-time), fall back to
        # benchmark_returns.csv (most recent row) for any benchmark still missing.
        _all_benchmark_1d: dict[str, float] = {
            _bm: _feat_return_1d[_bm]
            for _bm in _all_bm_symbols
            if _bm in _feat_return_1d
        }
        _missing_bms = [b for b in _all_bm_symbols if b not in _all_benchmark_1d]
        if _missing_bms:
            _bm_csv = project_root / "data" / "benchmarks" / "benchmark_returns.csv"
            if _bm_csv.exists():
                _bm_latest: dict[str, tuple[str, float]] = {}
                with open(_bm_csv, newline="") as _f:
                    for _row in csv.DictReader(_f):
                        _sym_bm = _row.get("symbol", "")
                        _ret_str = _row.get("daily_return", "")
                        _dt_str = _row.get("date", "")
                        if _sym_bm in _missing_bms and _ret_str:
                            try:
                                _bm_latest[_sym_bm] = (_dt_str, float(_ret_str))
                            except (TypeError, ValueError):
                                pass
                for _bm_sym, (_bm_dt, _bm_r) in _bm_latest.items():
                    _all_benchmark_1d[_bm_sym] = _bm_r
                    logger.debug(
                        "sector_shock: %s return_1d=%.4f loaded from benchmark_returns.csv "
                        "(date=%s; features had no data)",
                        _bm_sym, _bm_r, _bm_dt,
                    )

        for _sig in exit_signals:
            _sym = getattr(_sig, "symbol", None) or ""
            if not _sym:
                continue
            _pos = current_positions_full.get(_sym) or {}
            _unrealized_pct = float(_pos.get("unrealized_plpc", 0) or 0)
            # Fix 2: use actual return_1d from features; fall back to signal_strength proxy
            _1d_sym = _feat_return_1d.get(
                _sym,
                float((getattr(_sig, "signal_strength", 0) or 0)) * -1,
            )
            # Per-symbol benchmark selection from symbol_registry.yaml (2026-07-28 fix)
            _sym_sector_1d = get_symbol_sector_returns(
                symbol=_sym,
                all_benchmark_returns=_all_benchmark_1d,
                symbol_registry=_SYMBOL_REGISTRY,
                fallback_benchmarks=_ssh_config.benchmark_symbols,
            )
            _ssh_result = _ssh_analyzer.classify(
                symbol=_sym,
                current_return_pct=_unrealized_pct,
                symbol_1d_return_pct=_1d_sym,
                sector_1d_return_pcts=_sym_sector_1d,
            )
            # R3-v2 / F7: write to persistent JSONL shadow log for A/B activation tracking
            _ssh_log_path = project_root / "data" / "sector_shock_shadow_log.jsonl"
            _ssh_analyzer.log_shadow(_ssh_result, shadow_log_path=_ssh_log_path)
            # Count only genuine sector_shock_hold classifications (not hard_stop/soft_stop)
            # Activation condition: ≥10 valid sector_shock_hold events
            if _ssh_result.classification == "sector_shock_hold":
                _ssh_shadow_count += 1

    cooldown_config_path = project_root / "config" / "strategy" / "open_shock_cooldown.yaml"
    cooldown_result = None
    if cooldown_config_path.exists():
        with open(cooldown_config_path) as f:
            cooldown_config = yaml.safe_load(f) or {}
        cooldown_result = apply_open_shock_cooldown(
            exit_signals=exit_signals,
            features=all_features,
            get_mid_price=get_mid_price,
            now_utc=datetime.now(timezone.utc),
            config=cooldown_config,
        )
        exit_signals = cooldown_result.filtered_signals
    
    # Prioritize buy signals for sector diversification (V2 with dynamic allocation)
    entry_signals = breakout_signals + event_signals
    prioritized_entry = prioritize_buy_signals_v2(
        entry_signals,
        current_positions_full,
        equity=equity,
        max_sector_exposure_pct=0.80,  # 80% sector cap
    )
    all_signals = prioritized_entry + exit_signals

    # --- Dynamic Exposure Cap (signal-count × regime hybrid) ---
    # base_cap=68%  +  min(strong_buys × 5%, 20%)  [cautious: bonus capped at 10%]
    # Result range: cautious 68–78%, non-cautious 68–88%
    _STRONG_SIGNAL_THRESHOLD = 0.85
    _BASE_EXPOSURE_CAP = 0.68
    _SIGNAL_STEP = 0.05
    _MAX_BONUS = 0.20
    _CAUTIOUS_BONUS_CAP = 0.10
    _strong_buy_count = sum(
        1 for s in all_signals
        if getattr(s, 'action', None) == 'buy'
        and float(getattr(s, 'signal_strength', 0) or 0) >= _STRONG_SIGNAL_THRESHOLD
    )
    _bonus = min(_strong_buy_count * _SIGNAL_STEP, _MAX_BONUS)
    if price_based_regime == 'cautious':
        _bonus = min(_bonus, _CAUTIOUS_BONUS_CAP)
    dynamic_exposure_cap = _BASE_EXPOSURE_CAP + _bonus
    # -----------------------------------------------------------

    print(f"  Entry Signals:")
    print(f"    BreakoutMomentum: {len(breakout_signals)} signal(s)")
    if intraday_results:
        enhanced_count = sum(1 for s in breakout_signals if '_intraday_enhanced' in s.strategy_id)
        print(f"      (Intraday enhanced: {enhanced_count}/{len(breakout_signals)})")
    print(f"    EventSwing:       {len(event_signals)} signal(s)")
    print()
    print(f"  Exit Signals:")
    print(f"    SimpleExitV2:     {len(exit_signals)} signal(s) (with trailing stop)")
    for _es in exit_signals:
        _notes = " ".join((_es.evidence or {}).get("notes") or []) if hasattr(_es, "evidence") and isinstance(_es.evidence, dict) else ""
        if not _notes:
            _notes = str(getattr(_es, "reasoning", "") or "")
        _trigger, _reason = _classify_exit_reason_from_notes(_notes)
        logger.info(
            "exit_signal_generated symbol=%s trigger=%s reason=%s strength=%.2f",
            _es.symbol,
            _trigger,
            _reason,
            float(getattr(_es, "signal_strength", 0) or 0),
        )
    if not exit_signals:
        logger.info("exit_signals_none: no positions triggered exit criteria this run")
    if cooldown_result:
        metrics = cooldown_result.metrics
        if metrics.in_window:
            status = "ACTIVE" if metrics.active else "INACTIVE"
            def _fmt_pct(value: float | None) -> str:
                return "n/a" if value is None else f"{value:+.2%}"
            print(
                "    OpenShockCooldown:"
                f" {status}"
                f" hits={metrics.signals_hit}"
                f" SPY={_fmt_pct(metrics.spy_gap_pct)}"
                f" QQQ={_fmt_pct(metrics.qqq_gap_pct)}"
                f" losers={_fmt_pct(metrics.losers_ratio)}"
                f" avg_gap={_fmt_pct(metrics.avg_gap_pct)}"
            )
            if metrics.active:
                print(
                    "      "
                    f"held={cooldown_result.held_count} forced_sell={cooldown_result.forced_sell_count}"
                )
                audit_log.log_system_event(
                    "open_shock_cooldown_active",
                    details=(
                        f"hits={metrics.signals_hit} held={cooldown_result.held_count} "
                        f"forced_sell={cooldown_result.forced_sell_count} "
                        f"spy_gap={metrics.spy_gap_pct} qqq_gap={metrics.qqq_gap_pct} "
                        f"losers_ratio={metrics.losers_ratio} avg_gap={metrics.avg_gap_pct}"
                    ),
                )
    
    # Exit signal analysis
    if current_positions_full:
        print(f"    (Checked {len(current_positions_full)} positions)")
        
        # Find positions closest to exit criteria (V2 thresholds)
        STOP_LOSS_PCT = -7.0
        TRAILING_ACTIVATION_PCT = 5.0
        TRAILING_STOP_PCT = 3.0
        MAX_HOLD_DAYS = 10
        
        positions_with_metrics = []
        for sym, pos_data in current_positions_full.items():
            unreal_plpc = float(pos_data.get('unrealized_plpc', 0)) * 100
            positions_with_metrics.append({
                'symbol': sym,
                'pnl_pct': unreal_plpc,
                'dist_to_stop': abs(unreal_plpc - STOP_LOSS_PCT),
                'dist_to_trailing': abs(unreal_plpc - TRAILING_ACTIVATION_PCT),
            })
        
        if positions_with_metrics:
            closest_stop = min(positions_with_metrics, key=lambda x: x['dist_to_stop'])
            closest_trailing = min(positions_with_metrics, key=lambda x: x['dist_to_trailing'])
            print(f"    Closest to stop:  {closest_stop['symbol']} ({closest_stop['pnl_pct']:+.2f}%, need {STOP_LOSS_PCT:.2f}%)")
            print(f"    Closest to trailing: {closest_trailing['symbol']} ({closest_trailing['pnl_pct']:+.2f}%, activation at {TRAILING_ACTIVATION_PCT:+.2f}%)")
    print()
    
    print(f"  (Buy signals prioritized with dynamic sector allocation V2)")
    for sig in all_signals:
        print(f"  -> [{sig.strategy_id}] {sig.symbol}: {sig.action.upper()} strength={sig.signal_strength:.2f}")
        print(f"     {sig.reasoning}")

    if not all_signals:
        print(f"\n  No signals. Try --min-momentum 0.01 to lower threshold.")
        _print_summary([], [], equity, args.dry_run)
        return finish(
            _final_exit_code,
            equity_value=equity,
            extra={"reason": _final_reason or "no_signals"},
        )

    # 8. Decisions
    _section("8. Decision Engine")
    
    # Calculate portfolio metrics
    if current_positions_full:
        total_position_value = sum(float(p.get('market_value', 0)) for p in current_positions_full.values())
        total_unrealized_pl = sum(float(p.get('unrealized_pl', 0)) for p in current_positions_full.values())
        exposure_pct = (total_position_value / equity * 100) if equity > 0 else 0
        
        # Dynamic exposure cap (signal-count × regime hybrid)
        max_exposure_pct = dynamic_exposure_cap * 100
        max_exposure_value = equity * dynamic_exposure_cap
        available_capacity = max_exposure_value - total_position_value
        
        # Calculate sector breakdown
        from stock_swing.risk.position_sizing import SYMBOL_SECTORS
        sector_values = {}
        for sym, pos_data in current_positions_full.items():
            sector = SYMBOL_SECTORS.get(sym.upper(), 'Other')
            value = float(pos_data.get('market_value', 0))
            sector_values[sector] = sector_values.get(sector, 0) + value
        
        # Portfolio summary
        print("  Portfolio Summary:")
        print(f"    Total Positions:      {len(current_positions_full)}")
        print(f"    Total Value:          ${total_position_value:>12,.2f}")
        print(f"    Total Unrealized P&L: ${total_unrealized_pl:>12,.2f}")
        _cap_detail = f"base 68%+{int((_bonus)*100)}% ({_strong_buy_count} strong signals, {price_based_regime})"
        print(f"    Exposure:             {exposure_pct:>12.1f}% (max: {max_exposure_pct:.0f}% [{_cap_detail}])")
        print(f"    Available Capacity:   ${available_capacity:>12,.2f} ({available_capacity/equity*100:.1f}%)")
        print()
        
        # Sector allocation
        if sector_values:
            print("  Sector Allocation:")
            for sector, value in sorted(sector_values.items(), key=lambda x: x[1], reverse=True):
                sector_pct = (value / equity * 100)
                warning = " ⚠️" if sector_pct > 70 else ""  # Adjusted from 40 to 70 (2026-04-26)
                print(f"    {sector:15} ${value:>10,.2f} ({sector_pct:>5.1f}%){warning}")
            print()
        
        # Display current positions with details
        print("  Current Positions:")
        print(f"    {'Symbol':6} {'Qty':>6} {'Avg Entry':>10} {'Current':>10} {'P&L $':>10} {'P&L %':>8}")
        print(f"    {'-'*6} {'-'*6} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")
        winners = 0
        losers = 0
        for sym, pos_data in sorted(current_positions_full.items()):
            qty = int(float(pos_data.get('qty', 0)))
            avg_entry = float(pos_data.get('avg_entry_price', 0))
            current = float(pos_data.get('current_price', 0))
            unreal_pl = float(pos_data.get('unrealized_pl', 0))
            unreal_plpc = float(pos_data.get('unrealized_plpc', 0))
            print(f"    {sym:6} {qty:>6} ${avg_entry:>9.2f} ${current:>9.2f} ${unreal_pl:>9.2f} {unreal_plpc*100:>7.2f}%")
            if unreal_pl > 0:
                winners += 1
            elif unreal_pl < 0:
                losers += 1
        print(f"    {'─'*6} {'─'*6} {'─'*10} {'─'*10} {'─'*10} {'─'*8}")
        print(f"    Total: {len(current_positions_full)} positions ({winners}W / {losers}L)")
        print()
    else:
        print(f"  Current positions: {current_positions if current_positions else '(none)'}")

    risk_validator = RiskValidator(
        min_signal_strength=args.min_signal_strength,
        min_confidence=0.40,
        max_position_size=400,  # Increased from 50 to allow all valid requests (max $377)
    )
    decision_engine = DecisionEngine(runtime_mode=runtime_mode, risk_validator=risk_validator)
    decisions: list[DecisionRecord] = []

    for signal in all_signals:
        decision = decision_engine.process(signal, current_positions=current_positions)
        if isinstance(decision.evidence, dict):
            decision.evidence["market_regime"] = regime_for_sizing
            decision.evidence["macro_regime_raw"] = detected_regime
            decision.evidence["price_regime_raw"] = price_based_regime
        decisions.append(decision)
    attach_run_context(decisions, run_context)
    if experiment_context is not None:
        for _d in decisions:
            if isinstance(getattr(_d, "evidence", None), dict):
                _d.evidence.setdefault("experiment_id", experiment_context.experiment_id)
                _d.evidence.setdefault("config_hash", experiment_context.config_hash)

    # RF-5b: fill AI telemetry fields on every DecisionRecord
    for _d in decisions:
        attach_ai_telemetry(_d)
        if experiment_context is not None:
            if getattr(_d, "experiment_id", None) is None:
                _d.experiment_id = experiment_context.experiment_id
            if getattr(_d, "config_hash", None) is None:
                _d.config_hash = experiment_context.config_hash
        if getattr(_d, "decision_time", None) is None:
            _d.decision_time = _d.generated_at.isoformat()

    for decision in decisions:
        status = "PASS" if decision.action in {"buy", "sell"} and decision.risk_state == "pass" else "SKIP"
        print(f"  [{status}] {decision.symbol}: action={decision.action} risk={decision.risk_state} conf={decision.confidence:.2f}")
        for r in decision.deny_reasons[:2]:
            print(f"       deny: {r}")
        audit_log.log_decision(decision.decision_id, decision.action, decision.strategy_id, decision.symbol, decision.risk_state, decision.mode)

    # 9. Paper execution
    actionable = [d for d in decisions if d.action in {"buy", "sell"} and d.risk_state == "pass" and d.proposed_order is not None]
    
    # Portfolio allocation: Prioritize ETF or Stock buys based on target allocation
    # R2-v2 / H5: pass both config and registry so allocator uses registry classification
    portfolio_allocator = PortfolioAllocator(
        config_path=_ALLOC_CONFIG_PATH,
        registry_path=_REGISTRY_PATH,
    )
    _pre_alloc_buys = sum(1 for d in actionable if getattr(d.proposed_order, 'side', '') == 'buy')
    actionable = portfolio_allocator.filter_decisions_by_allocation(
        decisions=actionable,
        current_positions=current_positions_full,
        etf_symbols=ETF_SYMBOLS,
        account_equity=None,
    )
    # R6-v2: count allocation blocks (unknown symbol + projected band overweight)
    _post_alloc_buys = sum(1 for d in actionable if getattr(d.proposed_order, 'side', '') == 'buy')
    _allocation_blocked_count: int = max(_pre_alloc_buys - _post_alloc_buys, 0)

    # Exit-only mode: block ALL new buy orders (premarket / high-volatility guard)
    # Enable: export PAPER_DEMO_EXIT_ONLY=true
    # Use case: premarket run (09:25 ET) where price signals are noisy and
    # entry quality is low; exits (stop_loss / trailing_stop) still execute normally.
    # Added 2026-07-16
    if os.environ.get("PAPER_DEMO_EXIT_ONLY", "").lower() == "true":
        _exit_only_blocked = [d for d in actionable if d.action == "buy"]
        actionable = [d for d in actionable if d.action != "buy"]
        if _exit_only_blocked:
            _syms = ", ".join(d.symbol for d in _exit_only_blocked[:8])
            print(f"  Exit-only mode (PAPER_DEMO_EXIT_ONLY): blocked {len(_exit_only_blocked)} buy(s) [{_syms}{'...' if len(_exit_only_blocked) > 8 else ''}]")
        else:
            print("  Exit-only mode (PAPER_DEMO_EXIT_ONLY): no buys to block")

    # Off-hours buy guardrail: block new BUY orders outside regular market hours
    # (9:30-16:00 ET). Market orders with extended_hours=False cannot fill during
    # pre-market or after-hours, creating phantom accepted orders (2026-06-03 incident).
    # Override: export PAPER_DEMO_ALLOW_OFFHOURS_BUYS=true
    now_for_filter = datetime.now()
    actionable, blocked_offhours_buys = _filter_buys_outside_regular_hours(actionable, now_for_filter)
    if blocked_offhours_buys:
        _, offhours_status = MarketCalendar.is_regular_market_hours(now_for_filter)
        print(f"  Off-hours buy guardrail [{offhours_status}]: blocked {len(blocked_offhours_buys)} buy(s)")
        sample = ", ".join(sym for sym, _ in blocked_offhours_buys[:5])
        print(f"    blocked: {sample}{' ...' if len(blocked_offhours_buys) > 5 else ''}")

    actionable, deferred_offhours_sells = _filter_sells_outside_regular_hours(actionable, now_for_filter)
    if deferred_offhours_sells:
        _, offhours_status = MarketCalendar.is_regular_market_hours(now_for_filter)
        print(
            f"  Off-hours sell guardrail [{offhours_status}]: deferred "
            f"{len(deferred_offhours_sells)} non-catastrophic sell(s)"
        )
        sample = ", ".join(
            f"{symbol} ({reason})" for symbol, reason, _ in deferred_offhours_sells[:5]
        )
        if sample:
            print(f"    deferred: {sample}{' ...' if len(deferred_offhours_sells) > 5 else ''}")

    # ETF buy guardrail: block new ETF buys by default (PF 0.168 vs Stock 1.731)
    # Set PAPER_DEMO_ALLOW_ETF_BUYS=true to re-enable for experiments
    actionable, blocked_etf_buys = _filter_etf_buys_by_guardrail(actionable, ETF_SYMBOLS)
    if blocked_etf_buys:
        print(f"  ETF buy guardrail: blocked {len(blocked_etf_buys)} new ETF buy(s): {', '.join(blocked_etf_buys)}")

    # Risk budget guardrail: block all new buys when open risk >= 8% of equity
    # Warn at 5%. Override: export PAPER_DEMO_SKIP_RISK_BUDGET=true
    actionable, blocked_risk_budget, risk_budget_result = _filter_buys_by_risk_budget(
        actionable, project_root, equity
    )
    actionable, blocked_cluster_cap = _filter_buys_by_cluster_cap(
        actionable, current_positions_full, equity
    )

    # R2-D: Entry quality filters (volume / ADR / rolling PF gate)
    _records_by_symbol: dict[str, list] = {}
    for _rec in all_records:
        _sym = getattr(_rec, "symbol", None) or ""
        if _sym:
            _records_by_symbol.setdefault(_sym, []).append(_rec)
    _ef_config = EntryFilterConfig.from_env()
    _entry_filter = EntryFilterEngine(_ef_config)
    _ef_result = _entry_filter.filter(
        decisions=actionable,
        records_by_symbol=_records_by_symbol,
        closed_trades=pnl_tracker.state.trades,
        etf_symbols=set(ETF_SYMBOLS),
    )
    # BUY STOP LIST: compute once after filter (run-independent, from full PF history)
    _buy_stop_list = get_permanent_block_summary(
        closed_trades=pnl_tracker.get_clean_closed_trades(),
        config=_ef_config,
        etf_symbols=set(ETF_SYMBOLS),
    )
    _ef_result.stats["buy_stop_list"] = _buy_stop_list
    actionable = _ef_result.passed
    if _ef_result.blocked:
        _vol_n = len(_ef_result.stats.get("volume_blocked", []))
        _adr_n = len(_ef_result.stats.get("adr_blocked", []))
        _pf_n  = len(_ef_result.stats.get("rolling_pf_blocked", []))
        print(
            f"  🔎 Entry filter blocked {len(_ef_result.blocked)} buy(s) "
            f"(volume={_vol_n} adr={_adr_n} pf_gate={_pf_n}): "
            + ", ".join(f"{sym}[{rsn.split(':')[0]}]" for sym, rsn in _ef_result.blocked[:5])
            + (" ..." if len(_ef_result.blocked) > 5 else "")
        )
        audit_log.log_system_event(
            "entry_filter_blocked_buys",
            details=f"{len(_ef_result.blocked)} buy(s): {[s for s, _ in _ef_result.blocked[:5]]}",
        )

    _critical_buy_halt_reasons = list(dict.fromkeys(_buy_halt_reasons + _day_start_missing_metrics))
    if _critical_buy_halt_reasons:
        try:
            from stock_swing.guardrails.rule_engine import GuardAction as _CriticalGuardAction, GuardDecision as _CriticalGuardDecision

            if "_breaker_store" in dir() and _breaker_store is not None:
                _breaker_state = _breaker_store.apply_decision(
                    _CriticalGuardDecision(action=_CriticalGuardAction.halt, triggered=[])
                )
        except Exception as _guard_halt_exc:
            logger.warning("guardrail fail-closed HALT persistence failed: %s", _guard_halt_exc)
        _blocked_symbols = [getattr(_cand, "symbol", "") for _cand in actionable if getattr(_cand, "action", "") == "buy"]
        actionable = [d for d in actionable if getattr(d, "action", "") != "buy"]
        if _blocked_symbols:
            print(
                "  🛡 Guardrail fail-closed: blocked "
                f"{len(_blocked_symbols)} buy(s) due to critical missing evidence: "
                f"{', '.join(_critical_buy_halt_reasons)}"
            )
        _final_exit_code = 1
        _final_reason = _final_reason or "guardrail_missing_metrics"

    if (
        not _critical_buy_halt_reasons
        and _guard_engine is not None
        and apply_to_buy_candidate is not None
        and not _warning_only
    ):
        # F2: compute real broker/tracker mismatch count instead of hardcoded 0
        _bt_diff_prebuy = _build_broker_tracker_diff(
            list(current_positions_full.values()) if current_positions_full else [],
            pnl_tracker.get_open_positions(),
        )
        # R0-v2-C: full RiskSnapshot for pre-buy evaluation
        _prebuy_snapshot = build_risk_snapshot(
            trades=pnl_tracker.state.trades,
            equity=equity,
            unrealized_pnl=sum(float(p.get("unrealized_pl", 0) or 0)
                               for p in current_positions_full.values()) if current_positions_full else 0.0,
            prev_unrealized_pnl=_day_start_unrealized,
            stale_price_event_count=len(stale_symbols) if "stale_symbols" in dir() else 0,
            broker_tracker_mismatch_count=_bt_diff_prebuy["mismatch_count"],
        )
        for _missing_metric in _day_start_missing_metrics:
            if _missing_metric not in _prebuy_snapshot.missing_metrics:
                _prebuy_snapshot.missing_metrics.append(_missing_metric)
        _guard_metrics_now = _prebuy_snapshot.to_metrics()
        _guard_decision_now = _guard_engine.evaluate(_guard_metrics_now)

        # R0-v2-C: reduce_size → exposure_cap_override に反映
        _reduce_size_multiplier = 1.0
        from stock_swing.guardrails.rule_engine import GuardAction as _GA
        if _guard_decision_now.action == _GA.reduce_size:
            _reduce_size_multiplier = 0.5
            print(f"  🛡 Guardrail reduce_size: position sizing reduced to {_reduce_size_multiplier:.0%}")

        # R0-v2-C: flatten_risky → operator approval プラン生成（自動実行禁止）
        if _guard_decision_now.action == _GA.flatten_risky:
            _risky_syms = [p.get("symbol","") for p in (current_positions_full.values() if current_positions_full else [])]
            print(f"  ⚠️  Guardrail flatten_risky: manual approval required for {len(_risky_syms)} position(s): {', '.join(_risky_syms[:5])}")
            logger.warning("guardrail_flatten_risky positions=%s (operator approval required, NOT auto-flattened)", _risky_syms)

        _guardrail_blocked = []
        _new_actionable = []
        for _cand in actionable:
            _cand_dict = {"symbol": getattr(_cand, "symbol", ""), "action": getattr(_cand, "action", "")}
            _result = apply_to_buy_candidate(_cand_dict, _guard_decision_now, _breaker_state)
            if _result.get("action") == "deny" and _cand_dict.get("action") == "buy":
                _guardrail_blocked.append(_cand_dict["symbol"])
            else:
                _new_actionable.append(_cand)
        if _guardrail_blocked:
            print(f"  🛡 Guardrail blocked {len(_guardrail_blocked)} buy(s): {', '.join(_guardrail_blocked[:5])}")
        actionable = _new_actionable
    if blocked_cluster_cap:
        for sym, reason in blocked_cluster_cap:
            print(f"  🚫 Cluster cap block: {sym} — {reason}")
        audit_log.log_system_event(
            "cluster_cap_blocked_buys",
            details=f"{len(blocked_cluster_cap)} buy(s): {[s for s, _ in blocked_cluster_cap[:5]]}",
        )

    # Log allocation status
    alloc_status = portfolio_allocator.get_allocation_status(
        current_positions=current_positions_full,
        etf_symbols=ETF_SYMBOLS,
        account_equity=equity,
    )
    _etf_cap_indicator = " ⚠️ CAP HIT" if alloc_status["etf_cap_hit"] else ""
    print(f"\n  Portfolio Allocation (ETF cap = {alloc_status['target_etf_pct']:.0%} of equity = ${alloc_status['etf_cap_usd']:,.0f}):")
    print(f"    ETF:   {alloc_status['current_etf_pct']:>6.1%} of equity = ${alloc_status['etf_value']:>10,.0f}{_etf_cap_indicator}")
    print(f"    Stock: ${alloc_status['stock_value']:>10,.0f} (unrestricted)")
    if alloc_status["needs_rebalance"]:
        print(f"    ℹ️  ETF below target ({alloc_status['target_etf_pct']:.0%}): ETF buys prioritized")

    if args.dry_run:
        print("\n  DRY RUN - would submit:")
        for d in actionable:
            o = d.proposed_order
            print(f"    {o.side.upper()} {o.qty} {o.symbol} type={o.order_type} tif={o.time_in_force}")
        _print_summary(decisions, [], equity, args.dry_run)
        from stock_swing.reporting.console_summary import ConsoleSummary

        console_summary = ConsoleSummary.build(
            run_id=run_context.run_id if "run_context" in dir() else "unknown",
            equity=equity,
            open_position_count=len(current_positions_full),
            realized_pnl=float(pnl_tracker.state.cumulative_realized_pnl or 0),
            unrealized_pnl=(
                sum(float(p.get("unrealized_pl", 0) or 0) for p in current_positions_full.values())
                if current_positions_full else 0.0
            ),
            decisions=decisions,
            submissions=[],
            cluster_blocks=[sym for sym, _ in blocked_cluster_cap] if "blocked_cluster_cap" in dir() else [],
            risk_budget_pct=risk_budget_result.get("pct_of_equity", 0) if "risk_budget_result" in dir() else 0,
            stale_symbols=list(stale_symbols) if "stale_symbols" in dir() else [],
            price_sources={},
            market_regime=regime_for_sizing if "regime_for_sizing" in dir() else "unknown",
            warnings=[],
            experiment_id=experiment_context.experiment_id if experiment_context is not None else "unknown",
            guardrail_status=_breaker_state.status if "_breaker_state" in dir() and _breaker_state is not None else "unknown",
            api_metrics=_build_api_metrics(latency_tracker),
            price_integrity=_build_price_integrity(
                stale_symbols if "stale_symbols" in dir() else [],
                {},
            ),
            asset_class_breakdown=pnl_tracker.get_asset_class_breakdown(),
            exit_attribution_breakdown=pnl_tracker.get_exit_attribution_breakdown(),
            broker_tracker_diff=_build_broker_tracker_diff(
                list(current_positions_full.values()) if current_positions_full else [],
                pnl_tracker.get_open_positions(),
            ),
            # RF: 台帳品質・フィルター・シャドウ
            ledger_quality=pnl_tracker.get_ledger_quality_report(),
            entry_filter_stats=_ef_result.stats if "_ef_result" in dir() else {},
            sector_shock_shadow_count=_ssh_shadow_count if "_ssh_shadow_count" in dir() else 0,
            # RF-5b: AI telemetry
            ai_metrics=build_ai_metrics_from_decisions(decisions),
            # R0-v2-A: safety gate
            ledger_gate_status=_ledger_gate_status if "_ledger_gate_status" in dir() else "UNKNOWN",
            # R0-v2-B: equity bridge
            equity_bridge=_build_equity_bridge(
                broker_equity=equity,
                pnl_tracker=pnl_tracker,
                unrealized_pnl=(
                    sum(float(p.get("unrealized_pl", 0) or 0)
                        for p in current_positions_full.values())
                    if current_positions_full else 0.0
                ),
            ),
            # R6-v2: funnel stages (dry-run has no submissions/reconciliation)
            funnel_stages={
                "generated": len(decisions),
                "risk_denied": sum(1 for d in decisions if getattr(d, "action", "") == "deny"),
                "entry_blocked": len(_ef_result.blocked) if "_ef_result" in dir() else 0,
                "cluster_blocked": len(blocked_cluster_cap) if "blocked_cluster_cap" in dir() else 0,
                "allocation_blocked": _allocation_blocked_count if "_allocation_blocked_count" in dir() else 0,
                "guardrail_blocked": 0,
                "qty_zero": sum(skipped_buy_reasons.values()) if "skipped_buy_reasons" in dir() else 0,
                "submitted": 0,
                "accepted": 0,
                "filled": 0,
                "reconciled": 0,
            },
            open_position_details=pnl_tracker.get_open_position_signal_summary(
                broker_positions=current_positions_full or {}
            ),
            # circuit breaker detail for HALT visibility
            circuit_breaker_detail={
                "status": _breaker_state.status if "_breaker_state" in dir() and _breaker_state is not None else "unknown",
                "triggered_at": _breaker_state.triggered_at if "_breaker_state" in dir() and _breaker_state is not None else None,
                "triggered_rules": list(_breaker_state.triggered_rules or []) if "_breaker_state" in dir() and _breaker_state is not None else [],
                "reason": _breaker_state.reason if "_breaker_state" in dir() and _breaker_state is not None else "",
            },
            # Plan A: Stop Loss Health panel
            stop_loss_health=_build_stop_loss_health(
                pnl_tracker=pnl_tracker,
                exit_strat=exit_strat if "exit_strat" in dir() else None,
                current_prices={sym: float(pos.get("current_price", 0) or 0)
                                for sym, pos in (current_positions_full or {}).items()},
            ),
            # R7-v2-A: Source SLA
            source_sla=_get_source_sla(project_root),
        )
        console_summary.emit(save_path=project_root / "reports/console/latest_console_summary.json")
        return finish(
            _final_exit_code,
            decisions=decisions,
            equity_value=equity,
            extra={"reason": _final_reason or "dry_run"},
        )

    # R2-v2 / H5: pass AllocationConfig so PositionSizingPolicy uses same YAML multipliers
    executor = PaperExecutor(runtime_mode=runtime_mode, broker_client=broker, alloc_config=_ALLOC_CONFIG)
    reconciler = Reconciler(broker_client=broker)
    # R0-v2-C: apply reduce_size multiplier to exposure cap if guardrail fired
    _effective_exposure_cap = (
        dynamic_exposure_cap * _reduce_size_multiplier
        if "_reduce_size_multiplier" in dir() and _reduce_size_multiplier < 1.0
        else dynamic_exposure_cap
    )
    actionable, preview_cache, skipped_buy_reasons, skipped_buy_symbols = _prefilter_actionable_buys_for_submission(
        actionable,
        executor,
        exposure_cap_override=_effective_exposure_cap,
    )

    _section("9. Paper Order Submission")
    print(f"  Actionable: {len(actionable)}  Denied/held: {len(decisions) - len(actionable)}")
    if skipped_buy_reasons:
        total_skipped_buys = sum(skipped_buy_reasons.values())
        print(f"  Preflight skipped buys: {total_skipped_buys}")
        for reason, count in sorted(skipped_buy_reasons.items(), key=lambda item: (-item[1], item[0])):
            print(f"    {reason}: {count}")
        sample_skips = ", ".join(f"{symbol} ({reason})" for symbol, reason in skipped_buy_symbols[:5])
        if sample_skips:
            print(f"    examples: {sample_skips}")
        if total_skipped_buys > 5:
            print(f"    ... and {total_skipped_buys - 5} more")

    if not actionable:
        print("\n  No actionable decisions after exposure preflight.")
        _print_summary(decisions, [], equity, args.dry_run)
        return finish(
            _final_exit_code,
            decisions=decisions,
            equity_value=equity,
            extra={"reason": _final_reason or "no_actionable_decisions"},
        )

    submissions: list[OrderSubmission] = []
    _projected_positions_for_band = {
        sym: dict(pos) for sym, pos in (current_positions_full or {}).items()
    }
    
    # Symbol-level position size limit.
    # 2026-05-15 risk tightening: stocks use 6% of equity, ETFs use 70% of that cap
    # to reduce concentration in thematic / sector products.

    for decision in actionable:
        o = decision.proposed_order
        try:
            preview_qty, preview_sizing = preview_cache.get(decision.decision_id, (None, None))

            # Guard: skip SELL orders for positions the broker no longer holds.
            # Without this, a stale tracker position generates a 0-qty SELL which
            # is rejected by the broker, inflating order_rejection_rate_pct and
            # risking a spurious circuit-breaker HALT.
            if o.side == "sell":
                broker_qty = current_positions.get(o.symbol, 0)
                if broker_qty <= 0:
                    print(
                        f"\n  SKIP SELL {o.symbol}: no broker position "
                        f"(broker_qty=0, tracker may be stale — rebuild recommended)"
                    )
                    logger.warning(
                        "sell_skipped_no_broker_position symbol=%s "
                        "tracker_open=True broker_qty=0",
                        o.symbol,
                    )
                    continue

            # Check symbol-level position size limit for BUY orders
            if o.side == "buy" and o.symbol in current_positions_full:
                existing_pos = current_positions_full[o.symbol]
                existing_value = float(existing_pos.get('market_value', 0))
                
                # Determine position limit using the same sizing policy as order generation.
                # BUG FIX (2026-07-30): Must use alloc_config multipliers (stock=1.0, etf=1.0)
                # not the legacy effective_position_notional_pct() which bakes in
                # STOCK_POSITION_SIZE_MULTIPLIER=0.5 → gives half the real limit (e.g. $39K vs $78K).
                # This mismatch caused all existing-position BUYs to be blocked with
                # allocation_blocked even though the executor would size them correctly.
                is_etf = o.symbol in ETF_SYMBOLS
                _base_pct = float(_ALLOC_CONFIG.stock_new_buy_multiplier if not is_etf else _ALLOC_CONFIG.etf_new_buy_multiplier)
                position_limit_pct = DEFAULT_MAX_POSITION_NOTIONAL_PCT * _base_pct
                max_position_value = equity * position_limit_pct
                
                # Get estimated order value
                if preview_qty is None or preview_sizing is None:
                    preview_qty, preview_sizing = executor._calculate_position_size(
                        decision,
                        market_regime=(decision.evidence.get("market_regime") if isinstance(decision.evidence, dict) else "neutral") or "neutral",
                        exposure_cap_override=dynamic_exposure_cap,
                    )

                # Estimate order value (qty * current_price)
                current_price = get_mid_price(o.symbol)
                if current_price <= 0:
                    _reason = "allocation_blocked: price_unavailable (position_limit check)"
                    print(f"\n  SKIP BUY {o.symbol}: allocation price unavailable")
                    decision.block_reason = _reason
                    logger.warning(
                        "buy_skipped_allocation_blocked symbol=%s reason=%s decision_id=%s",
                        o.symbol, _reason, decision.decision_id,
                    )
                    _allocation_blocked_count += 1
                    continue
                estimated_order_value = preview_qty * current_price
                
                total_value = existing_value + estimated_order_value
                
                if total_value > max_position_value:
                    asset_type = "ETF" if is_etf else "Stock"
                    _reason = (
                        f"allocation_blocked: position_limit "
                        f"existing=${existing_value:.0f} + order=${estimated_order_value:.0f} "
                        f"= ${total_value:.0f} > cap=${max_position_value:.0f} "
                        f"({position_limit_pct:.0%} of equity, {asset_type})"
                    )
                    print(f"\n  SKIP {o.side.upper()} {preview_qty} {o.symbol} ({asset_type}): Position limit (${existing_value:.0f} + ${estimated_order_value:.0f} = ${total_value:.0f} > ${max_position_value:.0f} [{position_limit_pct:.0%}])")
                    decision.block_reason = _reason
                    logger.warning(
                        "buy_skipped_allocation_blocked symbol=%s reason=%s decision_id=%s",
                        o.symbol, _reason, decision.decision_id,
                    )
                    _allocation_blocked_count += 1
                    continue
            
            if preview_qty is None or preview_sizing is None:
                preview_qty, preview_sizing = executor._calculate_position_size(
                    decision,
                    market_regime=(decision.evidence.get("market_regime") if isinstance(decision.evidence, dict) else "neutral") or "neutral",
                    exposure_cap_override=dynamic_exposure_cap,
                )
            if o.side == "buy":
                current_price = get_mid_price(o.symbol)
                if preview_qty and preview_qty >= 1 and current_price > 0:
                    projected_notional = float(preview_qty) * float(current_price)
                    band_result = portfolio_allocator.check_projected_band(
                        o.symbol,
                        projected_notional,
                        _projected_positions_for_band,
                        equity,
                    )
                    if not band_result.allowed:
                        _reason = f"allocation_blocked: {band_result.reason} (projected_notional=${projected_notional:,.0f})"
                        print(
                            f"\n  SKIP BUY {o.symbol}: {band_result.reason} "
                            f"(projected_notional=${projected_notional:,.0f})"
                        )
                        decision.block_reason = _reason
                        logger.warning(
                            "buy_skipped_allocation_blocked symbol=%s reason=%s decision_id=%s",
                            o.symbol, _reason, decision.decision_id,
                        )
                        _allocation_blocked_count += 1
                        continue
                else:
                    _reason = "allocation_blocked: price_unavailable (projected_band check)"
                    print(f"\n  SKIP BUY {o.symbol}: allocation price unavailable")
                    decision.block_reason = _reason
                    logger.warning(
                        "buy_skipped_allocation_blocked symbol=%s reason=%s decision_id=%s",
                        o.symbol, _reason, decision.decision_id,
                    )
                    _allocation_blocked_count += 1
                    continue
            preview_basis = ""
            if preview_sizing:
                preview_basis = (
                    f" [risk={preview_sizing.get('shares_by_risk')} "
                    f"notional={preview_sizing.get('shares_by_notional')} "
                    f"exposure={preview_sizing.get('shares_by_exposure')}]"
                )
            print(f"\n  Submitting {o.side.upper()} {preview_qty} {o.symbol} ({o.order_type}){preview_basis} ... ", end="", flush=True)
            sub = executor.submit(
                decision,
                current_qty=current_positions.get(o.symbol) if o.side == "sell" else None,
                precomputed_qty=preview_qty,
                precomputed_sizing=preview_sizing,
            )
            submissions.append(sub)
            if sub.status == "submitted":
                sizing = sub.sizing_details or {}
                if sizing:
                    decision.evidence["sizing"] = sizing
                    print(
                        f"OK broker_id={sub.broker_order_id} qty={sub.qty} "
                        f"[risk={sizing.get('shares_by_risk')} notional={sizing.get('shares_by_notional')} exposure={sizing.get('shares_by_exposure')}]"
                    )
                else:
                    print(f"OK broker_id={sub.broker_order_id} qty={sub.qty}")

                # Persist exit reason for sell orders so reconcile_orders can
                # retrieve it when the fill is detected later.
                if o.side == "sell" and sub.broker_order_id:
                    notes = " ".join((decision.evidence or {}).get("notes") or [])
                    _exit_trigger, _exit_reason = _classify_exit_reason_from_notes(notes)
                    write_exit_reason(
                        project_root=project_root,
                        broker_order_id=sub.broker_order_id,
                        symbol=o.symbol,
                        exit_trigger=_exit_trigger,
                        exit_reason=_exit_reason,
                        metadata={
                            "signal_strength": getattr(decision, "signal_strength", None),
                            "return_pct": decision.evidence.get("return_pct") if isinstance(decision.evidence, dict) else None,
                        },
                    )
                    # R1-B: record exit_signal event in the durable event store so
                    # audit tooling can trace signal → submission → fill.
                    pnl_tracker.event_store.append(TradeEvent.create(
                        "exit_signal",
                        symbol=o.symbol,
                        broker_order_id=sub.broker_order_id,
                        run_id=run_context.run_id,
                        payload={
                            "exit_trigger": _exit_trigger,
                            "exit_reason": _exit_reason,
                            "signal_strength": getattr(decision, "signal_strength", None),
                            "return_pct": decision.evidence.get("return_pct") if isinstance(decision.evidence, dict) else None,
                            "source": "SimpleExitV2",
                        },
                    ))
                    logger.info(
                        "exit_signal_submitted symbol=%s broker_order_id=%s exit_reason=%s",
                        o.symbol, sub.broker_order_id, _exit_reason,
                    )

                if o.side == "buy":
                    _existing_projected = _projected_positions_for_band.get(o.symbol, {})
                    _existing_value = float(_existing_projected.get("market_value", 0) or 0)
                    _projected_positions_for_band[o.symbol] = {
                        **_existing_projected,
                        "symbol": o.symbol,
                        "market_value": _existing_value + float(sub.qty) * float(current_price),
                    }
                    # Only buy submissions create new open trades in the P&L tracker.
                    # Sell submissions are exits and must be recorded only after actual fills
                    # are confirmed during reconciliation.
                    entry_price = resolve_recorded_entry_price(sub, o.symbol, o.limit_price)

                    if entry_price > 0:
                        pnl_tracker.record_submission(
                            symbol=o.symbol,
                            strategy_id=decision.strategy_version_id,
                            side=o.side,
                            qty=sub.qty,
                            price=entry_price,
                            broker_order_id=sub.broker_order_id,
                            decision_id=decision.decision_id,
                            original_strategy_id=decision.strategy_id,
                            strategy_version_id=decision.strategy_version_id,
                            account_id=os.environ.get("BROKER_ACCOUNT_ID"),
                            signal_strength=getattr(decision, "signal_strength", None),
                            asset_class=getattr(decision.sizing, "asset_class_used", None) if decision.sizing else None,
                            # R0-v2-D: durable metadata 伝播
                            run_id=run_context.run_id if "run_context" in dir() else None,
                            experiment_id=(
                                experiment_context.experiment_id
                                if experiment_context is not None else None
                            ),
                            config_hash=(
                                experiment_context.config_hash
                                if experiment_context is not None else None
                            ),
                        )
                    else:
                        print(f"WARN: Skipped P&L tracking for {o.symbol} (entry_price unavailable)")
            else:
                print(f"WARN {sub.status}: {sub.reject_reason}")
            audit_log.log_submission(sub.submission_id, sub.decision_id, sub.symbol, sub.side, sub.qty, sub.status, sub.broker_order_id)
            if sub.sizing_details:
                _sd = sub.sizing_details
                _before = _sd.get('before_multiplier_qty')
                _after = _sd.get('after_multiplier_qty')
                _mult = _sd.get('multiplier_applied')
                _mult_str = (
                    f" [×{_mult:.2f}: {_before}→{_after}]"
                    if (_mult is not None and _mult != 1.0 and _before is not None)
                    else ""
                )
                print(
                    f"    sizing: equity=${_sd.get('account_equity')} "
                    f"price=${_sd.get('current_price')} "
                    f"final={_sd.get('final_shares')}{_mult_str} "
                    f"max_loss=${_sd.get('max_loss_usd')} "
                    f"max_notional=${_sd.get('max_position_notional_usd')} "
                    f"remaining_exposure=${_sd.get('remaining_exposure_capacity_usd')}"
                )
        except Exception as exc:
            print(f"ERROR: {exc}")
            audit_log.log_system_event("submission_error", AuditLevel.ERROR, details=f"{decision.symbol}: {exc}")

    _save_decisions(
        decisions,
        store,
        ts_tag,
        run_id=run_context.run_id if "run_context" in dir() else None,
        experiment_id=experiment_context.experiment_id if experiment_context is not None else None,
        config_hash=experiment_context.config_hash if experiment_context is not None else None,
    )

    # 10. Record daily snapshot (before reconciliation to avoid SIGTERM issues)
    try:
        if not args.dry_run:
            pnl_tracker.record_daily_snapshot(
                equity=equity,
                signals_generated=len(all_signals),
                orders_submitted=len([s for s in submissions if s.status == "submitted"]),
            )
            print("  ✓ Daily snapshot recorded")
    except Exception as e:
        print(f"  WARN: Daily snapshot failed: {e}")

    # 11. Reconciliation
    submitted = [s for s in submissions if s.broker_order_id]
    if submitted:
        _section("11. Reconciliation")
        # Build decision lookup so each submission maps to its own decision,
        # not to whichever 'decision' variable happens to be in outer scope.
        decision_by_id = {d.decision_id: d for d in decisions}
        for sub in submitted:
            try:
                result = reconciler.reconcile(sub)
                ok_statuses = {"submitted", "accepted", "new", "pending_new", "filled", "partially_filled"}
                ok = result.broker_status in ok_statuses
                print(f"  {'OK' if ok else 'WARN'}: {sub.symbol} broker_status={result.broker_status} discrepancies={len(result.discrepancies)}")
                for disc in result.discrepancies:
                    print(f"    {disc}")

                # CRITICAL FIX: Only record exit when actually filled
                # Previously accepted/submitted/new orders were prematurely closed using mid_price
                if result.side == 'sell' and result.broker_status in {'filled', 'partially_filled'}:
                    exit_price = None
                    exit_qty = None
                    if result.fills_detected:
                        try:
                            fill = result.fills_detected[0]
                            exit_price = float(fill.get('avg_price') or 0)
                            exit_qty = int(float(fill.get('qty') or 0))
                        except Exception:
                            exit_price = None
                            exit_qty = None
                    
                    # Only record if we have actual fill data
                    if exit_price and exit_price > 0:
                        # FIX-LEDGER-RACE (2026-07-31): ingest+consume this fill through
                        # FillLedger BEFORE recording the exit. This makes the inline
                        # reconciler participate in the same exactly-once ledger used by
                        # reconcile_orders.py cron, so a fill cannot be silently
                        # double-consumed (or have its consumption_events overwritten)
                        # by the two independent reconcile paths racing on the same
                        # broker fill within the 15-minute cron window.
                        _fill_already_consumed = False
                        _fill_quarantined = False
                        if sub.broker_order_id:
                            try:
                                _fk = fill_ledger.ingest(
                                    {
                                        "id": sub.broker_order_id,
                                        "order_id": sub.broker_order_id,
                                        "symbol": sub.symbol,
                                        "side": "sell",
                                        "qty": exit_qty,
                                        "filled_avg_price": exit_price,
                                        "filled_at": datetime.now(timezone.utc).isoformat(),
                                    },
                                    quarantine_on_missing=True,
                                )
                                fill_ledger.consume(
                                    _fk,
                                    trade_id=f"inline_reconcile:{sub.submission_id}",
                                    qty=exit_qty,
                                )
                            except FillQuarantinedError as _fq_exc:
                                _fill_quarantined = True
                                print(f"  WARN: {sub.symbol} fill quarantined, skipping exit record: {_fq_exc}")
                            except FillAlreadyConsumedError as _fac_exc:
                                _fill_already_consumed = True
                                print(f"  INFO: {sub.symbol} fill already consumed (race with cron reconcile?): {_fac_exc}")

                        if not _fill_already_consumed and not _fill_quarantined:
                            # Use the correct decision for THIS submission (not outer-scope variable)
                            decision_for_sub = decision_by_id.get(sub.decision_id)
                            notes_text = " ".join(
                                (getattr(decision_for_sub, 'evidence', None) or {}).get("notes") or []
                            ) if decision_for_sub else ""
                            _exit_trigger, exit_reason = _classify_exit_reason_from_notes(notes_text)
                            pnl_tracker.record_exit(
                                symbol=sub.symbol,
                                exit_price=exit_price,
                                exit_qty=exit_qty,
                                broker_order_id=sub.broker_order_id,
                                exit_strategy_id=getattr(decision_for_sub, 'strategy_id', 'unknown'),
                                exit_reason=exit_reason,
                            )
                            # R1-B: inline reconcile consumed this fill; remove from
                            # pending_exit_reasons so cron reconcile doesn't re-process.
                            if sub.broker_order_id:
                                delete_exit_reason(project_root, sub.broker_order_id)

                audit_log.log_reconciliation(sub.submission_id, sub.broker_order_id, result.status_matched, result.discrepancies)
                _reconciled_count = _reconciled_count + 1 if "_reconciled_count" in dir() else 1
            except Exception as exc:
                print(f"  WARN: {sub.symbol} reconcile failed: {exc}")

    if _guard_engine is not None and _breaker_store is not None and post_run_update is not None:
        try:
            # G1 fix: if new orders were submitted, wait briefly so broker API reflects fills
            # before computing broker/tracker diff (prevents race-condition false HALT).
            _new_submissions = [
                s for s in submissions
                if getattr(s, "status", "") in {"submitted", "accepted", "filled", "partially_filled"}
            ] if "submissions" in dir() else []
            if _new_submissions:
                import time as _time
                _wait_secs = 3
                print(f"  Waiting {_wait_secs}s for broker API to reflect {len(_new_submissions)} order(s)...")
                _time.sleep(_wait_secs)
                # Re-fetch fresh positions after wait
                try:
                    _fresh_positions_env = broker.fetch_positions()
                    _fresh_positions_list = _fresh_positions_env.payload if isinstance(_fresh_positions_env.payload, list) else []
                    _positions_for_diff = _fresh_positions_list
                except Exception as _fe:
                    logger.warning("Re-fetch positions after submission failed (using stale): %s", _fe)
                    _positions_for_diff = list(current_positions_full.values()) if current_positions_full else []
            else:
                _positions_for_diff = list(current_positions_full.values()) if current_positions_full else []

            # F2: compute real broker/tracker mismatch for post-run guardrail evaluation
            _bt_diff_postrun = _build_broker_tracker_diff(
                _positions_for_diff,
                pnl_tracker.get_open_positions(),
            )

            # G1-v2: exclude submission-lag symbols from mismatch count.
            # When a BUY is just submitted, the tracker records it immediately but the broker
            # positions API may lag (especially at market open) → symbol appears in tracker_only.
            # When a SELL is just submitted, the tracker closes it immediately but the broker
            # may still show it → symbol appears in broker_only.
            # Both are transient API-lag false positives, not real integrity issues.
            # G1-v2 / G1-v2-b: delegate to canonical module so tests call same code
            from stock_swing.guardrails.postrun_mismatch import apply_lag_exclusion
            _lag_result = apply_lag_exclusion(_bt_diff_postrun, _new_submissions)
            _adjusted_mismatch = _lag_result.adjusted_mismatch_count

            # R0-v2-C: full RiskSnapshot for post-run evaluation
            _lt_metrics = _build_api_metrics(latency_tracker)
            _api_error_rate_pct = (
                _lt_metrics.get("error_count", 0) /
                max(_lt_metrics.get("call_count", 1), 1) * 100
            )
            _run_ai_metrics = build_ai_metrics_from_decisions(
                decisions if "decisions" in dir() else []
            )
            _run_tokens = (
                _run_ai_metrics.get("input_tokens", 0) +
                _run_ai_metrics.get("output_tokens", 0)
            )
            _daily_budget = _run_ai_metrics.get("daily_token_budget", 300_000)
            _token_spend_spike_pct = max(0.0, (_run_tokens / max(_daily_budget, 1) - 1.0) * 100)
            _order_rejection_rate_pct = (
                len([s for s in submissions if s.status not in {"submitted", "accepted", "filled", "partially_filled"}])
                / len(submissions) * 100
                if "submissions" in dir() and len(submissions) >= 4 else 0.0
            )
            _postrun_snapshot = build_risk_snapshot(
                trades=pnl_tracker.state.trades,
                equity=equity,
                unrealized_pnl=sum(float(p.get("unrealized_pl", 0) or 0)
                                   for p in (_positions_for_diff if "_positions_for_diff" in dir() else [])),
                prev_unrealized_pnl=_day_start_unrealized,
                stale_price_event_count=len(stale_symbols) if "stale_symbols" in dir() else 0,
                broker_tracker_mismatch_count=_adjusted_mismatch,
                api_error_rate_pct=_api_error_rate_pct,
                order_rejection_rate_pct=_order_rejection_rate_pct,
                token_spend_spike_pct=_token_spend_spike_pct,
            )
            # FIX-GUARDRAIL-2: Propagate day-start missing metrics into snapshot
            if _day_start_missing_metrics:
                for _mm in _day_start_missing_metrics:
                    if _mm not in _postrun_snapshot.missing_metrics:
                        _postrun_snapshot.missing_metrics.append(_mm)
            if _postrun_snapshot.missing_metrics:
                from stock_swing.guardrails.rule_engine import GuardAction as _PostGuardAction, GuardDecision as _PostGuardDecision

                _post_state = _breaker_store.apply_decision(
                    _PostGuardDecision(action=_PostGuardAction.halt, triggered=[])
                )
                _final_exit_code = 1
                _final_reason = _final_reason or "guardrail_missing_metrics"
                logger.error(
                    "guardrail_post_run_missing_metrics=%s",
                    sorted(set(_postrun_snapshot.missing_metrics)),
                )
            else:
                _post_metrics = _postrun_snapshot.to_metrics()
                _post_state = post_run_update(_post_metrics, _guard_engine, _breaker_store)

            # R0-v2-A: recovery_pending → ok 遷移（clean scheduled run 検証）
            if _post_state.status == "recovery_pending" and _adjusted_mismatch == 0:
                _post_state = _breaker_store.mark_clean_run_complete()
                if _post_state.status == "ok":
                    logger.info("circuit_breaker: recovery_pending → ok (clean scheduled run verified)")
                    print("  INFO: circuit_breaker recovery_pending → ok (clean run 検証済み)")

            if _post_state.status != "ok":
                logger.warning("guardrail_post_run status=%s action=%s", _post_state.status, _post_state.action)
        except Exception as _exc:
            if hard_mode:
                if _breaker_store is not None:
                    try:
                        _breaker_store.halt(reason=f"guardrail_post_run_failure: {_exc}")
                    except Exception:
                        pass
                logger.critical("Guardrail post-run update failed in hard mode — HALT")
                sys.exit(1)
            logger.warning("Guardrail post-run update failed (non-fatal): %s", _exc)

    audit_log.log_system_event("paper_demo_complete", details=f"decisions={len(decisions)} submitted={len(submissions)}")

    # FIX-P6-6 / R0-v2-D: join coverage report (decision -> order -> trade)
    # Write to file every run so health dashboard can track coverage over time.
    try:
        _closed = [t for t in pnl_tracker.state.trades if t.get("status") == "closed"]
        # Separate legacy (pre-fix epoch) from post-fix epoch trades
        _post_fix_epoch = "2026-07-29"  # Batch A/B fix date
        _post_epoch = [t for t in _closed if str(t.get("entry_time", ""))[:10] >= _post_fix_epoch]
        _legacy     = [t for t in _closed if str(t.get("entry_time", ""))[:10] < _post_fix_epoch]

        def _cov(trades: list) -> dict:
            n = len(trades)
            if n == 0:
                return {"n": 0, "run_id_pct": None, "exp_id_pct": None, "cfg_hash_pct": None}
            return {
                "n": n,
                "run_id_pct":   round(sum(1 for t in trades if t.get("run_id")) / n * 100, 1),
                "exp_id_pct":   round(sum(1 for t in trades if t.get("experiment_id")) / n * 100, 1),
                "cfg_hash_pct": round(sum(1 for t in trades if t.get("config_hash")) / n * 100, 1),
            }

        _jc_all    = _cov(_closed)
        _jc_post   = _cov(_post_epoch)
        _jc_legacy = _cov(_legacy)

        # This-run decisions coverage
        _run_decisions = decisions
        _rd_run_id = sum(1 for d in _run_decisions if getattr(d, "run_id", None))
        _rd_exp_id = sum(1 for d in _run_decisions if getattr(d, "experiment_id", None))
        _rd_cfg    = sum(1 for d in _run_decisions if getattr(d, "config_hash", None))
        _rd_n = max(len(_run_decisions), 1)

        _join_report = {
            "run_id": run_context.run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "post_fix_epoch": _post_fix_epoch,
            "all_closed": _jc_all,
            "post_epoch_closed": _jc_post,
            "legacy_closed": _jc_legacy,
            "this_run_decisions": {
                "n": len(_run_decisions),
                "run_id_pct":   round(_rd_run_id / _rd_n * 100, 1),
                "exp_id_pct":   round(_rd_exp_id / _rd_n * 100, 1),
                "cfg_hash_pct": round(_rd_cfg / _rd_n * 100, 1),
            },
        }

        _jr_path = project_root / "data" / "audits" / "p6_join_coverage.json"
        _jr_path.parent.mkdir(parents=True, exist_ok=True)
        _jr_path.write_text(json.dumps(_join_report, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info(
            "P6 join_coverage: all_closed=%d run_id=%.1f%% | post_epoch=%d run_id=%.1f%% | this_run decisions=%d run_id=%.1f%%",
            _jc_all["n"], _jc_all["run_id_pct"] or 0,
            _jc_post["n"], _jc_post["run_id_pct"] or 0,
            len(_run_decisions), _join_report["this_run_decisions"]["run_id_pct"],
        )
    except Exception as _jc_exc:
        logger.warning("P6 join_coverage report failed: %s", _jc_exc)

    _print_summary(decisions, submissions, equity, args.dry_run)
    from stock_swing.reporting.console_summary import ConsoleSummary

    unrealized = (
        sum(float(p.get("unrealized_pl", 0) or 0) for p in current_positions_full.values())
        if current_positions_full else 0.0
    )
    ps_sources: dict[str, int] = {}
    for s in submissions:
        src = (s.sizing_details or {}).get("price_source", "unknown")
        ps_sources[src] = ps_sources.get(src, 0) + 1

    # G2 fix: prefer _post_state (updated by post_run_update) over stale _breaker_state
    _final_breaker_state_obj = (
        _post_state
        if "_post_state" in dir() and _post_state is not None
        else (_breaker_state if "_breaker_state" in dir() and _breaker_state is not None else None)
    )
    _final_breaker_status = _final_breaker_state_obj.status if _final_breaker_state_obj is not None else "unknown"
    _final_cb_detail: dict = (
        {
            "status": _final_breaker_state_obj.status,
            "triggered_at": _final_breaker_state_obj.triggered_at,
            "triggered_rules": list(_final_breaker_state_obj.triggered_rules or []),
            "reason": _final_breaker_state_obj.reason,
            "clear_note": _final_breaker_state_obj.clear_note,
        }
        if _final_breaker_state_obj is not None
        else {}
    )

    console_summary = ConsoleSummary.build(
        run_id=run_context.run_id if "run_context" in dir() else "unknown",
        equity=equity,
        open_position_count=len(current_positions_full),
        realized_pnl=float(pnl_tracker.state.cumulative_realized_pnl or 0),
        unrealized_pnl=unrealized,
        decisions=decisions,
        submissions=submissions,
        cluster_blocks=[sym for sym, _ in blocked_cluster_cap] if "blocked_cluster_cap" in dir() else [],
        risk_budget_pct=risk_budget_result.get("pct_of_equity", 0) if "risk_budget_result" in dir() else 0,
        stale_symbols=list(stale_symbols) if "stale_symbols" in dir() else [],
        price_sources=ps_sources,
        market_regime=regime_for_sizing if "regime_for_sizing" in dir() else "unknown",
        warnings=[],
        experiment_id=experiment_context.experiment_id if experiment_context is not None else "unknown",
        guardrail_status=_final_breaker_status,
        api_metrics=_build_api_metrics(latency_tracker),
        price_integrity=_build_price_integrity(
            stale_symbols if "stale_symbols" in dir() else [],
            ps_sources,
        ),
        asset_class_breakdown=pnl_tracker.get_asset_class_breakdown(),
        exit_attribution_breakdown=pnl_tracker.get_exit_attribution_breakdown(),
        broker_tracker_diff=_build_broker_tracker_diff_with_lag(
            list(current_positions_full.values()) if current_positions_full else [],
            pnl_tracker.get_open_positions(),
            lag_result=_lag_result if "_lag_result" in dir() else None,
        ),
        # RF-5b: AI telemetry
        ai_metrics=build_ai_metrics_from_decisions(decisions),
        # RF/G2: sector shock shadow count
        sector_shock_shadow_count=_ssh_shadow_count if "_ssh_shadow_count" in dir() else 0,
        # R6-v2: non-dry-run にも ledger_quality / entry_filter_stats を渡す
        ledger_quality=pnl_tracker.get_ledger_quality_report(),
        entry_filter_stats=_ef_result.stats if "_ef_result" in dir() else {},
        # R0-v2-A: safety gate
        ledger_gate_status=_ledger_gate_status if "_ledger_gate_status" in dir() else "UNKNOWN",
        # R0-v2-B: equity bridge
        equity_bridge=_build_equity_bridge(
            broker_equity=equity,
            pnl_tracker=pnl_tracker,
            unrealized_pnl=unrealized,
        ),
        # R6-v2: full 7-stage funnel (now 8 stages with allocation_blocked)
        funnel_stages={
            "generated": len(decisions),
            "risk_denied": sum(1 for d in decisions if getattr(d, "action", "") == "deny"),
            "entry_blocked": len(_ef_result.blocked) if "_ef_result" in dir() else 0,
            "cluster_blocked": len(blocked_cluster_cap) if "blocked_cluster_cap" in dir() else 0,
            "allocation_blocked": _allocation_blocked_count,
            "guardrail_blocked": len(_guardrail_blocked) if "_guardrail_blocked" in dir() else 0,
            "qty_zero": sum(skipped_buy_reasons.values()) if "skipped_buy_reasons" in dir() else 0,
            "submitted": len([s for s in submissions if s.status not in {"rejected"}]),
            "accepted": len([s for s in submissions if s.status in {"accepted", "new", "pending_new", "filled", "partially_filled"}]),
            "filled": len([s for s in submissions if s.status in {"filled", "partially_filled"}]),
            "reconciled": _reconciled_count if "_reconciled_count" in dir() else 0,
        },
        # open position signal values for console display
        open_position_details=pnl_tracker.get_open_position_signal_summary(
            broker_positions=current_positions_full or {}
        ),
        # circuit breaker detail for HALT visibility in console
        circuit_breaker_detail=_final_cb_detail,
        # Plan A: Stop Loss Health panel
        stop_loss_health=_build_stop_loss_health(
            pnl_tracker=pnl_tracker,
            exit_strat=exit_strat if "exit_strat" in dir() else None,
            current_prices={sym: float(pos.get("current_price", 0) or 0)
                            for sym, pos in (current_positions_full or {}).items()},
        ),
        # R7-v2-A: Source SLA
        source_sla=_get_source_sla(project_root),
    )
    console_summary.emit(save_path=project_root / "reports/console/latest_console_summary.json")

    # RF-5b: flush token usage to CSV
    _ai = console_summary.ai_metrics
    token_tracker.record(TokenUsageRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        workflow_name="paper_demo",
        model=list((_ai.get("model_counts") or {"rule-based": 1}).keys())[0],
        input_tokens=_ai.get("input_tokens", 0),
        output_tokens=_ai.get("output_tokens", 0),
        total_tokens=_ai.get("input_tokens", 0) + _ai.get("output_tokens", 0),
        estimated_cost=0.0,
        success=True,
    ))
    token_tracker.flush()

    # Send Telegram notification if requested
    if args.telegram:
        _send_telegram_summary(
            symbols=symbols,
            decisions=decisions,
            submissions=submissions,
            equity=equity,
            dry_run=args.dry_run,
            silent=args.silent,
            # 追加コンテキスト (改善版 2026-07-27)
            pnl_tracker=pnl_tracker,
            current_positions=current_positions_full or {},
            breaker_state=_breaker_state if "_breaker_state" in dir() else None,
            ledger_gate_status=_ledger_gate_status if "_ledger_gate_status" in dir() else "UNKNOWN",
            exit_strat=exit_strat if "exit_strat" in dir() else None,
        )

    return finish(
        _final_exit_code,
        decisions=decisions,
        submissions=submissions,
        equity_value=equity,
        extra={"reason": _final_reason} if _final_reason else None,
    )


def _build_equity_bridge(
    *,
    broker_equity: float,
    pnl_tracker,
    unrealized_pnl: float,
) -> dict:
    """R0-v2-B: Build equity bridge dict for ConsoleSummary."""
    try:
        import json as _json
        state = pnl_tracker.state
        baseline = float(getattr(state, "baseline_equity", None) or
                         _json.loads((pnl_tracker.project_root / "data" / "tracking" / "pnl_state.json").read_text()).get("baseline_equity", 1_000_000))
        realized = float(state.cumulative_realized_pnl or 0)
        # Note: quarantined_pnl=0 because our quarantined trades are data reconstruction
        # errors, not real broker fills. The ~$64K bridge gap is historical untracked
        # activity pre-tracker-epoch. Tolerance set to $100K to flag new unexplained gaps.
        result = compute_equity_bridge(
            broker_equity=broker_equity,
            baseline_equity=baseline,
            tracker_realized=realized,
            tracker_unrealized=unrealized_pnl,
            quarantined_pnl=0.0,
            tolerance_usd=100_000.0,
        )
        return result.to_dict()
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning("equity_bridge computation failed: %s", exc)
        return {}


def _build_api_metrics(latency_tracker) -> dict:
    """Build API metrics dict from LatencyTracker records."""
    if latency_tracker is None:
        return {}
    records = getattr(latency_tracker, "_records", [])
    if not records:
        return {}
    durations = [r.duration_ms for r in records if r.status == "ok"]
    errors = [r for r in records if r.status == "error"]
    durations_sorted = sorted(durations)
    n = len(durations_sorted)
    p50 = durations_sorted[int(n * 0.5)] if n > 0 else None
    p95 = durations_sorted[int(n * 0.95)] if n > 0 else None

    # Slowest endpoints
    from collections import defaultdict

    ep_max: dict[str, float] = defaultdict(float)
    for r in records:
        ep_max[r.endpoint] = max(ep_max[r.endpoint], r.duration_ms)
    slowest = sorted(
        [{"endpoint": ep, "duration_ms": ms} for ep, ms in ep_max.items()],
        key=lambda x: -x["duration_ms"],
    )[:3]

    return {
        "call_count": len(records),
        "error_count": len(errors),
        "p50_latency_ms": round(p50, 1) if p50 is not None else None,
        "p95_latency_ms": round(p95, 1) if p95 is not None else None,
        "slowest_endpoints": slowest,
    }


def _build_broker_tracker_diff_with_lag(
    broker_positions: list[dict],
    tracker_open: list[dict],
    lag_result=None,  # LagExclusionResult | None
) -> dict:
    """Build broker/tracker diff with lag exclusion metadata attached.

    Extends _build_broker_tracker_diff() with:
      - lag_excused_presence: symbols excluded as BUY/SELL presence lag
      - lag_excused_qty: symbols excluded as partial-fill qty lag
      - real_mismatch_count: count of non-lag mismatches (what guardrail saw)

    This allows Console to display lag vs real mismatches distinctly.
    """
    raw = _build_broker_tracker_diff(broker_positions, tracker_open)
    if lag_result is None:
        return {**raw, "lag_excused_presence": [], "lag_excused_qty": [], "real_mismatch_count": raw["mismatch_count"]}
    return {
        **raw,
        "lag_excused_presence": sorted(lag_result.excused_presence),
        "lag_excused_qty": list(lag_result.excused_qty),
        "real_mismatch_count": lag_result.adjusted_mismatch_count,
    }


def _build_broker_tracker_diff(
    broker_positions: list[dict],
    tracker_open: list[dict],
) -> dict:
    """R6-D: Compute diff between broker positions and tracker open trades."""
    broker_map: dict[str, float] = {}
    for pos in broker_positions:
        sym = str(pos.get("symbol") or "").strip()
        qty = float(pos.get("qty") or 0)
        if sym:
            broker_map[sym] = broker_map.get(sym, 0) + qty

    tracker_map: dict[str, float] = {}
    for t in tracker_open:
        sym = str(t.get("symbol") or "").strip()
        qty = float(t.get("qty") or 0)
        if sym:
            tracker_map[sym] = tracker_map.get(sym, 0) + qty

    broker_syms = set(broker_map)
    tracker_syms = set(tracker_map)
    broker_only = sorted(broker_syms - tracker_syms)
    tracker_only = sorted(tracker_syms - broker_syms)
    qty_mismatches = [
        {"symbol": sym, "broker_qty": broker_map[sym], "tracker_qty": tracker_map[sym]}
        for sym in sorted(broker_syms & tracker_syms)
        if abs(broker_map[sym] - tracker_map[sym]) > 0.5
    ]
    mismatch_count = len(broker_only) + len(tracker_only) + len(qty_mismatches)

    return {
        "broker_count": len(broker_map),
        "tracker_count": len(tracker_map),
        "mismatch_count": mismatch_count,
        "broker_only": broker_only,
        "tracker_only": tracker_only,
        "qty_mismatches": qty_mismatches,
    }


def _build_stop_loss_health(
    pnl_tracker,
    exit_strat,
    current_prices: dict[str, float] | None = None,
    post_exit_window_days: int = 14,
) -> dict:
    """Build stop_loss_health dict for ConsoleSummary.

    Args:
        pnl_tracker: PnLTracker instance (to read closed trades).
        exit_strat: SimpleExitV2Strategy instance (to read suppression stats).
        current_prices: {symbol: price} dict for post-exit drift check.
        post_exit_window_days: Look for stop_loss trades within this many days ago.

    Returns structured dict consumed by ConsoleRenderer._stop_loss_health().
    """
    from datetime import datetime, timedelta, timezone as _tz

    now = datetime.now(_tz.utc)
    closed = [t for t in pnl_tracker.state.trades if t.get("status") == "closed"]

    # ── 30日以内の stop_loss サマリー (true stops: PnL < 0)
    cutoff_30d = (now - timedelta(days=30)).isoformat()
    recent_sl = [
        t for t in closed
        if t.get("exit_reason") == "stop_loss"
        and (t.get("exit_time") or "") >= cutoff_30d
        and (t.get("pnl") or 0) < 0
    ]
    recent_30d: dict = {}
    if recent_sl:
        pnls = [t.get("pnl") or 0 for t in recent_sl]
        rets = [(t.get("return_pct") or 0) * 100 for t in recent_sl]
        recent_30d = {
            "count": len(recent_sl),
            "net_pnl": round(sum(pnls), 2),
            "avg_ret_pct": round(sum(rets) / len(rets), 2) if rets else 0.0,
        }

    # ── 今回 run の min_hold 抑制カウント
    suppression = exit_strat.get_suppression_stats() if exit_strat is not None else {}

    # ── post-exit 追跡: 7〜14日前の stop_loss 止損が今も exit_price を下回るか
    cutoff_7d  = (now - timedelta(days=7)).isoformat()
    cutoff_14d = (now - timedelta(days=post_exit_window_days)).isoformat()
    window_sl = [
        t for t in closed
        if t.get("exit_reason") == "stop_loss"
        and (t.get("pnl") or 0) < 0
        and cutoff_14d <= (t.get("exit_time") or "") <= cutoff_7d
    ]
    post_exit_check: dict = {}
    if window_sl and current_prices:
        checked = 0
        correct = 0
        for t in window_sl:
            sym = t.get("symbol", "")
            xp = t.get("exit_price") or 0
            cur = current_prices.get(sym)
            if cur is not None and xp > 0:
                checked += 1
                if cur < xp:
                    correct += 1
        if checked > 0:
            post_exit_check = {
                "checked": checked,
                "correct_stops": correct,
                "correct_rate": round(correct / checked, 3),
            }

    tiered = getattr(exit_strat, "tiered_min_hold_enabled", False) if exit_strat else False

    return {
        "tiered_min_hold_enabled": tiered,
        "recent_30d": recent_30d,
        "suppression": suppression,
        "post_exit_check": post_exit_check,
    }


def _get_source_sla(project_root: Path) -> dict:
    """R7-v2-A: Fetch source SLA status from SystemAdapter (fail-silent)."""
    try:
        from console.adapters.system_adapter import SystemAdapter
        adapter = SystemAdapter(project_root)
        sla = adapter._check_source_sla()
        return {
            "ok": sla.get("ok", False),
            "required_sources": sla.get("required_sources", []),
            "failing_sources": sla.get("failing_sources", []),
            "sources": [
                {"source": s.get("source"), "ok": s.get("ok"), "coverage": s.get("coverage")}
                for s in (sla.get("sources") or [])
            ],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "required_sources": [], "failing_sources": [], "sources": []}


def _build_price_integrity(
    stale_symbols: set | list,
    price_sources: dict[str, int],
    momentum_results: list | None = None,
) -> dict:
    """Build price integrity dict for ConsoleSummary."""
    del momentum_results

    stale_list = list(stale_symbols) if stale_symbols else []
    total = sum(price_sources.values()) if price_sources else 0
    stale_count = len(stale_list)
    fresh_count = max(total - stale_count, 0)

    # Count fallback sources (anything that isn't "massive")
    fallback_count = sum(v for k, v in (price_sources or {}).items() if k != "massive")

    return {
        "fresh_price_count": fresh_count,
        "stale_price_count": stale_count,
        "fallback_price_count": fallback_count,
        "top_stale_symbols": stale_list[:5],
        "price_source_breakdown": price_sources or {},
    }


def _save_decisions(
    decisions: list[DecisionRecord],
    store: StageStore,
    ts_tag: str,
    *,
    run_id: str | None = None,
    experiment_id: str | None = None,
    config_hash: str | None = None,
) -> None:
    for d in decisions:
        try:
            effective_run_id = getattr(d, "run_id", None) or run_id
            effective_experiment_id = getattr(d, "experiment_id", None) or experiment_id
            effective_config_hash = getattr(d, "config_hash", None) or config_hash
            decision_time = getattr(d, "decision_time", None) or d.generated_at.isoformat()
            doc = {
                "decision_id": d.decision_id,
                "schema_version": d.schema_version,
                "generated_at": d.generated_at.isoformat(),
                "decision_time": decision_time,
                "mode": d.mode,
                "strategy_id": d.strategy_id,
                "strategy_version_id": d.strategy_version_id,
                "symbol": d.symbol,
                "action": d.action,
                "confidence": d.confidence,
                "signal_strength": d.signal_strength,
                "risk_state": d.risk_state,
                "deny_reasons": d.deny_reasons,
                "requires_operator_approval": d.requires_operator_approval,
                "time_horizon": d.time_horizon,
                "evidence": d.evidence,
                # F5: AI telemetry fields
                "model": getattr(d, "model", None),
                "input_tokens": getattr(d, "input_tokens", None),
                "output_tokens": getattr(d, "output_tokens", None),
                "context_pack": getattr(d, "context_pack", None),
                "prompt_version": getattr(d, "prompt_version", None),
                "run_id": effective_run_id,
                "experiment_id": effective_experiment_id,
                "config_hash": effective_config_hash,
                "skip_reason": getattr(d, "skip_reason", None),
                "deny_reason": getattr(d, "deny_reason", None),
                "block_reason": getattr(d, "block_reason", None),
                "usage_source": getattr(d, "usage_source", None),
                "input_tokens_actual": getattr(d, "input_tokens_actual", None),
                "output_tokens_actual": getattr(d, "output_tokens_actual", None),
                "input_tokens_estimated": getattr(d, "input_tokens_estimated", None),
                "output_tokens_estimated": getattr(d, "output_tokens_estimated", None),
                "proposed_order": {
                    "symbol": d.proposed_order.symbol,
                    "side": d.proposed_order.side,
                    "order_type": d.proposed_order.order_type,
                    "qty": d.proposed_order.qty,
                    "time_in_force": d.proposed_order.time_in_force,
                    "limit_price": d.proposed_order.limit_price,
                } if d.proposed_order else None,
                "sizing": {
                    "final_shares": d.sizing.final_shares,
                    "shares_by_risk": d.sizing.shares_by_risk,
                    "shares_by_notional": d.sizing.shares_by_notional,
                    "shares_by_exposure": d.sizing.shares_by_exposure,
                    "regime_used": d.sizing.regime_used,
                    "asset_class_used": d.sizing.asset_class_used,
                    "risk_per_share": d.sizing.risk_per_share,
                    "stop_price": d.sizing.stop_price,
                    "latest_close": d.sizing.latest_close,
                    "atr": d.sizing.atr,
                    "max_loss_usd": d.sizing.max_loss_usd,
                    "max_position_notional_usd": d.sizing.max_position_notional_usd,
                    "remaining_exposure_capacity_usd": d.sizing.remaining_exposure_capacity_usd,
                    "account_equity": d.sizing.account_equity,
                    "current_price": d.sizing.current_price,
                    "current_total_exposure": d.sizing.current_total_exposure,
                    "current_sector_exposure": d.sizing.current_sector_exposure,
                    "sector_used": d.sizing.sector_used,
                    "max_sector_exposure_usd": d.sizing.max_sector_exposure_usd,
                    "remaining_sector_capacity_usd": d.sizing.remaining_sector_capacity_usd,
                    "confidence": d.sizing.confidence,
                    "applied_constraint": d.sizing.applied_constraint,
                    "skip_reason": d.sizing.skip_reason,
                },
            }
            # 2026-08-01 fix: ts_tag is fixed for the whole run (set once in main()),
            # so any symbol with >1 decision in the same run (e.g. a new BUY signal
            # AND a SELL/exit signal for an existing position on the same symbol)
            # collided on this filename and the later write silently overwrote the
            # earlier one. Audit-log scan across the full decision history (2026-04
            # through 2026-07) found 700+ such collision groups — every overwritten
            # decision's full evidence/sizing/confidence was permanently lost, with
            # only a single audit-log line surviving as evidence it ever existed.
            # Fix: suffix the filename with the decision_id (unique per decision)
            # so same-symbol/same-run decisions never collide.
            store.write_decisions(f"decision_{d.symbol}_{ts_tag}_{d.decision_id}.json", doc)
        except Exception:
            pass


def _build_closed_trade_export_row(trade: dict) -> dict:
    """Normalize tracker trade fields for CSV exports."""
    quantity = trade.get("quantity")
    if quantity in (None, "", 0):
        quantity = trade.get("qty", 0)
    realized_pnl = trade.get("realized_pnl")
    if realized_pnl in (None, "", 0):
        realized_pnl = trade.get("pnl", 0)
    return {
        "trade_id": trade.get("trade_id"),
        "symbol": trade.get("symbol"),
        "entry_time": trade.get("entry_time"),
        "exit_time": trade.get("exit_time"),
        "quantity": quantity,
        "realized_pnl": realized_pnl,
        "return_pct": trade.get("return_pct"),
        "holding_days": trade.get("holding_days"),
        "status": trade.get("status"),
    }


def _banner(title: str) -> None:
    print("=" * 60)
    print(f"  {title}")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)


def _section(title: str) -> None:
    print(f"\n-- {title} " + "-" * (55 - len(title)))


def _send_telegram_summary(
    symbols: list[str],
    decisions: list[DecisionRecord],
    submissions: list[OrderSubmission],
    equity: float,
    dry_run: bool,
    silent: bool,
    # 追加コンテキスト
    pnl_tracker=None,
    current_positions: dict | None = None,
    breaker_state=None,
    ledger_gate_status: str = "UNKNOWN",
    exit_strat=None,
) -> None:
    """取引時間中の Telegram サマリーを送信する（改善版 2026-07-27）。

    15分毎の reconciliation / paper_demo run 後に送信。
    HALT 発動時はバナーを最上部に表示する。
    """
    from stock_swing.utils.telegram_notifier import send_notification
    from datetime import datetime, timezone, timedelta
    import json as _json

    jst = timezone(timedelta(hours=9))
    jst_time = datetime.now(timezone.utc).astimezone(jst).strftime("%Y-%m-%d %H:%M JST")
    mode_tag = "🧪 テスト" if dry_run else "📊 ペーパー"

    # ── サーキットブレーカー状態を解決 ───────────────────────────────
    cb_status = "unknown"
    cb_triggered_at = ""
    cb_rules: list[str] = []
    if breaker_state is not None:
        cb_status = getattr(breaker_state, "status", "unknown") or "unknown"
        raw_at = getattr(breaker_state, "triggered_at", "") or ""
        try:
            cb_triggered_at = (
                datetime.fromisoformat(str(raw_at).replace("Z", "+00:00"))
                .astimezone(jst)
                .strftime("%m/%d %H:%M JST")
            )
        except Exception:
            cb_triggered_at = str(raw_at)[:16]
        for rule in (getattr(breaker_state, "triggered_rules", None) or []):
            if isinstance(rule, dict):
                cb_rules.append(rule.get("name", "?"))
    else:
        # ファイルから直接読む（フォールバック）
        try:
            cb_path = project_root / "data" / "guardrails" / "circuit_breaker.json"
            cb_data = _json.loads(cb_path.read_text())
            cb_status = cb_data.get("status", "unknown")
            raw_at = cb_data.get("triggered_at", "") or ""
            try:
                cb_triggered_at = (
                    datetime.fromisoformat(str(raw_at).replace("Z", "+00:00"))
                    .astimezone(jst)
                    .strftime("%m/%d %H:%M JST")
                )
            except Exception:
                cb_triggered_at = raw_at[:16]
            for rule in (cb_data.get("triggered_rules") or []):
                cb_rules.append(rule.get("name", "?"))
        except Exception:
            pass

    halted = cb_status in ("halted", "recovery_pending")

    # ── 資産情報 ─────────────────────────────────────────────────────
    baseline = 1_000_000.0
    try:
        if pnl_tracker is not None:
            baseline = float(getattr(pnl_tracker.state, "baseline_equity", None) or baseline)
    except Exception:
        pass
    baseline_ret = (equity - baseline) / baseline if baseline else 0.0
    ret_icon = "🔥" if baseline_ret >= 0.05 else ("✅" if baseline_ret >= 0 else ("⚠️" if baseline_ret >= -0.05 else "❌"))

    cum_pnl = 0.0
    unreal_pnl = 0.0
    if pnl_tracker is not None:
        try:
            cum_pnl = float(getattr(pnl_tracker.state, "cumulative_realized_pnl", 0) or 0)
        except Exception:
            pass
    if current_positions:
        try:
            unreal_pnl = sum(float(p.get("unrealized_pl", 0) or 0) for p in current_positions.values())
        except Exception:
            pass

    # ── 決定の分類 ────────────────────────────────────────────────────
    buys = [d for d in decisions if d.action == "buy" and d.risk_state == "pass"]
    sells = [d for d in decisions if d.action == "sell" and d.risk_state == "pass"]
    denied = [d for d in decisions if d.action == "deny"]
    held = [d for d in decisions if d.action in {"hold", "review"}]
    submitted_orders = [s for s in submissions if s.status == "submitted"]

    # ── 直近の決済取引（pnl_tracker から最新5件）────────────────────
    recent_trades: list[dict] = []
    if pnl_tracker is not None:
        try:
            closed = [t for t in pnl_tracker.state.trades if t.get("status") == "closed"]
            recent_trades = sorted(closed, key=lambda t: t.get("exit_time") or "", reverse=True)[:5]
        except Exception:
            pass

    # ── min_hold 抑制カウント ─────────────────────────────────────────
    sup_total = 0
    sup_noise = 0
    if exit_strat is not None:
        try:
            sup = exit_strat.get_suppression_stats()
            sup_total = sup.get("total", 0)
            sup_noise = sup.get("noise_7d", 0)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────
    # メッセージ構築
    # ─────────────────────────────────────────────────────────────────
    parts: list[str] = []

    # HALT バナー（最優先）
    if halted:
        rule_text = "、".join(cb_rules[:2]) if cb_rules else "不明"
        if cb_status == "halted":
            parts.append("🚨━━━━━━━━━━━━━━━━━━━━━━━━━━🚨")
            parts.append("<b>⛔ サーキットブレーカー 発動中</b>")
            parts.append("  <b>全トレード 一時停止</b>")
        else:
            parts.append("🚨━━━━━━━━━━━━━━━━━━━━━━━━━━🚨")
            parts.append("<b>⚠️ サーキットブレーカー 解除待ち</b>")
            parts.append("  手動承認が必要です")
        parts.append(f"<code>  発動: {cb_triggered_at}</code>")
        parts.append(f"<code>  原因: {rule_text}</code>")
        parts.append("🚨━━━━━━━━━━━━━━━━━━━━━━━━━━🚨")
        parts.append("")

    # ヘッダー
    parts.append(f"<b>{mode_tag} - Stock Swing</b>")
    parts.append(f"🗓 {jst_time}")
    parts.append("")

    # システム状態
    ledger_icon = "✅" if ledger_gate_status == "VALID" else ("❌" if ledger_gate_status == "INVALID" else "❓")
    cb_icon = "✅ 正常" if cb_status == "ok" else ("⛔ 停止中" if cb_status == "halted" else ("⚠️ 解除待ち" if cb_status == "recovery_pending" else f"❓ {cb_status}"))
    parts.append("<b>🛡 システム状態</b>")
    parts.append(f"<code>  CB  : {cb_icon}</code>")
    parts.append(f"<code>  台帳: {ledger_icon} {ledger_gate_status}</code>")
    parts.append("")

    # 資産状況
    parts.append(f"<b>💰 資産状況  {ret_icon} 元本比 {baseline_ret:+.2%}</b>")
    parts.append(f"<code>  総額: ${equity:>12,.2f}</code>")
    parts.append(f"<code>  確定: ${cum_pnl:>+12,.2f}</code>")
    if unreal_pnl:
        parts.append(f"<code>  含み: ${unreal_pnl:>+12,.2f}</code>")
    parts.append("")

    # 今回 run の分析結果
    parts.append(f"<b>📈 今回 run ({len(symbols)} 銘柄分析)</b>")
    parts.append(f"<code>  買いシグナル: {len(buys)}件  売りシグナル: {len(sells)}件</code>")
    parts.append(f"<code>  拒否: {len(denied)}件  保留: {len(held)}件</code>")
    parts.append("")

    # 注文
    if submitted_orders:
        parts.append(f"<b>📝 注文送信 ({len(submitted_orders)}件)</b>")
        for s in submitted_orders[:6]:
            side_ja = "買い" if s.side.upper() == "BUY" else "売り"
            parts.append(f"<code>  {side_ja} {s.qty:>4}株  {s.symbol}</code>")
        if len(submitted_orders) > 6:
            parts.append(f"<code>  ...他 {len(submitted_orders) - 6}件</code>")
        parts.append("")

    # 保有ポジション（簡略）
    if current_positions:
        pos_list = sorted(current_positions.values(), key=lambda p: p.get("symbol", ""))
        pos_syms = []
        for p in pos_list[:8]:
            sym = p.get("symbol", "?")
            unreal_p = float(p.get("unrealized_pl", 0) or 0)
            pct = float(p.get("unrealized_plpc", 0) or 0) * 100
            icon = "📈" if pct > 1 else ("📉" if pct < -5 else "")
            pos_syms.append(f"{sym}{icon}")
        parts.append(f"<b>📂 保有 ({len(current_positions)}件)</b>")
        parts.append(f"<code>  {' '.join(pos_syms)}</code>")
        parts.append("")

    # 直近の決済（5件）
    if recent_trades:
        parts.append("<b>🔄 直近の決済</b>")
        _REASON_JA = {
            "trailing_stop": "利確(追跡)", "breakeven_stop": "利確(BEP)",
            "stop_loss": "損切り", "time_based": "期間満了",
            "broker_fill": "手動", "corporate_action": "コーポレート",
        }
        for t in recent_trades[:4]:
            pnl = t.get("pnl") or 0
            sym = t.get("symbol") or "?"
            reason = _REASON_JA.get(t.get("exit_reason") or "", t.get("exit_reason") or "不明")
            icon = "✅" if pnl >= 0 else "❌"
            parts.append(f"<code>  {icon} {sym:<6} {reason:<9} ${pnl:>+,.0f}</code>")
        parts.append("")

    # 止損健全性（min_hold 抑制）
    if sup_total > 0:
        parts.append("<b>🔒 止損抑制 (Plan A)</b>")
        parts.append(f"<code>  今回 run: {sup_total}件抑制 (うちノイズ tier: {sup_noise}件)</code>")
        parts.append("")

    # メッセージ上限
    message = "\n".join(parts)
    if len(message) > 4000:
        message = message[:4000] + "\n…(省略)"

    success = send_notification(message, silent=silent)
    if success:
        print("\n✅ Telegramに送信しました")
    else:
        print("\n⚠️  Telegram送信失敗")


def _print_summary(decisions: list[DecisionRecord], submissions: list[OrderSubmission], equity: float, dry_run: bool) -> None:
    _banner("SUMMARY" + (" [DRY RUN]" if dry_run else ""))
    actionable = [d for d in decisions if d.action in {"buy", "sell"} and d.risk_state == "pass"]
    denied = [d for d in decisions if d.action == "deny"]
    held = [d for d in decisions if d.action in {"hold", "review"}]
    print(f"  Decisions : {len(decisions)}  Actionable: {len(actionable)}  Denied: {len(denied)}  Held: {len(held)}")
    if submissions:
        sub_ok = [s for s in submissions if s.status == "submitted"]
        print(f"  Orders    : {len(sub_ok)}/{len(submissions)} submitted")
        for s in submissions:
            print(f"    {'OK' if s.status == 'submitted' else 'NG'} {s.side.upper()} {s.qty:>4} {s.symbol}" + (f" [{s.broker_order_id}]" if s.broker_order_id else "") + (f" reason={s.reject_reason}" if s.reject_reason else ""))
    print(f"  Equity    : ${equity:,.2f}")
    print(f"  Decisions saved to data/decisions/")
    print("=" * 60)


def _build_cron_summary(
    symbols: list[str],
    decisions: list[DecisionRecord],
    submissions: list[OrderSubmission],
    equity: float,
    dry_run: bool,
    exit_code: int,
    extra: dict | None = None,
) -> dict:
    actionable = [d for d in decisions if d.action in {"buy", "sell"} and d.risk_state == "pass"]
    denied = [d for d in decisions if d.action == "deny"]
    held = [d for d in decisions if d.action in {"hold", "review"}]
    submitted_orders = [s for s in submissions if s.status == "submitted"]
    summary = {
        "job": "paper_demo",
        "status": "ok" if exit_code == 0 else "error",
        "exit_code": exit_code,
        "dry_run": dry_run,
        "symbols": len(symbols),
        "decisions": len(decisions),
        "actionable": len(actionable),
        "denied": len(denied),
        "held": len(held),
        "submitted_orders": len(submitted_orders),
        "attempted_submissions": len(submissions),
        "equity": round(float(equity or 0.0), 2),
    }
    if extra:
        summary.update(extra)
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
