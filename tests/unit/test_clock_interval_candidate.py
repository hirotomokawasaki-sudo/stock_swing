"""2026-11-02: real SDK decode -> MassiveClient -> Hybrid across host TZs."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('zone', ['UTC', 'Asia/Tokyo'])
@pytest.mark.parametrize('frame', ['1Day', '5Min'])
@pytest.mark.parametrize('enabled', [False, True])
def test_clock_interval_real_decode(tmp_path, zone, frame, enabled):
    root = Path(__file__).resolve().parents[2]
    script = '''
import json, runpy, sys
from pathlib import Path
import pytest
from stock_swing.sources import massive_client, hybrid_data_fetcher
root=Path(sys.argv[1]).resolve()
assert Path(massive_client.__file__).resolve().is_relative_to(root)
assert Path(hybrid_data_fetcher.__file__).resolve().is_relative_to(root)
fixture=runpy.run_path(str(root/'tests/unit/test_provider_bar_contracts.py'))
with pytest.MonkeyPatch.context() as mp:
 f,r,calls=fixture['setup_fetcher'](Path(sys.argv[2]),mp,enabled=sys.argv[4]=='True')
 records,source=f.fetch_bars('NVDA',sys.argv[3],3)
 row=records[0]
 assert row.event_time.timestamp()==fixture['EPOCH']/1000
 assert row.event_time.utcoffset().total_seconds()==0
 assert row.event_type==('bar_daily' if sys.argv[3]=='1Day' else 'bar_5min')
 assert source=='massive' and len(calls)==1
 if sys.argv[4]=='True':
  contract=row.payload['bar_contract']
  assert contract['research_qualified'] is False
  assert contract['provider_final'] is None
  assert contract['provider_first_publication_at'] is None
  fixture['load_input_run'](Path(sys.argv[2]),fixture['seal'](r))
 else:
  assert 'bar_contract' not in row.payload
 print(json.dumps(dict(timestamp=row.event_time.isoformat(),source=source)))
'''
    env = dict(os.environ, TZ=zone, PYTHONPATH=str(root/'src'), PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.check_output([sys.executable, '-B', '-c', script, str(root), str(tmp_path), frame, str(enabled)], env=env, text=True)
    assert json.loads(result)['timestamp'] == '2026-10-20T20:00:00+00:00'
