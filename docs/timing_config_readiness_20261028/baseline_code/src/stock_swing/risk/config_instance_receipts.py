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

    def capture(self, instance, consumer: str) -> None:
        receipt=instance_receipt(instance,consumer)
        receipt['recorded']=False
        try:
            path=self.root/'reports/config_instances'/f'{self.run_id}.jsonl'
            if any(p.is_symlink() for p in [self.root/'reports',path.parent,path]):raise ValueError('receipt_symlink')
            store=TradeEventStore(self.root,str(path.relative_to(self.root)))
            if receipt['status']!='observed':raise ValueError('receipt_refused')
            store.append(TradeEvent.create('config_instance_consumed',run_id=self.run_id,payload=dict(receipt,recorded=True)))
            receipt['recorded']=True
        except Exception as exc:
            receipt.update(status='unavailable',issues=receipt['issues']+['config_receipt_not_recorded:'+type(exc).__name__])
            self.failures+=1
        self.receipts.append(receipt)
