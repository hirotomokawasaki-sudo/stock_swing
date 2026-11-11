"""Opt-in receipts of already-constructed CLI configs, never raw environment."""
from __future__ import annotations
import hashlib
import inspect
import json
import math
import os
import re
from dataclasses import asdict, fields
from pathlib import Path
from stock_swing.risk.config_instance_specs import SPECS
from stock_swing.tracking.trade_event_store import TradeEvent, TradeEventStore


def instance_receipt(instance, consumer: str) -> dict:
    """Copy only allowlisted scalar fields; reject secrets/type/schema drift."""
    kind=type(instance).__name__
    receipt=dict(kind='instance:'+kind,status='unavailable',effective=None,
                 source='constructed_from_env_result',consumer='paper_demo',issues=[])
    try:
        spec=SPECS[kind]
        if type(instance).__module__!=spec['module'] or consumer!='paper_demo:'+kind:
            raise ValueError('config_identity_unqualified')
        if {f.name for f in fields(instance)}!=set(spec['fields']):
            raise ValueError('config_field_drift')
        values=asdict(instance)
        for name, annotation in spec['fields'].items():
            value=values[name]
            if annotation=='bool':valid=type(value) is bool
            elif annotation=='int':valid=type(value) is int
            elif annotation=='float':valid=type(value) in {int,float} and math.isfinite(value)
            elif annotation=='str':valid=value in {'shadow','paper_ab','active','disabled','enforce','off'}
            elif annotation=='list[str]':valid=isinstance(value,list) and len(value)<=64 and all(isinstance(x,str) and re.fullmatch(r'[A-Z][A-Z0-9.^-]{0,14}',x) for x in value)
            else:valid=False
            if not valid:raise ValueError('config_value_refused')
        source=Path(inspect.getfile(type(instance)))
        receipt.update(status='observed',effective=json.loads(json.dumps(values,allow_nan=False)),
            source_module=spec['module'],source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            environment_keys_present=[k for k in spec['environment_keys'] if k in os.environ])
    except Exception as exc:
        receipt['issues']=['config_observation_unavailable:'+type(exc).__name__]
    return receipt


class ConfigInstanceRecorder:
    """Reuse the existing append/fsync primitive; failures do not change trades."""
    def __init__(self, root: Path, run_id: str):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,180}',run_id):raise ValueError('unsafe_run_id')
        self.root=root;self.run_id=run_id;self.receipts=[];self.failures=0
        self._instances={};self._seen=set();self._finalized=False

    def _persist(self, receipt, event_type='config_instance_consumed'):
        receipt['recorded']=False
        problem=receipt['status'] not in {'observed','not_reached'}
        try:
            path=self.root/'reports/config_instances'/f'{self.run_id}.jsonl'
            if any(p.is_symlink() for p in [self.root/'reports',path.parent,path]):raise ValueError('receipt_symlink')
            store=TradeEventStore(self.root,str(path.relative_to(self.root)))
            store.append(TradeEvent.create(event_type,run_id=self.run_id,payload=dict(receipt,recorded=True)))
            receipt['recorded']=True
        except Exception as exc:
            receipt.update(status='unavailable',issues=receipt['issues']+['config_receipt_not_recorded:'+type(exc).__name__])
            problem=True
        if problem:self.failures+=1
        self.receipts.append(receipt)

    def capture(self, instance, consumer: str) -> None:
        receipt=instance_receipt(instance,consumer)
        kind=type(instance).__name__
        self._seen.add(kind)
        if receipt['status']=='observed':self._instances[kind]=(instance,receipt['effective'])
        self._persist(receipt)

    def construct(self, config_type, *, factory=None):
        """Record a failed attempt then re-raise the original error unchanged."""
        kind=config_type.__name__
        if kind not in SPECS or config_type.__module__!=SPECS[kind]['module']:
            raise ValueError('config_constructor_identity_unqualified')
        self._seen.add(kind)
        try:
            instance=(factory or config_type.from_env)()
        except Exception as exc:
            self._persist(dict(kind='instance:'+kind,status='construction_failed',
                effective=None,source='from_env_attempt',consumer='paper_demo',
                issues=['config_construction_failed:'+type(exc).__name__]),
                'config_instance_construction_failed')
            raise
        self.capture(instance,'paper_demo:'+kind)
        return instance

    def finalize(self):
        """Report unvisited families and endpoint drift; never instantiate/restore."""
        if self._finalized:return
        self._finalized=True
        for kind,(instance,before) in self._instances.items():
            current=instance_receipt(instance,'paper_demo:'+kind)
            if current['status']!='observed' or current['effective']!=before:
                current['status']='changed_since_capture' if current['status']=='observed' else 'unavailable'
                current['issues']+=['config_endpoint_changed_or_unavailable']
                self._persist(current,'config_instance_endpoint_changed')
        for kind in sorted(set(SPECS)-self._seen):
            self._persist(dict(kind='instance:'+kind,status='not_reached',effective=None,
                source='run_boundary',consumer='paper_demo',issues=[]),
                'config_instance_not_reached')
