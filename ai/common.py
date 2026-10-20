"""Shared paths, questions and helpers for the Phase 3 extraction + eval."""

import csv
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
TEXT_DIR = ROOT / "data" / "filing_text"
AI_DIR = ROOT / "data" / "ai"
LABELS_CSV = ROOT / "data" / "labels" / "labels.csv"
MODELS_CSV = Path(__file__).resolve().parent / "models.csv"
EXTRACTIONS_CSV = AI_DIR / "extractions.csv"
COST_LOG_CSV = AI_DIR / "cost_log.csv"
EVAL_CSV = AI_DIR / "eval_report.csv"
MISSES_CSV = AI_DIR / "eval_misses.csv"

LABEL_TICKERS = ["CRM", "NOW", "ADBE", "SNOW", "DDOG", "NET", "ASAN", "DUOL", "AI", "ZM"]

QUESTIONS = {
    "ai_cost_pressure": {
        "prompt": "Does the company say AI costs are pressuring its cost of revenue or gross margin?",
        "options": {
            "reported": "Yes, as something already happening (AI costs named as a driver of results)",
            "risk_only": "Only as a possible future risk (e.g. 'could impact our margins')",
            "none": "Not mentioned",
        },
    },
    "main_cost_driver": {
        "prompt": "What is the main driver of the change in cost of revenue in MD&A (the largest or first one named)?",
        "options": {
            "hosting_infrastructure": "Hosting, cloud, data center or infrastructure costs",
            "ai_compute": "AI compute, GPUs or third-party AI model costs",
            "personnel": "Personnel / headcount costs",
            "amortization": "Amortization (acquired intangibles or capitalized software)",
            "professional_services": "Professional services or partner fees",
            "payment_processing": "Payment processing or app store fees",
            "other": "Something else, or not stated",
        },
    },
    "ai_revenue": {
        "prompt": "Does the company say it earns revenue from AI products or features?",
        "options": {
            "yes": "Yes, AI products/features are sold or generate revenue",
            "no": "No, or only mentioned as development / plans",
        },
    },
}

CostPressure = Literal["reported", "risk_only", "none"]
CostDriver = Literal["hosting_infrastructure", "ai_compute", "personnel", "amortization",
                     "professional_services", "payment_processing", "other"]
YesNo = Literal["yes", "no"]
CostTrend = Literal["rising", "falling", "not_stated"]


class Extraction(BaseModel):
    ai_cost_pressure: CostPressure
    main_cost_driver: CostDriver
    ai_revenue: YesNo
    ai_cost_trend: CostTrend = Field(
        description="Whether the filing says AI costs (total or per unit) went up or down in the period")
    evidence_quote: str = Field(description="Exact sentence copied from the text that best supports ai_cost_pressure")
    rationale: str = Field(description="One short sentence explaining the answers")


def latest_text(ticker: str, form: str = "10-K") -> tuple[Path, str]:
    files = sorted(TEXT_DIR.glob(f"{ticker}_{form}_*.txt"))
    if not files:
        raise FileNotFoundError(f"No {form} text for {ticker} in {TEXT_DIR}")
    return files[-1], files[-1].read_text(encoding="utf-8")


def latest_10k_text(ticker: str) -> tuple[Path, str]:
    return latest_text(ticker, "10-K")


def all_tickers() -> list[str]:
    return sorted({p.name.split("_10-K_")[0] for p in TEXT_DIR.glob("*_10-K_*.txt")})


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def append_csv(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def normalize(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_in_text(quote: str, text: str) -> bool:
    q = normalize(quote).strip(' ."')
    return len(q) > 20 and q in normalize(text)
