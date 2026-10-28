"""Validate only consumed settings; defaults are legacy, not a new exit policy."""
from __future__ import annotations
import hashlib, math
from pathlib import Path
from typing import Any
import yaml

EXIT_DEFAULTS = dict(stop_loss_pct=-.07,breakeven_activation_pct=.03,trailing_activation_pct=.08,
 trailing_stop_pct=.04,max_hold_days=20,staged_trailing_enabled=False,staged_trailing_levels=[],
 min_hold_days=1,min_hold_days_enabled=True,emergency_stop_bypass_pct=-.12,
 tiered_min_hold_enabled=False,tiered_min_hold_levels=[],broker_recon_graduation_days=5,
 staged_breakeven_enabled=False,staged_breakeven_levels=[],volatility_adjusted_stop_enabled=False,
 volatility_multiplier_min=.5,volatility_multiplier_max=1.75,per_lot_time_based_exit_enabled=False)
INTRADAY_DEFAULTS = dict(lookback_bars=25,smoothing_window=5,vwap_threshold=.005,signal_criteria=dict(momentum_threshold=.003))


def _numeric(value: Any, *, integral=False, nonnegative=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value): raise ValueError("nonfinite_or_invalid_number")
    if integral and (type(value) is not int or value < 0): raise ValueError("invalid_integer")
    if nonnegative and value < 0: raise ValueError("negative_parameter")


def read_effective_config(path: Path, kind: str) -> tuple[dict, dict]:
    defaults=EXIT_DEFAULTS if kind=="exit" else INTRADAY_DEFAULTS
    receipt=dict(path=str(path.resolve()),kind=kind,sha256=None,status="unavailable",issues=[],unused_keys=[])
    try:
        data=path.read_bytes();receipt['sha256']=hashlib.sha256(data).hexdigest()
        raw=yaml.safe_load(data)
        if not isinstance(raw,dict): raise ValueError("root_not_mapping")
        values=dict(defaults,**{k:v for k,v in raw.items() if k in defaults})
        for key,value in values.items():
            if key.endswith('_enabled'):
                if type(value) is not bool: raise ValueError("invalid_boolean:"+key)
            elif key.endswith('_levels'):
                if not isinstance(value,list): raise ValueError("levels_not_list:"+key)
                fields={'staged_trailing_levels':('activation_pct','trailing_stop_pct'),'tiered_min_hold_levels':('offset_pct','min_hold_days'),'staged_breakeven_levels':('activation_pct','floor_pct')}[key]
                for row in value:
                    if not isinstance(row,dict) or not all(f in row for f in fields): raise ValueError("invalid_level:"+key)
                    for f in fields:_numeric(row[f],integral=f=='min_hold_days')
            elif key=='signal_criteria':
                if not isinstance(value,dict): raise ValueError("criteria_not_mapping")
                _numeric(value.get('momentum_threshold',.003),nonnegative=True)
            else:
                integer=key.endswith('_days') or key in {'lookback_bars','smoothing_window'}
                _numeric(value,integral=integer,nonnegative=key not in {'stop_loss_pct','emergency_stop_bypass_pct'})
                if key in {'lookback_bars','smoothing_window','max_hold_days'} and value<=0: raise ValueError("nonpositive_window")
        if kind=='exit' and values['volatility_multiplier_min']>values['volatility_multiplier_max']: raise ValueError('reversed_volatility_range')
        receipt.update(status='configured',unused_keys=sorted(set(raw)-set(defaults)),effective=values)
        return dict(values),receipt
    except (OSError,ValueError,TypeError,yaml.YAMLError) as exc:
        receipt['issues']=[str(exc) if isinstance(exc,ValueError) else type(exc).__name__]
        receipt['fallback']='legacy_missing_file_defaults; draft, not equivalent to configured exits'
        receipt['effective']=defaults
        return dict(defaults),receipt
