"""Regression: 2026-11-16 weekly audit, 423/425 unavailable prices.

Incident preimage is preserved in the operations-followthrough packet. The
existing provider ignored requested dates and hardcoded range=1mo.
"""
from datetime import datetime, timezone
import io
import json
import os
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts import audit_trades_with_market_data as audit


@pytest.fixture(autouse=True)
def fixed_audit_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 17, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(audit, 'datetime', Clock)


def install_provider(monkeypatch, payload=None, error=None):
    requests = []
    if payload is None:
        payload = {'chart': {'result': [{'timestamp': [1778587200],
            'indicators': {'quote': [{'low': [99], 'high': [101], 'close': [100]}]}}]}}
    def fetch(request, timeout):
        requests.append((request.full_url, timeout))
        if error:
            raise error
        return io.BytesIO(json.dumps(payload).encode())
    monkeypatch.setattr(audit.urllib.request, 'urlopen', fetch)
    return requests


@pytest.mark.parametrize('tz', ['UTC', 'Asia/Tokyo', 'America/New_York'])
def test_ac_historical_request_honors_inclusive_dates_in_every_host_timezone(monkeypatch, tz):
    requests = install_provider(monkeypatch)
    old = os.environ.get('TZ')
    try:
        monkeypatch.setenv('TZ', tz)
        time.tzset()
        bars = audit.fetch_yahoo_finance_bars('AAPL', '2026-05-12', '2026-11-13')
    finally:
        if old is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = old
        time.tzset()
    query = parse_qs(urlsplit(requests[0][0]).query)
    assert 'range' not in query, 'historical audit must not silently become recent-only'
    assert query['period1'] == [str(int(datetime(2026, 5, 12, tzinfo=timezone.utc).timestamp()))]
    assert query['period2'] == [str(int(datetime(2026, 11, 18, tzinfo=timezone.utc).timestamp()))], 'include post-trade splits through observation date'
    assert query['events'] == ['splits']
    assert query['interval'] == ['1d'] and requests[0][1] == 10
    assert bars == {'2026-05-12': (99.0, 101.0, 100.0)}


def test_ac_same_day_request_includes_whole_day_and_symbol_cannot_inject_query(monkeypatch):
    requests = install_provider(monkeypatch)
    audit.fetch_yahoo_finance_bars('BRK/B?range=max', '2026-05-12', '2026-05-12')
    url = urlsplit(requests[0][0]); query = parse_qs(url.query)
    assert int(query['period2'][0]) > int(query['period1'][0]) + 86400
    assert audit.fetch_yahoo_finance_bars('AAPL', '2026-12-01', '2026-12-01') == {}, 'bars outside the requested day must be excluded'
    assert url.path.endswith('BRK%2FB%3Frange%3Dmax') and 'range' not in query


def test_ac_recent_position_normalization_keeps_one_month_default(monkeypatch):
    requests = install_provider(monkeypatch)
    assert audit.fetch_yahoo_finance_bars('AAPL', '', '')
    assert parse_qs(urlsplit(requests[0][0]).query) == {'interval': ['1d'], 'range': ['1mo']}


@pytest.mark.parametrize('start,end', [('2026-05-13', '2026-05-12'),
    ('invalid', '2026-05-12'), ('2026-05-12', ''), ('', '2026-05-12')])
def test_ac_invalid_or_partial_date_range_is_unavailable_without_network(monkeypatch, start, end):
    requests = install_provider(monkeypatch)
    assert audit.fetch_yahoo_finance_bars('AAPL', start, end) == {}
    assert requests == [], 'invalid ranges must not fall back to recent data'


@pytest.mark.parametrize('payload', [{}, {'chart': {'result': []}},
    {'chart': {'result': None}}, {'chart': {'result': [{'timestamp': [1778587200],
        'indicators': {'quote': [{'low': [], 'high': [], 'close': []}]}}]}}])
def test_ac_absent_or_corrupt_provider_data_remains_unavailable(monkeypatch, payload):
    install_provider(monkeypatch, payload=payload)
    assert audit.fetch_yahoo_finance_bars('AAPL', '2026-05-12', '2026-05-13') == {}


