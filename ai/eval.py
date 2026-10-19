"""Score each model's extractions against your hand labels and report accuracy vs cost.

Run from the repo root after labeling and extracting:
    python ai/eval.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    EVAL_CSV, EXTRACTIONS_CSV, LABELS_CSV, MISSES_CSV, MODELS_CSV, QUESTIONS, ROOT, read_csv, write_csv,
)


def main() -> None:
    labels = {r["ticker"]: r for r in read_csv(LABELS_CSV)}
    if not labels:
        raise SystemExit("No labels yet. Run: streamlit run ai/label_app.py")
    extractions = read_csv(EXTRACTIONS_CSV)
    if not extractions:
        raise SystemExit("No extractions yet. Run: python ai/extract.py --tier all --labeled")

    report, misses = [], []
    for m in read_csv(MODELS_CSV):
        rows = [r for r in extractions if r["model"] == m["model"] and r["ticker"] in labels]
        if not rows:
            continue
        right = {q: 0 for q in QUESTIONS}
        for r in rows:
            for q in QUESTIONS:
                if r[q] == labels[r["ticker"]][q]:
                    right[q] += 1
                else:
                    misses.append({"model": m["model"], "ticker": r["ticker"], "question": q,
                                   "your_label": labels[r["ticker"]][q], "model_answer": r[q],
                                   "model_rationale": r["rationale"]})
        n = len(rows)
        cost = sum(float(r["cost_usd"]) for r in rows)
        report.append({
            "tier": m["tier"], "model": m["model"], "filings": n,
            "correct": sum(right.values()), "answers": n * len(QUESTIONS),
            "accuracy_pct": round(sum(right.values()) / (n * len(QUESTIONS)) * 100, 1),
            **{f"{q}_pct": round(right[q] / n * 100, 1) for q in QUESTIONS},
            "quote_found_pct": round(sum(r["quote_found"] == "True" for r in rows) / n * 100, 1),
            "cost_per_filing_usd": round(cost / n, 5),
            "total_cost_usd": round(cost, 4),
            "avg_latency_s": round(sum(float(r["latency_s"]) for r in rows) / n, 1),
        })

    if not report:
        raise SystemExit("No extractions for labeled companies yet.")
    cheapest = min(r["cost_per_filing_usd"] for r in report) or 1e-9
    best = max(r["accuracy_pct"] for r in report)
    for r in report:
        r["cost_vs_cheapest_x"] = round(r["cost_per_filing_usd"] / cheapest, 1)
        r["points_behind_best"] = round(best - r["accuracy_pct"], 1)

    write_csv(EVAL_CSV, report, list(report[0]))
    write_csv(MISSES_CSV, misses, ["model", "ticker", "question", "your_label", "model_answer", "model_rationale"])

    print(f"\nAccuracy vs cost on {len(labels)} labeled companies ({len(labels) * len(QUESTIONS)} answers each)\n")
    print(f"{'tier':<6} {'model':<24} {'accuracy':>8} {'behind best':>11} {'quotes real':>11} "
          f"{'$/filing':>9} {'x cheapest':>10} {'secs':>5}")
    for r in report:
        print(f"{r['tier']:<6} {r['model']:<24} {r['accuracy_pct']:>7.1f}% {r['points_behind_best']:>10.1f}pt "
              f"{r['quote_found_pct']:>10.0f}% {r['cost_per_filing_usd']:>9.5f} {r['cost_vs_cheapest_x']:>9.1f}x "
              f"{r['avg_latency_s']:>5.1f}")
    print("\nBy question:")
    for r in report:
        print(f"   {r['model']:<24} " + "  ".join(f"{q} {r[f'{q}_pct']:.0f}%" for q in QUESTIONS))
    print(f"\nSaved {EVAL_CSV.relative_to(ROOT)} and {len(misses)} misses to {MISSES_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
