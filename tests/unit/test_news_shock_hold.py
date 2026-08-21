"""Tests for news_shock_hold.py (2026-08-21, Plan D follow-up).

Shadow-only diagnostic for currently-held positions: classify_news_shock()
must never block or raise, and must correctly flag a held symbol whose very
recent news flow has turned sharply negative.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from stock_swing.risk.news_shock_hold import (
    NewsShockHoldConfig,
    classify_news_shock,
    log_shadow,
)


NOW = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)


def _article(headline: str, summary: str = "", days_ago: float = 0.2, source: str = "CNBC") -> dict:
    ts = (NOW - timedelta(days=days_ago)).timestamp()
    return {"headline": headline, "summary": summary, "datetime": ts, "source": source}


def test_negative_news_on_held_position_flags_shock():
    items = [
        _article("microsoft faces fraud investigation"),
        _article("microsoft issues profit warning"),
    ]
    result = classify_news_shock(
        "MSFT", items, now=NOW, company_name="Microsoft Corporation",
        unrealized_plpc=-0.03,
    )
    assert result.is_news_shock is True
    assert result.net_score is not None
    assert result.net_score < 0
    assert result.unrealized_plpc == -0.03
    assert "news_shock" in result.reason


def test_positive_news_on_held_position_not_flagged():
    items = [
        _article("microsoft beats estimates and raises guidance"),
        _article("microsoft upgraded on strong demand"),
    ]
    result = classify_news_shock(
        "MSFT", items, now=NOW, company_name="Microsoft Corporation",
    )
    assert result.is_news_shock is False


def test_irrelevant_news_filtered_out_not_flagged():
    # Same relevance filter as news_sentiment.py: generic market chatter
    # should not trigger a shock on a held position that isn't mentioned.
    items = [
        _article("Which dow jones stocks are moving on Thursday?"),
        _article("Mark Cuban Fires Back At Jensen Huang's AI Warning"),
    ]
    result = classify_news_shock(
        "MSFT", items, now=NOW, company_name="Microsoft Corporation",
    )
    assert result.is_news_shock is False
    assert result.article_count == 0


def test_stale_articles_beyond_shorter_lookback_excluded():
    # Default lookback for held positions (1 day) is shorter than Plan D's
    # entry-side default (3 days) -- a 2-day-old article should already be
    # excluded.
    items = [
        _article("microsoft faces fraud investigation", days_ago=2),
        _article("microsoft issues profit warning", days_ago=2),
    ]
    result = classify_news_shock(
        "MSFT", items, now=NOW, company_name="Microsoft Corporation",
    )
    assert result.article_count == 0
    assert result.is_news_shock is False


def test_recent_article_within_shorter_lookback_counted():
    items = [
        _article("microsoft faces fraud investigation", days_ago=0.5),
        _article("microsoft issues profit warning", days_ago=0.5),
    ]
    result = classify_news_shock(
        "MSFT", items, now=NOW, company_name="Microsoft Corporation",
    )
    assert result.article_count == 2
    assert result.is_news_shock is True


def test_milder_threshold_than_entry_side_can_still_flag():
    # negative_score_threshold default here (-0.25) is milder than Plan D's
    # entry-side default (-0.34), so a more moderately negative flow should
    # still flag as a shock for a held position.
    cfg = NewsShockHoldConfig()
    assert cfg.negative_score_threshold == -0.25
    items = [
        _article("microsoft beats estimates"),
        _article("microsoft faces fraud investigation and lawsuit and probe"),
    ]
    result = classify_news_shock(
        "MSFT", items, config=cfg, now=NOW, company_name="Microsoft Corporation",
    )
    assert result.net_score is not None
    assert result.net_score <= cfg.negative_score_threshold
    assert result.is_news_shock is True


def test_disabled_config_never_flags():
    cfg = NewsShockHoldConfig(disabled=True)
    items = [
        _article("microsoft faces fraud investigation"),
        _article("microsoft issues profit warning"),
    ]
    result = classify_news_shock(
        "MSFT", items, config=cfg, now=NOW, company_name="Microsoft Corporation",
    )
    assert result.is_news_shock is False
    assert result.reason == "disabled"


def test_none_news_items_not_flagged():
    result = classify_news_shock("MSFT", None, now=NOW, company_name="Microsoft Corporation")
    assert result.is_news_shock is False
    assert result.net_score is None


def test_config_from_env_defaults(monkeypatch):
    monkeypatch.delenv("NEWS_SHOCK_HOLD_MAX_ARTICLE_AGE_DAYS", raising=False)
    monkeypatch.delenv("NEWS_SHOCK_HOLD_NEGATIVE_THRESHOLD", raising=False)
    monkeypatch.delenv("NEWS_SHOCK_HOLD_MIN_ARTICLES", raising=False)
    monkeypatch.delenv("NEWS_SHOCK_HOLD_DISABLED", raising=False)
    cfg = NewsShockHoldConfig.from_env()
    assert cfg.max_article_age_days == 1
    assert cfg.negative_score_threshold == -0.25
    assert cfg.min_articles_for_signal == 2
    assert cfg.disabled is False
    assert cfg.is_enabled() is True


def test_config_from_env_overrides(monkeypatch):
    monkeypatch.setenv("NEWS_SHOCK_HOLD_MAX_ARTICLE_AGE_DAYS", "2")
    monkeypatch.setenv("NEWS_SHOCK_HOLD_NEGATIVE_THRESHOLD", "-0.4")
    monkeypatch.setenv("NEWS_SHOCK_HOLD_MIN_ARTICLES", "3")
    monkeypatch.setenv("NEWS_SHOCK_HOLD_DISABLED", "true")
    cfg = NewsShockHoldConfig.from_env()
    assert cfg.max_article_age_days == 2
    assert cfg.negative_score_threshold == -0.4
    assert cfg.min_articles_for_signal == 3
    assert cfg.disabled is True
    assert cfg.is_enabled() is False


def test_log_shadow_writes_jsonl_for_shock(tmp_path):
    log_path = tmp_path / "news_shock_hold_shadow_log.jsonl"
    items = [
        _article("microsoft faces fraud investigation"),
        _article("microsoft issues profit warning"),
    ]
    result = classify_news_shock(
        "MSFT", items, now=NOW, company_name="Microsoft Corporation",
        unrealized_plpc=-0.05,
    )
    log_shadow(result, shadow_log_path=log_path)

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["symbol"] == "MSFT"
    assert record["is_news_shock"] is True
    assert record["unrealized_plpc"] == -0.05


def test_log_shadow_without_path_does_not_raise():
    items = [
        _article("microsoft faces fraud investigation"),
        _article("microsoft issues profit warning"),
    ]
    result = classify_news_shock("MSFT", items, now=NOW, company_name="Microsoft Corporation")
    log_shadow(result, shadow_log_path=None)  # must not raise


def test_log_shadow_writes_non_shocks_too(tmp_path):
    log_path = tmp_path / "news_shock_hold_shadow_log.jsonl"
    items = [
        _article("microsoft beats estimates and raises guidance"),
        _article("microsoft upgraded on strong demand"),
    ]
    result = classify_news_shock("MSFT", items, now=NOW, company_name="Microsoft Corporation")
    assert result.is_news_shock is False
    log_shadow(result, shadow_log_path=log_path)
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
