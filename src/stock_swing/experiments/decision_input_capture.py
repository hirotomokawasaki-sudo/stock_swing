"""Opt-in immutable actual-boundary observations; never a full-replay certificate.

Reuses the existing fsynced blob/manifest publication. No environment dump,
broker I/O, ledger mutation, policy change or automatic measurement promotion.
"""
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import threading
import re
from urllib.parse import urlsplit, parse_qsl
from uuid import uuid4

from .measurement_capture import CaptureError, _encode, _sha, _token, _storage, _publish
from .measurement_capture import _sync_directory


def _credential_field(key):
    canonical=re.sub('[^a-z0-9]','',key.lower())
    return any(term in canonical for term in ('apikey','apisecret','authorization',
        'password','accesstoken','refreshtoken','privatekey','sessiontoken'))


def capture_value(value):
    """Freeze typed consumer arguments; refuse unsupported objects and secrets."""
    if is_dataclass(value): return capture_value(asdict(value))
    if isinstance(value, Enum): return capture_value(value.value)
    if isinstance(value, datetime):
        if value.utcoffset() is None: raise CaptureError('naive input observation clock')
        return value.isoformat()
    if isinstance(value, dict):
        result={}
        for key,item in value.items():
            if not isinstance(key,str): raise CaptureError('nontext input field')
            if _credential_field(key):
                raise CaptureError('credential field not permitted in measurement')
            result[key]=capture_value(item)
        return result
    if isinstance(value,(list,tuple)): return [capture_value(v) for v in value]
    if isinstance(value,(set,frozenset)):
        return sorted((capture_value(v) for v in value),key=lambda v:_encode(v))
    if isinstance(value,str) and '://' in value:
        try:
            parts=urlsplit(value)
            if parts.username is not None or parts.password is not None or any(
                    _credential_field(key) for key,_ in parse_qsl(parts.query,keep_blank_values=True)):
                raise CaptureError('credential URL not permitted in measurement')
        except ValueError as exc:
            raise CaptureError('invalid input URL') from exc
    if value is None or type(value) in (str,int,float,bool):
        try: _encode(value)
        except (ValueError,OverflowError): raise CaptureError('nonfinite input value') from None
        return value
    raise CaptureError('unsupported input value')


