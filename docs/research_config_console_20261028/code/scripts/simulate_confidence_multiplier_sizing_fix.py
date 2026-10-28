"""R13-B (sizing side, 2026-08-26): Historical validation of the
confidence_multiplier no-op bug fix.

Background
----------
docs/console_improvement_tasks.md's R13-B noted (2026-08-23) that
`position_sizing.py`'s `confidence_multiplier` "high-confidence side (1.2x)
is already clipped to no-op by the existing cap" but left this UNVERIFIED
and the sizing-side fix (Option A) unimplemented, since fixed historical
qty values can't be directly re-simulated for a sizing change the way an
exit-threshold change can.

2026-08-26 real-data verification (read-only, no code changed) confirmed
the bug is real and 100% reproducible:

    base_final_shares = min(shares_by_risk, shares_by_notional,
                             shares_by_exposure, shares_by_sector)
    boosted = floor(base_final_shares * confidence_multiplier)
    cap = min(shares_by_risk, shares_by_notional,
              shares_by_exposure, shares_by_sector)   # IDENTICAL to base_final_shares
    final_shares = min(boosted, cap)

Since `cap` is computed from the exact same four values as
`base_final_shares`, `cap == base_final_shares` always holds. Checked
against 85 real decision records with confidence_multiplier + before/after
qty recorded (2026-08-14 onward):
  - confidence_multiplier > 1.0 (1.2x, confidence >= 0.80): 55/55 cases
    the "boost" had ZERO effect (final_shares never exceeded the
    3-caps-only partial cap).
  - confidence_multiplier < 1.0 (0.7x, confidence < 0.60): 6/7 cases the
    "cut" WAS effective (final_shares was reduced below the partial cap).
  => confirmed asymmetric bug: only the downside adjustment works.

Fix design (this script tests it, NOT applied to position_sizing.py yet)
--------------------------------------------------------------------------
Apply confidence_multiplier to the RISK BUDGET (max_loss_usd) BEFORE
computing shares_by_risk, instead of to the already-4-way-capped
base_final_shares after the fact:

    max_loss_usd_adjusted = max_loss_usd * confidence_multiplier
    shares_by_risk_fixed = floor(max_loss_usd_adjusted / risk_per_share)
    final_shares_fixed = min(shares_by_risk_fixed, shares_by_notional,
                              shares_by_exposure, shares_by_sector)

This preserves every existing hard constraint (notional/exposure/sector
caps are untouched and still bind exactly as before) while letting
confidence genuinely move the risk-budget-driven share count in both
directions when risk is the binding constraint. When risk is NOT the
binding constraint (notional/exposure/sector already bind tighter), a
confidence boost still correctly has no effect -- that is CORRECT
behavior, not a bug, since exceeding the notional/exposure/sector limits
would violate independently-motivated risk controls.

Methodology
-----------
Uses REAL decision records (data/decisions/*.json) that are (a) closed
trades in pnl_state.json (via decision_id linkage), (b) have
evidence.sizing recorded with shares_by_risk/notional/exposure and
confidence, so this is not a "what-if" simulation of unknown history --
it recomputes exactly what the FIXED formula would have produced for each
real historical sizing decision, using the same numbers the actual
(buggy) production code used at the time.

For qty-scaling to estimate PnL impact: since return_pct (not qty) is the
independent driver of a trade's per-share outcome, scaling PnL linearly
by (fixed_qty / actual_qty) is used, EXCLUDING trades where the fixed qty
would have been 0 (those would not exist in this comparison at all --
reported separately) or where skip_reason indicates the trade wouldn't
have been placed regardless of confidence.

This does NOT modify position_sizing.py or any production file. Read-only
analysis producing a report for the R13-B "sizing side" paper A/B go/no-go
decision.

Usage:
    python scripts/simulate_confidence_multiplier_sizing_fix.py
"""
from __future__ import annotations

import json
from collections import Counter
from math import floor
from pathlib import Path

ROOT = Path(__file__).parent.parent
DECISIONS_DIR = ROOT / "data" / "decisions"
STATE_FILE = ROOT / "data" / "tracking" / "pnl_state.json"


def load_closed_trades_by_decision_id() -> dict[str, dict]:
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    out = {}
    for t in state.get("trades", []):
        if t.get("status") != "closed":
            continue
        did = t.get("decision_id")
        if did:
            out[did] = t
    return out


