"""Correlation cluster risk cap (P4-B).

Groups symbols into correlation clusters and enforces a max
notional exposure cap per cluster to prevent concentration risk.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Predefined correlation clusters.
# Each cluster groups symbols whose returns are highly correlated.
# ETFs and underlying stocks are grouped together.
CLUSTERS: dict[str, list[str]] = {
    "semis_us": [
        "NVDA", "AMD", "INTC", "MU", "QCOM", "MRVL",
        "AMAT", "LRCX", "KLAC", "ARM", "SNPS", "CDNS",
    ],
    "semis_etf": [
        "SOXX", "SOXQ", "SMH", "FTXL", "SMHX",
        "CHPX", "CHPS",
    ],
    "semis_combined": [
        "NVDA", "AMD", "INTC", "MU", "QCOM", "MRVL",
        "AMAT", "LRCX", "KLAC", "ARM", "SNPS", "CDNS",
        "SOXX", "SOXQ", "SMH", "FTXL", "SMHX", "CHPX", "CHPS",
    ],
    "cloud_software": [
        "MSFT", "CRM", "NOW", "SNOW", "DDOG", "MDB",
        "PLTR", "ADBE", "ORCL", "PATH", "FICO",
    ],
    "hyperscale": ["NVDA", "MSFT", "GOOGL", "AMZN", "META"],
    "cybersecurity": ["CRWD", "PANW", "FTNT", "RBRK"],
}

# Default cluster caps as fraction of account equity
DEFAULT_CLUSTER_CAPS: dict[str, float] = {
    "semis_combined": 0.40,
    "semis_us": 0.30,
    "semis_etf": 0.15,
    "cloud_software": 0.35,
    "hyperscale": 0.35,
    "cybersecurity": 0.20,
}


@dataclass
class ClusterExposure:
    cluster_name: str
    symbols: list[str]
    current_notional: float
    cap_notional: float
    cap_pct: float
    over_cap: bool
    utilization_pct: float


def get_cluster_for_symbol(symbol: str) -> list[str]:
    """Return all cluster names that contain this symbol."""
    return [name for name, members in CLUSTERS.items() if symbol.upper() in members]


def compute_cluster_exposures(
    positions: list[dict[str, Any]],
    account_equity: float,
    cluster_caps: dict[str, float] | None = None,
) -> list[ClusterExposure]:
    """Compute current exposure per cluster and flag over-cap clusters."""
    caps = cluster_caps or DEFAULT_CLUSTER_CAPS
    cluster_notional: dict[str, float] = {name: 0.0 for name in CLUSTERS}

    for pos in positions:
        sym = str(pos.get("symbol", "")).upper()
        try:
            mv = float(pos.get("market_value") or pos.get("current_price", 0)) * float(
                pos.get("qty") or pos.get("quantity", 1)
            )
            if "market_value" in pos:
                mv = float(pos["market_value"])
        except (TypeError, ValueError):
            mv = 0.0
        for cluster_name in get_cluster_for_symbol(sym):
            cluster_notional[cluster_name] = cluster_notional.get(cluster_name, 0.0) + mv

    result = []
    for cluster_name, cap_pct in caps.items():
        notional = cluster_notional.get(cluster_name, 0.0)
        cap_notional = account_equity * cap_pct
        over = notional > cap_notional
        util = (notional / cap_notional * 100) if cap_notional > 0 else 0.0
        result.append(
            ClusterExposure(
                cluster_name=cluster_name,
                symbols=CLUSTERS.get(cluster_name, []),
                current_notional=round(notional, 2),
                cap_notional=round(cap_notional, 2),
                cap_pct=cap_pct,
                over_cap=over,
                utilization_pct=round(util, 1),
            )
        )
    return result


def is_buy_blocked_by_cluster_cap(
    symbol: str,
    positions: list[dict[str, Any]],
    account_equity: float,
    cluster_caps: dict[str, float] | None = None,
) -> tuple[bool, str]:
    """Return (blocked, reason) for a proposed BUY of symbol.

    Blocked if adding any amount would push ANY cluster over cap
    (conservative: block if already at or over cap).
    """
    exposures = compute_cluster_exposures(positions, account_equity, cluster_caps)
    sym_clusters = get_cluster_for_symbol(symbol)
    for exp in exposures:
        if exp.cluster_name in sym_clusters and exp.over_cap:
            return True, (
                f"cluster_cap_exceeded: {exp.cluster_name} "
                f"${exp.current_notional:,.0f} >= cap ${exp.cap_notional:,.0f} "
                f"({exp.utilization_pct:.0f}% of {exp.cap_pct:.0%} limit)"
            )
    return False, ""
