"""Manual paper reductions for NOW/IBM; durable one-operation identity, no auto retry."""
import os,sys
from pathlib import Path
PROJECT_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT_ROOT/'src'))
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.execution.reduction_orders import ReductionResult,reduce_position,report_results

def main():
    try:
        broker=BrokerClient(api_key=os.getenv('BROKER_API_KEY'),api_secret=os.getenv('BROKER_API_SECRET'),paper_mode=True)
    except Exception as exc:
        return report_results([ReductionResult(s,'reduce_long',reason='broker_unavailable:'+type(exc).__name__) for s in ['NOW','IBM']])
    return report_results([reduce_position(broker,PROJECT_ROOT,s,'reduce_long') for s in ['NOW','IBM']])
if __name__=='__main__':raise SystemExit(main())
