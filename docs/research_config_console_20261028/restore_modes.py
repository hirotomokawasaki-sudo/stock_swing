"""Verify ALL bytes before restoring ordinary manifest permissions in a disposable clone."""
from pathlib import Path,PurePosixPath
import hashlib,json,stat
root=Path(__file__).resolve().parent
pairs=[]
for directory,manifest in [(root,'public_manifest.json'),(root.parent/'cancel_config_closure_20261028','manifest.json'),(root.parent/'timing_config_readiness_20261028','manifest.json')]:
 data=json.loads((directory/manifest).read_text())['files'];actual=set()
 for f in directory.rglob('*'):
  if f.is_symlink():raise ValueError('symlink refused')
  if f.is_file():actual.add(f.relative_to(directory).as_posix())
 if actual!=set(data)|{manifest}:raise ValueError('inventory drift')
 for name,pin in data.items():
  rel=PurePosixPath(name)
  if rel.is_absolute() or '..' in rel.parts or str(rel)!=name:raise ValueError('unsafe path')
  f=directory/name;mode=pin['mode']
  if mode not in (0o600,0o644,0o700,0o755):raise ValueError('unexpected mode')
  if hashlib.sha256(f.read_bytes()).hexdigest()!=pin['sha256']:raise ValueError('byte drift: '+name)
  pairs.append((f,mode))
changed=0
for f,mode in pairs:
 if stat.S_IMODE(f.stat().st_mode)!=mode:f.chmod(mode);changed+=1
print(json.dumps(dict(files_verified_before_restore=len(pairs),file_modes_restored=changed)))
