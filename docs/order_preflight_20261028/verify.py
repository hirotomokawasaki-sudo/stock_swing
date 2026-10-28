"""Verify the sealed packet before executing pinned isolated production code.

Run under deny.sb, with the existing venv and a clean environment. Tests use
only disposable copies, synthetic HTTP and a controlled external clock.
"""
from pathlib import Path, PurePosixPath
import argparse,hashlib,importlib.metadata,json,os,shutil,stat,subprocess,sys,tempfile


def check(packet):
    entries=json.loads((packet/'manifest.json').read_text())['files']
    actual=set()
    for p in packet.rglob('*'):
        if p.is_symlink():raise ValueError('symlink in packet')
        if p.is_file():actual.add(str(p.relative_to(packet)))
    if actual!=set(entries)|{'manifest.json'}:raise ValueError('packet inventory mismatch')
    for name,pin in entries.items():
        relative=PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or str(relative)!=name:raise ValueError('unsafe path')
        p=packet/name
        if hashlib.sha256(p.read_bytes()).hexdigest()!=pin['sha256'] or stat.S_IMODE(p.stat().st_mode)!=pin['mode']:raise ValueError('byte/mode mismatch: '+name)
    environment=json.loads((packet/'environment.json').read_text())
    if list(sys.version_info[:2])!=environment['python']:raise ValueError('Python drift')
    for name,version in environment['packages'].items():
        if importlib.metadata.version(name)!=version:raise ValueError('dependency drift: '+name)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--check-only',action='store_true');args=parser.parse_args()
    packet=Path(__file__).resolve().parent;output=Path(args.output).resolve()
    if output.is_relative_to(packet):raise ValueError('output must be outside packet')
    check(packet)
    if args.check_only:return
    with tempfile.TemporaryDirectory(prefix='order-preflight-replay-') as temp:
        job=Path(temp);root=job/'candidate';shutil.copytree(packet/'code',root)
        shutil.copytree(packet/'code',job/'baseline')
        shutil.copy2(packet/'baseline/src/stock_swing/cli/paper_demo.py',job/'baseline/src/stock_swing/cli/paper_demo.py')
        (job/'baseline/src/stock_swing/risk/order_preflight.py').unlink()
        for name in ['run_cli.py','risk_cli_driver.py','check_results.py','deny.sb']:
            shutil.copy2(packet/name,job/name)
        env={'PATH':'/usr/bin:/bin','TZ':'Asia/Tokyo','PYTHONDONTWRITEBYTECODE':'1','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTHONPATH':str(root/'src')+':'+str(root)}
        def run(command,cwd,label):
            result=subprocess.run(command,cwd=cwd,env=env,capture_output=True,text=True,timeout=150)
            if result.returncode:raise RuntimeError(label+': '+result.stdout[-1500:]+result.stderr[-1000:])
            return result.stdout
        run([sys.executable,'-B','-c',"from pathlib import Path;from stock_swing.cli import paper_demo;assert Path(paper_demo.__file__).resolve().is_relative_to((Path.cwd()/'src').resolve())"],root,'origin')
        config=job/'pytest.ini';config.write_text('[pytest]\n')
        focused=run([sys.executable,'-B','-m','pytest','-c',str(config),'--rootdir',str(root),'--import-mode=importlib','--tb=short','-q','-p','no:cacheprovider','tests/unit/test_order_preflight.py','tests/unit/test_risk_fail_closed.py','tests/unit/test_risk_budget.py','tests/unit/test_paper_executor.py'],root,'focused')
        if '135 passed' not in focused:raise ValueError('focused count changed: '+focused[-500:])
        run([sys.executable,'-B',str(job/'run_cli.py')],job,'CLI')
        run([sys.executable,'-B',str(job/'check_results.py')],job,'CLI assertions')
        observed=json.loads((job/'expected.json').read_text())
        if observed!=json.loads((packet/'expected.json').read_text()):raise ValueError('semantic replay differs')
        output.write_text(json.dumps({'integrity':'verified','focused_passed':135,'cli_cases':18,'normalized_outcomes_match':True,'known_unfixed_first_intent_retries':3,'production_applied':False},indent=2))
        print(output.read_text())

if __name__=='__main__':main()
