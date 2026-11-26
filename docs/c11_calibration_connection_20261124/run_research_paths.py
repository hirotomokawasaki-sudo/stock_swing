"""Offline, explicit-input command for the native C11/U research connection.

Publishes a research artifact outside the production repository. Never fetches
prices, creates a recorder, selects a formal U or invokes an order executor.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import native_paths
import path_driver

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['inputs','native-root','native-pins','guard-source','guard-sha256','source-ref','output']:
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--context-policy',required=True,choices=['explicit-engineering','require-observed-context'])
    args=parser.parse_args(argv)
    out=Path(args.output).resolve()
    if out.is_relative_to(REPO):
        raise ValueError('research output must stay outside the production repository')
    if not out.parent.is_dir():
        raise ValueError('explicit existing external output directory required')
    raw=Path(args.inputs).read_bytes();data=json.loads(raw);frames=deepcopy(data['frames']);excluded=0
    if args.context_policy=='require-observed-context':
        for f in frames:
            original=f['operational']
            f['operational']={a:x for a,x in original.items() if x.get('role')=='observed_source_bound'}
            excluded+=len(original)-len(f['operational'])
    result=native_paths.run(data['initial'],frames,native_source_root=args.native_root,
        native_pins=json.loads(Path(args.native_pins).read_bytes()),entry_policy=data['entry_policy'],exit_policy=data['exit_policy'],
        guard_source=args.guard_source,guard_sha256=args.guard_sha256,source_ref=args.source_ref,execution_model=native_paths.MODEL)
    accounts={}
    if args.context_policy=='explicit-engineering':
        for arm,text in result['ending_journals'].items():
            b=path_driver.core().ComparisonBook.loads(text);s=b.snapshot()
            accounts[arm]={k:s[k] for k in ['cash','equity','fees','realized_pnl','unrealized_pnl']}
            accounts[arm].update(model_total_pnl=s['equity']-b.policy.baseline_equity,
                role='assumption-conditioned model accounting, not observed PnL or formal C11/U effect')
    counts=dict(Counter(x['kind'] for x in result['audit']))
    report=dict(status='NATIVE_COMPONENT_PATH_COMPLETED',input_sha256=hashlib.sha256(raw).hexdigest(),
        context_policy=args.context_policy,excluded_model_contexts=excluded,model_accounting=accounts or None,
        code_sha256={n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in
            ['run_research_paths.py','native_entries.py','native_paths.py','path_driver.py']},
        audit_kind_counts=counts,paths=result,formal_U=None,economic_qualified=False,market_PnL=None,
        formal_profit_comparison_started=False,observed_context_role_does_not_certify_evidence=True,
        real_order_submissions=0,new_market_GET=0)
    encoded=(json.dumps(report,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    # Reuse the existing atomic, no-replace publication primitive, not a new store.
    from stock_swing.experiments.measurement_capture import _publish
    _publish(out,encoded)
    return dict(status=report['status'],context_policy=args.context_policy,independent_arms=len(result['ending_journals']),
        audit_kind_counts=counts,formal_U=None,economic_qualified=False,market_PnL=None,output=str(out))


if __name__=='__main__':
    try:
        print(json.dumps(main(),sort_keys=True))
    except Exception as exc:
        print('RESEARCH_PATH_FAILED: '+type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
