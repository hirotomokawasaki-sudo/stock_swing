#!/usr/bin/env python3
"""G5: Backfill AI/token telemetry into existing decision JSON files.

For rule-based decisions (model=rule-based), estimates telemetry using
the same logic as attach_ai_telemetry() and re-saves decision JSONs.
Also writes ai_usage/usage.jsonl compatible output.

Usage:
    python3 scripts/g5_backfill_decision_telemetry.py [--dry-run]
"""
import argparse, glob, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DECISIONS_DIR = PROJECT_ROOT / "data/decisions"
# 2026-08-01: removed TOKEN_USAGE_CSV constant (pointed at the live tracker's
# file with an incompatible schema). See BACKFILL_CSV below for this script's
# own dedicated output file.


def _tok(obj) -> int:
    """Estimate token count as len(json) / 4."""
    try:
        return max(1, len(json.dumps(obj, ensure_ascii=False, default=str)) // 4)
    except Exception:
        return 0


def compute_telemetry(doc: dict) -> dict:
    """Compute telemetry for a rule-based decision document."""
    strategy_id = doc.get("strategy_id", "rule-based")
    model = f"rule_based:{strategy_id}"
    evidence = doc.get("evidence", {}) or {}
    input_tokens = _tok(evidence)
    output_payload = {
        "action": doc.get("action"),
        "confidence": doc.get("confidence"),
        "signal_strength": doc.get("signal_strength"),
        "deny_reasons": doc.get("deny_reasons", []),
    }
    output_tokens = _tok(output_payload)
    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "context_pack": "evidence_v1",
        "telemetry_source": "estimated_rule_based",
        "telemetry_status": "legacy_backfill",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated without writing")
    args = parser.parse_args()

    files = sorted(glob.glob(str(DECISIONS_DIR / "*.json")))
    print(f"=== G5: Decision Telemetry Backfill ===")
    print(f"  Decision files: {len(files)}")
    print(f"  Mode: {'dry-run' if args.dry_run else 'WRITE'}")

    already_ok = 0
    updated = 0
    failed = 0
    usage_rows = []

    for f in files:
        try:
            with open(f, encoding="utf-8") as fp:
                doc = json.load(fp)

            # Skip if already has real telemetry (model not null and not legacy)
            if doc.get("model") and doc.get("input_tokens"):
                already_ok += 1
                continue

            telem = compute_telemetry(doc)
            doc.update(telem)

            if not args.dry_run:
                tmp = Path(f).with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as fp:
                    json.dump(doc, fp, indent=2, ensure_ascii=False, default=str)
                os.replace(tmp, f)

            usage_rows.append({
                "timestamp": doc.get("generated_at", ""),
                "symbol": doc.get("symbol", ""),
                "action": doc.get("action", ""),
                "model": telem["model"],
                "input_tokens": telem["input_tokens"],
                "output_tokens": telem["output_tokens"],
                "total_tokens": telem["total_tokens"],
                "context_pack": telem["context_pack"],
                "decision_id": doc.get("decision_id", ""),
                "run_id": doc.get("run_id", ""),
                "experiment_id": doc.get("experiment_id", ""),
                "telemetry_source": telem["telemetry_source"],
            })
            updated += 1

        except Exception as e:
            failed += 1
            print(f"  ⚠️  {Path(f).name}: {e}")

    print(f"  Already had telemetry: {already_ok}")
    print(f"  Updated: {updated}")
    print(f"  Failed: {failed}")

    # Write usage.jsonl
    if usage_rows and not args.dry_run:
        usage_out = PROJECT_ROOT / "data/analysis/ai_usage.jsonl"
        with open(usage_out, "w", encoding="utf-8") as fp:
            for row in usage_rows:
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"  Usage JSONL: {usage_out} ({len(usage_rows)} rows)")

        # 2026-08-01 fix: this backfill schema (decision_id/symbol/context_pack/
        # telemetry_source) is NOT compatible with TokenUsageTracker.flush()'s live
        # schema (success/retry_count/error/skip_reason) in context_budget.py.
        # Appending backfill rows directly into token_usage.csv previously produced
        # a file where column 8-11 meant different things depending on which row
        # you were looking at (1939 backfill-schema rows silently mixed with
        # tracker-schema rows under one header). Write backfill rows to their own
        # dedicated file instead so token_usage.csv stays single-schema.
        BACKFILL_CSV = PROJECT_ROOT / "data/analysis/token_usage_backfill.csv"
        import csv
        csv_exists = BACKFILL_CSV.exists()
        with open(BACKFILL_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if not csv_exists:
                w.writerow(["timestamp", "workflow_name", "model", "input_tokens",
                            "output_tokens", "total_tokens", "estimated_cost",
                            "decision_id", "symbol", "context_pack", "telemetry_source"])
            for row in usage_rows:
                w.writerow([
                    row["timestamp"], "paper_demo_backfill", row["model"],
                    row["input_tokens"], row["output_tokens"], row["total_tokens"],
                    0.0, row["decision_id"], row["symbol"], row["context_pack"],
                    row["telemetry_source"],
                ])
        print(f"  Token usage backfill CSV: {BACKFILL_CSV} ({len(usage_rows)} rows appended)")

    print(f"\n  ✅ Done. New decisions will have real telemetry after next paper_demo run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
