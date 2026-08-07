"""Tests for news_sentiment.py (Plan D, 2026-08-08 R10 follow-up).

Observability-only diagnostic: classify_news_sentiment() must never block
or raise, and must correctly flag a BUY firing alongside clearly negative
recent company news as a negative_sentiment_buy.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from stock_swing.risk.news_sentiment import (
    NewsSentimentConfig,
    classify_news_sentiment,
    load_latest_finnhub_news,
    log_observation,
)


NOW = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)


def _article(headline: str, summary: str = "", days_ago: float = 0.5) -> dict:
    ts = (NOW - timedelta(days=days_ago)).timestamp()
    return {"headline": headline, "summary": summary, "datetime": ts}


# ── classify_news_sentiment: negative incident profile ───────────────────── #

def test_negative_news_flagged_as_negative_sentiment_buy():
    items = [
        _article("Company faces SEC fraud investigation"),
        _article("Analysts downgrade stock after profit warning"),
        _article("Company announces layoffs amid weak demand"),
    ]
    result = classify_news_sentiment("NBIS", items, now=NOW)
    assert result.is_negative_sentiment_buy is True
    assert result.net_score is not None
    assert result.net_score < 0
    assert result.article_count == 3


def test_positive_news_not_flagged():
    items = [
        _article("Company beats estimates and raises guidance"),
        _article("Stock upgraded after strong demand reported"),
    ]
    result = classify_news_sentiment("AAA", items, now=NOW)
    assert result.is_negative_sentiment_buy is False
    assert result.net_score is not None
    assert result.net_score > 0


def test_mixed_neutral_news_not_flagged():
    items = [
        _article("Company beats estimates"),
        _article("Company faces lawsuit over patent dispute"),
    ]
    result = classify_news_sentiment("BBB", items, now=NOW)
    assert result.is_negative_sentiment_buy is False


def test_no_keyword_hits_returns_insufficient_signal():
    items = [
        _article("Company announces quarterly product update"),
        _article("CEO speaks at industry conference"),
    ]
    result = classify_news_sentiment("CCC", items, now=NOW)
    assert result.is_negative_sentiment_buy is False
    assert "insufficient_signal" in result.reason


# ── Article age filtering ─────────────────────────────────────────────────── #

def test_stale_articles_excluded_from_scoring():
    items = [
        _article("Company faces fraud investigation", days_ago=10),  # too old
        _article("Company faces fraud investigation", days_ago=20),  # too old
    ]
    cfg = NewsSentimentConfig(max_article_age_days=3)
    result = classify_news_sentiment("DDD", items, config=cfg, now=NOW)
    assert result.article_count == 0
    assert result.is_negative_sentiment_buy is False
    assert "insufficient_signal" in result.reason


def test_recent_articles_within_window_counted():
    items = [
        _article("Company faces fraud investigation", days_ago=1),
        _article("Analyst downgrade on weak demand", days_ago=2),
    ]
    cfg = NewsSentimentConfig(max_article_age_days=3)
    result = classify_news_sentiment("EEE", items, config=cfg, now=NOW)
    assert result.article_count == 2
    assert result.is_negative_sentiment_buy is True


# ── min_articles_for_signal threshold ─────────────────────────────────────── #

def test_below_min_articles_not_flagged_even_if_negative():
    items = [_article("Company under fraud investigation")]
    cfg = NewsSentimentConfig(min_articles_for_signal=2)
    result = classify_news_sentiment("FFF", items, config=cfg, now=NOW)
    assert result.is_negative_sentiment_buy is False
    assert "insufficient_signal" in result.reason


def test_at_min_articles_threshold_can_flag():
    items = [
        _article("Company under fraud investigation"),
        _article("Company issues profit warning"),
    ]
    cfg = NewsSentimentConfig(min_articles_for_signal=2)
    result = classify_news_sentiment("GGG", items, config=cfg, now=NOW)
    assert result.article_count == 2
    assert result.is_negative_sentiment_buy is True


# ── Boundary values on negative_score_threshold ───────────────────────────── #

def test_boundary_exactly_at_threshold_flags():
    # 1 positive, 4 negative hits (fraud, investigation, lawsuit, probe)
    # -> net = (1-4)/5 = -0.6
    items = [
        _article("Company beats estimates"),
        _article("Company faces fraud investigation and lawsuit and probe"),
    ]
    cfg = NewsSentimentConfig(negative_score_threshold=-0.6, min_articles_for_signal=1)
    result = classify_news_sentiment("HHH", items, config=cfg, now=NOW)
    assert result.net_score == -0.6
    assert result.is_negative_sentiment_buy is True  # inclusive boundary (<=)


def test_boundary_just_inside_not_flagged():
    items = [
        _article("Company beats estimates and raises guidance"),
        _article("Company faces lawsuit"),
    ]
    cfg = NewsSentimentConfig(negative_score_threshold=-0.6, min_articles_for_signal=1)
    result = classify_news_sentiment("III", items, config=cfg, now=NOW)
    assert result.is_negative_sentiment_buy is False


# ── Missing / malformed data fallback (never raises, never flags) ────────── #

def test_none_news_items_not_flagged():
    result = classify_news_sentiment("NBIS", None, now=NOW)
    assert result.is_negative_sentiment_buy is False
    assert "no_data" in result.reason
    assert result.net_score is None


def test_empty_news_items_not_flagged():
    result = classify_news_sentiment("NBIS", [], now=NOW)
    assert result.is_negative_sentiment_buy is False
    assert "no_data" in result.reason


def test_malformed_article_items_skipped_gracefully():
    items = [
        "not_a_dict",
        {"headline": None, "summary": None, "datetime": "not_a_number"},
        _article("Company faces fraud investigation"),
        _article("Company issues profit warning"),
    ]
    result = classify_news_sentiment("JJJ", items, now=NOW)
    assert result.article_count == 3  # malformed str skipped, 2 dicts counted (age None treated as recent)
    assert result.is_negative_sentiment_buy is True


def test_disabled_config_never_flags():
    cfg = NewsSentimentConfig(disabled=True)
    items = [
        _article("Company faces fraud investigation"),
        _article("Company issues profit warning"),
    ]
    result = classify_news_sentiment("NBIS", items, config=cfg, now=NOW)
    assert result.is_negative_sentiment_buy is False
    assert result.reason == "disabled"


def test_config_from_env_defaults(monkeypatch):
    monkeypatch.delenv("NEWS_SENTIMENT_MAX_ARTICLE_AGE_DAYS", raising=False)
    monkeypatch.delenv("NEWS_SENTIMENT_NEGATIVE_THRESHOLD", raising=False)
    monkeypatch.delenv("NEWS_SENTIMENT_MIN_ARTICLES", raising=False)
    monkeypatch.delenv("NEWS_SENTIMENT_DISABLED", raising=False)
    cfg = NewsSentimentConfig.from_env()
    assert cfg.max_article_age_days == 3
    assert cfg.negative_score_threshold == -0.34
    assert cfg.min_articles_for_signal == 2
    assert cfg.disabled is False


def test_config_from_env_overrides(monkeypatch):
    monkeypatch.setenv("NEWS_SENTIMENT_MAX_ARTICLE_AGE_DAYS", "5")
    monkeypatch.setenv("NEWS_SENTIMENT_NEGATIVE_THRESHOLD", "-0.5")
    monkeypatch.setenv("NEWS_SENTIMENT_MIN_ARTICLES", "3")
    monkeypatch.setenv("NEWS_SENTIMENT_DISABLED", "true")
    cfg = NewsSentimentConfig.from_env()
    assert cfg.max_article_age_days == 5
    assert cfg.negative_score_threshold == -0.5
    assert cfg.min_articles_for_signal == 3
    assert cfg.disabled is True


# ── log_observation: never raises, writes JSONL always ────────────────────── #

def test_log_observation_writes_jsonl_for_candidate(tmp_path):
    log_path = tmp_path / "news_sentiment_shadow_log.jsonl"
    items = [
        _article("Company faces fraud investigation"),
        _article("Company issues profit warning"),
    ]
    result = classify_news_sentiment("NBIS", items, now=NOW)
    log_observation(result, log_path=log_path)

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["symbol"] == "NBIS"
    assert record["is_negative_sentiment_buy"] is True


def test_log_observation_without_path_does_not_raise():
    items = [
        _article("Company faces fraud investigation"),
        _article("Company issues profit warning"),
    ]
    result = classify_news_sentiment("NBIS", items, now=NOW)
    log_observation(result, log_path=None)  # must not raise


def test_log_observation_still_writes_non_candidates_to_file(tmp_path):
    """Even non-candidates should be recorded for later threshold
    calibration, even though no INFO line is emitted for them."""
    log_path = tmp_path / "news_sentiment_shadow_log.jsonl"
    items = [
        _article("Company beats estimates and raises guidance"),
        _article("Company upgraded on strong demand"),
    ]
    result = classify_news_sentiment("AAA", items, now=NOW)
    assert result.is_negative_sentiment_buy is False
    log_observation(result, log_path=log_path)
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


# ── load_latest_finnhub_news: file discovery / freshness selection ───────── #

def test_load_latest_finnhub_news_missing_dir_returns_empty(tmp_path):
    missing_dir = tmp_path / "does_not_exist"
    result = load_latest_finnhub_news("AAPL", missing_dir)
    assert result == []


def test_load_latest_finnhub_news_no_matching_files_returns_empty(tmp_path):
    (tmp_path / "finnhub_msft_20260101.json").write_text("{}", encoding="utf-8")
    result = load_latest_finnhub_news("AAPL", tmp_path)
    assert result == []


def test_load_latest_finnhub_news_picks_freshest_snapshot(tmp_path):
    old_data = {
        "fetched_at": "2026-08-01T00:00:00+00:00",
        "payload": {"news": [{"headline": "old headline"}]},
    }
    new_data = {
        "fetched_at": "2026-08-07T00:00:00+00:00",
        "payload": {"news": [{"headline": "new headline"}]},
    }
    (tmp_path / "finnhub_aapl_news_20260801_000000.json").write_text(
        json.dumps(old_data), encoding="utf-8"
    )
    (tmp_path / "finnhub_aapl_news_20260807_000000.json").write_text(
        json.dumps(new_data), encoding="utf-8"
    )
    result = load_latest_finnhub_news("AAPL", tmp_path)
    assert result == [{"headline": "new headline"}]


def test_load_latest_finnhub_news_case_insensitive_symbol(tmp_path):
    data = {
        "fetched_at": "2026-08-07T00:00:00+00:00",
        "payload": {"news": [{"headline": "hi"}]},
    }
    (tmp_path / "finnhub_aapl_news_20260807_000000.json").write_text(
        json.dumps(data), encoding="utf-8"
    )
    result = load_latest_finnhub_news("aapl", tmp_path)
    assert result == [{"headline": "hi"}]


def test_load_latest_finnhub_news_malformed_json_skipped(tmp_path):
    (tmp_path / "finnhub_aapl_news_bad.json").write_text("not json", encoding="utf-8")
    result = load_latest_finnhub_news("AAPL", tmp_path)
    assert result == []


def test_load_latest_finnhub_news_empty_symbol_returns_empty(tmp_path):
    result = load_latest_finnhub_news("  ", tmp_path)
    assert result == []


def test_load_latest_finnhub_news_non_list_payload_skipped(tmp_path):
    data = {
        "fetched_at": "2026-08-07T00:00:00+00:00",
        "payload": {"news": "not_a_list"},
    }
    (tmp_path / "finnhub_aapl_news_20260807_000000.json").write_text(
        json.dumps(data), encoding="utf-8"
    )
    result = load_latest_finnhub_news("AAPL", tmp_path)
    assert result == []
