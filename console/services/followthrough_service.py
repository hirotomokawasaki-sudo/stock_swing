"""Read-only, scoped operational checks. Never an order or promotion gate.

Reuse acquired broker rows and saved artifacts; no network, ledger constructors,
repair, new scheduler, or fabricated missing-input defaults.
"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from pathlib import Path
from console.services.operational_evidence_service import _read, _stamp, _number

REVIEW = 'reports/console/latest_evidence_review.json'
SUMMARY = 'reports/console/latest_console_summary.json'
READINESS = 'docs/p4_s1_readiness_20261029/readiness.json'
VALUES = 'docs/p4_s1_readiness_20261029/decision_values.json'
TERMINAL = {'filled', 'canceled', 'cancelled', 'expired', 'rejected', 'replaced'}
ACTIVE = {'new', 'accepted', 'pending_new', 'accepted_for_bidding', 'partially_filled',
          'pending_cancel', 'pending_replace', 'done_for_day', 'held', 'suspended', 'stopped', 'calculated'}


def _fresh(evidence, now, *, complete=False):
    stamp, age = _stamp(evidence.get('as_of'), now)
    return (evidence.get('status') == 'ok' and stamp is not None and age <= 120
            and (not complete or evidence.get('complete') is True))


def position_comparison(root, positions, evidence, now):
    result = {'status': 'unknown', 'mismatch_symbols': None, 'mismatch_count': None,
              'broker_as_of': evidence.get('as_of'), 'read_at': now.isoformat(),
              'tracker_last_updated': None, 'tracker_sha256': None,
              'scope': '取得したbroker保有と保存台帳openの銘柄別・符号付き数量だけ。現金/注文/全口座の照合ではない。',
              'reason': '保有取得・台帳の完全な数量入力が必要。台帳修復・全口座不一致0の認定は行いません。'}
    if not _fresh(evidence, now, complete=True):
        return result
    # FIX-06 / 2026-11-06: a repeated state-only read cannot detect a prepared
    # transaction or mismatched correction events. Reuse the existing pair
    # reader in one nonblocking lock epoch, never recover from a display.
    try:
        from stock_swing.tracking.compatibility import read_analysis_snapshot
        from stock_swing.tracking.ledger_transaction import ledger_transaction
        path = root / 'data/tracking/pnl_state.json'
        # Keep the original bounded/strict JSON preflight, including no mkdir
        # for a missing input. Re-read the actual pair under the shared lock.
        _, status = _read(root, 'data/tracking/pnl_state.json')
        if status != 'ok':
            return result
        with ledger_transaction(root, recover=False, blocking=False):
            _, status = _read(root, 'data/tracking/pnl_state.json')
            if status != 'ok':
                return result
            raw, tracker_evidence = read_analysis_snapshot(path)
    except (OSError, ValueError, TypeError, RuntimeError, ImportError):
        return {**result, 'reason_code': 'ledger_pair_unavailable',
                'reason': '台帳と訂正イベントの同時点検証が未成立、または処理中。数量一致を認定せず、読取から復旧しません。'}
    if not isinstance(raw.get('trades'), list):
        return result
    if not isinstance(positions, list) or any(not isinstance(t, dict) for t in raw['trades']):
        return result
    quarantined = sum(t.get('status') == 'quarantined' for t in raw['trades'])
    if quarantined:
        return {**result, 'status':'quarantine_present', 'quarantined_rows':quarantined,
                'reason':'保存台帳に隔離行あり。対象外数量をゼロとして整合認定せず、既存の品質点検で扱います。'}
    def aggregate(rows, tracker):
        totals = {}
        for row in rows:
            if tracker and row.get('status') not in ('open', 'closed'):
                raise ValueError('unsupported tracker status')
            if tracker and row.get('status') != 'open':
                continue
            symbol = row.get('symbol');qty = _number(row.get('qty'))
            if not isinstance(symbol, str) or not symbol.strip() or qty is None or qty == 0:
                raise ValueError('incomplete quantity')
            # Existing tracker writer is long-only. Do not guess a short side.
            if tracker and (qty < 0 or row.get('side', 'buy') not in ('buy', 'long')):
                raise ValueError('unsupported tracker direction')
            symbol = symbol.upper().strip()
            if not tracker and symbol in totals:
                raise ValueError('duplicate broker position')
            totals[symbol] = totals.get(symbol, Decimal(0)) + Decimal(str(row['qty']))
        return totals
    try:
        broker = aggregate(positions, False);tracker = aggregate(raw['trades'], True)
        mismatch = sorted(s for s in broker.keys() | tracker.keys()
                          if broker.get(s, 0) != tracker.get(s, 0))
        return {**result, 'status': 'mismatch' if mismatch else 'matched_quantity_only',
                'mismatch_symbols': mismatch, 'mismatch_count': len(mismatch),
                'tracker_last_updated': raw.get('last_updated') if isinstance(raw.get('last_updated'), str) else None,
                'tracker_sha256': tracker_evidence['state_sha256'],
                'tracker_events_sha256': tracker_evidence['events_sha256'],
                'tracker_ledger_revision': tracker_evidence['ledger_revision'],
                'reason': '今回読んだ保存open数量との比較。last_updatedは台帳更新時刻で、口座の取得時刻ではありません。'}
    except (OSError, ValueError, TypeError, OverflowError):
        return result


def pending_risk(orders, evidence, now):
    result = {'status': 'unknown', 'as_of': evidence.get('as_of'),
              'observed_active_orders': None, 'pending_cancel': None,
              'observed_limit_buy_notional': None, 'unpriced_buy_orders': None,
              'reserved_cash': None, 'projected_concentration': None,
              'scope': str(evidence.get('scope') or '既存status=all/limit=500の取得範囲。') + ' limit買い残額は概算で、broker予約資金や買付余力ではない。',
              'reason': '全未約定/予約定義/注文案/分類が未資格。取消待ちの数量・資金を取消済み扱いしません。'}
    def unknown(code, reason, action):
        return {**result, 'reason_code':code, 'reason':reason, 'next_action':action,
                'observed_rows':len(orders) if isinstance(orders,list) else None, 'query_limit':500}
    if not evidence or evidence.get('status') is None:
        return unknown('not_acquired','注文cache未取得。','既存の注文取得結果を確認。表示補完のために追加broker callは行いません。')
    if evidence.get('status') == 'error':
        return unknown('acquisition_failed','注文取得が失敗したため数量・金額は未確認。','既存の取得状態を確認。取消/再発注は行いません。')
    if isinstance(orders,list) and len(orders)>=500:
        return unknown('query_cap','既存一覧の500件上限に到達。未約定全体は未確認。','取得範囲/ページ境界を既存の取得側で点検。古い完了注文と現未約定を混同しません。')
    if evidence.get('status') != 'ok':
        return unknown('partial_input','注文一覧が部分取得または資格未確認。','取得範囲・完全性を確認。部分的な合計を全体へ転用しません。')
    if evidence.get('query_status') == 'open' and evidence.get('complete') is not True:
        return unknown('partial_input','現在の未約定の取得完全性が未確認。','元取得のcomplete・上限・取得範囲を確認。')
    if not _fresh(evidence, now):
        return unknown('stale_input','元取得時刻が欠測/未来/120秒超で資格未確認。','元時刻と既存cache更新を確認。表示時刻で鮮度を更新しません。')
    if not isinstance(orders,list):
        return unknown('invalid_order','注文入力の形式が不正。','既存取得の型/必須項目を点検。修復/取消/再発注は行いません。')
    invalid = unknown('invalid_order','注文ID/状態/数量/価格に欠測・不正・競合あり。','既存取得行の必須項目と重複IDを点検。部分集計は表示しません。')
    ids=set(); active=cancel=unpriced=0;notional=0.0
    try:
        for row in orders:
            if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] or row['id'] in ids:
                return invalid
            ids.add(row['id']);state=row.get('status')
            if state in TERMINAL:continue
            if state not in ACTIVE or row.get('side') not in ('buy','sell'):return invalid
            qty=_number(row.get('qty'));filled=_number(row.get('filled_qty'))
            if qty is None or qty<=0 or filled is None or filled<0 or filled>qty:return invalid
            active+=1;cancel+=state=='pending_cancel'
            if row['side']=='buy':
                price=_number(row.get('limit_price'))
                if row.get('type')=='limit' and price is not None and price>0:
                    notional+=(qty-filled)*price
                else:unpriced+=1
        if _number(notional) is None:return invalid
    except (ValueError, TypeError, OverflowError):return invalid
    complete_open = evidence.get('query_status')=='open' and evidence.get('complete') is True
    return {**result, 'status':'observed_scope_only','observed_active_orders':active,
            'pending_cancel':cancel,'observed_limit_buy_notional':notional,
            'unpriced_buy_orders':unpriced, 'reason_code':'observed_query_scope',
            'observed_rows':len(orders),'query_limit':500,
            'complete_open_query':complete_open,
            'reason':'取得時点・照会口座の未約定数とlimit買い残だけを確認。実予約資金・注文案/分類・全口座照合は別。' if complete_open else result['reason'],
            'next_action':'価格未確定BUY・予約定義・注文案/分類の不足を別途確認。概算と実予約資金は別。'}


def live_scheduler_evidence(snapshot, now):
    """Reuse current Console scheduler acquisition; no network or receipt writes.

    Metadata is not history-run identity, application completion, loaded config,
    or SELL monitoring. Those certificates stay false even for last_status=ok.
    """
    result = {'status':'not_acquired', 'source':None, 'as_of':None, 'rows':[],
              'registered_job_observed':False, 'last_scheduler_status':'unknown',
              'last_scheduler_at':None, 'history_run_id_available':False,
              'application_run_linked':False, 'scheduled_verified':False,
              'effective_config_verified':False, 'sell_monitor_verified':False,
              'reason':'現在のscheduler取得結果なし。表示のための追加照会は行いません。'}
    if not isinstance(snapshot,dict):return result
    evidence = snapshot.get('evidence')
    if not isinstance(evidence,dict):return result
    stamp,age = _stamp(evidence.get('as_of'),now)
    if (evidence.get('status')!='ok' or evidence.get('complete') is not True
            or stamp is None or age>120 or evidence.get('source') not in ('gateway_cli','gateway_http')):
        return {**result,'status':'unqualified','reason':'scheduler取得が失敗・部分取得・古い・時刻不正のため現在値は未認定。'}
    jobs = snapshot.get('jobs')
    if not isinstance(jobs,list) or any(not isinstance(j,dict) for j in jobs):
        return {**result,'status':'invalid'}
    rows=[];ids=set();names=set()
    for job in jobs:
        name=job.get('name')
        if not isinstance(name,str) or not name.startswith('stock_swing_paper_demo_'):continue
        identity=job.get('id');state=job.get('state')
        state=state if isinstance(state,dict) else {}
        status=state.get('lastRunStatus') or job.get('last_run_status')
        last,_=_stamp(job.get('last_run'),now)
        if (not isinstance(identity,str) or not identity.strip() or identity in ids or name in names
                or type(job.get('enabled')) is not bool or last is None
                or status not in ('ok','error','skipped')):
            return {**result,'status':'invalid','reason':'売買jobの識別子・実行時刻・結果metadataに欠測/競合あり。'}
        ids.add(identity);names.add(name)
        rows.append({'name':name,'enabled':job['enabled'],'last_run':last,'last_status':status})
    if not rows:
        return {**result,'status':'not_observed','source':evidence['source'],'as_of':stamp,
                'reason':'今回取得したscheduler範囲に対象の売買jobはありません。'}
    primary=next((r for r in rows if r['name']=='stock_swing_paper_demo_market_close'),None)
    return {**result,'status':'metadata_observed','source':evidence['source'],'as_of':stamp,'rows':rows,
            'registered_job_observed':True,
            'last_scheduler_status':primary['last_status'] if primary else 'unknown',
            'last_scheduler_at':primary['last_run'] if primary else None,
            'reason':'既存scheduler一覧の独立metadataを自動接続。履歴固有実行ID・アプリrunとの対応・実効設定・SELL開始/完了は別途未確認。'}


def scheduler_evidence(root, now):
    raw,status=_read(root,REVIEW)
    result={'status':'unknown','reviewed_at':None,'registered_job_observed':False,
            'last_scheduler_status':'unknown','last_scheduler_at':None,
            'history_run_id_available':False,'application_run_linked':False,
            'scheduled_verified':False,'effective_config_verified':False,'sell_monitor_verified':False,
            'reason':'scheduler履歴の実行IDとアプリrunの同一性・実効設定・SELL開始/完了は未確認。'}
    stamp,age=_stamp(raw.get('reviewed_at'),now)
    if status!='ok' or stamp is None:return result
    result['reviewed_at']=stamp
    if age>86400:return {**result,'status':'stale'}
    summary,status=_read(root,SUMMARY)
    if status!='ok':return result
    try:
        current=hashlib.sha256((root/SUMMARY).read_bytes()).hexdigest()
        if current!=raw.get('summary_sha256'):return {**result,'status':'changed_summary'}
    except OSError:return result
    s=raw.get('scheduler')
    if (not isinstance(s,dict) or s.get('origin')!='gateway.automations.get'
            or s.get('job_name')!='stock_swing_paper_demo_market_close'
            or not isinstance(s.get('job_id'),str) or not s['job_id']
            or s.get('last_status') not in ('ok','error','skipped')):return result
    last,_=_stamp(s.get('last_run_at'),now)
    if last is None:return result
    # Current job metadata is real independent evidence, but has no history runID.
    result = {**result,'status':'metadata_observed','registered_job_observed':True,
            'last_scheduler_status':s['last_status'],'last_scheduler_at':last,
            'reason':'登録ジョブの独立metadataは確認。履歴取得は利用不可で、run ID対応や実効設定/SELL監視の証明は保留。'}
    relative = s.get('wrapper_log_path')
    duration = s.get('last_duration_ms')
    if (not isinstance(relative,str) or not re.fullmatch(
            r'logs/gateway_workflows/stock_swing_paper_demo_market_close_[0-9]{8}T[0-9]{6}_[a-f0-9]{8}\.log',relative)
            or type(duration) is not int or not 0 <= duration <= 7200000):
        return result
    try:
        path=root/relative
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size>8*1024*1024:
            return result
        body=path.read_bytes()
        if hashlib.sha256(body).hexdigest()!=s.get('wrapper_log_sha256'):return result
        ids=re.findall(r'^\s*Run ID\s*:\s*(\S+)\s*$',body.decode('utf-8'),re.M)
        run=summary.get('run',{})
        if not isinstance(run,dict):return result
        app_stamp,_=_stamp(run.get('timestamp'),now)
        if (len(ids)!=1 or not isinstance(run.get('run_id'),str) or ids[0]!=run['run_id']
                or run.get('mode')!='paper' or run.get('dry_run') is not False
                or run.get('invocation_source')!='paper_demo_scheduled' or app_stamp is None):return result
        start=datetime.fromisoformat(last);finish=start+timedelta(milliseconds=duration)
        if not start<=datetime.fromisoformat(app_stamp)<=finish:return result
        return {**result,'application_run_linked':True,
                'reason':'登録ジョブmetadata→保持ログ→保存サマリーrunが当該1回で一致。scheduler履歴固有ID・実効設定・SELL開始/完了は未確認。'}
    except (OSError,ValueError,TypeError,OverflowError):return result


def research_inputs(root):
    raw,status=_read(root,READINESS)
    result={'status':'unknown','source':READINESS,'deny_decisions':None,'deny_exact_snapshots':None,
            'sell_decisions':None,'sell_exact_snapshots':None,'exit_direct_link':False,
            'reason':'凍結済み入力の充足点検。利益効果・現在の前向き観測とは別。'}
    if status!='ok' or raw.get('scope') is None:return result
    try:
        deny=raw['groups']['deny'];sell=raw['groups']['sell']
        joins=[]
        for group in (deny,sell):
            counts=group['field_counts']['snapshot_join']
            if (not isinstance(counts,dict) or not counts or
                    any(type(v) is not int or v<0 for v in counts.values()) or
                    sum(counts.values())!=group['rows']):return result
            joins.append(counts.get('exact_unique_same_action',0))
        values=[deny['rows'],joins[0],sell['rows'],joins[1]]
        if any(type(v) is not int or v<0 for v in values) or values[1]>values[0] or values[3]>values[2]:return result
        return {**result,'status':'historical_input_audit','deny_decisions':values[0],
                'deny_exact_snapshots':values[1],'sell_decisions':values[2],'sell_exact_snapshots':values[3],
                'exit_direct_link':raw['frozen_ledger'].get('direct_SELL_to_closed_exit_join_available') is True}
    except (KeyError,TypeError):return result


def acceptance_evidence(root):
    raw,status=_read(root,VALUES)
    required=('capital_B','currency','evaluation_window','epsilon_percentage_points_per_window',
              'rho_metric','rho_value','rho_unit','delta_bps_per_day','formal_U_calibration_period',
              'formal_U_multiplier','formal_U_hash','long_run_variance','target_power','block_sessions',
              'required_sessions','formal_evaluation_session')
    missing=[k for k in required if raw.get(k) is None]
    labels = [
        ('研究基準資本B','通貨額','本人・Agent整合'), ('通貨','通貨コード','本人・Agent整合'),
        ('評価窓','営業日/期間','本人・Agent整合'), ('許容収益減epsilon','%ポイント/評価窓','本人'),
        ('必要リスク低減rhoの指標','時価DD等の指標名','本人・Agent定義'), ('必要リスク低減rhoの値','採用指標と同単位','本人'),
        ('必要リスク低減rhoの単位','%ポイント/通貨額等','本人・Agent定義'), ('実務効果delta','bps/日','本人・Agent費用整理'),
        ('正式U較正期間','評価から分離した適格期間','Agent'), ('正式U倍率','保有倍率','Agent'),
        ('正式Uの固定hash','較正入力/仕様のhash','Agent'), ('長期分散','同単位の依存考慮分散','Agent'),
        ('目標検出力','0〜1の比率','Agent'), ('依存block長','営業日','Agent'),
        ('必要標本期間','独立性を考慮した営業日','Agent'), ('正式判定session','固定session ID/日付','Agent')]
    details = [dict(key=k,label=label,unit=unit,owner=owner) for k,(label,unit,owner) in zip(required,labels) if k in missing]
    return {'status':'missing_values' if status=='ok' and missing else 'values_present_unqualified' if status=='ok' else 'unknown',
            'source':VALUES,'missing_fields':missing if status=='ok' else None,
            'missing_details':details if status=='ok' else None,
            'worksheet_url':'/api/console-evidence/document?name=worksheet',
            'formal_start_ready':False,'promotion_authorized':False,
            'reason':'本人の資本/許容値とAgentの較正/標本計算を分離。値の存在だけで入力・較正・費用・一回判定の資格を認定しません。'}


def get_followthrough(root:Path, *, positions=None, positions_evidence=None,
                      orders=None, orders_evidence=None, scheduler_snapshot=None, now=None):
    now=now or datetime.now(timezone.utc)
    saved_scheduler=scheduler_evidence(root,now)
    scheduler=live_scheduler_evidence(scheduler_snapshot,now) if scheduler_snapshot is not None else saved_scheduler
    if scheduler_snapshot is not None:
        scheduler['saved_review_status']=saved_scheduler['status']
        scheduler['reviewed_at']=saved_scheduler.get('reviewed_at')
    return {'position_comparison':position_comparison(root,positions,positions_evidence or {},now),
            'pending_risk':pending_risk(orders,orders_evidence or {},now),
            'scheduler':scheduler,'research_inputs':research_inputs(root),
            'acceptance':acceptance_evidence(root),
            'next_actions':['scheduler実行IDとアプリrun/SELL開始完了の照合（未取得を成功にしない）',
                            '既存healthの判定元・台帳品質と同時点口座の不足を確認（自動修復しない）',
                            '予約/注文案/分類の入力資格を確定。保存数量比較を全口座照合へ格上げしない',
                            'DENYは判断actionのsnapshot、SELLは出口IDの直接対応を既存記録へ接続',
                            '同条件・費用後・許容犠牲・終了条件を固定して採否を判断']}
