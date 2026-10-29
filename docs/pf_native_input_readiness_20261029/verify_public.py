"""Public projection: verify exact bytes before isolated synthetic technical replay."""
from pathlib import Path,PurePosixPath
import argparse,concurrent.futures,hashlib,json,os,shutil,stat,subprocess,sys,tempfile

def verify(root,restore=False):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate manifest key')
            result[key]=value
        return result
    manifest=json.loads((root/'public_manifest.json').read_text(),object_pairs_hook=unique)
    entries=manifest['files'];actual=set();pairs=[]
    for f in root.rglob('*'):
        if f.is_symlink():raise ValueError('symlink refused')
        if f.is_file():actual.add(f.relative_to(root).as_posix())
    if actual!=set(entries)|{'public_manifest.json'}:raise ValueError('inventory drift')
    for name,pin in entries.items():
        rel=PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or str(rel)!=name:raise ValueError('unsafe path')
        f=root/name;mode=pin['mode']
        if mode not in (0o600,0o644,0o700,0o755):raise ValueError('unsafe mode')
        if f.stat().st_size!=pin['bytes'] or hashlib.sha256(f.read_bytes()).hexdigest()!=pin['sha256']:raise ValueError('byte drift: '+name)
        pairs.append((f,mode))
    changed=0
    for f,mode in pairs:
        if stat.S_IMODE(f.stat().st_mode)!=mode:
            if not restore:raise ValueError('mode drift; use --restore-modes after byte validation')
            f.chmod(mode);changed+=1
    return dict(files_verified_before_restore=len(pairs),file_modes_restored=changed)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--check-only',action='store_true');ap.add_argument('--restore-modes',action='store_true');ap.add_argument('--output');args=ap.parse_args()
    p=Path(__file__).resolve().parent;checked=verify(p,args.restore_modes)
    if args.check_only:print(json.dumps(checked));return
    job=Path(tempfile.mkdtemp(prefix='pf-public-technical-')).resolve();shutil.copytree(p/'code',job/'candidate')
    for n in ['inputs','audit_inputs']:shutil.copytree(p/n,job/n)
    for n in ['run_native.py','native_driver.py','native_assertions.py','audit_inputs.py','test_input_audit.py','run_engineering.py']:shutil.copy2(p/n,job/n)
    (job/'deny.sb').write_text('(version 1)\n(allow default)\n(deny network*)\n(deny file-write* (subpath "/Users/hirotomookawasaki/stock_swing"))\n')
    (job/'pytest.ini').write_text('[pytest]\npythonpath = '+str(job/'candidate/src')+' '+str(job/'candidate')+'\n')
    env=dict(PATH='/opt/homebrew/bin:/usr/bin:/bin',TZ='Asia/Tokyo',PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONPATH=str(job/'candidate/src')+':'+str(job/'candidate'))
    def run(label,argv,cwd=job):
        with (job/(label+'.log')).open('w') as f:
            r=subprocess.run(['/usr/bin/sandbox-exec','-f',str(job/'deny.sb'),sys.executable,'-B',*argv],cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=180)
        if r.returncode:raise RuntimeError(label+' failed: '+str(job/(label+'.log')))
        return (job/(label+'.log')).read_text()[-1200:]
    probe="from pathlib import Path;import stock_swing.cli.paper_demo as m;import stock_swing.research.pf_execution_adapter as a;r=Path.cwd().resolve();assert all(Path(x.__file__).resolve().is_relative_to(r) for x in (m,a));print('imports confined to copy')"
    origins=run('origins',['-c',probe],job/'candidate')
    focused=run('focused',['-m','pytest','-c',str(job/'pytest.ini'),'--rootdir='+str(job/'candidate'),'--import-mode=importlib','-p','no:cacheprovider','--tb=short','-q',str(job/'candidate/tests/unit/test_pf_execution_adapter.py')])
    contracts=run('input_contracts',['-m','pytest','-c','/dev/null','--noconftest','-p','no:cacheprovider','--tb=short','-q','test_input_audit.py'])
    run('native',['run_native.py']);run('native_assertions',['native_assertions.py']);run('engineering',['run_engineering.py'])
    for n in ['NATIVE_ASSERTIONS.json','ENGINEERING_ORACLE.json']:
        if (job/n).read_bytes()!=(p/n).read_bytes():raise ValueError('synthetic summary drift '+n)
    result=dict(packet=checked,replay_root=str(job),origins=origins,focused_log=focused,input_contracts_log=contracts,native=json.loads((job/'NATIVE_ASSERTIONS.json').read_text()),engineering=json.loads((job/'ENGINEERING_ORACLE.json').read_text()),external_network_denied=True,original_repository_writes_denied=True,private_input_audit_repeated=False,full_private_suite_repeated=False,economic_AB_batches=0)
    if args.output:Path(args.output).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