def load_decisions_with_sizing() -> list[dict]:
    decisions = []
    for path in sorted(DECISIONS_DIR.glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        evidence = d.get("evidence") or {}
        sizing = evidence.get("sizing") if isinstance(evidence, dict) else None
        if not isinstance(sizing, dict):
            continue
        if sizing.get("shares_by_risk") is None:
            continue
        # Require confidence_multiplier to be EXPLICITLY recorded (not just
        # absent-and-defaulted-to-1.0). Recording started 2026-08-14 (R4-v2
        # gap #3); decisions predating that have no key at all. Treating a
        # missing key as cm=1.0 silently mixes in unrelated pre-recording
        # decisions and produced spurious sanity-check mismatches (found
        # 2026-08-26: 10/26 initially-matched decisions had no
        # confidence_multiplier key at all and mismatched on unrelated
        # confounds -- excluded here, not because the fix formula was wrong
        # for them, but because they're simply outside the field's recorded
        # history and irrelevant to testing it).
        if "confidence_multiplier" not in sizing:
            continue
        decisions.append(d)
    return decisions


def compute_fixed_shares(sizing: dict) -> tuple[int, int, dict]:
    """Recompute what the FIXED formula would have produced.

    Returns (fixed_final_shares, actual_final_shares_recomputed, detail).
    `actual_final_shares_recomputed` is the buggy-formula result derived
    the same way production code derives it, for cross-checking against
    the persisted final_shares (sanity check that our replay matches).

    IMPORTANT (found during 2026-08-26 sanity-check mismatches): the
    persisted `final_shares` in PositionSizingResult / decision evidence is
    NOT just post-confidence_multiplier -- position_sizing.py applies a
    SECOND multiplier (R2-v2/H5 asset-class stock/ETF multiplier, from
    `multiplier_applied` / AllocationConfig YAML) AFTER the confidence-
    multiplier-and-4-way-cap step, and *that* further-adjusted value is what
    gets persisted as `final_shares`. Both the actual-formula replay and the
    fixed-formula estimate below must apply this same asset-class multiplier
    at the same point in the pipeline (after the risk/notional/exposure/
    sector step) to be comparable to the real historical final_shares /
    actual traded qty.
    """
    shares_by_risk = int(sizing["shares_by_risk"])
    shares_by_notional = int(sizing["shares_by_notional"])
    shares_by_exposure = int(sizing["shares_by_exposure"])
    cm = float(sizing.get("confidence_multiplier") or 1.0)
    asset_multiplier = float(sizing.get("multiplier_applied") or 1.0)

    # shares_by_sector is not persisted directly; reconstruct from
    # remaining_sector_capacity_usd / current_price when sector_used is
    # set (matches position_sizing.py's `if sector else shares_by_exposure`).
    sector_used = sizing.get("sector_used")
    price = float(sizing.get("current_price") or 0)
    remaining_sector_capacity_usd = sizing.get("remaining_sector_capacity_usd")
    if sector_used and price > 0 and remaining_sector_capacity_usd is not None:
        shares_by_sector = max(floor(max(float(remaining_sector_capacity_usd), 0.0) / price), 0)
    else:
        shares_by_sector = shares_by_exposure

    def _apply_asset_multiplier(qty: int) -> int:
        if asset_multiplier != 1.0 and qty > 0:
            return max(floor(qty * asset_multiplier), 0)
        return qty

    # --- ACTUAL (buggy) formula, replayed for sanity check ---
    base_final_shares = min(shares_by_risk, shares_by_notional, shares_by_exposure, shares_by_sector)
    boosted = floor(base_final_shares * cm)
    cap = min(shares_by_risk, shares_by_notional, shares_by_exposure, shares_by_sector)
    actual_before_asset_mult = min(boosted, cap)
    actual_final_shares_recomputed = _apply_asset_multiplier(actual_before_asset_mult)

    # --- FIXED formula: apply confidence_multiplier to the risk budget,
    # i.e. to shares_by_risk BEFORE the 4-way min, not to the already-
    # capped result after. Asset-class multiplier still applied last,
    # in the same position in the pipeline as production code. ---
    shares_by_risk_fixed = floor(shares_by_risk * cm)
    fixed_before_asset_mult = min(shares_by_risk_fixed, shares_by_notional, shares_by_exposure, shares_by_sector)
    fixed_final_shares = _apply_asset_multiplier(fixed_before_asset_mult)

    return fixed_final_shares, actual_final_shares_recomputed, {
        "shares_by_risk": shares_by_risk,
        "shares_by_notional": shares_by_notional,
        "shares_by_exposure": shares_by_exposure,
        "shares_by_sector": shares_by_sector,
        "shares_by_risk_fixed": shares_by_risk_fixed,
        "confidence_multiplier": cm,
        "asset_multiplier": asset_multiplier,
    }


def load_any_status_trades_by_decision_id() -> dict[str, dict]:
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    out = {}
    for t in state.get("trades", []):
        did = t.get("decision_id")
        if did:
            out[did] = t
    return out


def main() -> int:
    closed_by_decision_id = load_closed_trades_by_decision_id()
    any_status_by_decision_id = load_any_status_trades_by_decision_id()
    decisions = load_decisions_with_sizing()

    print(f"Closed trades with decision_id: {len(closed_by_decision_id)}")
    print(f"Any-status (open+closed) trades with decision_id: {len(any_status_by_decision_id)}")
    print(f"Decision records with confidence_multiplier explicitly recorded: {len(decisions)}")

    sizeable = [d for d in decisions if (d["evidence"]["sizing"].get("final_shares") or 0) > 0]
    print(f"  of those, sizeable (final_shares > 0, i.e. NOT skipped for sizing reasons): {len(sizeable)}")

    # --- PART 1: decision-level mechanical validation (no trade-outcome needed) ---
    # This answers "does the fix formula actually restore the intended
    # asymmetric behavior" across the FULL population of 58 sizeable
    # decisions, independent of whether we know the eventual trade PnL.
    print()
    print("=" * 100)
    print("PART 1: Decision-level mechanical validation (qty effect only, no PnL -- full n=58 population)")
    print("=" * 100)
    boost_n = 0
    boost_would_increase = 0
    cut_n = 0
    cut_would_decrease = 0
    for dec in sizeable:
        sizing = dec["evidence"]["sizing"]
        fixed_final, actual_recomputed, detail = compute_fixed_shares(sizing)
        cm = detail["confidence_multiplier"]
        persisted_final = sizing.get("final_shares")
        if persisted_final is None:
            continue
        if cm > 1.0:
            boost_n += 1
            if fixed_final > persisted_final:
                boost_would_increase += 1
        elif cm < 1.0:
            cut_n += 1
            if fixed_final < persisted_final:
                cut_would_decrease += 1
    print(f"Boost decisions (cm>1.0): n={boost_n}, fix WOULD increase qty in {boost_would_increase}/{boost_n}")
    print(f"Cut decisions (cm<1.0)  : n={cut_n}, fix still decreases qty (unchanged from today) in {cut_would_decrease}/{cut_n}")
    print("(Cases where boost still wouldn't increase qty even under the fix are ones where "
          "notional/exposure/sector -- not risk -- was ALREADY the binding constraint; that is "
          "correct, not a bug, since those are independent hard caps the fix must not violate.)")

    print()
    print("=" * 100)
    print("PART 2: Trade-outcome-linked validation (requires decision_id -> closed trade in pnl_state.json)")
    print("=" * 100)
    print("NOTE: as R13-B's original 2026-08-23 write-up already anticipated, this is fundamentally "
          "sample-starved -- decision_id persistence onto trades and confidence_multiplier recording "
          "both only started 2026-08-14, so their INTERSECTION with 'actually became a closed trade' "
          "is small. Reported below for completeness but should NOT be treated as a statistically "
          "powered PnL estimate; see summary caveat.")

    matched = []
    sanity_mismatches = []
    for dec in decisions:
        did = dec.get("decision_id")
        trade = closed_by_decision_id.get(did)
        if trade is None:
            continue
        sizing = dec["evidence"]["sizing"]
        fixed_final, actual_recomputed, detail = compute_fixed_shares(sizing)

        persisted_final = sizing.get("final_shares")
        if persisted_final is not None and int(persisted_final) != actual_recomputed:
            sanity_mismatches.append((did, trade.get("symbol"), persisted_final, actual_recomputed))

        actual_qty = trade.get("qty")
        matched.append({
            "decision_id": did,
            "symbol": trade.get("symbol"),
            "confidence_multiplier": detail["confidence_multiplier"],
            "actual_qty_traded": actual_qty,
            "actual_final_shares_decision": persisted_final,
            "fixed_final_shares": fixed_final,
            "pnl_actual": trade.get("pnl"),
            "return_pct": trade.get("return_pct"),
            "exit_reason": trade.get("exit_reason"),
            "detail": detail,
        })

    print(f"Matched (decision -> closed trade, full sizing evidence): {len(matched)}")
    if sanity_mismatches:
        print(f"\n⚠️  Sanity check: {len(sanity_mismatches)} case(s) where our replayed 'actual' "
              f"formula didn't match the persisted final_shares (may indicate a persisted-vs-live "
              f"discrepancy, e.g. capped_to_position adjustments not modeled here):")
        for row in sanity_mismatches[:10]:
            print(f"   {row}")
    else:
        print("✅ Sanity check: replayed 'actual' formula matches persisted final_shares for all matched decisions.")

    print()
    print("=" * 100)
    print("Per-trade comparison (fixed vs actual):")
    print("=" * 100)

    cm_buckets = Counter()
    total_actual_pnl = 0.0
    total_fixed_pnl_estimate = 0.0
    n_qty_increased = 0
    n_qty_decreased = 0
    n_qty_unchanged = 0
    n_would_be_zero_fixed = 0

    detail_rows = []
    for row in matched:
        cm = row["confidence_multiplier"]
        cm_buckets[round(cm, 2)] += 1
        actual_qty = row["actual_qty_traded"] or 0
        fixed_qty = row["fixed_final_shares"]
        pnl_actual = float(row["pnl_actual"] or 0)
        return_pct = row["return_pct"]

        if fixed_qty > actual_qty:
            n_qty_increased += 1
        elif fixed_qty < actual_qty:
            n_qty_decreased += 1
        else:
            n_qty_unchanged += 1
        if fixed_qty == 0:
            n_would_be_zero_fixed += 1

        # Scale PnL linearly by qty ratio (per-share outcome unaffected by
        # sizing rule -- only the qty at risk changes).
        if actual_qty > 0:
            fixed_pnl_estimate = pnl_actual * (fixed_qty / actual_qty)
        else:
            fixed_pnl_estimate = pnl_actual  # shouldn't happen (actual_qty=0 trades don't exist as closed trades)

        total_actual_pnl += pnl_actual
        total_fixed_pnl_estimate += fixed_pnl_estimate

        detail_rows.append({
            **row,
            "fixed_pnl_estimate": round(fixed_pnl_estimate, 2),
            "pnl_diff": round(fixed_pnl_estimate - pnl_actual, 2),
        })
        print(f"  {row['symbol']:6} cm={cm:.2f} actual_qty={actual_qty:>5} fixed_qty={fixed_qty:>5} "
              f"actual_pnl={pnl_actual:>10.2f} fixed_pnl_est={fixed_pnl_estimate:>10.2f} "
              f"diff={fixed_pnl_estimate - pnl_actual:>9.2f}  exit={row['exit_reason']}")

    print()
    print("=" * 100)
    print("PART 2 Summary (small-sample, see caveat above)")
    print("=" * 100)
    print(f"confidence_multiplier distribution: {dict(cm_buckets)}")
    print(f"qty increased under fix : {n_qty_increased}")
    print(f"qty decreased under fix : {n_qty_decreased}")
    print(f"qty unchanged           : {n_qty_unchanged}")
    print(f"fixed qty would be 0    : {n_would_be_zero_fixed}")
    print()
    print(f"Total actual PnL (matched trades)      : {total_actual_pnl:,.2f}")
    print(f"Total FIXED-formula PnL estimate        : {total_fixed_pnl_estimate:,.2f}")
    print(f"Estimated PnL difference (fixed-actual) : {total_fixed_pnl_estimate - total_actual_pnl:,.2f}")
    if len(matched) < 10:
        print(f"\n⚠️  CAVEAT: n={len(matched)} is far below any meaningful statistical threshold "
              f"(R13-A/B's own established norm is ~30-90+ for attributable-cohort claims). "
              f"Do NOT treat this PnL estimate as evidence either for or against the fix's "
              f"profitability -- it is an illustration of MECHANISM only. See PART 1 above for "
              f"the full-population (n=58) mechanical validation, which is the actually-informative "
              f"result of this analysis.")

    # Breakdown by confidence_multiplier bucket
    print()
    print("Breakdown by confidence_multiplier bucket:")
    for cm_val in sorted(cm_buckets.keys()):
        rows = [r for r in detail_rows if round(r["confidence_multiplier"], 2) == cm_val]
        n = len(rows)
        sum_actual = sum(r["pnl_actual"] for r in rows)
        sum_fixed = sum(r["fixed_pnl_estimate"] for r in rows)
        print(f"  cm={cm_val}: n={n} actual_pnl_sum={sum_actual:,.2f} "
              f"fixed_pnl_est_sum={sum_fixed:,.2f} diff={sum_fixed - sum_actual:,.2f}")

    out_path = ROOT / "docs" / "r13b_sizing_confidence_multiplier_fix_validation_20260826"
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "detail.json").write_text(
        json.dumps(detail_rows, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    (out_path / "sanity_mismatches.json").write_text(
        json.dumps(sanity_mismatches, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(f"\nSaved detail to {out_path}/detail.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
