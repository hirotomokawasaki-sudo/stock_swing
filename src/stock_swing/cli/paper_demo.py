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
import os
import sys
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root / "src"))


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
from stock_swing.core.runtime import RuntimeMode, RuntimeModeError, read_runtime_mode
from stock_swing.core.types import CanonicalRecord
from stock_swing.decision_engine.decision_engine import DecisionEngine, DecisionRecord
from stock_swing.decision_engine.risk_validator import RiskValidator
from stock_swing.execution.paper_executor import OrderSubmission, PaperExecutor
from stock_swing.execution.reconciler import Reconciler
from stock_swing.risk.portfolio_allocator import PortfolioAllocator
from stock_swing.feature_engine.macro_regime_feature import MacroRegimeFeature
from stock_swing.feature_engine.price_momentum_feature import PriceMomentumFeature
from stock_swing.normalization.broker_normalizer import BrokerNormalizer
from stock_swing.safety.audit_logger import AuditLevel, AuditLogger
from stock_swing.safety.kill_switch import KillSwitch
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.storage.stage_store import StageStore
from stock_swing.strategy_engine.breakout_momentum_strategy import BreakoutMomentumStrategy
from stock_swing.strategy_engine.event_swing_strategy import EventSwingStrategy
from stock_swing.strategy_engine.simple_exit_strategy import SimpleExitStrategy
from stock_swing.strategy_engine.simple_exit_v2_strategy import SimpleExitV2Strategy
from stock_swing.tracking.pnl_tracker import PnLTracker
from stock_swing.utils.market_calendar import MarketCalendar
from stock_swing.utils.signal_prioritization import prioritize_buy_signals, prioritize_buy_signals_v2


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

# Unified paper-demo / monitoring universe
# Stocks: existing core AI stocks + approved additional normal stocks
# ETFs: approved normal ETFs only (no leveraged / inverse / bear / short / yield-enhanced ETFs)
DEFAULT_SYMBOLS = [
    "NVDA", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "AMD", "TSM", "ASML",
    "INTC", "MU", "ARM", "AMAT", "LRCX", "KLAC", "QCOM", "MRVL", "PLTR", "ADBE",
    "CRM", "ORCL", "NOW", "SNOW", "MDB", "DDOG", "PATH", "FICO", "SMCI", "PANW",
    "CRWD", "FTNT", "ANET", "CSCO", "IBM", "HPE", "DELL", "HPQ", "SNPS", "CDNS",
    "V", "MA", "INTU", "NBIS", "CRDO", "RBRK", "CIEN", "SHOC", "SOXQ", "SOXX",
    "SMH", "FTXL", "PTF", "SMHX", "FRWD", "TTEQ", "GTOP", "CHPX", "CHPS", "PSCT",
    "QTEC", "TDIV", "SKYY", "QTUM",
]

# Legacy CLI compatibility: "full" maps to the unified universe as well.
TECH_UNIVERSE_FULL = DEFAULT_SYMBOLS

# ETF symbols for portfolio allocation
ETF_SYMBOLS = {
    'SHOC', 'SOXQ', 'SOXX', 'SMH', 'FTXL', 'PTF', 'SMHX', 'FRWD', 
    'TTEQ', 'GTOP', 'CHPX', 'CHPS', 'PSCT', 'QTEC', 'TDIV', 'SKYY', 'QTUM'
}