def test_ac_provider_failure_is_not_automatically_retried(monkeypatch):
    requests = install_provider(monkeypatch, error=OSError('provider unavailable'))
    assert audit.fetch_yahoo_finance_bars('AAPL', '2026-05-12', '2026-05-13') == {}
    assert len(requests) == 1


def test_ac_missing_price_does_not_hide_valid_neighbor(monkeypatch):
    payload = {'chart': {'result': [{'timestamp': [1778587200, 1778673600],
        'indicators': {'quote': [{'low': [99, None], 'high': [101, None], 'close': [100, None]}]}}]}}
    install_provider(monkeypatch, payload)
    assert audit.fetch_yahoo_finance_bars('AAPL', '2026-05-12', '2026-05-13') == {'2026-05-12': (99.0, 101.0, 100.0)}


def split_fixture(events):
    return {'chart': {'result': [{'timestamp': [1778587200, 1778673600],
        'events': {'splits': events},
        'indicators': {'quote': [{'low': [99, 24], 'high': [101, 26], 'close': [100, 25]}]}}]}}


@pytest.mark.parametrize('numerator,denominator', [(4, 1), (10, 1), (3, 1), (1, 10)])
def test_ac_subsequent_split_reverses_market_basis_only(monkeypatch, numerator, denominator):
    payload = split_fixture({'split': {'date': 1778630400, 'numerator': numerator, 'denominator': denominator}})
    before = json.dumps(payload, sort_keys=True)
    install_provider(monkeypatch, payload)
    bars = audit.fetch_yahoo_finance_bars('TEST', '2026-05-12', '2026-05-13')
    factor = numerator / denominator
    assert bars['2026-05-12'] == (99 * factor, 101 * factor, 100 * factor)
    assert bars['2026-05-13'] == (24, 26, 25), 'split day is already on the new share basis'
    assert json.dumps(payload, sort_keys=True) == before


def test_ac_split_after_last_trade_and_multiple_splits_are_not_missed(monkeypatch):
    payload = split_fixture({'first': {'date': 1782864000, 'numerator': 4, 'denominator': 1},
                             'second': {'date': 1793836800, 'numerator': 3, 'denominator': 1}})
    install_provider(monkeypatch, payload)
    assert audit.fetch_yahoo_finance_bars('TEST', '2026-05-12', '2026-05-12') == {'2026-05-12': (1188, 1212, 1200)}


@pytest.mark.parametrize('bad', [0, -1, True, None, '4', float('nan'), float('inf')])
@pytest.mark.parametrize('field', ['numerator', 'denominator'])
def test_ac_invalid_split_cannot_silently_clear_anomaly(monkeypatch, bad, field):
    event = {'date': 1782864000, 'numerator': 4, 'denominator': 1}
    event[field] = bad
    payload = split_fixture({'bad': event})
    install_provider(monkeypatch, payload)
    assert audit.fetch_yahoo_finance_bars('TEST', '2026-05-12', '2026-05-13') == {}


def test_ac_split_events_are_ignored_for_existing_current_position_basis(monkeypatch):
    install_provider(monkeypatch, split_fixture({'bad': {'numerator': 'invalid'}}))
    assert audit.fetch_yahoo_finance_bars('TEST', '', '') == {
        '2026-05-12': (99, 101, 100), '2026-05-13': (24, 26, 25)}


