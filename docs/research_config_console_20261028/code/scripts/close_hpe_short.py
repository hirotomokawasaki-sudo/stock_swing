"""Manual paper HPE short cover, not a new-long BUY or unconditional fill claim."""
import os,sys
from pathlib import Path
PROJECT_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT_ROOT/'src'))
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.execution.reduction_orders import ReductionResult,reduce_position,report_results

def main():
    # Preserve the existing script's local environment loading; never include .env in evidence copies.
    env_file=PROJECT_ROOT/'.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line=line.strip()
            if line and not line.startswith('#') and '=' in line:
                key,value=line.split('=',1);os.environ[key]=value
    try:
        broker=BrokerClient(api_key=os.environ['BROKER_API_KEY'],api_secret=os.environ['BROKER_API_SECRET'],paper_mode=True)
    except Exception as exc:
        return report_results([ReductionResult('HPE','cover_short',reason='broker_unavailable:'+type(exc).__name__)])
    def confirm(qty):return input(f'Confirm BUY {qty} HPE to close short? (yes/no): ').lower()=='yes'
    return report_results([reduce_position(broker,PROJECT_ROOT,'HPE','cover_short',confirm)])
if __name__=='__main__':raise SystemExit(main())
