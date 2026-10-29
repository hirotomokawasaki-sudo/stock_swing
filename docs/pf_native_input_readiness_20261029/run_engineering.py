from pathlib import Path
from decimal import Decimal
import json,sys
j=Path(__file__).resolve().parent;sys.path.insert(0,str(j/'candidate/src'))
from stock_swing.research.pf_execution_adapter import ExecutionArm
from stock_swing.research.comparison_book import Instrument
from datetime import datetime,timedelta,timezone
T=datetime(2026,11,2,14,35,tzinfo=timezone.utc)
def t(s):return (T+timedelta(seconds=s)).isoformat()
def order(s,oid,qty,side):return dict(kind='submit',event_id=oid,at=t(s),order=dict(id=oid,symbol='NVDA',qty=qty,side=side,type='market',time_in_force='gtc',max_fill_price=101),quotes={'NVDA':dict(price=100,as_of=t(s))})
def q(s,px,v):
 end=(T+timedelta(seconds=s)).replace(second=0,microsecond=0)
 return dict(kind='quote',event_id='q'+str(s),at=t(s),quote=dict(symbol='NVDA',bid=px,ask=px,executed_at=t(s),available_at=t(s),basis='raw'),prior_bar=dict(symbol='NVDA',start=(end-timedelta(minutes=1)).isoformat(),end=end.isoformat(),available_at=end.isoformat(),volume=v,basis='raw'))
events=[order(0,'buy',15,'buy'),q(1,100,600),q(2,100,600),q(61,100,1000),order(62,'sell1',7,'sell'),q(63,110,1000),dict(kind='cancel',event_id='cancel',at=t(64),order_id='sell1'),order(65,'sell2',14,'sell'),q(121,110,1000),q(181,110,1000)]
# Independent direct arithmetic and independent pending-order map. Expected
# fills are predeclared to exercise quota carry, partial FIFO and cancellation.
expected=[[],[('buy',6,100)],[],[('buy',9,100)],[],[('sell1',1,110)],[],[],[('sell2',10,110)],[('sell2',4,110)]]
arm=ExecutionArm('PF-A',[Instrument('NVDA','stock','fixture',1)]);cash=Decimal('1000000');qty=0;realized=Decimal(0);pending={};checkpoints=[]
for i,(event,fills) in enumerate(zip(events,expected)):
 out=arm.apply(event)
 if event['kind']=='submit':pending[event['order']['id']]=dict(qty=event['order']['qty'],side=event['order']['side'])
 if event['kind']=='cancel':del pending[event['order_id']]
 if event['kind']=='quote':
  actual=[(x['order_id'],x['qty'],x['raw_price']) for x in out['fills']];assert actual==fills,(i,actual,fills)
  for oid,n,price in fills:
   side=pending[oid]['side'];pending[oid]['qty']-=n
   if not pending[oid]['qty']:del pending[oid]
   if side=='buy':cash-=Decimal(n)*Decimal(price)*Decimal('1.0005');qty+=n
   else:
    cash+=Decimal(n)*Decimal(price)*Decimal('.9995');qty-=n
    realized+=Decimal(n)*(Decimal(price)*Decimal('.9995')-Decimal(100)*Decimal('1.0005'))
 snap=arm.snapshot();actualqty=sum(lot['qty'] for lot in snap['lots'].values())
 reserved=sum(Decimal(v['qty'])*Decimal('101')*Decimal('1.0005') for v in pending.values() if v['side']=='buy')
 assert abs(Decimal(str(snap['cash']))-cash)<Decimal('.00000001') and actualqty==qty
 assert abs(Decimal(str(snap['realized_pnl']))-realized)<Decimal('.00000001')
 assert abs(Decimal(str(snap['reserved_cash']))-reserved)<Decimal('.00000001')
 prior=arm.dumps();arm=ExecutionArm.loads(prior);assert arm.dumps()==prior
 checkpoints.append(dict(index=i,cash_qty_PnL_pending_oracle_equal=True,restart_equal=True))
result=dict(checkpoints=len(checkpoints),checks=checkpoints,all_equal=True,classification='synthetic engineering arithmetic, not economic A/B batch',same_author_independent_arithmetic=True)
(j/'ENGINEERING_ORACLE.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print(json.dumps(result))