class DecisionInputRecorder:
    """A run-scoped recorder. Disabled is zero storage I/O, even for bad inputs.

    record() is strict. observe() is a non-disruptive instrumentation adapter:
    failure is retained in memory and must be surfaced by the run finalizer.
    An observed broker ACK is not a fill; an order aggregate is not an execution.
    """
    def __init__(self, project_root, *, enabled, run_id):
        if type(enabled) is not bool: raise CaptureError('invalid observation mode')
        self.root=Path(project_root);self.enabled=enabled;self.run_id=run_id
        self.failures=0;self.committed=0;self._lock=threading.RLock()
        self._references=[];self._sealed_ref=None

    def record(self, stage, identity, payload, *, observed_at):
        if not self.enabled: return None
        with self._lock:
            if self._sealed_ref is not None:
                raise CaptureError('input run already sealed')
            ref=self._record(stage,identity,payload,observed_at=observed_at)
            if ref not in self._references:
                self._references.append(ref)
                self.committed=len(self._references)
            return ref

    def _record(self, stage, identity, payload, *, observed_at):
        try:
            _token(self.run_id);_token(stage);_token(identity)
            if not isinstance(observed_at,datetime) or observed_at.utcoffset() is None:
                raise CaptureError('observation clock must be aware')
            encoded=_encode(capture_value(payload))
            envelope=dict(schema_version=1,run_id=self.run_id,stage=stage,identity=identity,
                local_observed_at=observed_at.astimezone(timezone.utc).isoformat(),
                payload_sha256=_sha(encoded),scope='actual_boundary_partial_inputs_not_F1',
                provider_available_at_certified=False,full_replay_ready=False)
            envelope['manifest_sha256']=_sha(_encode(envelope))
            root,folder=_storage(self.root,create=True)
            if (folder/'blobs').is_symlink(): raise CaptureError('symlinked input blob directory')
            manifests=folder/'decision_manifests'
            if manifests.is_symlink(): raise CaptureError('symlinked observation directory')
            manifests.mkdir(mode=0o700,exist_ok=True)
            _sync_directory(manifests.parent)
            key=_sha(_encode([self.run_id,stage,identity]))
            _publish(folder/'blobs'/envelope['payload_sha256'],encoded)
            _publish(manifests/(key+'.json'),_encode(envelope))
            ref=str((manifests/(key+'.json')).relative_to(root))
            load_decision_input(root,ref)
            return ref
        except CaptureError: raise
        except (ValueError,TypeError,OSError,OverflowError,RecursionError) as exc:
            raise CaptureError('input observation not committed') from exc

    def observe(self, stage, payload, *, identity=None, observed_at=None):
        """Record one callback without changing trading flow on capture failure."""
        if not self.enabled: return None
        with self._lock:
            try:
                ref=self.record(stage,identity or str(uuid4()),payload,
                    observed_at=observed_at or datetime.now(timezone.utc))
                return ref
            except CaptureError:
                self.failures+=1
                return None

    def note_failure(self):
        """Retain an explicit refused-input gap even if its safe receipt was saved."""
        if self.enabled:
            with self._lock:
                if self._sealed_ref is not None:
                    raise CaptureError('input run already sealed')
                self.failures += 1

    def seal(self):
        """Publish the exact observed run set; this is not full-input readiness."""
        if not self.enabled: return None
        with self._lock:
            try:
                if self._sealed_ref is not None:
                    load_input_run(self.root,self._sealed_ref)
                    return self._sealed_ref
                observed=[load_decision_input(self.root,ref) for ref in self._references]
                ends=[o for o in observed if o['manifest']['stage']=='run_end']
                if len(ends)!=1 or not observed or observed[-1] is not ends[0]:
                    raise CaptureError('one terminal run_end observation required')
                if (ends[0]['payload'].get('observations_before_end')!=len(observed)-1
                        or ends[0]['payload'].get('capture_failures')!=self.failures):
                    raise CaptureError('run_end counters do not match recorder')
                root,folder=_storage(self.root,create=True)
                target=folder/'run_manifests'
                if target.is_symlink(): raise CaptureError('symlinked run directory')
                target.mkdir(mode=0o700,exist_ok=True);_sync_directory(target.parent)
                envelope=dict(schema_version=1,run_id=_token(self.run_id),
                    observations=[dict(ref=ref,manifest_sha256=o['manifest']['manifest_sha256'])
                                  for ref,o in zip(self._references,observed)],
                    capture_failures=self.failures,full_replay_ready=False,
                    scope='sealed_observed_subset_not_full_strategy_replay')
                envelope['manifest_sha256']=_sha(_encode(envelope))
                path=target/(_sha(_encode(self.run_id))+'.json')
                _publish(path,_encode(envelope))
                ref=str(path.relative_to(root));load_input_run(root,ref)
                self._sealed_ref=ref
                return ref
            except CaptureError: raise
            except (ValueError,KeyError,TypeError,OSError) as exc:
                raise CaptureError('input run not sealed') from exc


