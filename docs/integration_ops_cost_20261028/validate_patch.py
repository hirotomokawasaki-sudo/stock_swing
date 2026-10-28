from pathlib import Path
import argparse,hashlib,json,shutil,stat,subprocess,tempfile
parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
p=Path(__file__).resolve().parent;output=Path(args.output).resolve()
if output.is_relative_to(p):raise ValueError('output must be outside sealed packet')
changes=json.loads((p/'source_changes.json').read_text());out={}
for label in ['combined','delta']:
 with tempfile.TemporaryDirectory(prefix='integrated-patch-') as temp:
  root=Path(temp);baseline=p/'baseline' if label=='combined' else p/'safety_code'
  names=changes['changed'] if label=='combined' else changes['delta_from_safety']
  before={}
  for rel in names:
   source=baseline/rel;t=root/rel;t.parent.mkdir(parents=True,exist_ok=True)
   before[rel]=dict(exists=source.exists(),sha=hashlib.sha256(source.read_bytes()).hexdigest() if source.exists() else None,mode=stat.S_IMODE(source.stat().st_mode) if source.exists() else None)
   if source.exists():shutil.copy2(source,t)
  def git(*args):
   r=subprocess.run(['git','apply',*args,str(p/(label+'.patch'))],cwd=root,capture_output=True,text=True)
   if r.returncode:raise RuntimeError(r.stderr)
  git('--check');git()
  for rel in names:
   assert (root/rel).read_bytes()==(p/'code'/rel).read_bytes(),rel
   # Git patches carry executable mode, while packet/source privacy modes are explicit pins.
   (root/rel).chmod((p/'code'/rel).stat().st_mode & 0o777)
  git('--reverse','--check');git('--reverse')
  for rel,pin in before.items():
   t=root/rel;assert t.exists()==pin['exists'],rel
   if t.exists():
    assert hashlib.sha256(t.read_bytes()).hexdigest()==pin['sha'],rel
    t.chmod(pin['mode']);assert stat.S_IMODE(t.stat().st_mode)==pin['mode']
  out[label]=dict(files=len(names),forward_bytes_match=True,reverse_bytes_match=True,privacy_modes_restored_from_pins=True)
output.write_text(json.dumps(out,indent=2,sort_keys=True));print(json.dumps(out))
