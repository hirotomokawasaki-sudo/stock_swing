from pathlib import Path
import json
j=Path(__file__).resolve().parent;d=json.loads((j/'NATIVE.json').read_text());r=d['results']
for scenario in ['normal','pf_blocked','restricted','volume','sell','unknown_account','dry','halt','reduced_skip']:
 for v in ['native_A','adapter_A','adapter_B']:
  x=r[scenario+'_'+v];assert x['main_exit']==(1 if scenario=='unknown_account' else 0),(scenario,v)
  expected=0 if scenario in ['restricted','volume','unknown_account','dry','halt'] or scenario in ['pf_blocked','reduced_skip'] and v!='adapter_B' else 1
  assert len(x['posts'])==expected,(scenario,v)
  if scenario=='sell':assert x['posts'][0]['side']=='sell' and len(x['legs'])==1
 for v in ['adapter_A','adapter_B']:
  for receipt in r[scenario+'_'+v]['filters']:assert receipt['config']['disabled'] is False
(j/'NATIVE_ASSERTIONS.json').write_text(json.dumps(dict(cases=d['cases'],all_scenarios_expected=True,A_native_business_HTTP_identical=d['A_native_business_HTTP_identical'],normal_native_quantity=r['normal_adapter_A']['posts'][0]['qty'],sell_native_quantity=r['sell_adapter_A']['posts'][0]['qty'],PF_only_changes=['pf_blocked','reduced_skip'],controls_preserved=['restricted','volume','halt','unknown_account','dry','sell'],guard_configuration_unmodified=True),sort_keys=True,indent=2)+'\n')
