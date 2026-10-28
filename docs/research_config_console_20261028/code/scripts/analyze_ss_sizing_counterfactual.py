#!/usr/bin/env python3
"""R13-B1: entry_signal_strength 帯域縮小サイジングの反実仮想分析（読み取り専用）.

背景（docs/console_improvement_tasks.md R13-B、2026-09-05時点）:
signal_strength と実現PnLの関係は非単調で、高スコア帯（おおむね0.85-1.00、
ちょうど1.00を除く）に損失が集中している疑いがある。本スクリプトは
「高スコア帯のエントリーをサイズ縮小していたら実績はどう変わったか」を
一次近似（PnL線形スケール）で測定する。

反実仮想ルール:
  バンド B ∈ {[0.85,1.0), [0.88,1.0), [0.90,1.0)} × 縮小率 f ∈ {0.5, 0.0}
  entry_signal_strength ∈ B の closed トレードの PnL を pnl×f に置換。
  entry_signal_strength == 1.0 ちょうどはフルサイズ維持（バンドは全て
  1.0 を含まない半開区間）。バンド外・ss なしトレードは無変更。

一次近似の限界（重要、summary.md にも明記）:
  - PnL×f の線形スケールは「同じエントリー/イグジットで株数だけ f 倍」の近似。
    実際のサイジング変更は資金再配分（浮いた資金が他トレードのサイズ・
    exposure cap・sector cap 判定を変える）と複利効果を通じて他トレードの
    PnL も変えるが、それらは一切考慮しない。
  - f=0（エントリー自体をスキップ）でも、そのトレードが存在しないことによる
    ポートフォリオ構成・guardrail 状態の変化は考慮しない。
  - 対象は entry_signal_strength が記録された closed トレードのみ（記録は
    バックフィル由来を含む）。記録なしの closed トレードは母集団外。

出力: バンド×縮小率×コホート（全期間 / exit>=2026-07-16）ごとの
  Net PnL 差 / PF 前後 / 影響件数（勝ち・負け内訳＝機会損失の明示）。
  --json PATH で per-trade 詳細を JSON 保存。

読み取り専用: data/tracking/pnl_state.json を読むのみ。本番設定・戦略
挙動・台帳への書き込みは一切行わない。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PNL_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "tracking" / "pnl_state.json"

BANDS = [
    ("[0.85,1.00)", 0.85),
    ("[0.88,1.00)", 0.88),
    ("[0.90,1.00)", 0.90),
]
FACTORS = [0.5, 0.0]
RECENT_COHORT_START = "2026-07-16"


def profit_factor(pnls: list[float]) -> float | None:
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)
    if gross_loss <= 0:
        return None
    return gross_win / gross_loss


def fmt_pf(pf: float | None) -> str:
    return f"{pf:.3f}" if pf is not None else "inf"


def load_ss_trades(path: Path) -> list[dict]:
    state = json.loads(path.read_text())
    closed = [t for t in state["trades"] if t.get("status") == "closed"]
    ss_trades = [t for t in closed if t.get("entry_signal_strength") is not None]
    return ss_trades


def analyze_cohort(trades: list[dict], label: str, results: dict) -> None:
    pnls = [t["pnl"] for t in trades]
    base_net = sum(pnls)
    base_pf = profit_factor(pnls)
    print(f"\n=== コホート: {label} (n={len(trades)}) ===")
    print(f"baseline: net ${base_net:,.2f} / PF {fmt_pf(base_pf)}")
    header = (
        f"{'band':<12} {'f':>4} {'affected':>8} {'aff_win(n/$)':>16} "
        f"{'aff_loss(n/$)':>17} {'net_diff':>12} {'PF before→after':>18}"
    )
    print(header)
    print("-" * len(header))
    cohort_out = {
        "label": label,
        "n": len(trades),
        "baseline_net": round(base_net, 2),
        "baseline_pf": base_pf,
        "variants": [],
    }
    for band_label, lo in BANDS:
        in_band = [t for t in trades if lo <= t["entry_signal_strength"] < 1.0]
        for f in FACTORS:
            cf_pnls = [
                t["pnl"] * f if lo <= t["entry_signal_strength"] < 1.0 else t["pnl"]
                for t in trades
            ]
            cf_net = sum(cf_pnls)
            cf_pf = profit_factor(cf_pnls)
            wins = [t for t in in_band if t["pnl"] > 0]
            losses = [t for t in in_band if t["pnl"] < 0]
            win_sum = sum(t["pnl"] for t in wins)
            loss_sum = sum(t["pnl"] for t in losses)
            diff = cf_net - base_net
            print(
                f"{band_label:<12} {f:>4.1f} {len(in_band):>8} "
                f"{len(wins):>4}/${win_sum:>9,.0f} "
                f"{len(losses):>4}/${loss_sum:>10,.0f} "
                f"{diff:>+12,.0f} "
                f"{fmt_pf(base_pf):>8}→{fmt_pf(cf_pf)}"
            )
            cohort_out["variants"].append(
                {
                    "band": band_label,
                    "band_lo": lo,
                    "factor": f,
                    "affected_n": len(in_band),
                    "affected_wins_n": len(wins),
                    "affected_wins_pnl": round(win_sum, 2),
                    "affected_losses_n": len(losses),
                    "affected_losses_pnl": round(loss_sum, 2),
                    "cf_net": round(cf_net, 2),
                    "net_diff": round(diff, 2),
                    "pf_before": base_pf,
                    "pf_after": cf_pf,
                    "affected_trades": [
                        {
                            "trade_id": t["trade_id"],
                            "symbol": t["symbol"],
                            "ss": t["entry_signal_strength"],
                            "pnl": t["pnl"],
                            "exit_time": t.get("exit_time"),
                            "exit_reason": t.get("exit_reason"),
                        }
                        for t in sorted(in_band, key=lambda x: x["pnl"])
                    ],
                }
            )
    results["cohorts"].append(cohort_out)


def print_reference_distribution(trades: list[dict]) -> None:
    """再計算した分布の参考表示（過去引用値との突き合わせ用）。"""
    print("\n=== 参考: entry_signal_strength 分布の再計算（2026-09-05時点データ） ===")
    exactly_one = [t for t in trades if t["entry_signal_strength"] == 1.0]
    print(
        f"ss==1.00 ちょうど: n={len(exactly_one)} / "
        f"net ${sum(t['pnl'] for t in exactly_one):,.2f}"
    )
    for band_label, lo in BANDS:
        in_band = [t for t in trades if lo <= t["entry_signal_strength"] < 1.0]
        print(
            f"ss∈{band_label}: n={len(in_band)} / "
            f"net ${sum(t['pnl'] for t in in_band):,.2f}"
        )
    # 件数5分位（sort順、同値は下位分位優先）
    ordered = sorted(trades, key=lambda t: t["entry_signal_strength"])
    n = len(ordered)
    print("件数5分位（sort順）:")
    for q in range(5):
        seg = ordered[q * n // 5 : (q + 1) * n // 5]
        pnl = sum(t["pnl"] for t in seg)
        print(
            f"  Q{q+1} [{seg[0]['entry_signal_strength']:.4f}, "
            f"{seg[-1]['entry_signal_strength']:.4f}] n={len(seg)} "
            f"net ${pnl:,.2f} avg ${pnl/len(seg):,.0f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pnl-state", type=Path, default=PNL_STATE_PATH)
    parser.add_argument("--json", type=Path, help="per-trade詳細のJSON保存先")
    args = parser.parse_args()

    trades = load_ss_trades(args.pnl_state)
    print(f"entry_signal_strength 付き closed トレード: {len(trades)}件")
    print_reference_distribution(trades)

    results: dict = {"generated_from": str(args.pnl_state), "cohorts": []}
    analyze_cohort(trades, "全期間", results)
    recent = [t for t in trades if (t.get("exit_time") or "") >= RECENT_COHORT_START]
    analyze_cohort(recent, f"exit>={RECENT_COHORT_START}", results)

    print(
        "\n注意: PnL×f の一次近似（資金再配分・複利効果・guardrail/cap 相互作用は"
        "無視）。詳細はスクリプト docstring / summary.md 参照。"
    )

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"JSON保存: {args.json}")


if __name__ == "__main__":
    main()
