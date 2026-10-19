"""Ask-the-data agent: question -> SQL on the semantic layer -> DuckDB -> short answer.

Run from the repo root:
    python agent/agent.py "Which companies' gross margins fell the most since FY2022?"
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

import duckdb
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "warehouse.duckdb"
SEMANTIC = (ROOT / "semantic" / "metrics.yml").read_text(encoding="utf-8")

MODEL = os.getenv("AGENT_MODEL", "gemini-3.1-flash-lite")
PRICES = {  # USD per 1M tokens (input, output)
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.8-flash": (0.75, 3.75),
}
MAX_ROWS = 50
ALLOWED_TABLES = {"marts.mart_margin_squeeze", "marts.fct_company_quarter", "marts.mart_ai_disclosures"}

SQL_PROMPT = """You write DuckDB SQL for questions about SaaS company financials.
Use only the semantic layer below. Return one read-only SELECT (or WITH ... SELECT) query.

{semantic}

Question: {question}
{retry}"""

ANSWER_PROMPT = """Answer the question in 1-3 plain sentences using only these query results.
Quote the numbers with units. If the results are empty, say the data doesn't answer it.

Question: {question}
SQL: {sql}
Results (first {n} rows):
{rows}"""


class SqlPlan(BaseModel):
    sql: str = Field(description="One DuckDB SELECT query")
    metrics_used: list[str] = Field(description="Metric or column names from the semantic layer used")


class Agent:
    def __init__(self, model: str = MODEL):
        load_dotenv(ROOT / ".env")
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise SystemExit("GEMINI_API_KEY is missing from .env")
        self.client = genai.Client(api_key=key)
        self.model = model
        self.db = duckdb.connect(str(DB_PATH), read_only=True)

    def _generate(self, prompt: str, schema=None) -> tuple[types.GenerateContentResponse, float]:
        config = types.GenerateContentConfig(temperature=0)
        if schema:
            config.response_mime_type = "application/json"
            config.response_schema = schema
        for attempt in range(6):
            try:
                resp = self.client.models.generate_content(model=self.model, contents=prompt, config=config)
                u = resp.usage_metadata
                inp, out = PRICES.get(self.model, (0, 0))
                out_tok = (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
                return resp, (u.prompt_token_count or 0) / 1e6 * inp + out_tok / 1e6 * out
            except errors.APIError as e:
                if e.code in (429, 500, 503) and attempt < 5:
                    time.sleep(10 * 2 ** attempt)
                    continue
                raise
        raise RuntimeError("unreachable")

    def run_sql(self, sql: str) -> tuple[list[str], list[tuple]]:
        check_sql(sql)
        rel = self.db.sql(sql)
        return rel.columns, rel.fetchmany(MAX_ROWS)

    def plan(self, question: str) -> dict:
        """Write and run SQL, retrying once with the error if it fails."""
        cost, retry, last_error = 0.0, "", None
        for _ in range(2):
            resp, c = self._generate(SQL_PROMPT.format(semantic=SEMANTIC, question=question, retry=retry), SqlPlan)
            cost += c
            plan: SqlPlan = resp.parsed
            try:
                cols, rows = self.run_sql(plan.sql)
                return {"sql": plan.sql, "metrics_used": plan.metrics_used, "columns": cols, "rows": rows,
                        "cost_usd": cost, "error": None}
            except Exception as e:
                last_error = str(e).splitlines()[0]
                retry = f"\nYour previous query failed:\n{plan.sql}\nError: {last_error}\nFix it."
        return {"sql": plan.sql, "metrics_used": plan.metrics_used, "columns": [], "rows": [],
                "cost_usd": cost, "error": last_error}

    def ask(self, question: str) -> dict:
        start = time.perf_counter()
        result = self.plan(question)
        if result["error"]:
            result["answer"] = f"I couldn't build a working query: {result['error']}"
        else:
            rows = "\n".join(str(dict(zip(result["columns"], r))) for r in result["rows"][:20])
            resp, c = self._generate(ANSWER_PROMPT.format(question=question, sql=result["sql"],
                                                          n=min(20, len(result["rows"])), rows=rows or "(none)"))
            result["cost_usd"] += c
            result["answer"] = resp.text.strip()
        result["seconds"] = round(time.perf_counter() - start, 1)
        return result


def check_sql(sql: str) -> None:
    s = re.sub(r"--.*?$|/\*.*?\*/", " ", sql, flags=re.S | re.M).strip().rstrip(";").lower()
    if ";" in s:
        raise ValueError("Only one statement is allowed")
    if not re.match(r"^(select|with)\b", s):
        raise ValueError("Only SELECT queries are allowed")
    if re.search(r"\b(read_csv|read_parquet|read_json|glob|attach|copy|install|load|pragma)\b", s):
        raise ValueError("File and system functions are not allowed")
    for schema, table in re.findall(r"\b(raw|staging|seeds|marts|main|information_schema)\.(\w+)", s):
        if f"{schema}.{table}" not in ALLOWED_TABLES:
            raise ValueError(f"Table {schema}.{table} is not in the semantic layer")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    args = ap.parse_args()
    r = Agent().ask(args.question)
    print(f"\n{r['answer']}\n")
    print(f"SQL:\n{r['sql']}\n")
    print(f"{len(r['rows'])} rows | ${r['cost_usd']:.5f} | {r['seconds']}s | {MODEL}")


if __name__ == "__main__":
    main()
