"""Inventory-first, external-network/main-write-denied packet-only reproduction."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,importlib.metadata,json,re,shutil,stat,subprocess,sys,tempfile
FOCUSED=['test_reduction_orders','test_emergency_reduction_regression','test_submission_guard','test_submit_retry_boundary','test_effective_config_safety','test_order_preflight','test_risk_fail_closed','test_risk_budget','test_paper_executor','test_provider_bar_contracts','test_decision_input_capture','test_measurement_capture','test_provider_cli_copy','test_cancellation_safety','test_config_instance_receipts','test_reconcile_orders','test_cancellation_timing','test_config_instance_coverage']
def check(packet,dependencies=True):
 manifest=json.loads((packet/'manifest.json').read_text())
 if not isinstance(manifest,dict) or set(manifest)!={'files'}:raise ValueError('manifest shape')
 entries=manifest['files'];actual=set()
 for f in packet.rglob('*'):
  if f.is_symlink():raise ValueError('symlink in packet')
  if f.is_file():actual.add(f.relative_to(packet).as_posix())
 if actual!=set(entries)|{'manifest.json'}:raise ValueError('inventory mismatch')
 for name,pin in entries.items():
  rel=PurePosixPath(name)
  if rel.is_absolute() or '..' in rel.parts or str(rel)!=name:raise ValueError('unsafe manifest path')
  f=packet/name
  if set(pin)!={'sha256','mode'} or hashlib.sha256(f.read_bytes()).hexdigest()!=pin['sha256'] or stat.S_IMODE(f.stat().st_mode)!=pin['mode']:raise ValueError('byte/mode mismatch:'+name)
 if not dependencies:return
 environment=json.loads((packet/'environment.json').read_text())
 if list(sys.version_info[:2])!=environment['python']:raise ValueError('Python drift')
 for name,version in environment['packages'].items():
  if importlib.metadata.version(name)!=version:raise ValueError('dependency drift:'+name)
 import massive
 sdk=Path(massive.__file__).resolve().parent
 if {str(f.relative_to(sdk)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sdk.rglob('*.py')}!=environment['massive_sdk']:raise ValueError('SDK drift')

def cancel_projection(rows):
 return {k:dict(delete_count=v['delete_count'],post_count=v['post_count'],outcomes=[{f:o[f] for f in ['result','process_exit','exit_reason_present'] if f in o} for o in v['outcomes']]) for k,v in rows.items()}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output');parser.add_argument('--check-only',action='store_true');args=parser.parse_args()
 packet=Path(__file__).resolve().parent;check(packet)
 if args.check_only:return
 if not args.output:raise ValueError('output required')
 output=Path(args.output).resolve()
 if output.is_relative_to(packet):raise ValueError('output must be outside packet')
 with tempfile.TemporaryDirectory(prefix='timing-config-replay-') as temp:
  job=Path(temp).resolve();root=job/'candidate';shutil.copytree(packet/'code',root);shutil.copytree(packet/'baseline_code',job/'baseline')
  for name in ['run_cli.py','cli_driver.py','check_cli.py','previous_safety_expected.json','deny.sb','run_config_cli.py','run_cancel_paths.py','cancel_driver.py','run_timing_paths.py','timing_driver.py','run_rollback.py']:
   shutil.copy2(packet/name,job/name)
  env=dict(PATH='/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONPATH=str(root/'src')+':'+str(root))
  def run(command,cwd,label,timeout=180):
   process=subprocess.run(['/usr/bin/sandbox-exec','-f',str(packet/'deny.sb'),*command],cwd=cwd,env=env,capture_output=True,text=True,timeout=timeout)
   if process.returncode:raise RuntimeError(label+':'+process.stdout[-2000:]+process.stderr[-1200:])
   return process.stdout
  run([sys.executable,'-B','-c',"from pathlib import Path;from stock_swing.execution import cancellation_guard,submission_guard;from stock_swing.risk import config_instance_receipts;assert all(Path(m.__file__).resolve().is_relative_to((Path.cwd()/'src').resolve()) for m in (cancellation_guard,submission_guard,config_instance_receipts))"],root,'origin')
  calendar=json.loads(run([sys.executable,'-B',str(packet/'check_calendar.py')],root,'calendar'))
  assert calendar==json.loads((packet/'calendar_validation.json').read_text()),'calendar drift'
  config=job/'pytest.ini';config.write_text('[pytest]\n')
  focused=run([sys.executable,'-B','-m','pytest','-c',str(config),'--rootdir',str(root),'--import-mode=importlib','-q','--tb=short','-p','no:cacheprovider',*[f'tests/unit/{name}.py' for name in FOCUSED]],root,'focused')
  assert '502 passed' in focused,focused
  run([sys.executable,'-B',str(job/'run_cancel_paths.py')],job,'cancel selectors/manual/main/restart',timeout=180)
  assert cancel_projection(json.loads((job/'cancel_path_results.json').read_text()))==json.loads((packet/'cancel_expected.json').read_text()),'cancel outcome drift'
  run([sys.executable,'-B',str(job/'run_timing_paths.py')],job,'time selector and main',timeout=180)
  assert json.loads((job/'timing_path_results.json').read_text())==json.loads((packet/'timing_path_results.json').read_text()),'time outcome drift'
  run([sys.executable,'-B',str(job/'run_rollback.py')],job,'rollback rehearsal')
  assert json.loads((job/'rollback_rehearsal.json').read_text())==json.loads((packet/'rollback_rehearsal.json').read_text()),'rollback drift'
  run([sys.executable,'-B',str(job/'run_config_cli.py')],job,'observed config CLI',timeout=240)
  assert json.loads((job/'config_cli_results.json').read_text())==json.loads((packet/'config_cli_results.json').read_text()),'config outcome drift'
  run([sys.executable,'-B',str(job/'run_cli.py')],job,'normal CLI',timeout=720)
  run([sys.executable,'-B',str(job/'check_cli.py')],job,'CLI assertions')
  assert json.loads((job/'expected.json').read_text())==json.loads((packet/'expected.json').read_text()),'normal CLI drift'
  result=dict(integrity='verified',resolved_copy_origins=True,focused_passed=502,cancel_version_cases=38,cancel_processes=42,config_cli_cases=33,time_version_cases=58,rollback_cases=3,previous_cli_cases=40,normalized_outcomes_match=True,full_private_suite_repeated=False,production_applied=False,public_push=False)
  output.write_text(json.dumps(result,indent=2,sort_keys=True));print(output.read_text())
if __name__=='__main__':main()
