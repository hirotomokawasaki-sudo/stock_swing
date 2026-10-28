"""Opt-in provider-response lineage, NOT completed-bar/PIT qualification.

Reuses DecisionInputRecorder. No new store, broker requests or eligibility rules.
Exact HTTP body hashes and decoded-envelope hashes are labelled separately.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re


def normalize_interval(value):
    """Canonicalize supported Alpaca intervals; refuse unknowns before I/O."""
    if not isinstance(value, str):
        raise ValueError('unsupported bar interval')
    v = value.lower()
    if v in {'day', 'daily', '1day', '1d'}:
        return '1Day'
    match = re.fullmatch(r'([1-9][0-9]?)(min|t|hour|h)', v)
    if match:
        n, unit = int(match[1]), match[2]
        if unit in {'min', 't'} and n <= 59:
            return f'{n}Min'
        if unit in {'hour', 'h'} and n <= 23:
            return f'{n}Hour'
    if v in {'1week', '1w'}:
        return '1Week'
    match = re.fullmatch(r'(1|2|3|4|6|12)(month|m)', v)
    if match:
        return f'{int(match[1])}Month'
    raise ValueError('unsupported bar interval')


def record_bar_response(recorder, *, provider, request, response, received_at,
                        raw_bytes=None, response_request_id=None):
    """Bind a response version to the existing run recorder, preserving unknowns.

    Exact raw bytes are hashed, not persisted. The decoded JSON is separately
    persisted and validated by the existing recorder. No headers/auth URLs saved.
    A decoded-only adapter must not claim its hash represents HTTP body bytes.
    """
    if recorder is None or not recorder.enabled:
        return None
    encoded = json.dumps(response, sort_keys=True, separators=(',', ':'),
                         allow_nan=False).encode()
    contract = dict(schema_version=1, provider=provider,
        requested_interval=request['interval'],
        requested_feed=request.get('feed'),
        requested_adjustment=request.get('adjustment'),
        request=deepcopy(request), response_adjusted=response.get('adjusted'),
        response_request_id=response_request_id or response.get('request_id'),
        received_at=received_at.astimezone(timezone.utc).isoformat(),
        raw_sha256=hashlib.sha256(raw_bytes if raw_bytes is not None else encoded).hexdigest(),
        raw_representation='HTTP_body_bytes' if raw_bytes is not None else 'decoded_JSON',
        raw_body_saved=False, decoded_sha256=hashlib.sha256(encoded).hexdigest(),
        provider_first_publication_at=None, provider_final=None,
        bar_window_end=None, research_qualified=False)
    contract['version_sha256'] = hashlib.sha256(json.dumps(contract, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    ref = recorder.observe('provider_response', dict(contract=contract, response=response),
                           observed_at=received_at)
    return dict(contract, observation_ref=ref)


def observe_canonical_bars(recorder, records):
    if recorder is not None and recorder.enabled:
        recorder.observe('canonical_provider_bars', dict(records=records,
            scope='returned_subset_not_all_candidate_or_decision_inputs',
            research_qualified=False))
