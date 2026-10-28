"""Three packet-integrity rejection probes, using disposable copies only."""
from pathlib import Path
import json,subprocess,sys,tempfile,zipfile

def probes(packet):
    outcomes=[]
    manifest=json.loads((packet/'input_manifest.json').read_text());first=manifest['files'][0]['path']
    for mode,expected in [('missing_input','archive inventory mismatch'),('changed_input',first),('changed_spec','changed spec')]:
        with tempfile.TemporaryDirectory(prefix='signal-diagnostic-negative-') as dirname:
            bad=Path(dirname)
            for name in ['SPEC.json','input_manifest.json']:(bad/name).write_bytes((packet/name).read_bytes())
            if mode=='changed_spec':
                (bad/'SPEC.json').write_bytes((bad/'SPEC.json').read_bytes()+b'\n')
                # run() verifies the specification before opening this intentionally absent archive.
            else:
                with zipfile.ZipFile(packet/'inputs.zip') as source,zipfile.ZipFile(bad/'inputs.zip','w',compression=zipfile.ZIP_DEFLATED) as dest:
                    for name in source.namelist():
                        if mode=='missing_input' and name==first:continue
                        blob=source.read(name)
                        if mode=='changed_input' and name==first:blob+=b' '
                        dest.writestr(name,blob)
            result=subprocess.run([sys.executable,'-I','-B',str(packet/'diagnose.py'),'--packet',str(bad),'--verify'],capture_output=True,text=True)
            assert result.returncode!=0 and expected in result.stderr,(mode,result.returncode,result.stdout,result.stderr[-300:])
            outcomes.append({'case':mode,'rejected_before_diagnostic_result':True,'returncode':result.returncode})
    return outcomes
if __name__=='__main__':print(json.dumps({'negative_integrity_cases':probes(Path(__file__).resolve().parent)},sort_keys=True))
