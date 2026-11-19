#!/usr/bin/env python3
"""Read sealed actual inputs; compare entry components without any order path.

This is not a portfolio or fill simulator. The cron runner invokes it only
after the one actual workflow has ended, under network/write confinement.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / 'src'))
from stock_swing.experiments.candidate_input_capture import load_candidate_inputs
from stock_swing.experiments.decision_input_capture import load_input_run
from stock_swing.experiments.measurement_capture import _encode, _sha, _publish
from stock_swing.feature_engine.base_feature import FeatureResult
from stock_swing.strategy_engine.breakout_momentum_strategy import BreakoutMomentumStrategy
from stock_swing.strategy_engine.event_swing_strategy import EventSwingStrategy
from stock_swing.decision_engine.risk_validator import RiskValidator, RiskState
from stock_swing.risk.entry_filter import EntryFilterConfig, EntryFilterEngine
from stock_swing.risk.pf_history_receipt import load_pf_history

FOLDER = Path('data/analysis/entry_strength_shadow_v1')
PROTOCOL = 'paper050-shadow060-components-v1-20261118'


def _one(observations, stage):
    selected = [o['payload'] for o in observations if o['manifest']['stage'] == stage]
    if len(selected) != 1:
        raise ValueError('missing_or_duplicate_comparison_input:' + stage)
    return selected[0]


def _safe(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlinked_comparison_storage')


def build_strength_comparison(root: Path, run_id: str) -> dict:
    """Verify closure and actual generation; fail rather than infer missing gates."""
    if not isinstance(run_id, str) or not re.fullmatch(r'paper_demo-[A-Za-z0-9_-]{1,120}', run_id):
        raise ValueError('invalid_run_identity')
    root = Path(root).absolute()
    ref = 'data/audits/measurement_inputs/run_manifests/' + _sha(_encode(run_id)) + '.json'
    run = load_input_run(root, ref)
    checked = load_candidate_inputs(root, ref)
    if not run['capture_complete'] or not checked['capture_complete']:
        raise ValueError('incomplete_actual_capture')
    obs = run['observations']
    universe = _one(obs, 'candidate_universe')
    arguments = universe['arguments']
    if arguments.get('min_signal_strength') != .50 or arguments.get('min_momentum') != .05:
        raise ValueError('unexpected_actual_primary_policy')
    generation = _one(obs, 'entry_generation_inputs')
    features = [FeatureResult(**dict(f, computed_at=datetime.fromisoformat(f['computed_at'])))
                for f in generation['features']]
    stale = set(generation['stale_symbols'])
    stage = _one(obs, 'entry_filter_result')
    pf = load_pf_history(root, stage['pf_history_receipt'])
    if pf['run_id'] != run_id:
        raise ValueError('PF_run_mismatch')
    ef_source = SOURCE_ROOT / 'src/stock_swing/risk/entry_filter.py'
    if pf['entry_filter_source_sha256'] != _sha(ef_source.read_bytes()):
        raise ValueError('PF_consumer_source_mismatch')
    etfs = set(pf['etf_symbols'])
    baseline = [s for s in BreakoutMomentumStrategy(.05, .50, etfs).generate(features)
                + EventSwingStrategy().generate(features) if s.symbol not in stale]
    actual = sorted((s['symbol'], s['action'], s['strategy_id']) for s in generation['generated'])
    if sorted((s.symbol, s.action, s.strategy_id) for s in baseline) != actual:
        raise ValueError('actual_generation_does_not_match_pinned_components')
    records = defaultdict(list)
    for o in obs:
        if o['manifest']['stage'] == 'canonical_provider_bars':
            for r in o['payload']['records']:
                records[r['symbol']].append(SimpleNamespace(**r))
    config = EntryFilterConfig(**pf['entry_config'])
    history = [r['consumed'] for r in pf['history']]
    arms = {}
    for label, strength in [('paper_policy_050', .50), ('shadow_reference_060', .60)]:
        signals = [s for s in BreakoutMomentumStrategy(.05, strength, etfs).generate(features)
                   if s.symbol not in stale]
        validator = RiskValidator(strength, .40, 400)
        passed, denied = [], []
        for s in signals:
            risk = validator.validate(s, {})
            if risk.risk_state == RiskState.PASS:
                passed.append(s)
            else:
                denied.append(dict(symbol=s.symbol, reasons=risk.deny_reasons))
        filtered = EntryFilterEngine(config).filter(passed, dict(records), history, etfs)
        arms[label] = dict(min_signal_strength=strength,
            generated_symbols=sorted(s.symbol for s in signals),
            risk_passed_symbols=sorted(s.symbol for s in passed), risk_denied=denied,
            entry_passed_symbols=sorted(s.symbol for s in filtered.passed),
            entry_blocked=sorted([list(x) for x in filtered.blocked]))
    source_hashes = {str(f.relative_to(SOURCE_ROOT)): _sha(f.read_bytes())
                     for f in sorted((SOURCE_ROOT / 'src/stock_swing').rglob('*.py'))}
    source_hashes['scripts/entry_strength_shadow.py'] = _sha(Path(__file__).read_bytes())
    definition = dict(protocol=PROTOCOL, primary=.50, reference=.60, momentum=.05,
        confidence=.40, source_hashes=source_hashes,
        scope='breakout_generation_risk_entry_components_not_orders_or_portfolio',
        independent_virtual_portfolio_implemented=False)
    primary = set(arms['paper_policy_050']['entry_passed_symbols'])
    reference = set(arms['shadow_reference_060']['entry_passed_symbols'])
    if not reference <= primary:
        raise ValueError('reference_not_subset_of_primary_component')
    return dict(definition=definition, definition_sha256=_sha(_encode(definition)),
        run_id=run_id, run_ref=ref, input_manifest_sha256=run['manifest']['manifest_sha256'],
        source_exit_success=run['declared_exit_success'], requested_symbols=len(universe['symbols']),
        actual_primary_arguments=arguments, PF_receipt_sha256=stage['pf_history_receipt']['sha256'],
        arms=arms, entry_common_symbols=sorted(primary & reference),
        entry_added_050_symbols=sorted(primary - reference),
        risk_positions_scope='empty_position_component_not_path_dependent_book',
        later_gates='not_replayed_including_quarantine_exit_only_capital_size_and_execution',
        virtual_portfolio_PnL=None, economic_qualified=False,
        eligible_to_trade=False, orders_submitted=0)


def save_strength_comparison(root: Path, result: dict) -> dict:
    """Publish one immutable source/policy-bound result; exact retries are no-ops."""
    definition = result['definition']
    if (_sha(_encode(definition)) != result['definition_sha256']
            or definition.get('protocol') != PROTOCOL
            or result.get('eligible_to_trade') is not False
            or result.get('orders_submitted') != 0):
        raise ValueError('invalid_comparison_result')
    folder = Path(root).absolute() / FOLDER / result['definition_sha256'] / 'runs'
    _safe(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (_sha(_encode(result['run_id'])) + '.json')
    payload = dict(result=result, sha256=_sha(_encode(result)))
    _publish(path, _encode(payload))
    loaded = load_strength_comparison(root, str(path.relative_to(Path(root).absolute())))
    return dict(status='recorded', protocol=PROTOCOL, run_id=result['run_id'],
        path=str(path.relative_to(Path(root).absolute())), sha256=payload['sha256'],
        primary_strength=.50, shadow_strength=.60,
        primary_entry_count=len(loaded['arms']['paper_policy_050']['entry_passed_symbols']),
        shadow_entry_count=len(loaded['arms']['shadow_reference_060']['entry_passed_symbols']),
        source_exit_success=result['source_exit_success'], eligible_to_trade=False,
        scope=definition['scope'], portfolio_PnL_available=False, orders_submitted=0)


def load_strength_comparison(root: Path, ref: str) -> dict:
    """Strict recorded-result reader: missing/corrupt data is never zero success."""
    if not isinstance(ref, str) or not re.fullmatch(
            r'data/analysis/entry_strength_shadow_v1/[0-9a-f]{64}/runs/[0-9a-f]{64}\.json', ref):
        raise ValueError('unsafe_comparison_reference')
    path = Path(root).absolute() / ref
    _safe(path)
    payload = json.loads(path.read_bytes())
    result = payload['result']
    if (_sha(_encode(result)) != payload['sha256']
            or _sha(_encode(result['definition'])) != result['definition_sha256']
            or result['definition']['protocol'] != PROTOCOL
            or path.parent.parent.name != result['definition_sha256']
            or path.stem != _sha(_encode(result['run_id']))):
        raise ValueError('corrupt_comparison_result')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args(argv)
    try:
        result = save_strength_comparison(args.root, build_strength_comparison(args.root, args.run_id))
    except Exception as exc:
        print(json.dumps(dict(status='error', reason=type(exc).__name__, eligible_to_trade=False,
                              orders_submitted=0, retry_workflow=False)))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