def main() -> int:  # noqa: C901
    parser = argparse.ArgumentParser(description="stock_swing paper trading demo")
    parser.add_argument("--symbols", type=str, default=",".join(DEFAULT_SYMBOLS),
                        help="Comma-separated symbols (overrides --universe)")
    parser.add_argument("--universe", type=str, choices=["default", "full"], default="default",
                        help="Predefined symbol universe: default (10 tech) / full (14 tech+ETF)")
    parser.add_argument("--timeframe", type=str, default="1Day")
    parser.add_argument("--bar-limit", type=int, default=20)
    parser.add_argument("--min-momentum", type=float, default=0.025)
    parser.add_argument("--min-signal-strength", type=float, default=0.52)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-outside-hours", action="store_true")
    parser.add_argument("--telegram", action="store_true", help="Send summary to Telegram")
    parser.add_argument("--silent", action="store_true", help="Send Telegram notification silently")
    args = parser.parse_args()

    # Resolve symbol universe (--symbols overrides --universe)
    if args.symbols != ",".join(DEFAULT_SYMBOLS):
        # User explicitly passed --symbols
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.universe == "full":
        symbols = TECH_UNIVERSE_FULL
    else:
        symbols = DEFAULT_SYMBOLS

    _banner("stock_swing Paper Trading Demo")
    print(f"  Symbols   : {', '.join(symbols)}")
    print(f"  Timeframe : {args.timeframe} x {args.bar_limit} bars")
    print(f"  Dry run   : {args.dry_run}")
    print()

    # 1. Runtime mode
    _section("1. Runtime Mode")
    try:
        runtime_mode_str = read_runtime_mode(project_root)
    except (FileNotFoundError, RuntimeModeError) as exc:
        print(f"  ERROR: {exc}")
        return 1

    if runtime_mode_str != "paper":
        print(f"  ERROR: Must be 'paper', got '{runtime_mode_str}'")
        return 1

    runtime_mode = RuntimeMode.PAPER
    print(f"  OK: runtime_mode={runtime_mode_str}")

    # 2. Kill switch
    _section("2. Kill Switch")
    ks_file = project_root / "data" / "audits" / "kill_switch.txt"
    kill_switch = KillSwitch(state_file=ks_file)
    try:
        kill_switch.check()
        print("  OK: Kill switch ACTIVE (execution allowed)")
    except RuntimeError as exc:
        print(f"  ERROR: {exc}")
        return 1

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
        return 1

    broker = BrokerClient(
        api_key=os.environ["BROKER_API_KEY"],
        api_secret=os.environ["BROKER_API_SECRET"],
        paper_mode=True,
        base_url=os.environ["BROKER_BASE_URL"],
    )
    print(f"  URL: {broker.base_url}")

    try:
        account_env = broker.fetch_account()
        acct = account_env.payload
        equity = float(acct.get("equity", 100_000))
        buying_power = float(acct.get("buying_power", 100_000))
        print(f"  OK: status={acct.get('status')} equity=${equity:,.2f} bp=${buying_power:,.2f}")
    except Exception as exc:
        print(f"  ERROR: Account fetch failed: {exc}")
        return 1

    # Infrastructure
    paths = PathManager(project_root)
    store = StageStore(paths, allow_raw_overwrite=True)
    ts_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    audit_log = AuditLogger(
        log_file=project_root / "data" / "audits" / f"paper_demo_{datetime.now().strftime('%Y%m%d')}.log",
        min_level=AuditLevel.INFO,
    )
    audit_log.log_system_event("paper_demo_start", details=f"symbols={symbols} dry_run={args.dry_run}")

    # 5. Data collection (parallel)
    _section("5. Data Collection (Broker Bars)")
    normalizer = BrokerNormalizer()
    all_records: list[CanonicalRecord] = []
    max_workers = int(os.environ.get("PAPER_DEMO_MAX_WORKERS", "8"))

    def fetch_single_symbol(symbol: str) -> tuple[str, list[CanonicalRecord], int, str | None]:
        """Fetch bars for a single symbol. Returns (symbol, records, bar_count, error)."""
        try:
            raw = broker.fetch_bars(symbol, timeframe=args.timeframe, limit=args.bar_limit)
            bar_count = len(raw.payload.get("bars", []))
            records = normalizer.normalize(raw)
            return (symbol, records, bar_count, None)
        except Exception as exc:
            return (symbol, [], 0, str(exc))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_single_symbol, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol, records, bar_count, error = future.result()
            if error:
                print(f"  WARN: {symbol:<6} fetch failed: {error}")
            else:
                all_records.extend(records)
                print(f"  OK: {symbol:<6} {bar_count:3d} bars -> {len(records):3d} records")

    if not all_records:
        print("\n  ERROR: No data fetched. Cannot proceed.")
        return 1
    print(f"\n  Total records: {len(all_records)} (fetched with {max_workers} parallel workers)")

    # 6. Features
    _section("6. Feature Computation")
    momentum_feat = PriceMomentumFeature(period_days=args.bar_limit)
    macro_feat = MacroRegimeFeature()
    momentum_results = momentum_feat.compute(all_records)
    macro_results = macro_feat.compute([])
    detected_regime = macro_results[0].values.get('regime', 'unknown') if macro_results else 'unknown'
    macro_based_regime = 'bullish' if detected_regime == 'expansion' else ('cautious' if detected_regime in {'recession', 'high_volatility'} else 'neutral')
    price_based_regime = _infer_price_based_regime(momentum_results)
    regime_for_sizing = price_based_regime if detected_regime == 'unknown' else macro_based_regime
    all_features = momentum_results + macro_results

    print(f"  Macro regime: {detected_regime}")
    print(f"  Price regime: {price_based_regime}")
    print(f"  Sizing regime: {regime_for_sizing}")
    print()
    print(f"  {'Symbol':<6}  {'Momentum':>10}  {'Trend':<10}  {'Bars':>5}")
    print(f"  {'------':<6}  {'--------':>10}  {'----':>10}  {'----':>5}")
    for f in sorted(momentum_results, key=lambda x: x.values.get("momentum", 0), reverse=True):
        m = f.values.get("momentum", 0)
        t = f.values.get("trend", "?")
        b = f.values.get("bars_used", 0)
        print(f"  {f.symbol:<6}  {m:>+10.2%}  {t:<10}  {b:>5}")

    # 7. Strategy signals
    _section("7. Strategy Signals")
    
    # First, get current positions for exit strategy
    current_positions_full: dict[str, dict] = {}
    current_positions: dict[str, int] = {}
    try:
        pos_env = broker.fetch_positions()
        pos_data = pos_env.payload
        if isinstance(pos_data, list):
            for pos in pos_data:
                sym = pos.get("symbol")
                qty = int(float(pos.get("qty", 0)))
                if sym and qty > 0:
                    current_positions[sym] = qty
                    current_positions_full[sym] = pos
    except Exception as exc:
        print(f"  WARN: Could not fetch positions for exit strategy: {exc}")
    
    # Entry strategies
    breakout_strat = BreakoutMomentumStrategy(
        min_momentum=args.min_momentum,
        min_signal_strength=args.min_signal_strength,
    )
    event_strat = EventSwingStrategy()
    breakout_signals = breakout_strat.generate(all_features)
    event_signals = event_strat.generate(all_features)
    
    # Exit strategy for current positions (V2 with trailing stop)
    # Load exit strategy config
    exit_config_path = project_root / "config" / "strategy" / "simple_exit_v2.yaml"
    if exit_config_path.exists():
        with open(exit_config_path) as f:
            exit_config = yaml.safe_load(f)
        exit_strat = SimpleExitV2Strategy(
            stop_loss_pct=exit_config.get('stop_loss_pct', -0.07),
            trailing_activation_pct=exit_config.get('trailing_activation_pct', 0.05),
            trailing_stop_pct=exit_config.get('trailing_stop_pct', 0.03),
            max_hold_days=exit_config.get('max_hold_days', 2),
        )
    else:
        # Fallback to default values
        exit_strat = SimpleExitV2Strategy(
            stop_loss_pct=-0.07,
            trailing_activation_pct=0.05,
            trailing_stop_pct=0.03,
            max_hold_days=2,  # Changed from 10 to 2
        )
    exit_signals = exit_strat.generate(all_features, current_positions_full)
    
    # Prioritize buy signals for sector diversification (V2 with dynamic allocation)
    entry_signals = breakout_signals + event_signals
    prioritized_entry = prioritize_buy_signals_v2(
        entry_signals,
        current_positions_full,
        equity=equity,
        max_sector_exposure_pct=0.80,  # 80% sector cap
    )
    all_signals = prioritized_entry + exit_signals

    print(f"  Entry Signals:")
    print(f"    BreakoutMomentum: {len(breakout_signals)} signal(s)")
    print(f"    EventSwing:       {len(event_signals)} signal(s)")
    print()
    print(f"  Exit Signals:")
    print(f"    SimpleExitV2:     {len(exit_signals)} signal(s) (with trailing stop)")
    
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
        return 0

    # 8. Decisions
    _section("8. Decision Engine")
    
    # Calculate portfolio metrics
    if current_positions_full:
        total_position_value = sum(float(p.get('market_value', 0)) for p in current_positions_full.values())
        total_unrealized_pl = sum(float(p.get('unrealized_pl', 0)) for p in current_positions_full.values())
        exposure_pct = (total_position_value / equity * 100) if equity > 0 else 0
        
        # Get max exposure for current regime
        from stock_swing.risk.position_sizing import REGIME_LIMITS
        regime_for_limit = (decision.evidence.get("market_regime") if isinstance(decision.evidence, dict) else "neutral") if 'decision' in locals() else "neutral"
        max_exposure_pct = REGIME_LIMITS.get(regime_for_limit, 0.70) * 100
        max_exposure_value = equity * REGIME_LIMITS.get(regime_for_limit, 0.70)
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
        print(f"    Exposure:             {exposure_pct:>12.1f}% (max: {max_exposure_pct:.0f}%)")
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
        status = "PASS" if decision.action in {"buy", "sell"} and decision.risk_state == "pass" else "SKIP"
        print(f"  [{status}] {decision.symbol}: action={decision.action} risk={decision.risk_state} conf={decision.confidence:.2f}")
        for r in decision.deny_reasons[:2]:
            print(f"       deny: {r}")
        audit_log.log_decision(decision.decision_id, decision.action, decision.strategy_id, decision.symbol, decision.risk_state, decision.mode)

    # 9. Paper execution
    actionable = [d for d in decisions if d.action in {"buy", "sell"} and d.risk_state == "pass" and d.proposed_order is not None]
    
    # Portfolio allocation: Prioritize ETF or Stock buys based on target allocation
    portfolio_allocator = PortfolioAllocator(
        project_root / "config" / "strategy" / "portfolio_allocation.yaml"
    )
    actionable = portfolio_allocator.filter_decisions_by_allocation(
        decisions=actionable,
        current_positions=current_positions_full,
        etf_symbols=ETF_SYMBOLS
    )
    
    # Log allocation status
    alloc_status = portfolio_allocator.get_allocation_status(
        current_positions=current_positions_full,
        etf_symbols=ETF_SYMBOLS
    )
    print(f"\n  Portfolio Allocation:")
    print(f"    ETF:   {alloc_status['current_etf_pct']:>6.1%} (target: {alloc_status['target_etf_pct']:.1%}) = ${alloc_status['etf_value']:>10,.0f}")
    print(f"    Stock: {alloc_status['current_stock_pct']:>6.1%} (target: {alloc_status['target_stock_pct']:.1%}) = ${alloc_status['stock_value']:>10,.0f}")
    if alloc_status['needs_rebalance']:
        rebal_type = 'ETF' if alloc_status['etf_deficit'] > 0 else 'Stock'
        print(f"    ⚠️  Rebalancing needed: Prioritizing {rebal_type} purchases")
    
    _section("9. Paper Order Submission")
    print(f"  Actionable: {len(actionable)}  Denied/held: {len(decisions) - len(actionable)}")

    if not actionable:
        print("\n  No actionable decisions.")
        _print_summary(decisions, [], equity, args.dry_run)
        return 0

    if args.dry_run:
        print("\n  DRY RUN - would submit:")
        for d in actionable:
            o = d.proposed_order
            print(f"    {o.side.upper()} {o.qty} {o.symbol} type={o.order_type} tif={o.time_in_force}")
        _print_summary(decisions, [], equity, args.dry_run)
        return 0

    executor = PaperExecutor(runtime_mode=runtime_mode, broker_client=broker)
    reconciler = Reconciler(broker_client=broker)
    pnl_tracker = PnLTracker(project_root)
    submissions: list[OrderSubmission] = []
    
    # Symbol-level position size limit (12% of equity per symbol, 15% for ETFs)
    MAX_POSITION_PER_SYMBOL_PCT = 0.12
    MAX_POSITION_PER_ETF_PCT = 0.15  # Higher limit for diversified ETFs
    max_position_per_symbol = equity * MAX_POSITION_PER_SYMBOL_PCT

    for decision in actionable:
        o = decision.proposed_order
        try:
            # Check symbol-level position size limit for BUY orders
            if o.side == "buy" and o.symbol in current_positions_full:
                existing_pos = current_positions_full[o.symbol]
                existing_value = float(existing_pos.get('market_value', 0))
                
                # Determine position limit (higher for ETFs)
                is_etf = o.symbol in ETF_SYMBOLS
                position_limit_pct = MAX_POSITION_PER_ETF_PCT if is_etf else MAX_POSITION_PER_SYMBOL_PCT
                max_position_value = equity * position_limit_pct
                
                # Get estimated order value
                preview_qty, preview_sizing = executor._calculate_position_size(
                    decision,
                    market_regime=(decision.evidence.get("market_regime") if isinstance(decision.evidence, dict) else "neutral") or "neutral",
                )
                
                # Estimate order value (qty * current_price)
                try:
                    q = broker.fetch_latest_quote(o.symbol).payload
                    quote = q.get("quote", q)
                    current_price = (float(quote.get("bp", 0) or 0) + float(quote.get("ap", 0) or 0)) / 2
                    estimated_order_value = preview_qty * current_price
                except:
                    estimated_order_value = preview_qty * 100  # Conservative estimate
                
                total_value = existing_value + estimated_order_value
                
                if total_value > max_position_value:
                    asset_type = "ETF" if is_etf else "Stock"
                    print(f"\n  SKIP {o.side.upper()} {preview_qty} {o.symbol} ({asset_type}): Position limit (${existing_value:.0f} + ${estimated_order_value:.0f} = ${total_value:.0f} > ${max_position_value:.0f} [{position_limit_pct:.0%}])")
                    continue
            
            preview_qty, preview_sizing = executor._calculate_position_size(
                decision,
                market_regime=(decision.evidence.get("market_regime") if isinstance(decision.evidence, dict) else "neutral") or "neutral",
            )
            preview_basis = ""
            if preview_sizing:
                preview_basis = (
                    f" [risk={preview_sizing.get('shares_by_risk')} "
                    f"notional={preview_sizing.get('shares_by_notional')} "
                    f"exposure={preview_sizing.get('shares_by_exposure')}]"
                )
            print(f"\n  Submitting {o.side.upper()} {preview_qty} {o.symbol} ({o.order_type}){preview_basis} ... ", end="", flush=True)
            sub = executor.submit(decision)
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
                # Fetch current price for P&L tracking entry
                entry_price = 0.0
                try:
                    q = broker.fetch_latest_quote(o.symbol).payload
                    quote = q.get("quote", q)
                    bid = float(quote.get("bp", 0) or 0)
                    ask = float(quote.get("ap", 0) or 0)
                    if bid and ask:
                        entry_price = round((bid + ask) / 2, 4)
                except Exception:
                    pass
                
                # Only record submission if we have a valid entry price
                if entry_price > 0:
                    pnl_tracker.record_submission(
                        symbol=o.symbol,
                        strategy_id=decision.strategy_id,
                        side=o.side,
                        qty=sub.qty,
                        price=entry_price,
                        broker_order_id=sub.broker_order_id,
                        decision_id=decision.decision_id,
                    )
                else:
                    print(f"WARN: Skipped P&L tracking for {o.symbol} (entry_price unavailable)")
            else:
                print(f"WARN {sub.status}: {sub.reject_reason}")
            audit_log.log_submission(sub.submission_id, sub.decision_id, sub.symbol, sub.side, sub.qty, sub.status, sub.broker_order_id)
            if sub.sizing_details:
                print(
                    f"    sizing: equity=${sub.sizing_details.get('account_equity')} "
                    f"price=${sub.sizing_details.get('current_price')} "
                    f"max_loss=${sub.sizing_details.get('max_loss_usd')} "
                    f"max_notional=${sub.sizing_details.get('max_position_notional_usd')} "
                    f"remaining_exposure=${sub.sizing_details.get('remaining_exposure_capacity_usd')}"
                )
        except Exception as exc:
            print(f"ERROR: {exc}")
            audit_log.log_system_event("submission_error", AuditLevel.ERROR, details=f"{decision.symbol}: {exc}")

    _save_decisions(decisions, store, ts_tag)

    # 10. Reconciliation
    submitted = [s for s in submissions if s.broker_order_id]
    if submitted:
        _section("10. Reconciliation")
        for sub in submitted:
            try:
                result = reconciler.reconcile(sub)
                ok_statuses = {"submitted", "accepted", "new", "pending_new", "filled", "partially_filled"}
                ok = result.broker_status in ok_statuses
                print(f"  {'OK' if ok else 'WARN'}: {sub.symbol} broker_status={result.broker_status} discrepancies={len(result.discrepancies)}")
                for disc in result.discrepancies:
                    print(f"    {disc}")

                if result.side == 'sell' and result.broker_status in {'filled', 'partially_filled', 'submitted', 'accepted', 'new', 'pending_new'}:
                    exit_price = None
                    if result.fills_detected:
                        try:
                            exit_price = float(result.fills_detected[0].get('avg_price') or 0)
                        except Exception:
                            exit_price = None
                    if not exit_price:
                        try:
                            q = broker.fetch_latest_quote(sub.symbol).payload
                            quote = q.get('quote', q)
                            bid = float(quote.get('bp', 0) or 0)
                            ask = float(quote.get('ap', 0) or 0)
                            exit_price = round((bid + ask) / 2, 4) if bid and ask else 0.0
                        except Exception:
                            exit_price = 0.0
                    if exit_price:
                        exit_reason = "strategy_exit"
                        notes = " ".join((decision.evidence or {}).get("notes") or []).lower() if getattr(decision, 'evidence', None) else ""
                        if "stop loss" in notes:
                            exit_reason = "stop_loss"
                        elif "take profit" in notes:
                            exit_reason = "take_profit"
                        elif "max hold" in notes:
                            exit_reason = "max_hold"
                        pnl_tracker.record_exit(
                            symbol=sub.symbol,
                            exit_price=exit_price,
                            broker_order_id=sub.broker_order_id,
                            exit_strategy_id=decision.strategy_id,
                            exit_reason=exit_reason,
                        )

                audit_log.log_reconciliation(sub.submission_id, sub.broker_order_id, result.status_matched, result.discrepancies)
            except Exception as exc:
                print(f"  WARN: {sub.symbol} reconcile failed: {exc}")

    audit_log.log_system_event("paper_demo_complete", details=f"decisions={len(decisions)} submitted={len(submissions)}")

    # Record daily P&L snapshot
    try:
        if not args.dry_run:
            pnl_tracker.record_daily_snapshot(
                equity=equity,
                signals_generated=len(all_signals),
                orders_submitted=len([s for s in submissions if s.status == "submitted"]),
            )
    except Exception:
        pass

    _print_summary(decisions, submissions, equity, args.dry_run)
    
    # Send Telegram notification if requested
    if args.telegram:
        _send_telegram_summary(
            symbols=symbols,
            decisions=decisions,
            submissions=submissions,
            equity=equity,
            dry_run=args.dry_run,
            silent=args.silent,
        )
    
    return 0


