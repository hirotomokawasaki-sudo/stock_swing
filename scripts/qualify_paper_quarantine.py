#!/usr/bin/env python3
"""Owner-only local Paper quarantine tool; never submit/cancel/reject an order.

Default is a GET-only qualification over the existing journal. --apply requires
a fresh journal CAS and independently copy-restored backup. Normal deployment
drain, complete application backup and version-selector qualification are still
the operator's prerequisites; this script does not claim to perform them.
"""
from pathlib import Path
import argparse, fcntl, hashlib, json, os, shutil, sys

PROJECT_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT_ROOT/'src'))
from stock_swing.execution.submission_guard import SubmissionGuard
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.sources.retry import RetryConfig


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=PROJECT_ROOT)
    parser.add_argument('--client-order-id',required=True)
    parser.add_argument('--authorization-file',type=Path,required=True)
    parser.add_argument('--expected-journal-sha256')
    parser.add_argument('--backup-dir',type=Path)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--revoke',action='store_true')
    args=parser.parse_args()
    if (args.apply or args.revoke) and (not args.backup_dir or not args.expected_journal_sha256):
        parser.error('mutation requires --backup-dir and --expected-journal-sha256')
    if args.apply and args.revoke:parser.error('choose activation or revocation')
    root=args.project_root.resolve()
    auth=json.loads(args.authorization_file.read_text())
    authority={k:auth[k] for k in ('requester_id','reference','instruction_sha256')}
    authority['kind']='owner_instruction'
    SubmissionGuard._check_authority(authority)
    env={}
    for line in (root/'.env').read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            k,v=line.split('=',1);env[k.strip()]=v.strip().strip('"').strip("'")
    route=env.get('BROKER_BASE_URL','https://paper-api.alpaca.markets').rstrip('/')
    if route not in {'https://paper-api.alpaca.markets','https://paper-api.alpaca.markets/v2'}:
        raise ValueError('paper_route_required')
    broker=BrokerClient(api_key=env['BROKER_API_KEY'],api_secret=env['BROKER_API_SECRET'],
        paper_mode=True,base_url=route,retry_config=RetryConfig(max_attempts=1,timeout=10))
    # This transport guard also covers future accidental mutating calls.
    import httpx
    send=httpx.Client.send
    def read_only(client,request,**kwargs):
        if request.method!='GET' or request.url.host!='paper-api.alpaca.markets':
            raise ValueError('quarantine_tool_get_only')
        return send(client,request,**kwargs)
    httpx.Client.send=read_only
    try:
        account=broker.fetch_account().payload
        guard=SubmissionGuard(broker,root,account.get('id'))
        guard._paper_quarantine_only()
        raw=guard.store.path.read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        if args.expected_journal_sha256 is not None and digest!=args.expected_journal_sha256:
            raise ValueError('quarantine_tool_journal_cas')
        if args.apply or args.revoke:
            backup=args.backup_dir
            if backup.exists() or any(p.is_symlink() for p in (backup,*backup.parents)):
                raise ValueError('fresh_private_backup_required')
            backup.mkdir(parents=True,mode=0o700)
            for source in (guard.store.path,guard.marker):
                shutil.copy2(source,backup/source.name)
            restored=backup/'independent-restored.jsonl'
            shutil.copy2(backup/guard.store.path.name,restored)
            if (restored.read_bytes()!=raw or hashlib.sha256(restored.read_bytes()).hexdigest()!=args.expected_journal_sha256
                    or (backup/guard.marker.name).read_text()!=guard.namespace+'\n'):
                raise ValueError('quarantine_tool_backup_mismatch')
        if args.revoke:
            with guard.lock_path.open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                guard._load()
                if hashlib.sha256(guard.store.path.read_bytes()).hexdigest()!=args.expected_journal_sha256:
                    raise ValueError('quarantine_tool_revocation_cas')
                if args.client_order_id not in guard.quarantines:
                    raise ValueError('quarantine_tool_not_active')
                guard._append('submission_quarantine_revoked',client_order_id=args.client_order_id,authority=authority)
                guard._load()
            result=dict(applied=True,revoked=True,original_outcome='unknown',new_buys='held')
        else:
            result=guard.qualify_quarantine(args.client_order_id,authority,apply=args.apply,
                expected_journal_sha256=args.expected_journal_sha256)
        print(json.dumps(result,sort_keys=True,allow_nan=False))
        return 0
    finally:
        httpx.Client.send=send



if __name__=='__main__':
    os.umask(0o077)
    try:raise SystemExit(main())
    except Exception as exc:
        print(json.dumps(dict(status='unavailable',error_type=type(exc).__name__,automatic_retry=False)))
        raise SystemExit(2)
