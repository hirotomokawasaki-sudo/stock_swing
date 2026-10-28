"""Optional, partial candidate checkpoints, not a full strategy replay recorder.

Reuse the existing audits stage and standard-library immutable publication.
StageStore/FeatureSnapshotStore alone do not provide immutable, fsynced manifest
publication. Blobs precede the manifest; an orphan blob is NOT an observation.
No broker, environment-variable dump, raw/free-text metadata or ledger writes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from stock_swing.core.path_manager import PathManager
def _sync_directory(folder):
    """Same fsync primitive as the existing recorder, without ledger dependencies."""
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)



class CaptureError(RuntimeError):
    """The measurement was not committed or cannot be trusted for replay."""


_TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z')
_STAGES = {'generated_daily', 'prioritized_entry'}
_CLI_TYPES = {'symbols': str, 'universe': str, 'timeframe': str, 'bar_limit': int,
              'min_momentum': float, 'min_signal_strength': float,
              'intraday_candidate_limit': int, 'dry_run': bool,
              'allow_outside_hours': bool}
_MISSING = ['complete_identity_and_decision_join', 'executed_code_and_dirty_patch',
            'effective_config', 'complete_candidate_filter_trace',
            'raw_market_inputs_and_availability', 'account_lots_pending_reservations',
            'dated_classification_and_lookthrough', 'entry_exit_cost_precedence',
            'whole_run_completion_and_replay_equality']


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode() + b'\n'


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _token(value):
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise CaptureError('invalid measurement identity')
    return value


def _storage(project_root, *, create):
    root = Path(project_root).absolute()
    folder = root/'data/audits/measurement_inputs'
    # Reject existing symlink ancestors, including the supplied root. This is a
    # cooperative local store, not an adversarial-filesystem isolation boundary.
    for part in [folder, *folder.parents]:
        if part.is_symlink():
            raise CaptureError('symlinked measurement storage')
    if create:
        audits = PathManager(root).data_stage('audits')
        for target in [audits/'measurement_inputs', folder/'blobs', folder/'manifests']:
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            _sync_directory(target.parent)
    return root, folder


def _publish(path, data):
    """Atomic no-replace link; identical retries are allowed, conflicts refuse."""
    if path.is_symlink():
        raise CaptureError('symlinked measurement object')
    if path.exists():
        if path.read_bytes() != data:
            raise CaptureError('immutable measurement identity conflict')
        return
    fd, name = tempfile.mkstemp(prefix='.capture-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(name, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                raise CaptureError('immutable measurement identity conflict')
        _sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CaptureError('invalid candidate numeric value')
    try:
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise CaptureError('nonfinite or out-of-range candidate value')
    except OverflowError as exc:
        raise CaptureError('overflow candidate value') from exc
    return value


def capture_candidates(project_root, *, enabled, run_id, experiment_id, stage,
                       observed_at, signals, stale_symbols, cli_settings,
                       source_revision, ranking_inputs=None):
    """Checkpoint only the caller's exact ordered signals at the named boundary.

    Disabled: zero I/O. Enabled failure: raise; never report a saved observation.
    Identity is run+stage; retries must supply the SAME recorded timestamp/inputs.
    CLI values are a partial allowlist, explicitly NOT effective runtime config.
    This function does not filter, sort, mutate signals, or invoke execution.
    """
    if enabled is False:
        return None
    try:
        if enabled is not True or stage not in _STAGES:
            raise CaptureError('invalid capture mode or stage')
        _token(run_id)
        if experiment_id is not None:
            _token(experiment_id)
        if not isinstance(source_revision, str) or not source_revision:
            raise CaptureError('missing recorded source revision')
        if not isinstance(observed_at, datetime) or observed_at.utcoffset() is None:
            raise CaptureError('measurement time must be timezone-aware')
        if not isinstance(signals, (list, tuple)) or not isinstance(stale_symbols, (list, tuple, set)):
            raise CaptureError('invalid candidate or stale-symbol collection')
        if not isinstance(cli_settings, dict):
            raise CaptureError('invalid CLI settings')
        candidates = []
        for i, signal in enumerate(signals):
            action = signal.action
            if action not in {'buy', 'sell', 'hold'}:
                raise CaptureError('invalid candidate action')
            candidates.append(dict(ordinal=i, symbol=_token(signal.symbol),
                                   strategy_id=_token(signal.strategy_id), action=action,
                                   signal_strength=_number(signal.signal_strength),
                                   confidence=_number(signal.confidence)))
        settings = {}
        for key, kind in _CLI_TYPES.items():
            if key not in cli_settings:
                continue
            value = cli_settings[key]
            if kind is float:
                if type(value) not in (float, int) or not math.isfinite(value):
                    raise CaptureError('invalid numeric CLI setting')
            elif type(value) is not kind:
                raise CaptureError('invalid CLI setting type')
            settings[key] = value
        sources = {}
        for path in [Path(__file__), Path(__file__).parents[1]/'cli/paper_demo.py']:
            sources[path.name] = _sha(path.read_bytes())
        payload = dict(candidates=candidates, stale_symbols=sorted({_token(s) for s in stale_symbols}),
                       cli_settings=settings, cli_scope='selected_arguments_not_effective_config',
                       source_files_on_disk=sources,
                       source_scope='recorded_revision_and_on_disk_files_not_executed_tree_attestation')
        if ranking_inputs is not None:
            _validated_ranking(ranking_inputs)
            payload['ranking_inputs'] = json.loads(_encode(ranking_inputs))
        encoded = _encode(payload)
        manifest = dict(schema_version=1, run_id=run_id, experiment_id=experiment_id,
                        stage=stage, observed_at=observed_at.astimezone(timezone.utc).isoformat(),
                        et_calendar_date=observed_at.astimezone(ZoneInfo('America/New_York')).date().isoformat(),
                        exchange_session_certified=False, source_revision=source_revision,
                        payload_sha256=_sha(encoded), candidate_count=len(candidates),
                        scope='partial_candidate_measurement_not_F1', full_replay_ready=False,
                        missing_contract_sections=list(_MISSING))
        manifest['manifest_sha256'] = _sha(_encode(manifest))
        identity = _sha(_encode([run_id, stage]))
        root, folder = _storage(project_root, create=True)
        target = folder/'manifests'/f'{identity}.json'
        # An existing manifest must also have intact dependencies on retry.
        if target.exists():
            loaded = load_capture(root, str(target.relative_to(root)))
            if loaded['manifest'] != manifest:
                raise CaptureError('immutable measurement identity conflict')
            return str(target.relative_to(root))
        _publish(folder/'blobs'/manifest['payload_sha256'], encoded)
        _publish(target, _encode(manifest))
        ref = str(target.relative_to(root))
        load_capture(root, ref)
        return ref
    except CaptureError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, OverflowError) as exc:
        raise CaptureError('candidate measurement not committed') from exc


def capture_ranking_inputs(*, signals, current_positions, equity, max_sector_exposure_pct):
    """Freeze allowlisted actual ranking arguments, not whole-account state/config.

    Preserve absence and numeric strings in position fields because the consumer
    applies its own float/default semantics. Capture the module classification
    map as used by this function, without calling it a dated registry.
    """
    from stock_swing.utils.signal_prioritization import SYMBOL_SECTORS
    try:
        def finite(value):
            if isinstance(value,bool) or not isinstance(value,(str,int,float)) or not math.isfinite(float(value)):
                raise CaptureError('invalid ranking numeric input')
            return value
        if not isinstance(signals,(list,tuple)) or not isinstance(current_positions,dict):
            raise CaptureError('invalid ranking collection')
        for limit in (equity,max_sector_exposure_pct):
            if isinstance(limit,bool) or not isinstance(limit,(int,float)):
                raise CaptureError('ranking limits must be numeric arguments')
            finite(limit)
        if float(equity)<0 or not 0<=float(max_sector_exposure_pct)<=1:
            raise CaptureError('invalid ranking limit')
        ordered=[]
        for signal in signals:
            metadata=getattr(signal,'metadata',None)
            selected={}
            if isinstance(metadata,dict) and 'estimated_notional' in metadata:
                value=metadata['estimated_notional']
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                    raise CaptureError('invalid estimated notional')
                selected['estimated_notional']=value
            if signal.action not in {'buy','sell','hold'}:raise CaptureError('invalid ranking action')
            ordered.append(dict(symbol=_token(signal.symbol),strategy_id=_token(signal.strategy_id),
                                action=signal.action,signal_strength=_number(signal.signal_strength),
                                confidence=_number(signal.confidence),metadata=selected))
        positions={}
        for symbol,position in current_positions.items():
            _token(symbol)
            if not isinstance(position,dict):raise CaptureError('invalid ranking position')
            positions[symbol]={k:finite(position[k]) for k in ['qty','current_price','avg_entry_price'] if k in position}
        symbols={s['symbol'].upper() for s in ordered}|{s.upper() for s in positions}
        sources={name:_sha((Path(__file__).parents[1]/directory/name).read_bytes()) for directory,name in
                 [('utils','signal_prioritization.py'),('risk','position_sizing.py')]}
        return dict(scope='prioritize_buy_signals_v2_arguments_only',ordered_candidates=ordered,
                    current_positions=positions,equity=equity,max_sector_exposure_pct=max_sector_exposure_pct,
                    symbol_sectors={s:SYMBOL_SECTORS.get(s) for s in sorted(symbols)},
                    classification_basis='module_mapping_not_dated_registry',source_sha256=sources)
    except CaptureError:raise
    except (ValueError,TypeError,AttributeError,OSError,OverflowError) as exc:
        raise CaptureError('invalid ranking input snapshot') from exc


def _validated_ranking(saved):
    try:
        regenerated=capture_ranking_inputs(
            signals=[SimpleNamespace(**row) for row in saved['ordered_candidates']],
            current_positions=saved['current_positions'],equity=saved['equity'],
            max_sector_exposure_pct=saved['max_sector_exposure_pct'])
        if regenerated!=saved:raise CaptureError('ranking source/mapping/schema conflict')
    except (KeyError,TypeError,AttributeError) as exc:
        raise CaptureError('missing or invalid ranking inputs') from exc


def replay_saved_ranking(observation):
    """Replay only prioritization with captured arguments and matching local source.

    This is not feature generation, order sizing/execution, PIT certification,
    a complete effective-config replay or an economic qualification.
    """
    from stock_swing.utils.signal_prioritization import prioritize_buy_signals_v2
    try:
        saved=observation['payload']['ranking_inputs'];_validated_ranking(saved)
        result=prioritize_buy_signals_v2(
            signals=[SimpleNamespace(**row) for row in saved['ordered_candidates']],
            current_positions=saved['current_positions'],equity=saved['equity'],
            max_sector_exposure_pct=saved['max_sector_exposure_pct'])
        fields=['symbol','strategy_id','action','signal_strength','confidence']
        actual=[{k:getattr(s,k) for k in fields} for s in result]
        recorded=[{k:r[k] for k in fields} for r in observation['payload']['candidates']]
        return dict(scope='ranking_segment_only',input_count=len(saved['ordered_candidates']),
                    output_count=len(actual),ordered_output_matches=actual==recorded,full_replay_ready=False)
    except (KeyError,TypeError,AttributeError,ValueError) as exc:
        raise CaptureError('cannot replay missing/invalid ranking observation') from exc


def load_capture(project_root, ref):
    """Verify one committed manifest and its exact dependency without mutation."""
    try:
        root, folder = _storage(project_root, create=False)
        path = Path(ref)
        if (path.is_absolute() or path.parent != Path('data/audits/measurement_inputs/manifests')
                or not re.fullmatch(r'[0-9a-f]{64}\.json', path.name)):
            raise CaptureError('unsafe measurement reference')
        target = root/path
        if target.is_symlink():
            raise CaptureError('symlinked measurement manifest')
        manifest = json.loads(target.read_bytes())
        claimed = manifest.pop('manifest_sha256')
        if _sha(_encode(manifest)) != claimed:
            raise CaptureError('corrupt measurement manifest')
        if (manifest['scope'] != 'partial_candidate_measurement_not_F1'
                or manifest['full_replay_ready'] is not False
                or manifest['missing_contract_sections'] != _MISSING
                or manifest['stage'] not in _STAGES or manifest['schema_version'] != 1
                or manifest['exchange_session_certified'] is not False
                or path.stem != _sha(_encode([manifest['run_id'],manifest['stage']]))):
            raise CaptureError('unsupported measurement contract')
        checksum = manifest['payload_sha256']
        if not isinstance(checksum, str) or not re.fullmatch('[0-9a-f]{64}', checksum):
            raise CaptureError('invalid dependency hash')
        blob = folder/'blobs'/checksum
        if blob.is_symlink():
            raise CaptureError('symlinked measurement dependency')
        data = blob.read_bytes()
        if _sha(data) != checksum:
            raise CaptureError('corrupt measurement dependency')
        payload = json.loads(data)
        if len(payload['candidates']) != manifest['candidate_count']:
            raise CaptureError('candidate count mismatch')
        manifest['manifest_sha256'] = claimed
        return dict(manifest=manifest, payload=payload)
    except CaptureError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise CaptureError('missing or invalid measurement observation') from exc
