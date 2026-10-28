from pathlib import Path
import argparse,hashlib,json,shutil,stat,subprocess,tempfile
parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);a=parser.parse_args()
p=Path(__file__).resolve().parent;out=Path(a.output).resolve()
if out.is_relative_to(p):raise ValueError('output must be outside packet')
changes=json.loads((p/'source_changes.json').read_text());result={}
for label in ['combined','delta','tests']:
 with tempfile.TemporaryDirectory(prefix='reduction-patch-') as temp:
  root=Path(temp);base=p/('baseline' if label=='combined' else 'baseline_code');names=['tests/unit/test_reduction_orders.py','tests/unit/test_emergency_reduction_regression.py'] if label=='tests' else changes[label+'_runtime'];before={}
  for rel in names:
   source=base/rel;dest=root/rel;dest.parent.mkdir(parents=True,exist_ok=True)
   before[rel]=dict(exists=source.exists(),bytes=source.read_bytes() if source.exists() else None,mode=stat.S_IMODE(source.stat().st_mode) if source.exists() else None)
   if source.exists():shutil.copy2(source,dest)
  def git(*args):
   process=subprocess.run(['git','apply',*args,str(p/(label+'.patch'))],cwd=root,capture_output=True,text=True)
   if process.returncode:raise RuntimeError(process.stderr)
  git('--check');git()
  for rel in names:
   assert (root/rel).read_bytes()==(p/'code'/rel).read_bytes(),rel
   (root/rel).chmod(stat.S_IMODE((p/'code'/rel).stat().st_mode))
  git('--reverse','--check');git('--reverse')
  for rel,pin in before.items():
   f=root/rel;assert f.exists()==pin['exists'],rel
   if f.exists():
    assert f.read_bytes()==pin['bytes'],rel;f.chmod(pin['mode']);assert stat.S_IMODE(f.stat().st_mode)==pin['mode']
  result[label]=dict(files=len(names),forward_bytes_match=True,reverse_bytes_match=True,privacy_modes_restored_from_pins=True)
out.write_text(json.dumps(result,indent=2,sort_keys=True));print(json.dumps(result))
