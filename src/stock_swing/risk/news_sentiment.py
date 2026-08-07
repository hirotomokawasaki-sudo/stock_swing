"""Plan D (2026-08-08, R10 follow-up): company-news sentiment diagnostic
(observability-only).

Purpose
-------
`collect_data.py`'s `stock_swing_news_collection` cron (every 4h) has fetched
Finnhub company-news (`data/raw/finnhub/finnhub_{symbol}_news_*.json`) for
every universe symbol since 2026-05-28, but nothing in the pipeline has ever
read that data back for a trading decision -- it exists only for console
display. This module is the lowest-cost, zero-new-contract way to start
using it: a simple lexicon-based headline/summary sentiment score, computed
from data already on disk, logged alongside each BUY decision for later
review.

Why lexicon-based (no new dependency)
--------------------------------------
No sentiment library (vaderSentiment, textblob, ...) is installed in this
environment and adding one is a separate decision. A small, transparent
keyword lexicon is enough to flag the cases that matter most for this
diagnostic: a BUY firing on price/momentum while the concurrent news flow is
sharply negative (e.g. a fraud investigation, guidance cut, recall) --
exactly the kind of disconnect the 2026-08-07 NBIS incident review flagged
as worth watching for other sources of information the strategy currently
ignores.

Why observability-only (not wired into signal_strength/sizing/exit)
----------------------------------------------------------------------
Same rationale as `distance_from_high.py` (Plan C) and `volatility_gate.py`
(Plan B): folding an unvalidated sentiment score directly into
signal_strength or a hard block would silently change position sizing and
exit-conviction tiers for every BUY, with no paper-verified evidence yet
that doing so improves outcomes. This module only classifies and logs. See
docs/console_improvement_tasks.md for the planned review/promotion
schedule (same "shadow -> paper_ab -> active" pattern as Plan B).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Small, transparent keyword lexicon. Deliberately conservative (financial-
# news-flavored terms only) to avoid over-firing on generic market chatter.
# Case-insensitive substring match against headline + summary.
POSITIVE_TERMS: frozenset[str] = frozenset(
    {
        "beats estimates",
        "beat estimates",
        "raises guidance",
        "raised guidance",
        "record revenue",
        "record profit",
        "upgrade",
        "upgraded",
        "outperform",
        "strong demand",
        "better-than-expected",
        "beats expectations",
        "surge",
        "surges",
        "soar",
        "soars",
        "rally",
        "rallies",
        "buyback",
        "share repurchase",
        "raises dividend",
        "raised dividend",
        "wins contract",
        "new contract",
        "partnership",
    }
)

NEGATIVE_TERMS: frozenset[str] = frozenset(
    {
        "misses estimates",
        "missed estimates",
        "cuts guidance",
        "cut guidance",
        "lowers guidance",
        "downgrade",
        "downgraded",
        "underperform",
        "weak demand",
        "worse-than-expected",
        "misses expectations",
        "plunge",
        "plunges",
        "crash",
        "crashes",
        "sell-off",
        "selloff",
        "lawsuit",
        "sued",
        "investigation",
        "probe",
        "fraud",
        "recall",
        "layoffs",
        "job cuts",
        "bankruptcy",
        "delisted",
        "delisting",
        "sec charges",
        "class action",
        "data breach",
        "warns",
        "warning",
        "profit warning",
    }
)

DEFAULT_MAX_ARTICLE_AGE_DAYS = 3
DEFAULT_NEGATIVE_SCORE_THRESHOLD = -0.34  # net_negative / total <= this
DEFAULT_MIN_ARTICLES_FOR_SIGNAL = 2


@dataclass
class NewsSentimentConfig:
    """Threshold configuration for the news sentiment diagnostic.

    Env overrides:
        NEWS_SENTIMENT_MAX_ARTICLE_AGE_DAYS  only count articles this
                                              recent (default 3)
        NEWS_SENTIMENT_NEGATIVE_THRESHOLD    net score <= this flags
                                              "negative_sentiment_buy"
                                              (default -0.34)
        NEWS_SENTIMENT_MIN_ARTICLES          minimum matched articles
                                              before flagging (default 2)
        NEWS_SENTIMENT_DISABLED              set "true" to skip evaluation
    """

    max_article_age_days: int = DEFAULT_MAX_ARTICLE_AGE_DAYS
    negative_score_threshold: float = DEFAULT_NEGATIVE_SCORE_THRESHOLD
    min_articles_for_signal: int = DEFAULT_MIN_ARTICLES_FOR_SIGNAL
    disabled: bool = False

    @classmethod
    def from_env(cls) -> "NewsSentimentConfig":
        return cls(
            max_article_age_days=int(
                os.environ.get(
                    "NEWS_SENTIMENT_MAX_ARTICLE_AGE_DAYS",
                    DEFAULT_MAX_ARTICLE_AGE_DAYS,
                )
            ),
            negative_score_threshold=float(
                os.environ.get(
                    "NEWS_SENTIMENT_NEGATIVE_THRESHOLD",
                    DEFAULT_NEGATIVE_SCORE_THRESHOLD,
                )
            ),
            min_articles_for_signal=int(
                os.environ.get(
                    "NEWS_SENTIMENT_MIN_ARTICLES", DEFAULT_MIN_ARTICLES_FOR_SIGNAL
                )
            ),
            disabled=os.environ.get("NEWS_SENTIMENT_DISABLED", "").lower()
            in ("1", "true", "yes"),
        )


@dataclass
class NewsSentimentResult:
    symbol: str
    is_negative_sentiment_buy: bool
    net_score: float | None  # (pos_hits - neg_hits) / (pos_hits + neg_hits), None if no data
    positive_hits: int
    negative_hits: int
    article_count: int
    reason: str
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _score_article_text(text: str) -> tuple[int, int]:
    """Return (positive_hits, negative_hits) for one lowercased text blob."""
    pos = sum(1 for term in POSITIVE_TERMS if term in text)
    neg = sum(1 for term in NEGATIVE_TERMS if term in text)
    return pos, neg


def load_latest_finnhub_news(
    symbol: str,
    finnhub_raw_dir: Path | str,
) -> list[dict[str, Any]]:
    """Return the news article list from the most recent finnhub
    'company-news' snapshot for *symbol*, or [] if none found/unreadable.

    Mirrors finnhub_metric_lookup.load_latest_finnhub_metric()'s pattern,
    but selects the `_news_` snapshot files (written by
    collect_data.py's collect_finnhub()) rather than the 'stock/metric'
    ones.
    """
    raw_dir = Path(finnhub_raw_dir)
    if not raw_dir.exists():
        return []

    sym_lower = symbol.strip().lower()
    if not sym_lower:
        return []

    candidates = sorted(raw_dir.glob(f"finnhub_{sym_lower}_news_*.json"))
    if not candidates:
        return []

    best_news: list[dict[str, Any]] | None = None
    best_fetched_at = ""
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fetched_at = str(data.get("fetched_at") or "")
        payload = data.get("payload") or {}
        news = payload.get("news") if isinstance(payload, dict) else None
        if not isinstance(news, list):
            continue
        if fetched_at > best_fetched_at:
            best_fetched_at = fetched_at
            best_news = news

    return best_news or []


def classify_news_sentiment(
    symbol: str,
    news_items: list[dict[str, Any]] | None,
    config: NewsSentimentConfig | None = None,
    now: datetime | None = None,
) -> NewsSentimentResult:
    """Classify recent company-news sentiment for a BUY candidate
    (observability only -- never blocks or modifies a decision).

    Args:
        symbol: Stock symbol.
        news_items: Finnhub `company-news` article list (as returned by
            load_latest_finnhub_news / the raw `payload["news"]` field).
            Each item is expected to have `headline`, `summary`, and a unix
            `datetime` field.
        config: NewsSentimentConfig (defaults to from_env()).
        now: Override "current time" for testing.

    Returns:
        NewsSentimentResult. `is_negative_sentiment_buy` flags the case this
        diagnostic exists to surface: a BUY firing while recent news flow
        skews clearly negative.
    """
    cfg = config or NewsSentimentConfig.from_env()
    now_dt = now or datetime.now(timezone.utc)

    if cfg.disabled:
        return NewsSentimentResult(
            symbol=symbol,
            is_negative_sentiment_buy=False,
            net_score=None,
            positive_hits=0,
            negative_hits=0,
            article_count=0,
            reason="disabled",
        )

    if not news_items:
        return NewsSentimentResult(
            symbol=symbol,
            is_negative_sentiment_buy=False,
            net_score=None,
            positive_hits=0,
            negative_hits=0,
            article_count=0,
            reason="no_data: no recent news articles available",
        )

    cutoff_ts = now_dt.timestamp() - cfg.max_article_age_days * 86400
    total_pos = 0
    total_neg = 0
    counted = 0
    for item in news_items:
        if not isinstance(item, dict):
            continue
        article_ts = item.get("datetime")
        try:
            article_ts_f = float(article_ts) if article_ts is not None else None
        except (TypeError, ValueError):
            article_ts_f = None
        if article_ts_f is not None and article_ts_f < cutoff_ts:
            continue
        headline = str(item.get("headline") or "").lower()
        summary = str(item.get("summary") or "").lower()
        pos, neg = _score_article_text(f"{headline} {summary}")
        total_pos += pos
        total_neg += neg
        counted += 1

    total_hits = total_pos + total_neg
    if total_hits == 0 or counted < cfg.min_articles_for_signal:
        return NewsSentimentResult(
            symbol=symbol,
            is_negative_sentiment_buy=False,
            net_score=0.0 if total_hits else None,
            positive_hits=total_pos,
            negative_hits=total_neg,
            article_count=counted,
            reason=(
                f"insufficient_signal: {counted} recent article(s), "
                f"{total_hits} keyword hit(s) (need >= "
                f"{cfg.min_articles_for_signal} articles)"
            ),
        )

    net_score = round((total_pos - total_neg) / total_hits, 3)
    is_negative = net_score <= cfg.negative_score_threshold

    reason = (
        f"negative_sentiment_buy: net_score={net_score:.2f} "
        f"(<= {cfg.negative_score_threshold:.2f}) from {counted} recent "
        f"article(s), pos={total_pos} neg={total_neg}"
        if is_negative
        else (
            f"not_flagged: net_score={net_score:.2f} from {counted} recent "
            f"article(s), pos={total_pos} neg={total_neg}"
        )
    )

    return NewsSentimentResult(
        symbol=symbol,
        is_negative_sentiment_buy=is_negative,
        net_score=net_score,
        positive_hits=total_pos,
        negative_hits=total_neg,
        article_count=counted,
        reason=reason,
    )


def log_observation(
    result: NewsSentimentResult,
    log_path: Path | str | None = None,
) -> None:
    """Log a news-sentiment observation (diagnostic only, never blocks).

    Mirrors the shadow-log pattern used by volatility_gate.py and
    distance_from_high.py: always emits an INFO line when flagged, and
    appends a structured JSON record to *log_path* when provided so
    negative-sentiment BUYs accumulate for later review.
    """
    if result.is_negative_sentiment_buy:
        logger.info(
            "news_sentiment OBSERVATION symbol=%s NEGATIVE_SENTIMENT_BUY "
            "net_score=%s articles=%s | %s",
            result.symbol,
            result.net_score,
            result.article_count,
            result.reason,
        )

    if log_path is None:
        return

    out_path = Path(log_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "symbol": result.symbol,
            "is_negative_sentiment_buy": result.is_negative_sentiment_buy,
            "net_score": result.net_score,
            "positive_hits": result.positive_hits,
            "negative_hits": result.negative_hits,
            "article_count": result.article_count,
            "reason": result.reason,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(out_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        logger.warning(
            "news_sentiment: failed to write log to %s: %s", out_path, exc
        )
