"""Public projection technical replay only; private research inputs deliberately absent."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,importlib.metadata,json,os,shutil,stat,subprocess,sys,tempfile
def check(packet):
 manifest=json.loads((packet/'public_manifest.json').read_text())
 if not isinstance(manifest,dict) or set(manifest)!={'files'} or not isinstance(manifest['files'],dict):raise ValueError('manifest shape')
 actual=set()
 for f in packet.rglob('*'):
  if f.is_symlink():raise ValueError('symlink refused')
  if f.is_file():actual.add(str(f.relative_to(packet)))
 if actual!=set(manifest['files'])|{'public_manifest.json'}:raise ValueError('inventory drift')
 for name,pin in manifest['files'].items():
  rel=PurePosixPath(name)
  if rel.is_absolute() or '..' in rel.parts or str(rel)!=name:raise ValueError('unsafe manifest name')
  f=packet/name
  if set(pin)!={'sha256','mode'} or hashlib.sha256(f.read_bytes()).hexdigest()!=pin['sha256'] or stat.S_IMODE(f.stat().st_mode)!=pin['mode']:raise ValueError('byte/mode drift:'+name)
 env=json.loads((packet/'environment.json').read_text())
 if list(sys.version_info[:2])!=env['python']:raise ValueError('Python drift')
 for name,version in env['packages'].items():
  if importlib.metadata.version(name)!=version:raise ValueError('dependency drift:'+name)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--check-only',action='store_true');ap.add_argument('--output');ap.add_argument('--browser',action='store_true');a=ap.parse_args();packet=Path(__file__).resolve().parent;check(packet)
 if a.check_only:print('exact packet integrity verified');return
 if not a.output:raise ValueError('output required')
 out=Path(a.output).resolve()
 if out.is_relative_to(packet):raise ValueError('output must be outside packet')
 with tempfile.TemporaryDirectory(prefix='research-config-console-replay-') as tmp:
  job=Path(tmp).resolve();shutil.copytree(packet/'code',job/'candidate');shutil.copytree(packet/'baseline',job/'baseline')
  for name in ['run_remaining_cli.py','cli_driver.py','verify_integration.py','browser_integration.cjs','deny.sb','deny_browser.sb']:
   shutil.copy2(packet/name,job/name)
  env=dict(PATH='/opt/homebrew/bin:/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONPATH=str(job/'candidate/src')+':'+str(job/'candidate')+':'+str(packet/'research'),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
  def run(cmd,cwd,label,timeout=360,profile='deny.sb'):
   p=subprocess.run(['/usr/bin/sandbox-exec','-f',str(packet/profile),*cmd],cwd=cwd,env=env,capture_output=True,text=True,timeout=timeout)
   if p.returncode:raise RuntimeError(label+':'+p.stdout[-1600:]+p.stderr[-1000:])
   return p.stdout
  run([sys.executable,'-B','-c',"from pathlib import Path;import stock_swing.cli.paper_demo as p;import console.services.dashboard_service as d;assert all(Path(m.__file__).resolve().is_relative_to(Path.cwd()) for m in (p,d))"],job/'candidate','isolated source origin')
  config=job/'pytest.ini';config.write_text('[pytest]\n')
  research=run([sys.executable,'-B','-m','pytest','-c',str(config),'--rootdir',str(packet/'research'),'-p','no:cacheprovider','-q',str(packet/'research/test_diagnostic.py')],packet/'research','research contracts')
  assert '24 passed' in research,research
  previous=['test_reduction_orders','test_emergency_reduction_regression','test_submission_guard','test_submit_retry_boundary','test_effective_config_safety','test_order_preflight','test_risk_fail_closed','test_risk_budget','test_paper_executor','test_provider_bar_contracts','test_decision_input_capture','test_measurement_capture','test_provider_cli_copy','test_cancellation_safety','test_config_instance_receipts','test_reconcile_orders','test_cancellation_timing','test_config_instance_coverage']
  extra=['test_config_remaining_paths','test_console_evidence_20261028','test_console_cancel_integration']
  focused=run([sys.executable,'-B','-m','pytest','-c',str(config),'--rootdir',str(job/'candidate'),'--import-mode=importlib','-p','no:cacheprovider','-q','--tb=short',*[f'tests/unit/{x}.py' for x in previous+extra]],job/'candidate','focused combined regression')
  assert '567 passed' in focused,focused
  run([sys.executable,'-B',str(job/'run_remaining_cli.py')],job,'44 actual CLI cases',timeout=600)
  run([sys.executable,'-B',str(job/'verify_integration.py')],job/'candidate','cancel/service/serialization/actual JS/text')
  integration=json.loads((job/'integration_results.json').read_text())
  if integration!=json.loads((packet/'integration_results.json').read_text()):raise ValueError('integration outcome drift')
  browser=None
  if a.browser:
   shutil.copytree(packet/'vendors',job/'vendors')
   run(['/opt/homebrew/bin/node',str(job/'browser_integration.cjs')],job,'actual browser',profile='deny_browser.sb')
   browser=json.loads((job/'browser_results.json').read_text())
  receipt=dict(integrity='verified',private_research_outcome_repeated=False,decimal_cells_repeated=0,research_tests=24,combined_focused_tests=567,actual_CLI_cases=44,integration=integration,browser=browser,full_private_suite_repeated=False,production_applied=False,push=False)
  out.write_text(json.dumps(receipt,indent=2,sort_keys=True));print(out.read_text())
if __name__=='__main__':main()
