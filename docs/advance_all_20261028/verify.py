"""Inventory-first replay; all execution occurs in a disposable packet-only copy."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,importlib.metadata,json,os,shutil,stat,subprocess,sys,tempfile

def check(packet):
 entries=json.loads((packet/'manifest.json').read_text())['files'];actual=set()
 for p in packet.rglob('*'):
  if p.is_symlink():raise ValueError('symlink in packet')
  if p.is_file():actual.add(str(p.relative_to(packet)))
 if actual!=set(entries)|{'manifest.json'}:raise ValueError('inventory mismatch')
 for name,pin in entries.items():
  rel=PurePosixPath(name)
  if rel.is_absolute() or '..' in rel.parts or str(rel)!=name:raise ValueError('unsafe path')
  p=packet/name
  if hashlib.sha256(p.read_bytes()).hexdigest()!=pin['sha256'] or stat.S_IMODE(p.stat().st_mode)!=pin['mode']:raise ValueError('byte/mode mismatch:'+name)
 environment=json.loads((packet/'environment.json').read_text())
 if list(sys.version_info[:2])!=environment['python']:raise ValueError('Python drift')
 for name,version in environment['packages'].items():
  if importlib.metadata.version(name)!=version:raise ValueError('dependency drift:'+name)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--check-only',action='store_true');args=parser.parse_args()
 packet=Path(__file__).resolve().parent;out=Path(args.output).resolve()
 if out.is_relative_to(packet):raise ValueError('output must be outside packet')
 check(packet)
 if args.check_only:return
 with tempfile.TemporaryDirectory(prefix='advance-all-replay-') as temp:
  job=Path(temp);root=job/'candidate';shutil.copytree(packet/'code',root);shutil.copytree(packet/'code',job/'baseline')
  shutil.copytree(packet/'baseline',job/'baseline',dirs_exist_ok=True)
  for name in json.loads((packet/'baseline_missing.json').read_text()):
   path=job/'baseline'/name
   if path.exists():path.unlink()
  for name in ['run_cli.py','cli_driver.py','check_cli.py','deny.sb']:shutil.copy2(packet/name,job/name)
  env={'PATH':'/usr/bin:/bin','TZ':'Asia/Tokyo','PYTHONDONTWRITEBYTECODE':'1','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTHONPATH':str(root/'src')+':'+str(root)}
  def run(command,cwd,label,timeout=200):
   result=subprocess.run(command,cwd=cwd,env=env,capture_output=True,text=True,timeout=timeout)
   if result.returncode:raise RuntimeError(label+': '+result.stdout[-1800:]+result.stderr[-1000:])
   return result.stdout
  run([sys.executable,'-B','-c',"from pathlib import Path;from stock_swing.cli import paper_demo;from stock_swing.execution import submission_guard;assert all(Path(m.__file__).resolve().is_relative_to((Path.cwd()/'src').resolve()) for m in (paper_demo,submission_guard))"],root,'origin')
  config=job/'pytest.ini';config.write_text('[pytest]\n')
  focused=run([sys.executable,'-B','-m','pytest','-c',str(config),'--rootdir',str(root),'--import-mode=importlib','--tb=short','-q','-p','no:cacheprovider',*[f'tests/unit/{name}.py' for name in ['test_submit_retry_boundary','test_submission_guard','test_effective_config_safety','test_order_preflight','test_risk_fail_closed','test_risk_budget','test_paper_executor']]],root,'focused')
  # Actual CLI: non-dry on copies, internal strategy/engine/allocator/executor real.
  run([sys.executable,'-B',str(job/'run_cli.py')],job,'CLI',timeout=500)
  run([sys.executable,'-B',str(job/'check_cli.py')],job,'assertions')
  expected=json.loads((job/'expected.json').read_text())
  if expected!=json.loads((packet/'expected.json').read_text()):raise ValueError('normalized outcomes differ')
  out.write_text(json.dumps(dict(integrity='verified',origin='packet only',focused_tail=focused[-400:],cli_cases=38,normalized_outcomes_match=True,unknown_first_posts=1,production_applied=False),indent=2));print(out.read_text())

if __name__=='__main__':main()
