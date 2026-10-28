"""Regression CMP-C01, 2026-10-28, 8909e79: mutating HTTP retry after unknown ACK."""
import httpx
import pytest
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.sources.retry import RetryConfig


@pytest.mark.parametrize("failure", ["timeout","server","rate","bad_json"])
@pytest.mark.parametrize("method", ["POST","DELETE"])
def test_ac_mutation_never_retried(monkeypatch,failure,method):
    calls=[]
    def transport(request):
        calls.append(request.method)
        if failure=="timeout":raise httpx.ReadTimeout("accepted, response lost",request=request)
        if failure=="bad_json":return httpx.Response(200,text="{")
        return httpx.Response(500 if failure=="server" else 429,json={})
    original=httpx.Client
    monkeypatch.setattr(httpx,"Client",lambda **kw:original(transport=httpx.MockTransport(transport),**kw))
    broker=BrokerClient(api_key="fixture",api_secret="fixture",paper_mode=True,retry_config=RetryConfig(initial_delay=.001))
    with pytest.raises(Exception):broker.fetch(endpoint="v2/orders",method=method)
    assert calls==[method], "unknown mutating result must not be automatically replayed"


def test_ac_read_retries_retained(monkeypatch):
    calls=[]
    def transport(request):
        calls.append(request.method)
        return httpx.Response(500,json={}) if len(calls)<3 else httpx.Response(200,json={"id":"fixture"})
    original=httpx.Client
    monkeypatch.setattr(httpx,"Client",lambda **kw:original(transport=httpx.MockTransport(transport),**kw))
    broker=BrokerClient(api_key="fixture",api_secret="fixture",paper_mode=True,retry_config=RetryConfig(initial_delay=.001))
    assert broker.fetch_account().payload["id"]=="fixture" and calls==["GET"]*3, "read recovery unchanged"
