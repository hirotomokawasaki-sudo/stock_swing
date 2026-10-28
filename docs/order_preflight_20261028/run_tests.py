from pathlib import Path
import os,sys,subprocess,json
job=Path(__file__).parent;root=job/'candidate'
env={'PATH':'/usr/bin:/bin','TZ':'Asia/Tokyo','PYTHONDONTWRITEBYTECODE':'1','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTHONPATH':str(root/'src')+':'+str(root)}
args=sys.argv[1:];label=args.pop(0)
command=['/usr/bin/sandbox-exec','-f',str(job/'deny.sb'),'/Users/hirotomookawasaki/stock_swing/venv/bin/python','-B','-m','pytest','--tb=short','-q','-p','no:cacheprovider',*args]
with (job/(label+'.log')).open('w') as log:
 run=subprocess.run(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
print(json.dumps({'label':label,'exit_code':run.returncode,'tail':(job/(label+'.log')).read_text()[-3500:]}))
