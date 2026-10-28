"""Plan D follow-up (2026-08-21): held-position news-shock diagnostic
(shadow-only, observability-only).

Purpose
-------
Plan D's original news_sentiment.py (2026-08-08) only checks the news flow
for a *new* BUY candidate. That has a structural weakness discussed with the
user on 2026-08-21: by the time a symbol is a live BUY candidate (price/
momentum has already fired), any negative news driving that setup has likely
already been priced in -- the same "information already reflected in the
gap" pattern found in the Plan C (distance_from_high) 08-14 conditional-gap
analysis. A negative-news check gated on *new entries* is checking for
stale information.

This module instead applies the same lexicon/relevance/source-weighting
machinery to **currently-held open positions**, mirroring the existing
sector_shock_hold.py pattern (shadow-only regime-aware exit hint) but for an
individual-symbol news shock rather than a broad sector drawdown. News that
breaks *while a position is already held* has not necessarily been priced in
yet -- that is the scenario this diagnostic is built to catch early, as a
potential future exit-tightening signal (never as an entry filter).

Why shadow-only (never blocks or tightens an exit automatically)
------------------------------------------------------------------
Same rationale as sector_shock_hold.py, volatility_gate.py (Plan B),
distance_from_high.py (Plan C), and news_sentiment.py (Plan D): folding an
unvalidated signal directly into exit logic would silently change hold/exit
behavior for every open position with zero paper-verified evidence that
doing so improves outcomes. This module only classifies and logs held
positions whose recent news flow has turned sharply negative since the
position was likely last reviewed, for later review against actual trade
outcomes (same "shadow -> paper_ab -> active" pattern documented in
docs/console_improvement_tasks.md).

Usage (shadow mode)
--------------------
from stock_swing.risk.news_shock_hold import (
    NewsShockHoldConfig,
    classify_news_shock,
    log_shadow,
)

config = NewsShockHoldConfig.from_env()
result = classify_news_shock(
    symbol="NVDA",
    news_items=load_latest_finnhub_news("NVDA", finnhub_raw_dir),
    config=config,
    company_name="NVIDIA Corporation",
)
log_shadow(result, shadow_log_path=Path("data/news_shock_hold_shadow_log.jsonl"))
# result.is_news_shock -> True if recent news flow has turned sharply
# negative for a currently-held symbol (does not fire on new BUYs)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stock_swing.risk.news_sentiment import (
    NewsSentimentConfig,
    classify_news_sentiment,
)

logger = logging.getLogger(__name__)

# Held positions warrant a shorter lookback than fresh-BUY sentiment (Plan
# D's default 3 days): a genuinely fresh shock relevant to an *already
# open* position is more actionable within ~1 trading day of it breaking.
DEFAULT_MAX_ARTICLE_AGE_DAYS = 1
# Slightly less strict than Plan D's entry-side threshold (-0.34): this is
# an early-warning shadow diagnostic on held positions, not an entry
# gate, so a modestly negative flow is still worth logging for review.
DEFAULT_NEGATIVE_SCORE_THRESHOLD = -0.25
DEFAULT_MIN_ARTICLES_FOR_SIGNAL = 2


@dataclass
class NewsShockHoldConfig:
    """Threshold configuration for the held-position news-shock diagnostic.

    Env overrides:
        NEWS_SHOCK_HOLD_MAX_ARTICLE_AGE_DAYS  only count articles this
                                               recent (default 1)
        NEWS_SHOCK_HOLD_NEGATIVE_THRESHOLD    net score <= this flags
                                               "news_shock" (default -0.25)
        NEWS_SHOCK_HOLD_MIN_ARTICLES          minimum matched articles
                                               before flagging (default 2)
        NEWS_SHOCK_HOLD_DISABLED               set "true" to skip evaluation
    """

    max_article_age_days: int = DEFAULT_MAX_ARTICLE_AGE_DAYS
    negative_score_threshold: float = DEFAULT_NEGATIVE_SCORE_THRESHOLD
    min_articles_for_signal: int = DEFAULT_MIN_ARTICLES_FOR_SIGNAL
    disabled: bool = False

    @classmethod
    def from_env(cls) -> "NewsShockHoldConfig":
        return cls(
            max_article_age_days=int(
                os.environ.get(
                    "NEWS_SHOCK_HOLD_MAX_ARTICLE_AGE_DAYS",
                    DEFAULT_MAX_ARTICLE_AGE_DAYS,
                )
            ),
            negative_score_threshold=float(
                os.environ.get(
                    "NEWS_SHOCK_HOLD_NEGATIVE_THRESHOLD",
                    DEFAULT_NEGATIVE_SCORE_THRESHOLD,
                )
            ),
            min_articles_for_signal=int(
                os.environ.get(
                    "NEWS_SHOCK_HOLD_MIN_ARTICLES", DEFAULT_MIN_ARTICLES_FOR_SIGNAL
                )
            ),
            disabled=os.environ.get("NEWS_SHOCK_HOLD_DISABLED", "").lower()
            in ("1", "true", "yes"),
        )

    def is_enabled(self) -> bool:
        return not self.disabled


@dataclass
class NewsShockHoldResult:
    symbol: str
    is_news_shock: bool
    net_score: float | None
    article_count: int
    unrealized_plpc: float | None
    reason: str
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def classify_news_shock(
    symbol: str,
    news_items: list[dict[str, Any]] | None,
    config: NewsShockHoldConfig | None = None,
    now: datetime | None = None,
    company_name: str | None = None,
    unrealized_plpc: float | None = None,
) -> NewsShockHoldResult:
    """Classify whether a *currently held* symbol's recent news flow has
    turned sharply negative (shadow-only -- never blocks or tightens an
    exit).

    Reuses news_sentiment.classify_news_sentiment()'s relevance filtering,
    negation guard, and source-reliability weighting (same lexicon and
    logic), but with a shorter lookback window and a milder threshold
    tuned for "worth reviewing on a held position" rather than "block this
    BUY" (see module docstring for the entry-vs-hold rationale).

    Args:
        symbol: Stock symbol of the currently held position.
        news_items: Finnhub `company-news` article list (same shape as
            news_sentiment.load_latest_finnhub_news's return value).
        config: NewsShockHoldConfig (defaults to from_env()).
        now: Override "current time" for testing.
        company_name: Registry `description` field, passed through to the
            relevance filter.
        unrealized_plpc: Current unrealized return (fraction, e.g. -0.05 for
            -5%) of the held position, if available. Logged alongside the
            classification for later review (does this diagnostic correlate
            with positions that are already underwater?), never used to
            gate the classification itself.

    Returns:
        NewsShockHoldResult. `is_news_shock` flags a held position whose
        very-recent news flow has turned clearly negative.
    """
    cfg = config or NewsShockHoldConfig.from_env()
    now_dt = now or datetime.now(timezone.utc)

    if cfg.disabled:
        return NewsShockHoldResult(
            symbol=symbol,
            is_news_shock=False,
            net_score=None,
            article_count=0,
            unrealized_plpc=unrealized_plpc,
            reason="disabled",
        )

    sentiment_cfg = NewsSentimentConfig(
        max_article_age_days=cfg.max_article_age_days,
        negative_score_threshold=cfg.negative_score_threshold,
        min_articles_for_signal=cfg.min_articles_for_signal,
        disabled=False,
        relevance_filter_enabled=True,
        source_weighting_enabled=True,
    )
    sentiment_result = classify_news_sentiment(
        symbol, news_items, sentiment_cfg, now=now_dt, company_name=company_name,
    )

    reason = sentiment_result.reason.replace(
        "negative_sentiment_buy", "news_shock"
    )

    return NewsShockHoldResult(
        symbol=symbol,
        is_news_shock=sentiment_result.is_negative_sentiment_buy,
        net_score=sentiment_result.net_score,
        article_count=sentiment_result.article_count,
        unrealized_plpc=unrealized_plpc,
        reason=reason,
    )


def log_shadow(
    result: NewsShockHoldResult,
    shadow_log_path: Path | str | None = None,
) -> None:
    """Log a news-shock-hold observation (diagnostic only, never blocks or
    tightens an exit).

    Mirrors the shadow-log pattern used by news_sentiment.py / Plan B/C/E:
    always emits an INFO line when flagged, and appends a structured JSON
    record to *shadow_log_path* when provided so held-position news shocks
    accumulate for later review against actual trade outcomes (was the
    position exited later at a worse price than when the shock fired?).
    """
    if result.is_news_shock:
        logger.info(
            "news_shock_hold OBSERVATION symbol=%s NEWS_SHOCK net_score=%s "
            "articles=%s unrealized_plpc=%s | %s",
            result.symbol,
            result.net_score,
            result.article_count,
            result.unrealized_plpc,
            result.reason,
        )

    if shadow_log_path is None:
        return

    out_path = Path(shadow_log_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "symbol": result.symbol,
            "is_news_shock": result.is_news_shock,
            "net_score": result.net_score,
            "article_count": result.article_count,
            "unrealized_plpc": result.unrealized_plpc,
            "reason": result.reason,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(out_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        logger.warning(
            "news_shock_hold: failed to write log to %s: %s", out_path, exc
        )
