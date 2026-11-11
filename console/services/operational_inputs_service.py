"""Pure display projections of acquired evidence; never a trading gate.

No broker calls, tracking constructors, quality stamps, order actions or repairs.
Buying power is broker-reported capacity, not withdrawable or settled cash.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import yaml

from console.services.operational_evidence_service import _number, _stamp, _read


def _fresh(evidence, now):
    stamp, age = _stamp((evidence or {}).get('as_of'), now)
    return (evidence or {}).get('status') == 'ok' and age is not None and age <= 120


def funds_projection(account, evidence, *, now):
    """Expose allowlisted original account fields, with no second reservation debit."""
    fresh = _fresh(evidence, now)
    raw = account if isinstance(account, dict) and fresh else {}
    fields = ('cash', 'buying_power', 'non_marginable_buying_power',
              'regt_buying_power', 'daytrading_buying_power', 'initial_margin', 'maintenance_margin')
    result = {key: _number(raw.get(key)) for key in fields}
    # Cash can be signed; capacities/margins cannot be interpreted as negative.
    for key in fields[1:]:
        if result[key] is not None and result[key] < 0:
            result[key] = None
    result.update(status='reported' if fresh else 'unknown',
        as_of=evidence.get('as_of') if fresh else None,
        currency=raw.get('currency') if isinstance(raw.get('currency'),str) and len(raw['currency'])==3 else None,
        reserved_cash=None, free_settled_cash=None, withdrawable_cash=None,
        buying_power_includes_open_order_effect=True if result['buying_power'] is not None else None,
        reason='broker報告の現在買付余力。未約定概算を再控除しません。予約額・受渡済み現金・出金可能額は別で、取得値がなく未確認。',
        definition_source='https://docs.alpaca.markets/us/docs/orders-at-alpaca')
    return result


def portfolio_projection(root, positions, positions_evidence, pending, account, account_evidence, *, now, proposal=None):
    """Current MTM and explicit limit-BUY scenario, not an execution-risk approval.

    No saved historical decision is silently reused as a current proposal. Pending
    orders or short/complex positions withhold the simple scenario. Its allocation
    projection assumes fixed prices/equity, ignores fees and does not certify fills.
    """
    result = dict(status='unknown', as_of=(positions_evidence or {}).get('as_of'),
        account_as_of=(account_evidence or {}).get('as_of'),
        current_gross_exposure_pct=None, current_largest_position_pct=None,
        classified_positions=None, total_positions=None, classification_coverage=None,
        projected_concentration=None, projected_status='no_proposal' if proposal is None else 'unqualified_inputs',
        reserved_cash=None, policy_approved=False, atomic_snapshot=False,
        reason='現在の評価額と明示注文案のシナリオは別。追加取得・売買許可判定は行いません。')
    if not (_fresh(positions_evidence, now) and _fresh(account_evidence, now)):
        return result
    equity = _number((account or {}).get('equity'))
    if equity is None or equity <= 0 or (account or {}).get('currency')!='USD' or not isinstance(positions, list):
        return result
    try:
        registry_bytes = (root/'config/reference/symbol_registry.yaml').read_bytes()
        registry = yaml.safe_load(registry_bytes)['symbols']
        if not isinstance(registry, dict):
            raise ValueError('registry schema')
        values = {}; classified = 0
        for row in positions:
            if not isinstance(row, dict):
                raise ValueError('position schema')
            symbol = row.get('symbol'); qty = _number(row.get('qty')); value = _number(row.get('market_value'))
            if (not isinstance(symbol, str) or not symbol or symbol in values or
                    qty is None or qty <= 0 or value is None or value < 0 or
                    row.get('side', 'long') != 'long'):
                raise ValueError('unsupported position')
            info = registry.get(symbol, {})
            qualified = (isinstance(info, dict) and info.get('asset_class') in ('stock','etf')
                         and isinstance(info.get('sector'),str) and info['sector'] not in ('','unknown'))
            classified += qualified
            values[symbol] = Decimal(str(value))
        total = len(values); gross = sum(values.values(), Decimal(0)); denominator = Decimal(str(equity))
        if _number(float(gross/denominator)) is None:
            raise ValueError('nonfinite exposure')
        result.update(status='observed_scope_only', total_positions=total, classified_positions=classified,
            classification_coverage=classified/total if total else None,
            classification_state='empty_population' if not total else 'complete' if classified==total else 'partial',
            registry_sha256=hashlib.sha256(registry_bytes).hexdigest(),
            current_gross_exposure_pct=float(gross/denominator),
            current_largest_position_pct=float(max(values.values(), default=Decimal(0))/denominator))
        if proposal is not None:
            symbol = proposal.get('symbol'); qty = _number(proposal.get('qty')); price = _number(proposal.get('limit_price'))
            info = registry.get(symbol, {}) if isinstance(symbol,str) else {}
            if (proposal.get('side')!='buy' or proposal.get('type')!='limit' or qty is None or qty<=0 or
                    price is None or price<=0 or info.get('asset_class') not in ('stock','etf') or
                    info.get('sector') in (None,'','unknown') or classified!=total or
                    pending.get('complete_open_query') is not True or
                    pending.get('status')!='observed_scope_only' or
                    not _fresh(dict(status='ok',as_of=pending.get('as_of')),now) or
                    type(pending.get('observed_active_orders')) is not int or pending['observed_active_orders']!=0):
                return result
            values[symbol] = values.get(symbol,Decimal(0)) + Decimal(str(qty))*Decimal(str(price))
            if _number(float(sum(values.values())/denominator)) is None:
                return result
            result.update(projected_status='limit_buy_scenario',
                projected_concentration=float(max(values.values())/denominator),
                projected_gross_exposure_pct=float(sum(values.values())/denominator),
                projection_scope='Explicit limit-BUY notional at fixed equity/prices; no fees/fill/permission certification')
        return result
    except (OSError, ValueError, TypeError, KeyError, OverflowError, AttributeError, yaml.YAMLError):
        return result


def quality_context(root, *, now):
    """Describe scheduled age and quarantines without waiving strict health."""
    result = dict(status='unknown', as_of=now.isoformat(), strict_health_waived=False,
        summary_at_or_after_due=None, breaker_at_or_after_due=None, day_start_matches_due_session=None,
        expected_completed_slot=None, inline_quarantined=None, separate_quarantined=None,
        ledger_audit_status='unknown', quality_stamp_updated=False,
        reason='定時更新との対応と台帳隔離を説明する補助情報。既存health・売買ゲートの判定は変更しません。')
    try:
        from scripts.check_operational_recovery import expected_run_at, _fresh as at_or_after
        from zoneinfo import ZoneInfo
        due = expected_run_at(now)
        summary, ss = _read(root, 'reports/console/latest_console_summary.json')
        cb, cs = _read(root, 'data/guardrails/circuit_breaker.json')
        day, ds = _read(root, 'data/guardrails/day_start_snapshot.json')
        run = summary.get('run', {})
        genuine = ss=='ok' and run.get('dry_run') is False and run.get('invocation_source')=='paper_demo_scheduled'
        result.update(expected_completed_slot=due.isoformat(), summary_genuine=genuine,
            summary_at_or_after_due=genuine and at_or_after(run.get('timestamp'),due,now),
            breaker_at_or_after_due=cs=='ok' and at_or_after(cb.get('last_evaluated_at'),due,now),
            day_start_matches_due_session=ds=='ok' and day.get('market_date')==due.astimezone(ZoneInfo('America/New_York')).date().isoformat())
        # FIX-06 / 2026-11-09: explanatory counts must use the same coherent
        # state/events boundary as the quantity panel. Never recover on read,
        # block behind a writer, or create a missing tracking directory.
        from stock_swing.tracking.compatibility import read_analysis_snapshot
        from stock_swing.tracking.ledger_transaction import ledger_transaction
        path=root/'data/tracking/pnl_state.json'
        _, status = _read(root, 'data/tracking/pnl_state.json')
        if status != 'ok':
            return result
        with ledger_transaction(root, recover=False, blocking=False):
            _, status = _read(root, 'data/tracking/pnl_state.json')
            if status != 'ok':
                return result
            raw, ledger_evidence = read_analysis_snapshot(path)
        rows=raw['trades']; isolated=raw.get('quarantined_trades',[])
        if not isinstance(rows,list) or not isinstance(isolated,list) or not all(isinstance(x,dict) for x in rows+isolated):
            raise ValueError('ledger schema')
        result.update(status='reported', ledger_sha256=ledger_evidence['state_sha256'],
            ledger_events_sha256=ledger_evidence['events_sha256'],
            ledger_revision=ledger_evidence['ledger_revision'],
            inline_quarantined=sum(t.get('status')=='quarantined' for t in rows), separate_quarantined=len(isolated),
            ledger_audit_status='not_recertified', quarantine_count_scope='two containers may overlap; do not add',
            ledger_next_action='正しいentry/exit原証拠と更新経路を確認。原台帳・品質stampを自動修復しません。')
        return result
    except (OSError, ValueError, TypeError, KeyError, ImportError, AttributeError, RuntimeError):
        return {**result, 'reason_code':'quality_inputs_unavailable',
            'reason':'根拠入力が不正・処理中・未取得のため台帳件数は未確認。読取から復旧せず、既存health・売買ゲートの判定を変更しません。'}
