#!/usr/bin/env python3
"""Integrity first, then pinned isolated focused regressions; never main imports."""
from pathlib import Path, PurePosixPath
import argparse,hashlib,importlib.metadata,json,os,re,shutil,stat,subprocess,sys,tempfile

FOCUSED=['tests/unit/test_provider_bar_contracts.py','tests/unit/test_provider_cli_copy.py',
         'tests/unit/test_decision_input_capture.py','tests/unit/test_measurement_capture.py',
         'tests/unit/test_massive_client.py']

def encoded(value):return json.dumps(value,sort_keys=True,indent=2).encode()+b'\n'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--check-only',action='store_true');args=parser.parse_args()
    packet=Path(__file__).resolve().parent;output=Path(args.output).resolve()
    if output.is_relative_to(packet):raise ValueError('output must be outside sealed packet')
    manifest=json.loads((packet/'manifest.json').read_text())
    if not isinstance(manifest,dict) or set(manifest)!={'files'} or not isinstance(manifest['files'],dict):raise ValueError('malformed manifest')
    entries=manifest['files'];actual=set()
    for p in packet.rglob('*'):
        if p.is_symlink():raise ValueError('symlink in packet')
        if p.is_file():actual.add(p.relative_to(packet).as_posix())
    if actual!=set(entries)|{'manifest.json'}:raise ValueError('packet inventory mismatch')
    for name,pin in entries.items():
        relative=PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or str(relative)!=name:raise ValueError('unsafe manifest path')
        p=packet/name
        if (set(pin)!={'sha256','mode'} or hashlib.sha256(p.read_bytes()).hexdigest()!=pin['sha256']
                or stat.S_IMODE(p.stat().st_mode)!=pin['mode']):raise ValueError('packet byte/mode mismatch: '+name)
    pins=json.loads((packet/'source_pins.json').read_text())
    for pin in pins:
        data=(packet/pin['path']).read_bytes()
        git_blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if git_blob!=pin['git_blob'] or hashlib.sha256(data).hexdigest()!=pin['sha256']:raise ValueError('source pin mismatch')
    environment=json.loads((packet/'environment.json').read_text())
    if list(sys.version_info[:2])!=environment['python']:raise ValueError('Python version drift')
    for name,version in environment['packages'].items():
        if importlib.metadata.version(name)!=version:raise ValueError('dependency version drift: '+name)
    import massive
    sdk=Path(massive.__file__).parent
    current={str(p.relative_to(sdk)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sdk.rglob('*.py'))}
    if current!=environment['massive_sdk']:raise ValueError('SDK source drift')
    if args.check_only:return
    with tempfile.TemporaryDirectory(prefix='provider-packet-replay-') as temp:
        root=Path(temp)/'candidate';shutil.copytree(packet/'code',root)
        config=Path(temp)/'pytest.ini';config.write_text('[pytest]\n')
        env={'PATH':'/usr/bin:/bin','TZ':'Asia/Tokyo','PYTHONDONTWRITEBYTECODE':'1',
             'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTHONPATH':str(root/'src')+':'+str(root)}
        # Assert module origin in a fresh child before pytest may modify import paths.
        probe=subprocess.run([sys.executable,'-B','-c',"from pathlib import Path;import stock_swing;assert Path(stock_swing.__file__).resolve().is_relative_to(Path.cwd()/'src')"],cwd=root,env=env,capture_output=True,text=True)
        if probe.returncode:raise RuntimeError(probe.stderr)
        command=[sys.executable,'-B','-m','pytest','-c',str(config),'--rootdir',str(root),'--import-mode=importlib','--tb=short','-q',*FOCUSED]
        run=subprocess.run(command,cwd=root,env=env,capture_output=True,text=True,timeout=90)
        if run.returncode:raise RuntimeError(run.stdout+run.stderr)
        passed=int(re.search(r'(\d+) passed',run.stdout)[1])
        if passed!=90:raise ValueError('unexpected focused coverage')
        old=Path(temp)/'baseline';shutil.copytree(root,old,ignore=shutil.ignore_patterns('.pytest_cache','__pycache__'))
        for p in (packet/'baseline').rglob('*'):
            if p.is_file():shutil.copyfile(p,old/p.relative_to(packet/'baseline'))
        env['PYTHONPATH']=str(old/'src')+':'+str(old)
        oldcommand=[sys.executable,'-B','-m','pytest','-c',str(config),'--rootdir',str(old),'--import-mode=importlib','--tb=short','-q','tests/unit/test_provider_bar_contracts.py','-k','legacy_constructor or epoch_is']
        baseline=subprocess.run(oldcommand,cwd=old,env=env,capture_output=True,text=True,timeout=30)
        if baseline.returncode!=1 or '5 failed, 1 passed' not in baseline.stdout:raise RuntimeError(baseline.stdout+baseline.stderr)
        result=dict(integrity_files=len(entries),source_pins=len(pins),sdk_files=len(current),
                    focused_passed=passed,baseline_regressions=dict(failed=5,passed=1),
                    isolation_policy='caller_must_use_provided_OS_sandbox',
                    full_suite_repeated=False,production_applied=False,qualified_observations_added=0)
        expected=packet/'expected.json'
        if expected.exists() and expected.read_bytes()!=encoded(result):raise ValueError('saved result differs')
        output.write_bytes(encoded(result))
    print(output.read_text(),end='')

if __name__=='__main__':main()
