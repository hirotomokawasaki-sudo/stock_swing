"""Opt-in actual PF-input receipt; not a clean-ledger or portfolio certification.

Reuse immutable fsynced publication. Only PF-consumed fields and allowlisted leg
identities are retained. No raw notes, environment, broker calls or ledger writes.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

from stock_swing.experiments.measurement_capture import _publish
from stock_swing.risk.config_instance_receipts import instance_receipt
from stock_swing.risk.entry_filter import EntryFilterConfig, compute_rolling_pf

FOLDER=Path('data/audits/pf_history')
SCHEMA='pf-consumed-history-v1-20261029'
LINEAGE=('trade_id','execution_leg_id','entry_order_id','exit_order_id',
         'broker_order_id','decision_id','entry_time','exit_time','quarantined')


def _encode(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,
                      separators=(',',':')).encode()+b'\n'


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _token(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,179}',value):
        raise ValueError('invalid identity')
    return value


def _clock(value):
    stamp=value if isinstance(value,datetime) else datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:raise ValueError('ambiguous clock')
    return stamp.isoformat()


def _no_links(path):
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('symlink receipt')


def _scalar(value):
    if value is None or type(value) in {bool,int}:return value
    if type(value) is float and math.isfinite(value):return value
    if isinstance(value,str) and len(value)<=180 and re.fullmatch(r'[A-Za-z0-9_.:+ -]*',value):return value
    raise ValueError('unsupported receipt scalar')


class PFHistoryCapture:
    """Snapshot before the real filter; commit its output without reevaluation."""
    def __init__(self, *, root, run_id, experiment_config_hash, decisions,
                 closed_trades, entry_config, etf_symbols, observed_at, dry_run=False):
        self.root=Path(root);self.doc=None;self.dry_run=dry_run
        try:
            config=instance_receipt(entry_config,'paper_demo:EntryFilterConfig')
            if config['status']!='observed':raise ValueError('unqualified entry config')
            rows=[]
            for i,t in enumerate(closed_trades):
                status=_scalar(t.get('status'))
                consumed={'status':status}
                if status=='closed':
                    symbol=t.get('symbol');pnl=t.get('pnl')
                    if symbol:_token(symbol)
                    if pnl is not None and not math.isfinite(float(pnl)):
                        raise ValueError('nonfinite consumed PnL')
                    consumed.update(symbol=_scalar(symbol),pnl=_scalar(pnl))
                rows.append(dict(source_index=i,consumed=consumed,
                    lineage={k:_scalar(t[k]) for k in LINEAGE if k in t} if status=='closed' else {}))
            self.doc=dict(schema=SCHEMA,run_id=_token(run_id),
                experiment_config_hash=_token(experiment_config_hash),
                observed_at=_clock(observed_at),input_source='pnl_tracker.state.trades',
                clean_history_certified=False,full_portfolio_replay=False,
                loader_input_qualification='not_observed; empty consumed state is not proof of a known empty ledger',
                history=rows,history_sha256=_sha(_encode(rows)),
                history_hash_scope='ordered consumed projection plus allowlisted lineage; not raw file bytes',
                entry_config=config['effective'],entry_config_sha256=_sha(_encode(config['effective'])),
                entry_filter_source_sha256=config['source_sha256'],
                etf_symbols=sorted(_token(s) for s in etf_symbols),
                decisions=[dict(decision_id=_token(d.decision_id),symbol=_token(d.symbol),
                    action=_token(d.action),generated_at=_clock(d.generated_at)) for d in decisions])
            _encode(self.doc)
        except Exception:
            self.doc=None

    def finish(self,result):
        if self.dry_run:return dict(status='dry_run',schema=SCHEMA)
        try:
            if self.doc is None:raise ValueError('input unavailable')
            doc=dict(self.doc,outputs=dict(passed_ids=[_token(d.decision_id) for d in result.passed],
                blocked=[[ _token(symbol),str(reason)] for symbol,reason in result.blocked]))
            data=_encode(doc);relative=FOLDER/(doc['run_id']+'.json')
            path=self.root/relative;_no_links(path);path.parent.mkdir(parents=True,exist_ok=True)
            _publish(path,data)
            return dict(status='recorded',schema=SCHEMA,path=relative.as_posix(),
                        sha256=_sha(data),run_id=doc['run_id'],history_sha256=doc['history_sha256'])
        except Exception as exc:
            return dict(status='unavailable',schema=SCHEMA,reason=type(exc).__name__)


def load_pf_history(root,ref, *, decision_id=None):
    """Verify the exact immutable object and its decision join before replay."""
    if not isinstance(ref,dict) or ref.get('status')!='recorded' or ref.get('schema')!=SCHEMA:
        raise ValueError('unsupported receipt')
    relative=PurePosixPath(ref['path'])
    if (relative.is_absolute() or '..' in relative.parts or str(relative)!=ref['path']
            or relative.parent!=PurePosixPath(FOLDER.as_posix())
            or relative.name!=_token(ref['run_id'])+'.json'):
        raise ValueError('unsafe receipt path')
    path=Path(root)/relative;_no_links(path);data=path.read_bytes()
    if _sha(data)!=ref['sha256']:raise ValueError('receipt hash mismatch')
    doc=json.loads(data)
    if (doc['schema']!=SCHEMA or doc['run_id']!=ref['run_id']
            or doc['history_sha256']!=_sha(_encode(doc['history']))
            or doc['history_sha256']!=ref['history_sha256']
            or doc['entry_config_sha256']!=_sha(_encode(doc['entry_config']))
            or doc['clean_history_certified'] is not False):
        raise ValueError('receipt dependency mismatch')
    linked=ref.get('decision_id')
    if linked is not None:
        if decision_id is not None and decision_id!=linked:raise ValueError('conflicting decision link')
        decision_id=linked
    ids=[row['decision_id'] for row in doc['decisions']]
    if len(ids)!=len(set(ids)) or decision_id is not None and decision_id not in ids:
        raise ValueError('receipt decision mismatch')
    _clock(doc['observed_at'])
    return doc


def replay_pf_history(doc):
    """Bounded PF arithmetic only; not volume/ADR, full decisions, Exit or profit A/B."""
    config=EntryFilterConfig(**doc['entry_config'])
    pin=instance_receipt(config,'paper_demo:EntryFilterConfig')
    if pin['status']!='observed' or pin['source_sha256']!=doc['entry_filter_source_sha256']:
        raise ValueError('PF source changed')
    rows=[row['consumed'] for row in doc['history'] if row['consumed']['status']=='closed']
    stats=compute_rolling_pf(rows,min_trades=config.min_trades_for_gate)
    return {sym:dict(closed_count=p.closed_count,profit_factor=p.profit_factor,
        gate3_would_block=(not config.disabled and sym not in config.pf_gate_skip_symbols
            and p.profit_factor is not None and p.profit_factor<config.rolling_pf_gate),
        gate4_would_block=(not config.disabled and config.stock_reduced_mode
            and sym not in doc['etf_symbols'] and p.closed_count>=config.stock_reduced_min_trades
            and (p.profit_factor if p.profit_factor is not None else 0)<config.stock_reduced_pf_gate))
        for sym,p in stats.items()}
