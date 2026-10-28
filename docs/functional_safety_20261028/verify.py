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
    if output.is_relative_to(packet):raise ValueError('output must be outside sealed packet')
    check(packet)
    if args.check_only:return
    with tempfile.TemporaryDirectory(prefix='functional-safety-replay-') as temp:
        job=Path(temp);root=job/'code';shutil.copytree(packet/'code',root)
        env={'PATH':'/usr/bin:/bin','TZ':'Asia/Tokyo','PYTHONDONTWRITEBYTECODE':'1','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTHONPATH':str(root/'src')+':'+str(root)}
        config=job/'pytest.ini';config.write_text('[pytest]\n')
        def run(command,cwd,label,expected=0):
            result=subprocess.run(command,cwd=cwd,env=env,capture_output=True,text=True,timeout=90)
            (job/(label+'.log')).write_text(result.stdout+result.stderr)
            if result.returncode!=expected:raise RuntimeError(label+': '+result.stdout[-2000:]+result.stderr[-1000:])
            return result.stdout
        run([sys.executable,'-B','-c',"from pathlib import Path;from stock_swing.cli import paper_demo;assert Path(paper_demo.__file__).resolve().is_relative_to(Path.cwd()/'src')"],root,'origin')
        command=[sys.executable,'-B','-m','pytest','-c',str(config),'--rootdir',str(root),'--import-mode=importlib','--tb=short','-q','-p','no:cacheprovider']
        focused=run(command+['tests/unit/test_risk_fail_closed.py','tests/unit/test_risk_budget.py','tests/unit/test_paper_executor.py'],root,'focused')
        if '75 passed' not in focused:raise ValueError('focused coverage drift')
        baseline=job/'old';shutil.copytree(root,baseline)
        for p in (packet/'baseline').rglob('*'):
            if p.is_file():shutil.copy2(p,baseline/p.relative_to(packet/'baseline'))
        env['PYTHONPATH']=str(baseline/'src')+':'+str(baseline)
        oldcommand=[part.replace(str(root),str(baseline)) for part in command]
        old=run(oldcommand+['tests/unit/test_risk_fail_closed.py'],baseline,'baseline',1)
        if '46 failed, 1 passed' not in old:raise ValueError('baseline contract drift')
        env['PYTHONPATH']=str(root/'src')+':'+str(root)
        for name in ['run_cli.py','risk_cli_driver.py','diagnostics.py','deny.sb']:
            shutil.copy2(packet/name,job/name)
        shutil.copytree(packet/'baseline',job/'baseline')
        run([sys.executable,'-B',str(job/'run_cli.py')],job,'cli')
        cli=json.loads((job/'cli_results.json').read_text())
        diagnostic=json.loads(run([sys.executable,'-B',str(job/'diagnostics.py')],job,'diagnostics'))
        result={'focused_passed':75,'baseline_contract_failed':46,'baseline_contract_passed':1,
                'cli_cases':len(cli),'cli_http_methods':sorted({method for d in cli.values() for method,_ in d['http_calls']}),
                'unknown_buy_held':all(not cli['candidate_'+kind]['would_buy_lines'] for kind in ['missing','broken']),
                'normal_buy_preserved':cli['candidate_empty']['would_buy_lines']==cli['baseline_empty']['would_buy_lines'],
                'yaml_disabled_still_same':cli['candidate_empty']['business_decision_lines']==cli['candidate_yaml_disabled']['business_decision_lines'],
                'cli_threshold_changes_signal':not cli['candidate_threshold_high']['business_decision_lines'],
                'exit_null_aborts':cli['candidate_exit_null']['main_exit']==99,
                'K01_K02_diagnostic_cases':len(diagnostic)-1,'full_suite_repeated':False,'production_applied':False}
        expected=packet/'expected.json'
        encoded=json.dumps(result,indent=2,sort_keys=True)+'\n'
        if expected.exists() and expected.read_text()!=encoded:raise ValueError('result differs')
        output.write_text(encoded)
    print(output.read_text(),end='')

if __name__=='__main__':main()
