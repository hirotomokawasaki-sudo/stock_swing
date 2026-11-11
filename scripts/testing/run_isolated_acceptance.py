#!/usr/bin/env python3
"""Run repository tests on a fresh copy, without live data, credentials or network.

macOS sandbox-exec is required. CLI boundary tests own their child sandbox;
localhost-only API test is a separate, explicitly loopback-enabled group.
No installation, broker call, job execution, or production state change.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--group', choices=['all', 'full', 'cli', 'localhost'], default='all')
    args = parser.parse_args()
    if not Path('/usr/bin/sandbox-exec').exists():
        parser.error('This isolation runner requires macOS sandbox-exec; no unprotected fallback.')
    source = args.root.resolve()
    packet = (args.output or Path(tempfile.mkdtemp(prefix='stock-swing-acceptance-'))).resolve()
    if packet.is_relative_to(source):
        parser.error('--output must be outside the source repository')
    packet.mkdir(parents=True, exist_ok=True)
    target = packet / 'candidate'
    if target.exists():
        parser.error('output/candidate already exists; choose a new output directory')
    pins = {}
    for name in ['src', 'console', 'scripts', 'tests', 'config', 'docs']:
        shutil.copytree(source / name, target / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache'))
    for path in target.rglob('*'):
        if path.is_file():
            pins[str(path.relative_to(target))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (packet / 'INPUTS.json').write_text(json.dumps(pins, indent=2))
    (packet / 'pytest.ini').write_text('[pytest]\ntestpaths = tests\npythonpath = '+str(target/'src')+' '+str(target)+'\n')
    profile = '\n'.join(['(version 1)', '(allow default)', '(deny network*)', '(deny file-write*)',
        '(allow file-write* (subpath '+json.dumps(str(packet))+'))',
        '(allow file-write* (literal "/dev/null"))',
        '(deny file-read* (subpath '+json.dumps(str(source))+'))',
        '(allow file-read* (subpath '+json.dumps(sys.prefix)+'))', ''])
    (packet / 'deny.sb').write_text(profile)
    (packet / 'localhost.sb').write_text(profile+'\n(allow network-bind (local ip "localhost:*"))\n(allow network-inbound (local ip "localhost:*"))\n(allow network-outbound (remote ip "localhost:*"))\n')
    driver = r'''from pathlib import Path
import sys, json, os
p=Path(__file__).resolve().parent
root=p/'candidate'
sys.path[:0]=[str(root/'src'),str(root)]
os.chdir(root)
import stock_swing.tracking.compatibility as ledger
assert Path(ledger.__file__).resolve().is_relative_to(root)
import pytest
class Receipt:
 def __init__(self):self.rows=[]
 def pytest_runtest_logreport(self, report):
  if report.when=='call' or (report.when=='setup' and report.failed):
   self.rows.append({'nodeid':report.nodeid,'when':report.when,'outcome':report.outcome})
 def pytest_sessionfinish(self, session, exitstatus):
  (p/(sys.argv[1]+'.json')).write_text(json.dumps({'exitstatus':int(exitstatus),'rows':self.rows,'ledger_origin':ledger.__file__},indent=2))
sys.exit(pytest.main(['--rootdir',str(root),'-c',str(p/'pytest.ini'),'--basetemp',str(p/'test-tmp'/sys.argv[1]),'--import-mode=importlib','--tb=short','-q']+sys.argv[2:], plugins=[Receipt()]))
'''
    (packet / 'driver.py').write_text(driver)
    (packet / 'home').mkdir(exist_ok=True)
    (packet / 'test-tmp').mkdir(exist_ok=True)
    env = {'PATH':os.environ.get('PATH','/usr/bin:/bin'), 'HOME':str(packet/'home'),
           'TMPDIR':str(packet), 'TZ':'Asia/Tokyo', 'PYTHONDONTWRITEBYTECODE':'1',
           'PYTHONPATH':str(target/'src')+os.pathsep+str(target)}
    groups = ['full','cli','localhost'] if args.group=='all' else [args.group]
    results = {}
    for group in groups:
        command = [sys.executable,'-B',str(packet/'driver.py'),group]
        if group=='cli':
            command += ['tests/unit/test_k03_cli_status.py','tests/unit/test_k04_cli_status.py']
        else:
            command = ['/usr/bin/sandbox-exec','-f',str(packet/(('deny' if group=='full' else 'localhost')+'.sb'))]+command
            command += ['tests']
            command += (['--ignore=tests/unit/test_k03_cli_status.py','--ignore=tests/unit/test_k04_cli_status.py','-k','not test_remote_readonly_rejects_query_token_and_accepts_header'] if group=='full' else ['-k','test_remote_readonly_rejects_query_token_and_accepts_header'])
        with (packet/(group+'.log')).open('w') as log:
            result = subprocess.run(command,cwd=target,env=env,stdout=log,stderr=subprocess.STDOUT)
        results[group] = result.returncode
        print(group, 'returncode', result.returncode, flush=True)
        print((packet/(group+'.log')).read_text()[-6000:], flush=True)
    rows = []
    for group in groups:
        path = packet/(group+'.json')
        if path.exists(): rows.extend(json.loads(path.read_text())['rows'])
    passed = {r['nodeid'] for r in rows if r['outcome']=='passed'}
    skipped = {r['nodeid'] for r in rows if r['outcome']=='skipped'}
    receipt = {'source':str(source),'groups':results,'unique_passed':len(passed),'unique_skipped':len(skipped),'copied_files':len(pins),'no_live_data_or_env_copied':True}
    (packet/'RESULT.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt,indent=2));print('Evidence:',packet)
    return 0 if all(value==0 for value in results.values()) else 1

if __name__=='__main__':
    sys.exit(main())