def load_input_run(project_root, ref):
    """Verify run closure and every hash dependency; missing never means empty."""
    try:
        root,folder=_storage(project_root,create=False);path=Path(ref)
        if (path.is_absolute() or path.parent!=Path('data/audits/measurement_inputs/run_manifests')
                or path.suffix!='.json' or len(path.stem)!=64
                or any(c not in '0123456789abcdef' for c in path.stem)
                or (folder/'run_manifests').is_symlink() or (root/path).is_symlink()):
            raise CaptureError('unsafe run reference')
        envelope=json.loads((root/path).read_bytes());claimed=envelope.pop('manifest_sha256')
        run_id=_token(envelope['run_id'])
        if (_sha(_encode(envelope))!=claimed or envelope.get('schema_version')!=1
                or envelope.get('scope')!='sealed_observed_subset_not_full_strategy_replay'
                or envelope.get('full_replay_ready') is not False
                or path.stem!=_sha(_encode(run_id))
                or type(envelope['capture_failures']) is not int or envelope['capture_failures']<0):
            raise CaptureError('invalid run manifest')
        refs=envelope['observations']
        if not isinstance(refs,list) or not refs or len({item['ref'] for item in refs})!=len(refs):
            raise CaptureError('missing or duplicate run observations')
        observations=[]
        for item in refs:
            o=load_decision_input(root,item['ref']);m=o['manifest']
            _token(m['stage']);_token(m['identity'])
            dt=datetime.fromisoformat(m['local_observed_at'])
            if (m['run_id']!=run_id or m['manifest_sha256']!=item['manifest_sha256']
                    or dt.utcoffset() is None or not isinstance(o['payload'],dict)):
                raise CaptureError('input run dependency mismatch')
            observations.append(o)
        ends=[o for o in observations if o['manifest']['stage']=='run_end']
        if len(ends)!=1 or observations[-1] is not ends[0]:
            raise CaptureError('run closure missing or not terminal')
        end=ends[0]['payload']
        if (type(end.get('exit_code')) is not int
                or type(end.get('observations_before_end')) is not int
                or end['observations_before_end']!=len(observations)-1
                or type(end.get('capture_failures')) is not int
                or end['capture_failures']!=envelope['capture_failures']):
            raise CaptureError('run closure counters invalid')
        envelope['manifest_sha256']=claimed
        return dict(manifest=envelope,observations=observations,
            capture_complete=envelope['capture_failures']==0,
            declared_exit_success=end['exit_code']==0,full_replay_ready=False)
    except CaptureError: raise
    except (ValueError,KeyError,TypeError,OSError,IndexError) as exc:
        raise CaptureError('missing or invalid input run') from exc


def load_decision_input(project_root, ref):
    """Read a committed, hash-bound observation; no correction or fallback."""
    try:
        root,folder=_storage(project_root,create=False);path=Path(ref)
        if (folder/'blobs').is_symlink(): raise CaptureError('symlinked input blob directory')
        if (path.is_absolute() or path.parent != Path('data/audits/measurement_inputs/decision_manifests')
                or len(path.stem)!=64 or any(c not in '0123456789abcdef' for c in path.stem)
                or path.suffix!='.json' or (root/path).is_symlink()):
            raise CaptureError('unsafe decision input reference')
        # Check every storage ancestor, including the newly added manifest dir.
        if (folder/'decision_manifests').is_symlink(): raise CaptureError('symlinked observation directory')
        envelope=json.loads((root/path).read_bytes());claimed=envelope.pop('manifest_sha256')
        if (_sha(_encode(envelope))!=claimed or envelope.get('schema_version')!=1
                or envelope.get('scope')!='actual_boundary_partial_inputs_not_F1'
                or envelope.get('full_replay_ready') is not False
                or envelope.get('provider_available_at_certified') is not False
                or path.stem!=_sha(_encode([envelope['run_id'],envelope['stage'],envelope['identity']]))):
            raise CaptureError('corrupt or unsupported input manifest')
        sha=envelope['payload_sha256']
        if not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):
            raise CaptureError('invalid input dependency hash')
        blob=folder/'blobs'/sha
        if blob.is_symlink(): raise CaptureError('symlinked input blob')
        raw=blob.read_bytes()
        if _sha(raw)!=sha: raise CaptureError('corrupt input dependency')
        envelope['manifest_sha256']=claimed
        return dict(manifest=envelope,payload=json.loads(raw))
    except CaptureError: raise
    except (ValueError,KeyError,TypeError,OSError) as exc:
        raise CaptureError('missing or invalid decision input') from exc
