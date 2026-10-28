"""Performance breakdown service.

Computes ETF vs Stock (and sector) profit factor splits from local exports.
No broker credentials required.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ETF_SYMBOLS: frozenset[str] = frozenset({
    'SHOC', 'SOXQ', 'SOXX', 'SMH', 'FTXL', 'PTF', 'SMHX', 'FRWD',
    'TTEQ', 'GTOP', 'CHPX', 'CHPS', 'PSCT', 'QTEC', 'TDIV', 'SKYY', 'QTUM',
})

SYMBOL_SECTORS: dict[str, str] = {
    'NVDA':'semis','AVGO':'semis','AMD':'semis','TSM':'semis','ASML':'semis',
    'INTC':'semis','MU':'semis','ARM':'semis','AMAT':'semis','LRCX':'semis',
    'KLAC':'semis','QCOM':'semis','MRVL':'semis','SMCI':'semis','SNPS':'semis',
    'CDNS':'semis','SOXX':'semis','SOXQ':'semis','SMH':'semis','FTXL':'semis',
    'SMHX':'semis','SHOC':'semis','CHPX':'semis','CHPS':'semis',
    'MSFT':'software','CRM':'software','NOW':'software','SNOW':'software',
    'MDB':'software','DDOG':'software','PLTR':'software','ADBE':'software',
    'ORCL':'software','PATH':'software','FICO':'software','SKYY':'software',
    'TTEQ':'software','GTOP':'software','PTF':'software','QTEC':'software',
    'PSCT':'software','TDIV':'software','FRWD':'software','IBM':'software',
    'CSCO':'software','HPE':'software','DELL':'software','HPQ':'software',
    'CIEN':'software','RBRK':'software','CRWD':'software','PANW':'software',
    'FTNT':'software','ANET':'software','NBIS':'software','CRDO':'software',
    'INTU':'software',
    'GOOGL':'internet','AMZN':'internet','META':'internet','TSLA':'internet',
    'V':'fintech','MA':'fintech',
    'QTUM':'thematic',
}


def _pf(gross_win: float, gross_loss: float) -> float | None:
    if gross_loss == 0:
        return None  # avoid inf; caller adds warning
    return round(gross_win / gross_loss, 3)


def _group_stats(trades: list[dict]) -> dict[str, Any]:
    wins   = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    gross_win  = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    total_pnl  = sum(t["pnl"] for t in trades)
    return {
        "closed_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "pnl": round(total_pnl, 2),
        "profit_factor": _pf(gross_win, gross_loss),
        "win_rate": round(len(wins) / len(trades), 4) if trades else None,
    }


def _load_trades(project_root: Path) -> tuple[list[dict], list[str]]:
    """Load closed trades from exports CSV or pnl_state fallback."""
    warnings: list[str] = []
    trades: list[dict] = []

    csv_path = project_root / "exports/closed_trades.csv"
    if csv_path.exists():
        try:
            for row in csv.DictReader(csv_path.open(encoding="utf-8")):
                pnl_raw = row.get("pnl") or row.get("realized_pnl") or "0"
                try:
                    pnl = float(pnl_raw)
                except ValueError:
                    pnl = 0.0
                trades.append({"symbol": row.get("symbol", "").upper(), "pnl": pnl})
            return trades, warnings
        except Exception as exc:
            warnings.append(f"Could not parse closed_trades.csv: {exc}")

    # Fallback: pnl_state.json
    state_path = project_root / "data/tracking/pnl_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            for t in state.get("trades", []):
                if t.get("status") == "closed":
                    trades.append({
                        "symbol": str(t.get("symbol", "")).upper(),
                        "pnl": float(t.get("pnl") or 0),
                    })
            return trades, warnings
        except Exception as exc:
            warnings.append(f"Could not parse pnl_state.json: {exc}")

    warnings.append("No closed trade data available")
    return [], warnings


def _diagnose(by_class: list[dict]) -> list[str]:
    msgs: list[str] = []
    etf = next((x for x in by_class if x["asset_class"] == "ETF"), None)
    stk = next((x for x in by_class if x["asset_class"] == "Stock"), None)
    if etf and (etf["profit_factor"] or 0) < 0.5:
        msgs.append("ETF trades are the primary source of drawdown.")
    if stk and stk["pnl"] > 0:
        msgs.append("Stock trades show positive PnL despite sub-50% win rate." if (stk["win_rate"] or 1) < 0.5
                    else "Stock trades show positive PnL.")
    if etf and stk:
        etf_pf = etf["profit_factor"] or 0
        stk_pf = stk["profit_factor"] or 0
        if stk_pf > 1.0 and etf_pf < 1.0:
            msgs.append(f"ETF guardrail recommended: ETF PF {etf_pf:.3f} vs Stock PF {stk_pf:.3f}.")
    return msgs


def get_performance_breakdown(project_root: Path) -> dict[str, Any]:
    """Return ETF/Stock/sector performance breakdown.

    Args:
        project_root: Absolute path to repo root.
    """
    trades, warnings = _load_trades(project_root)

    if not trades:
        return {"available": False, "warnings": warnings}

    etf_trades   = [t for t in trades if t["symbol"] in ETF_SYMBOLS]
    stock_trades = [t for t in trades if t["symbol"] not in ETF_SYMBOLS]

    by_class = [
        {"asset_class": "ETF",   **_group_stats(etf_trades)},
        {"asset_class": "Stock", **_group_stats(stock_trades)},
    ]

    # Sector breakdown
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        sector = SYMBOL_SECTORS.get(t["symbol"], "other")
        by_sector[sector].append(t)

    sector_rows = []
    for sector, st in sorted(by_sector.items()):
        s = _group_stats(st)
        sector_rows.append({
            "sector": sector,
            "closed_trades": s["closed_trades"],
            "pnl": s["pnl"],
            "profit_factor": s["profit_factor"],
        })
    sector_rows.sort(key=lambda x: x["pnl"])

    # Zero-loss warning
    for row in by_class + sector_rows:
        if row.get("profit_factor") is None and row.get("closed_trades", 0) > 0:
            warnings.append(
                f"{row.get('asset_class') or row.get('sector')}: "
                "no losing trades — profit_factor is null (undefined)."
            )

    return {
        "overall": _group_stats(trades),
        "by_asset_class": by_class,
        "by_sector": sector_rows,
        "diagnosis": _diagnose(by_class),
        "warnings": warnings,
    }
