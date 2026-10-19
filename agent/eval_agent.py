"""Score the agent on agent/test_questions.yml.

Run from the repo root:
    python agent/eval_agent.py
    python agent/eval_agent.py --ids 3 7     # rerun specific questions
"""

import argparse
import csv
import math
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent import MODEL, ROOT, Agent  # noqa: E402

QUESTIONS = Path(__file__).resolve().parent / "test_questions.yml"
REPORT = ROOT / "data" / "ai" / "agent_eval.csv"


def flat(rows: list[tuple]) -> list:
    out = []
    for r in rows:
        for v in r:
            if isinstance(v, Decimal):
                v = float(v)
            if isinstance(v, (date, datetime)):
                v = v.isoformat()[:10]
            out.append(v)
    return out


def same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        for scale in (1, 1e3, 1e6, 1e9, 1e-3, 1e-6, 1e-9):
            x = b * scale
            if math.isclose(a, x, rel_tol=0.002, abs_tol=0.06):
                return True
        return False
    return str(a).strip().lower() == str(b).strip().lower()


def score(gold_rows: list[tuple], agent_rows: list[tuple]) -> tuple[bool, str]:
    if len(agent_rows) != len(gold_rows):
        return False, f"{len(agent_rows)} rows, expected {len(gold_rows)}"
    have = flat(agent_rows)
    missing = [g for g in flat(gold_rows) if g is not None and not any(same(h, g) for h in have)]
    return (not missing), ("" if not missing else f"missing {missing[:3]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", type=int)
    args = ap.parse_args()

    tests = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    if args.ids:
        tests = [t for t in tests if t["id"] in args.ids]
    agent = Agent()
    results, total_cost = [], 0.0
    for t in tests:
        gold = agent.db.sql(t["gold_sql"]).fetchall()
        r = agent.ask(t["question"])
        ok, why = (False, f"error: {r['error']}") if r["error"] else score(gold, r["rows"])
        total_cost += r["cost_usd"]
        results.append({"id": t["id"], "question": t["question"], "passed": ok, "reason": why,
                        "expected": flat(gold)[:30], "agent_answer": r["answer"], "agent_sql": r["sql"],
                        "cost_usd": round(r["cost_usd"], 6), "seconds": r["seconds"]})
        print(f"{'PASS' if ok else 'FAIL'}  Q{t['id']:<2} {t['question']}")
        if not ok:
            print(f"        {why}; expected {flat(gold)[:6]}")
            print(f"        agent SQL: {' '.join(r['sql'].split())[:200]}")

    passed = sum(r["passed"] for r in results)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0]))
        w.writeheader()
        w.writerows(results)
    print(f"\nScore: {passed}/{len(results)} with {MODEL} | total cost ${total_cost:.4f} "
          f"| ${total_cost / len(results):.5f} per question")
    print(f"Saved {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