@pytest.mark.parametrize('price,exit_code', [(400, 0), (900, 1)])
def test_ac_real_audit_removes_split_basis_false_alarm_but_keeps_real_error(tmp_path, monkeypatch, capsys, price, exit_code):
    install_provider(monkeypatch, split_fixture({'split': {
        'date': 1778630400, 'numerator': 4, 'denominator': 1}}))
    path = tmp_path/'data/tracking/pnl_state.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'trades': [{'symbol': 'TEST', 'trade_id': 'split-fixture',
        'status': 'closed', 'side': 'buy', 'qty': 1, 'asset_class': 'stock',
        'entry_time': '2026-05-12T12:00:00Z', 'exit_time': '2026-05-12T13:00:00Z',
        'entry_price': price, 'exit_price': price, 'pnl': 0, 'holding_days': 0}],
        'cumulative_realized_pnl': 0}))
    before = path.read_bytes()
    monkeypatch.setattr(audit, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(audit, 'load_broker_positions', lambda *_: [])
    monkeypatch.setattr('sys.argv', ['audit'])
    assert audit.main() == exit_code
    output = capsys.readouterr().out
    assert 'Total closed trades audited: 1' in output
    assert 'Total anomalies detected:    ' + str(exit_code) in output
    assert path.read_bytes() == before, 'audit must never rewrite trade prices or PnL'


def corrected_cross_split(tmp_path, adjustment, *, price=100):
    from stock_swing.tracking.history_migration import prepare_migration, apply_migration
    from stock_swing.tracking.ledger_transaction import FILES
    old = dict(symbol='TEST', trade_id='original', status='closed', side='buy', qty=1,
        broker_order_id='fixture-buy', exit_broker_order_id='fixture-sell',
        asset_class='stock', entry_time='2026-05-12T12:00:00Z',
        exit_time='2026-05-13T13:00:00Z', entry_price=400, exit_price=25,
        pnl=-375, holding_days=25/24)
    new = dict(old, trade_id='replacement', qty=4, entry_price=price,
        pnl=(25-price)*4, corporate_action_adjustments=adjustment)
    state = dict(trades=[old], quarantined_trades=[], cumulative_realized_pnl=-375)
    raw = {name: b'' for name in FILES}
    raw['pnl_state.json'] = json.dumps(state).encode()
    raw['fill_consumed_ledger.json'] = b'{"fills":[]}'
    path = tmp_path/'data/tracking';path.mkdir(parents=True)
    for name, body in raw.items(): (path/name).write_bytes(body)
    plan = prepare_migration(raw, row_changes=[], corporate_plans=[dict(
        retire_records=[dict(collection='trades', row_index=0, before=old)],
        candidate_rows=[new])], evidence_sha256='a'*64,
        recorded_at='2026-06-01T00:00:00Z', reason='synthetic split basis regression')
    apply_migration(tmp_path, plan)
    return path/'pnl_state.json'


@pytest.mark.parametrize('fault,expected', [(None, 0), ('real_error', 1),
    ('ratio', 2), ('symbol', 2), ('date', 2), ('ordering', 2), ('duplicate', 2),
    ('unbound', 2), ('malformed', 2), ('absent_adjustment', 1), ('none_adjustment', 1)])
def test_ac_bound_cross_split_entry_basis_without_changing_financials(tmp_path, monkeypatch, capsys, fault, expected):
    adjustment = dict(group_id='synthetic-split', ratio='4', symbol='TEST',
        effective_date='2026-05-13', effective_ordering='before_orders_on_UTC_effective_date')
    if fault == 'ratio': adjustment['ratio'] = 'nan'
    if fault == 'symbol': adjustment['symbol'] = 'OTHER'
    if fault == 'date': adjustment['effective_date'] = '2026-05-14'
    if fault == 'ordering': adjustment['effective_ordering'] = 'unknown'
    adjustments = [adjustment] * (2 if fault == 'duplicate' else 1)
    if fault == 'malformed': adjustments = {}
    if fault == 'none_adjustment': adjustments = None
    if fault == 'absent_adjustment': adjustments = []
    path = corrected_cross_split(tmp_path, adjustments, price=900 if fault == 'real_error' else 100)
    if fault == 'unbound':
        state = json.loads(path.read_text())
        state.pop('history_migrations'); state.pop('measurement_lineage')
        path.write_text(json.dumps(state))
        (path.parent/'trade_events.jsonl').write_bytes(b'')
    before = {p.name: p.read_bytes() for p in path.parent.iterdir() if p.is_file()}
    install_provider(monkeypatch, split_fixture({'split': {
        'date': 1778630400, 'numerator': 4, 'denominator': 1}}))
    monkeypatch.setattr(audit, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(audit, 'load_broker_positions', lambda *_: [])
    monkeypatch.setattr('sys.argv', ['audit'])
    assert audit.main() == expected
    assert before == {p.name: p.read_bytes() for p in path.parent.iterdir() if p.is_file()}
    if fault is None:
        assert 'validated_historical_replacement' in capsys.readouterr().out
