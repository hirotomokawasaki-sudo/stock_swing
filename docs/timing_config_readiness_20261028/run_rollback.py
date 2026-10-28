from pathlib import Path
import json,shutil,subprocess,sys,hashlib
j=Path(__file__).resolve().parent;out={}
for case in ['manual_pending_cancel_0','manual_canceled_0','manual_lost_restart']:
 root=j/'rollback_copies_final'/case
 shutil.copytree(j/'cancel_copies_final'/('candidate_'+case),root)
 calls=lambda:[json.loads(x) for x in (root/'http_calls.jsonl').read_text().splitlines()]
 before=sum(x[0]=='DELETE' for x in calls())
 protected={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'data/tracking').glob('*.json')}
 journal_before={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'data/tracking/cancel_intents').glob('*')}
 shutil.copytree(j/'baseline/src',root/'src',dirs_exist_ok=True)
 env=dict(PATH='/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONPATH=str(root/'src'),PYTHONDONTWRITEBYTECODE='1',BROKER_API_KEY='fixture',BROKER_API_SECRET='fixture')
 run=subprocess.run(['/usr/bin/sandbox-exec','-f',str(j/'deny.sb'),sys.executable,'-B',str(root/'driver.py')],cwd=root,env=env,capture_output=True,text=True,timeout=60)
 assert run.returncode==(1 if case=='manual_lost_restart' else 0),(case,run.stderr[-1000:])
 data=json.loads(run.stdout) if run.returncode==0 else {}
 after=sum(x[0]=='DELETE' for x in calls());assert before==after==1,(case,before,after)
 assert all(hashlib.sha256((root/n).read_bytes()).hexdigest()==v for n,v in protected.items()),case
 if case=='manual_lost_restart':assert all(hashlib.sha256((root/n).read_bytes()).hexdigest()==v for n,v in journal_before.items()),case
 out[case]=dict(old_code_read_new_journal=case!='manual_lost_restart',lookup_404_stops_before_journal=case=='manual_lost_restart',delete_before=before,delete_after=after,process_exit=run.returncode,result=data.get('result'),financial_json_bytes_unchanged=True,journal_deleted=False)
(j/'rollback_rehearsal.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
