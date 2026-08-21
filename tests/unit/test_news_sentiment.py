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
    is_relevant_article,
    load_latest_finnhub_news,
    log_observation,
)


NOW = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)


def _article(headline: str, summary: str = "", days_ago: float = 0.5) -> dict:
    ts = (NOW - timedelta(days=days_ago)).timestamp()
    return {"headline": headline, "summary": summary, "datetime": ts}


# ── classify_news_sentiment: negative incident profile ───────────────────── #

# NOTE: these fixtures use generic "Company ..." headlines (no ticker/company
# name literally present), predating the 2026-08-21 relevance filter (see
# below). They test the keyword-scoring logic in isolation, so they pass
# relevance_filter_enabled=False explicitly rather than relying on synthetic
# headlines that happen to mention the symbol.
_NO_RELEVANCE_FILTER = NewsSentimentConfig(relevance_filter_enabled=False)


def test_negative_news_flagged_as_negative_sentiment_buy():
    items = [
        _article("Company faces SEC fraud investigation"),
        _article("Analysts downgrade stock after profit warning"),
        _article("Company announces layoffs amid weak demand"),
    ]
    result = classify_news_sentiment("NBIS", items, config=_NO_RELEVANCE_FILTER, now=NOW)
    assert result.is_negative_sentiment_buy is True
    assert result.net_score is not None
    assert result.net_score < 0
    assert result.article_count == 3


def test_positive_news_not_flagged():
    items = [
        _article("Company beats estimates and raises guidance"),
        _article("Stock upgraded after strong demand reported"),
    ]
    result = classify_news_sentiment("AAA", items, config=_NO_RELEVANCE_FILTER, now=NOW)
    assert result.is_negative_sentiment_buy is False
    assert result.net_score is not None
    assert result.net_score > 0


def test_mixed_neutral_news_not_flagged():
    items = [
        _article("Company beats estimates"),
        _article("Company faces lawsuit over patent dispute"),
    ]
    result = classify_news_sentiment("BBB", items, config=_NO_RELEVANCE_FILTER, now=NOW)
    assert result.is_negative_sentiment_buy is False


def test_no_keyword_hits_returns_insufficient_signal():
    items = [
        _article("Company announces quarterly product update"),
        _article("CEO speaks at industry conference"),
    ]
    result = classify_news_sentiment("CCC", items, config=_NO_RELEVANCE_FILTER, now=NOW)
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
    cfg = NewsSentimentConfig(max_article_age_days=3, relevance_filter_enabled=False)
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
    cfg = NewsSentimentConfig(min_articles_for_signal=2, relevance_filter_enabled=False)
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
    cfg = NewsSentimentConfig(
        negative_score_threshold=-0.6, min_articles_for_signal=1, relevance_filter_enabled=False
    )
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
    result = classify_news_sentiment("JJJ", items, config=_NO_RELEVANCE_FILTER, now=NOW)
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
    monkeypatch.delenv("NEWS_SENTIMENT_RELEVANCE_FILTER_DISABLED", raising=False)
    cfg = NewsSentimentConfig.from_env()
    assert cfg.max_article_age_days == 3
    assert cfg.negative_score_threshold == -0.34
    assert cfg.min_articles_for_signal == 2
    assert cfg.disabled is False
    assert cfg.relevance_filter_enabled is True


def test_config_from_env_overrides(monkeypatch):
    monkeypatch.setenv("NEWS_SENTIMENT_MAX_ARTICLE_AGE_DAYS", "5")
    monkeypatch.setenv("NEWS_SENTIMENT_NEGATIVE_THRESHOLD", "-0.5")
    monkeypatch.setenv("NEWS_SENTIMENT_MIN_ARTICLES", "3")
    monkeypatch.setenv("NEWS_SENTIMENT_DISABLED", "true")
    monkeypatch.setenv("NEWS_SENTIMENT_RELEVANCE_FILTER_DISABLED", "true")
    cfg = NewsSentimentConfig.from_env()
    assert cfg.max_article_age_days == 5
    assert cfg.negative_score_threshold == -0.5
    assert cfg.min_articles_for_signal == 3
    assert cfg.disabled is True
    assert cfg.relevance_filter_enabled is False


# ── Relevance filter (2026-08-21, R9 mid-review follow-up) ───────────────── #


def test_is_relevant_article_matches_ticker():
    assert is_relevant_article("msft stock rallies on earnings", "MSFT") is True


