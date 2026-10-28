"""Inventory/dependency-first replay; external I/O denied; all mutations in fresh copies."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,importlib.metadata,json,re,shutil,stat,subprocess,sys,tempfile
FOCUSED=['test_submit_retry_boundary','test_submission_guard','test_effective_config_safety','test_order_preflight','test_risk_fail_closed','test_risk_budget','test_paper_executor','test_provider_bar_contracts','test_decision_input_capture','test_measurement_capture','test_provider_cli_copy']
def check(packet,dependencies=True):
 manifest=json.loads((packet/'manifest.json').read_text())
 if not isinstance(manifest,dict) or set(manifest)!={'files'}:raise ValueError('invalid manifest')
 entries=manifest['files'];actual=set()
 for p in packet.rglob('*'):
  if p.is_symlink():raise ValueError('symlink in packet')
  if p.is_file():actual.add(p.relative_to(packet).as_posix())
 if actual!=set(entries)|{'manifest.json'}:raise ValueError('inventory mismatch')
 for name,pin in entries.items():
  rel=PurePosixPath(name)
  if rel.is_absolute() or '..' in rel.parts or str(rel)!=name:raise ValueError('unsafe manifest path')
  p=packet/name
  if set(pin)!={'sha256','mode'} or hashlib.sha256(p.read_bytes()).hexdigest()!=pin['sha256'] or stat.S_IMODE(p.stat().st_mode)!=pin['mode']:raise ValueError('byte/mode mismatch:'+name)
 if not dependencies:return
 env=json.loads((packet/'environment.json').read_text())
 if list(sys.version_info[:2])!=env['python']:raise ValueError('Python drift')
 for name,version in env['packages'].items():
  if importlib.metadata.version(name)!=version:raise ValueError('dependency drift:'+name)
 import massive
 sdk=Path(massive.__file__).resolve().parent
 current={str(p.relative_to(sdk)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sdk.rglob('*.py')}
 if current!=env['massive_sdk']:raise ValueError('SDK byte drift')

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output');parser.add_argument('--check-only',action='store_true');args=parser.parse_args()
 packet=Path(__file__).resolve().parent
 check(packet)
 if args.check_only:return
 if not args.output:raise ValueError('output required')
 out=Path(args.output).resolve()
 if out.is_relative_to(packet):raise ValueError('output must be outside packet')
 with tempfile.TemporaryDirectory(prefix='integration-ops-cost-replay-') as temp:
  job=Path(temp);root=job/'candidate';shutil.copytree(packet/'code',root);shutil.copytree(packet/'safety_code',job/'safety')
  for name in ['run_cli.py','cli_driver.py','check_cli.py','previous_safety_expected.json','run_emergency.py','emergency_driver.py','deny.sb','audit_usage.py','test_audit_usage.py','usage_review_inputs.json']:
   shutil.copy2(packet/name,job/name)
  env=dict(PATH='/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONPATH=str(root/'src')+':'+str(root)+':'+str(job))
  def run(command,cwd,label,timeout=180):
   process=subprocess.run(['/usr/bin/sandbox-exec','-f',str(packet/'deny.sb'),*command],cwd=cwd,env=env,capture_output=True,text=True,timeout=timeout)
   if process.returncode:raise RuntimeError(label+':'+process.stdout[-2000:]+process.stderr[-1200:])
   return process.stdout
  origin=run([sys.executable,'-B','-c',"from pathlib import Path;from stock_swing.cli import paper_demo;from stock_swing.sources import broker_client;assert all(Path(m.__file__).resolve().is_relative_to((Path.cwd()/'src').resolve()) for m in (paper_demo,broker_client))"],root,'origin')
  config=job/'pytest.ini';config.write_text('[pytest]\n')
  focused=run([sys.executable,'-B','-m','pytest','-c',str(config),'--rootdir',str(root),'--import-mode=importlib','--tb=short','-q','-p','no:cacheprovider',*[f'tests/unit/{name}.py' for name in FOCUSED]],root,'focused')
  assert re.search(r'295 passed',focused),focused
  audit=run([sys.executable,'-B','-m','pytest','-c',str(config),'--rootdir',str(job),'--import-mode=importlib','--noconftest','--tb=short','-q','-p','no:cacheprovider',str(job/'test_audit_usage.py')],job,'audit')
  assert '10 passed' in audit,audit
  run([sys.executable,'-B',str(job/'run_cli.py')],job,'actual CLI',timeout=720)
  run([sys.executable,'-B',str(job/'check_cli.py')],job,'CLI assertions')
  assert json.loads((job/'expected.json').read_text())==json.loads((packet/'expected.json').read_text()),'CLI outcomes drift'
  run([sys.executable,'-B',str(job/'run_emergency.py')],job,'actual scripts',timeout=120)
  for name in ['emergency_results.json','emergency_summary.json']:
   assert json.loads((job/name).read_text())==json.loads((packet/name).read_text()),name
  run([sys.executable,'-B',str(job/'audit_usage.py'),'--review',str(job/'usage_review_inputs.json'),'--out',str(job/'usage_summary.json')],job,'usage')
  assert json.loads((job/'usage_summary.json').read_text())==json.loads((packet/'usage_summary.json').read_text()),'usage drift'
  result=dict(integrity='verified',origin='packet-only resolved copy',focused_passed=295,audit_passed=10,cli_cases=40,script_cases=46,normalized_outcomes_match=True,usage_summary_match=True,full_suite_repeated=False,full_replay_qualified=False,production_applied=False)
  out.write_text(json.dumps(result,indent=2,sort_keys=True));print(out.read_text())
if __name__=='__main__':main()
