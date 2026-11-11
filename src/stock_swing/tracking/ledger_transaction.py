"""Recoverable local-file unit of work for cooperating tracking writers.

Four fixed ledger files, one process/thread lock and a durable roll-forward
journal. This is NOT atomic visibility for uncoordinated raw file readers, nor
protection against legacy scripts that bypass the lock. No broker I/O here.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from dataclasses import asdict
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

FILES = frozenset({'pnl_state.json','fill_ledger.jsonl','fill_consumed_ledger.json','trade_events.jsonl'})
_ACTIVE = ContextVar('tracking_transaction', default=None)
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


class LedgerConflict(RuntimeError):
    """Unknown/conflicting state requires investigation, never overwrite it."""


def digest(data):
    return None if data is None else hashlib.sha256(data).hexdigest()


def json_revision(data):
    return digest(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode())


def _read(path):
    return path.read_bytes() if path.exists() else None


def _sync_directory(folder):
    fd=os.open(folder,os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def _replace(path,data):
    fd,name=tempfile.mkstemp(prefix='.ledger-write-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(name): os.unlink(name)


def _recover(folder):
    journal=folder/'.ledger_transaction.json'
    if not journal.exists(): return
    try:
        record=json.loads(journal.read_bytes())
        if record.get('version')!=1 or record.get('state')!='prepared':
            raise ValueError('unsupported journal state')
        entries=record['files']
        if not isinstance(entries,list) or not entries: raise ValueError('empty journal')
        seen=set();decoded=[]
        for item in entries:
            name=item['name']
            if name not in FILES or name in seen: raise ValueError('invalid/duplicate journal path')
            seen.add(name)
            if (folder/name).is_symlink(): raise ValueError('symlinked journal target')
            data=base64.b64decode(item['after'],validate=True)
            if digest(data)!=item['after_sha256']: raise ValueError('journal payload hash mismatch')
            before=item['before_sha256']
            if before is not None and (not isinstance(before,str) or len(before)!=64): raise ValueError('invalid before hash')
            current=digest(_read(folder/name))
            if current not in {before,item['after_sha256']}:
                raise LedgerConflict('ledger differs from both prepared versions: '+name)
            decoded.append((folder/name,data))
    except (ValueError,KeyError,TypeError,AttributeError) as exc:
        raise LedgerConflict('invalid transaction journal; manual evidence review required') from exc
    # Validate the whole write set before advancing ANY file.
    for path,data in decoded:
        if _read(path)!=data: _replace(path,data)
    journal.unlink();_sync_directory(folder)


class _Transaction:
    def __init__(self,root):
        self.root=root;self.folder=root/'data/tracking';self.before={};self.after={};self.failed=False

    def key(self,path):
        path=Path(path)
        if path.parent.resolve()!=self.folder.resolve() or path.name not in FILES or path.is_symlink():
            raise LedgerConflict('unsupported or symlinked tracking path')
        return path.name

    def read(self,path):
        name=self.key(path)
        if name in self.after: return self.after[name]
        if name not in self.before: self.before[name]=_read(self.folder/name)
        return self.before[name]

    def stage(self,path,data):
        self.read(path);self.after[self.key(path)]=data

    def commit(self):
        changed={n:b for n,b in self.after.items() if b!=self.before[n]}
        if not changed: return
        for name,before in self.before.items():
            if _read(self.folder/name)!=before:
                raise LedgerConflict('uncoordinated ledger change: '+name)
        record={'version':1,'state':'prepared','files':[
            {'name':name,'before_sha256':digest(self.before[name]),'after_sha256':digest(data),
             'after':base64.b64encode(data).decode()}
            for name,data in sorted(changed.items())]}
        _replace(self.folder/'.ledger_transaction.json',json.dumps(record,sort_keys=True,allow_nan=False).encode())
        _recover(self.folder)


@contextmanager
def ledger_transaction(project_root, *, recover=True, blocking=True):
    """Stage nested updates; failed bodies publish nothing, prepared work recovers.

    Nested exceptions must escape the outer unit of work. Callers must not catch
    an error inside a transaction and then continue with partial intended writes.
    """
    root=Path(project_root).resolve(); active=_ACTIVE.get()
    if active is not None:
        if active.root!=root: raise LedgerConflict('cross-root nested transaction unsupported')
        try:
            yield active
        except BaseException:
            active.failed=True
            raise
        return
    folder=root/'data/tracking';folder.mkdir(parents=True,exist_ok=True)
    with _LOCKS_GUARD: lock=_LOCKS.setdefault(str(root),threading.RLock())
    if not lock.acquire(blocking=blocking):
        raise LedgerConflict('tracking thread lock busy')
    try:
        with (folder/'.ledger.lock').open('a+b') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            if not recover and (folder/'.ledger_transaction.json').exists():
                raise LedgerConflict('prepared transaction requires writer recovery')
            _recover(folder)
            tx=_Transaction(root);token=_ACTIVE.set(tx)
            try:
                yield tx
                if tx.failed: raise LedgerConflict('nested transaction failed; all staged writes discarded')
                tx.commit()
            finally:
                _ACTIVE.reset(token)
                fcntl.flock(handle,fcntl.LOCK_UN)
    finally:
        lock.release()


def read_bytes(project_root,path):
    active=_ACTIVE.get()
    if active is not None and active.root==Path(project_root).resolve(): return active.read(path)
    return _read(Path(path))


def stage_bytes(project_root,path,data):
    with ledger_transaction(project_root) as tx: tx.stage(path,data)


def ledger_operation(*,refresh=None):
    """Serialize a tracker operation and reload its state under the shared lock."""
    def decorate(function):
        @wraps(function)
        def call(self,*args,**kwargs):
            with ledger_transaction(self.project_root):
                if refresh=='state':
                    if hasattr(self, 'state') and json_revision(asdict(self.state)) != self._loaded_state_revision:
                        self._save_state()  # preserve explicit edits only if the loaded revision still matches
                    self.state=self._load_state()
                elif refresh=='history_read':
                    raw=read_bytes(self.project_root,self.state_path)
                    data=json.loads(raw) if raw is not None else {}
                    if data.get('history_migrations') or self.state.history_migrations:
                        if json_revision(asdict(self.state))!=self._loaded_state_revision:
                            raise LedgerConflict('unsaved reader edits across history transition')
                        self.state=self._load_state()
                elif refresh=='fills': self._loaded=False;self._ensure_loaded()
                return function(self,*args,**kwargs)
        return call
    return decorate


def recover_ledger(project_root):
    """Explicitly finish a prepared local transaction without a new broker call."""
    with ledger_transaction(project_root): pass