def _save_decisions(decisions: list[DecisionRecord], store: StageStore, ts_tag: str) -> None:
    for d in decisions:
        try:
            doc = {
                "decision_id": d.decision_id,
                "schema_version": d.schema_version,
                "generated_at": d.generated_at.isoformat(),
                "mode": d.mode,
                "strategy_id": d.strategy_id,
                "symbol": d.symbol,
                "action": d.action,
                "confidence": d.confidence,
                "signal_strength": d.signal_strength,
                "risk_state": d.risk_state,
                "deny_reasons": d.deny_reasons,
                "requires_operator_approval": d.requires_operator_approval,
                "time_horizon": d.time_horizon,
                "evidence": d.evidence,
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
            store.write_decisions(f"decision_{d.symbol}_{ts_tag}.json", doc)
        except Exception:
            pass


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
) -> None:
    """Send paper demo summary to Telegram."""
    from stock_swing.utils.telegram_notifier import send_notification
    
    actionable = [d for d in decisions if d.action in {"buy", "sell"} and d.risk_state == "pass"]
    denied = [d for d in decisions if d.action == "deny"]
    held = [d for d in decisions if d.action in {"hold", "review"}]
    submitted_orders = [s for s in submissions if s.status == "submitted"]
    
    # Build summary message in Japanese
    mode_tag = "🧪 テスト実行" if dry_run else "📊 ペーパー取引"
    from datetime import datetime, timezone, timedelta
    jst = timezone(timedelta(hours=9))
    jst_time = datetime.now(timezone.utc).astimezone(jst).strftime('%Y-%m-%d %H:%M JST')
    
    lines = [
        f"<b>{mode_tag} - Stock Swing</b>",
        f"🗓 {jst_time}",
        "",
        f"<b>📈 分析結果</b>",
        f"<code>銘柄数        : {len(symbols)}</code>",
        f"<code>判断数        : {len(decisions)}</code>",
        f"<code>  実行可能    : {len(actionable)}</code>",
        f"<code>  拒否        : {len(denied)}</code>",
        f"<code>  保留        : {len(held)}</code>",
        "",
    ]
    
    if submissions:
        lines.append(f"<b>📝 注文</b>")
        lines.append(f"<code>送信済み      : {len(submitted_orders)}/{len(submissions)}</code>")
        for s in submitted_orders[:5]:  # Show first 5
            side_ja = "買い" if s.side.upper() == "BUY" else "売り"
            lines.append(f"<code>  {side_ja:4} {s.qty:>4}株 {s.symbol}</code>")
        if len(submitted_orders) > 5:
            lines.append(f"<code>  ... 他{len(submitted_orders) - 5}件</code>")
        lines.append("")
    
    lines.append(f"<b>💰 口座</b>")
    lines.append(f"<code>資産総額      : ${equity:,.2f}</code>")
    
    if denied:
        lines.append("")
        lines.append(f"⚠️ <b>{len(denied)}件のシグナルを拒否</b>")
    
    message = "\n".join(lines)
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


if __name__ == "__main__":
    raise SystemExit(main())
