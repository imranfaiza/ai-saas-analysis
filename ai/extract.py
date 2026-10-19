"""Run Gemini over each company's latest 10-K margin text and log tokens + cost per call.

Run from the repo root (needs GEMINI_API_KEY in .env):
    python ai/extract.py --list-models              # check which model names your key can use
    python ai/extract.py --tier cheap --labeled     # 10 labeled companies, cheap model
    python ai/extract.py --tier all --labeled       # all three models on the labeled companies
    python ai/extract.py --tier cheap               # all 25 companies

Results are cached in data/ai/extractions.csv; rerun with --refresh to call the API again.
"""

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    COST_LOG_CSV, EXTRACTIONS_CSV, LABEL_TICKERS, MODELS_CSV, QUESTIONS, ROOT, Extraction,
    all_tickers, append_csv, latest_10k_text, quote_in_text, read_csv, write_csv,
)

PROMPT = """You are a financial analyst reading excerpts from a SaaS company's annual report (10-K).
Answer from the excerpts only. Do not use outside knowledge.

Questions:
{questions}

Rules:
- ai_cost_pressure = "reported" only if the company says AI-related costs (AI compute, GPUs, third-party
  AI models, AI infrastructure) actually increased its cost of revenue or reduced gross margin in the period.
  Use "risk_only" if AI costs are only described as something that may or could affect margins.
- main_cost_driver = the first or largest driver named where MD&A explains the change in cost of revenue.
- ai_revenue = "yes" if the company sells AI products or features or reports revenue from them.
- evidence_quote must be one sentence copied exactly from the excerpts.

Excerpts:
<<<
{text}
>>>"""


def question_block() -> str:
    lines = []
    for key, q in QUESTIONS.items():
        opts = "; ".join(f'"{k}" = {v}' for k, v in q["options"].items())
        lines.append(f"- {key}: {q['prompt']} Options: {opts}")
    return "\n".join(lines)


def call(client: genai.Client, model: str, prompt: str) -> tuple[types.GenerateContentResponse, float]:
    config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
        response_schema=Extraction,
    )
    for attempt in range(6):
        start = time.perf_counter()
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=config)
            return resp, time.perf_counter() - start
        except errors.APIError as e:
            if e.code in (429, 500, 503) and attempt < 5:
                wait = 10 * 2 ** attempt
                print(f"   {e.code} from API, waiting {wait}s")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("unreachable")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="cheap", help="cheap, mid, top or all")
    ap.add_argument("--labeled", action="store_true", help="only the 10 labeled companies")
    ap.add_argument("--tickers", nargs="*")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--list-models", action="store_true")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is missing. Add a line GEMINI_API_KEY=... to .env in the repo root.")
    client = genai.Client(api_key=key)

    if args.list_models:
        for m in client.models.list():
            if "generateContent" in (m.supported_actions or []):
                print(m.name.removeprefix("models/"))
        return

    models = read_csv(MODELS_CSV)
    if args.tier != "all":
        models = [m for m in models if m["tier"] == args.tier]
        if not models:
            raise SystemExit(f"No tier '{args.tier}' in {MODELS_CSV}")
    tickers = args.tickers or (LABEL_TICKERS if args.labeled else all_tickers())

    existing = {(r["model"], r["ticker"]): r for r in read_csv(EXTRACTIONS_CSV)}
    questions = question_block()

    for m in models:
        model, tier = m["model"], m["tier"]
        in_price, out_price = float(m["input_usd_per_1m"]), float(m["output_usd_per_1m"])
        print(f"\n== {tier}: {model} ==")
        for t in tickers:
            if (model, t) in existing and not args.refresh:
                print(f"   {t}: cached")
                continue
            path, text = latest_10k_text(t)
            resp, seconds = call(client, model, PROMPT.format(questions=questions, text=text))
            u = resp.usage_metadata
            in_tok = u.prompt_token_count or 0
            out_tok = (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
            cost = in_tok / 1e6 * in_price + out_tok / 1e6 * out_price
            ts = datetime.now().isoformat(timespec="seconds")

            append_csv(COST_LOG_CSV, {
                "called_at": ts, "tier": tier, "model": model, "ticker": t, "filing": path.name,
                "input_tokens": in_tok, "output_tokens": out_tok,
                "thinking_tokens": u.thoughts_token_count or 0,
                "cost_usd": round(cost, 6), "latency_s": round(seconds, 2),
            })

            ex: Extraction | None = resp.parsed
            if ex is None:
                print(f"   {t}: could not parse response")
                continue
            existing[(model, t)] = {
                "tier": tier, "model": model, "ticker": t, "filing": path.name,
                **ex.model_dump(),
                "quote_found": quote_in_text(ex.evidence_quote, text),
                "cost_usd": round(cost, 6), "latency_s": round(seconds, 2), "extracted_at": ts,
            }
            print(f"   {t}: {ex.ai_cost_pressure:<9} {ex.main_cost_driver:<22} ai_rev={ex.ai_revenue:<3} "
                  f"${cost:.4f} {seconds:.1f}s")
            write_csv(EXTRACTIONS_CSV, list(existing.values()), list(existing[(model, t)]))

    print(f"\nSaved {EXTRACTIONS_CSV.relative_to(ROOT)} and {COST_LOG_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
