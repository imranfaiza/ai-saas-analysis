"""MCP server exposing the margin warehouse to Claude Desktop (or any MCP client).

Tools:
    ask_margin_data(question)  - the Gemini agent answers in plain English, with its SQL
    run_sql(sql)               - run a read-only query against the semantic-layer tables
    describe_metrics()         - the semantic layer: tables, columns and metric definitions

Test locally:  python mcp_server.py   (it waits for an MCP client on stdin/stdout)
"""

import sys
from pathlib import Path

from mcp.server import MCPServer

sys.path.insert(0, str(Path(__file__).resolve().parent / "agent"))
from agent import MAX_ROWS, SEMANTIC, Agent  # noqa: E402

mcp = MCPServer(
    "margin-squeeze",
    instructions="SEC-filing data on gross margins, AI cost disclosures and efficiency metrics for 25 public "
                 "SaaS companies. Call describe_metrics first, then run_sql or ask_margin_data.",
)
_agent: Agent | None = None


def agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent()
    return _agent


@mcp.tool()
def describe_metrics() -> str:
    """Return the semantic layer: the tables, columns and metric definitions you may query."""
    return SEMANTIC


@mcp.tool()
def run_sql(sql: str) -> str:
    """Run one read-only DuckDB SELECT on marts.mart_margin_squeeze, marts.fct_company_quarter or
    marts.mart_ai_disclosures. Returns up to 50 rows as a table."""
    try:
        cols, rows = agent().run_sql(sql)
    except Exception as e:
        return f"Query failed: {e}"
    lines = [" | ".join(cols)] + [" | ".join("" if v is None else str(v) for v in r) for r in rows]
    more = f"\n(showing first {MAX_ROWS} rows)" if len(rows) == MAX_ROWS else ""
    return "\n".join(lines) + more


@mcp.tool()
def ask_margin_data(question: str) -> str:
    """Ask a plain-English question about SaaS gross margins, AI cost disclosures, growth, R&D, S&M,
    free cash flow or Rule of 40. A Gemini agent writes SQL on the semantic layer and answers."""
    r = agent().ask(question)
    return f"{r['answer']}\n\nSQL used:\n{r['sql']}"


if __name__ == "__main__":
    mcp.run()