def test_is_relevant_article_matches_company_name():
    assert is_relevant_article(
        "microsoft corporation announces new product", "MSFT", "Microsoft Corporation"
    ) is True


def test_is_relevant_article_rejects_unrelated_market_chatter():
    text = "which dow jones stocks are moving on thursday?"
    assert is_relevant_article(text, "MSFT", "Microsoft Corporation") is False


def test_is_relevant_article_rejects_other_company_mentioned_alongside():
    # Real-world case found in the MSFT feed: an article about NVIDIA's CEO
    # commenting on AI, with no mention of Microsoft at all.
    text = "mark cuban fires back at jensen huang's ai warning"
    assert is_relevant_article(text, "MSFT", "Microsoft Corporation") is False


def test_is_relevant_article_empty_text_not_relevant():
    assert is_relevant_article("", "MSFT", "Microsoft Corporation") is False


def test_is_relevant_article_strips_corporate_suffix():
    # "NVIDIA Corporation" -> alias "nvidia" should match plain "Nvidia"
    assert is_relevant_article("nvidia unveils new chip", "NVDA", "NVIDIA Corporation") is True


def test_classify_news_sentiment_filters_irrelevant_articles_by_default():
    # 2 relevant negative articles + 3 irrelevant articles that would
    # otherwise flip the net_score positive if scored.
    items = [
        _article("Microsoft faces fraud investigation"),
        _article("Microsoft issues profit warning"),
        _article("Which dow jones stocks are moving on Thursday?"),
        _article("Company beats estimates and raises guidance"),  # unrelated ticker chatter
        _article("Stock upgraded after strong demand reported"),  # unrelated ticker chatter
    ]
    result = classify_news_sentiment(
        "MSFT", items, now=NOW, company_name="Microsoft Corporation"
    )
    assert result.article_count == 2
    assert result.filtered_irrelevant_count == 3
    assert result.is_negative_sentiment_buy is True


def test_classify_news_sentiment_relevance_filter_can_be_disabled():
    items = [
        _article("Microsoft faces fraud investigation"),
        _article("Microsoft issues profit warning"),
        _article("Company beats estimates and raises guidance"),
        _article("Stock upgraded after strong demand reported"),
    ]
    cfg = NewsSentimentConfig(relevance_filter_enabled=False)
    result = classify_news_sentiment(
        "MSFT", items, config=cfg, now=NOW, company_name="Microsoft Corporation"
    )
    assert result.article_count == 4
    assert result.filtered_irrelevant_count == 0
    # unrelated positive keyword hits now count too, flipping the net score
    assert result.is_negative_sentiment_buy is False


def test_classify_news_sentiment_without_company_name_falls_back_to_ticker():
    items = [
        _article("MSFT faces fraud investigation"),
        _article("MSFT issues profit warning"),
    ]
    result = classify_news_sentiment("MSFT", items, now=NOW)
    assert result.article_count == 2
    assert result.is_negative_sentiment_buy is True


def test_classify_news_sentiment_insufficient_signal_reports_filtered_count():
    items = [
        _article("Which dow jones stocks are moving on Thursday?"),
        _article("Best ETFs to watch this week"),
    ]
    result = classify_news_sentiment(
        "MSFT", items, now=NOW, company_name="Microsoft Corporation"
    )
    assert result.article_count == 0
    assert result.filtered_irrelevant_count == 2
    assert "insufficient_signal" in result.reason
    assert "filtered as irrelevant" in result.reason


# ── log_observation: never raises, writes JSONL always ────────────────────── #

def test_log_observation_writes_jsonl_for_candidate(tmp_path):
    log_path = tmp_path / "news_sentiment_shadow_log.jsonl"
    items = [
        _article("Company faces fraud investigation"),
        _article("Company issues profit warning"),
    ]
    result = classify_news_sentiment("NBIS", items, config=_NO_RELEVANCE_FILTER, now=NOW)
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
    result = classify_news_sentiment("NBIS", items, config=_NO_RELEVANCE_FILTER, now=NOW)
    log_observation(result, log_path=None)  # must not raise


def test_log_observation_still_writes_non_candidates_to_file(tmp_path):
    """Even non-candidates should be recorded for later threshold
    calibration, even though no INFO line is emitted for them."""
    log_path = tmp_path / "news_sentiment_shadow_log.jsonl"
    items = [
        _article("Company beats estimates and raises guidance"),
        _article("Company upgraded on strong demand"),
    ]
    result = classify_news_sentiment("AAA", items, config=_NO_RELEVANCE_FILTER, now=NOW)
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
