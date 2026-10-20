"""Margin Squeeze dashboard: is AI eating SaaS gross margins?

Run locally from the repo root:
    streamlit run streamlit_app.py
"""

import os
import sys
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
DB_PATH = ROOT / "warehouse.duckdb"
AI_DIR = ROOT / "data" / "ai"
MAX_QUESTIONS_PER_SESSION = 10

PRESSURE_LABELS = {"reported": "Already hurting margins", "risk_only": "Future risk only", "none": "Not mentioned"}
PRESSURE_COLORS = alt.Scale(domain=list(PRESSURE_LABELS.values()), range=["#d62728", "#f2a541", "#9e9e9e"])

st.set_page_config(page_title="Margin Squeeze", page_icon="📉", layout="wide")


@st.cache_resource
def db() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=True)


@st.cache_data
def query(sql: str) -> pd.DataFrame:
    return db().sql(sql).df()


@st.cache_data
def read_ai_csv(name: str) -> pd.DataFrame:
    path = AI_DIR / name
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def companies() -> pd.DataFrame:
    df = query("""
        select s.*, d.ai_cost_pressure, d.main_cost_driver, d.earns_ai_revenue, d.evidence_quote,
               d.evidence_quote_verified, d.filing_period_end
        from marts.mart_margin_squeeze s
        left join marts.mart_ai_disclosures d using (ticker)
    """)
    df["ai_disclosure"] = df["ai_cost_pressure"].map(PRESSURE_LABELS)
    return df


def pct(v, digits=1) -> str:
    return "–" if pd.isna(v) else f"{v:.{digits}f}%"


# ---------------------------------------------------------------- pages

def overview() -> None:
    df = companies()
    st.title("Is AI eating SaaS margins?")
    st.caption(
        "Gross margin in each company's fiscal 2022 (the last full year before ChatGPT) vs the latest trailing "
        "twelve months, for 25 public SaaS companies. Source: SEC XBRL filings, built with dbt + DuckDB."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Median margin change", f"{df.margin_change_bps.median():+.0f} bps")
    c2.metric("Margins compressed", f"{(df.margin_change_bps < 0).sum()} of {len(df)}")
    c3.metric("Costs growing faster than revenue", f"{(df.cost_growth_gap_pts > 0).sum()} of {len(df)}")
    c4.metric("Say AI costs already hurt margins", f"{(df.ai_cost_pressure == 'reported').sum()} of {len(df)}")

    st.subheader("Gross margin change since FY2022")
    show_ai = st.toggle("Exclude C3.ai (revenue collapse, −4,570 bps, squashes the chart)", value=True)
    chart_df = df[df.ticker != "AI"] if show_ai else df
    bars = alt.Chart(chart_df).mark_bar().encode(
        x=alt.X("margin_change_bps:Q", title="Change in gross margin (basis points; 100 bps = 1 point)"),
        y=alt.Y("company_name:N", sort="x", title=None),
        color=alt.Color("ai_disclosure:N", title="What the 10-K says about AI costs", scale=PRESSURE_COLORS),
        tooltip=["company_name", "fy2022_gross_margin_pct", "ttm_gross_margin_pct", "margin_change_bps",
                 "cost_growth_gap_pts", "ai_disclosure"],
    ).properties(height=620)
    st.altair_chart(bars, width="stretch")

    st.subheader("Are delivery costs outgrowing revenue?")
    st.caption("Cost growth gap = TTM cost of revenue growth − TTM revenue growth. Right of zero means the cost "
               "of delivering the product is growing faster than sales.")
    scatter = alt.Chart(chart_df).mark_circle(size=140).encode(
        x=alt.X("cost_growth_gap_pts:Q", title="Cost growth gap (pts)"),
        y=alt.Y("margin_change_bps:Q", title="Margin change since FY2022 (bps)"),
        color=alt.Color("ai_disclosure:N", title="AI cost disclosure", scale=PRESSURE_COLORS),
        tooltip=["company_name", "cost_growth_gap_pts", "margin_change_bps", "ai_disclosure"],
    )
    labels = scatter.mark_text(dx=9, align="left", fontSize=11).encode(text="ticker:N", color=alt.value("#444"))
    rule = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(strokeDash=[4, 4], color="#999").encode(x="x:Q")
    st.altair_chart((scatter + labels + rule).properties(height=420), width="stretch")

    st.subheader("All companies")
    table = df[["ticker", "company_name", "segment", "fy2022_gross_margin_pct", "ttm_gross_margin_pct",
                "margin_change_bps", "ttm_revenue_growth_pct", "cost_growth_gap_pts", "ttm_sales_marketing_pct",
                "ttm_rnd_pct", "ttm_fcf_margin_pct", "rule_of_40", "ai_disclosure", "ttm_through"]]
    st.dataframe(
        table.sort_values("margin_change_bps"),
        hide_index=True,
        width="stretch",
        column_config={
            "ticker": "Ticker", "company_name": "Company", "segment": "Segment",
            "fy2022_gross_margin_pct": st.column_config.NumberColumn("FY2022 GM %", format="%.1f"),
            "ttm_gross_margin_pct": st.column_config.NumberColumn("TTM GM %", format="%.1f"),
            "margin_change_bps": st.column_config.NumberColumn("Change (bps)", format="%+d"),
            "ttm_revenue_growth_pct": st.column_config.NumberColumn("Rev growth %", format="%.1f"),
            "cost_growth_gap_pts": st.column_config.NumberColumn("Cost gap (pts)", format="%+.1f"),
            "ttm_sales_marketing_pct": st.column_config.NumberColumn("S&M %", format="%.1f"),
            "ttm_rnd_pct": st.column_config.NumberColumn("R&D %", format="%.1f"),
            "ttm_fcf_margin_pct": st.column_config.NumberColumn("FCF margin %", format="%.1f"),
            "rule_of_40": st.column_config.NumberColumn("Rule of 40", format="%.1f"),
            "ai_disclosure": "AI cost disclosure", "ttm_through": "TTM through",
        },
    )
    with st.expander("Method and limits"):
        st.markdown(
            "- **Gross margin** = (revenue − cost of revenue) ÷ revenue, from XBRL facts in 10-K and 10-Q filings. "
            "Restatements use the latest filed value; Q4 = annual − Q1–Q3.\n"
            "- **FY2022** is each company's own fiscal year, so it ends between January and December 2022.\n"
            "- **Workday and Intuit** don't tag total cost of revenue; it is summed from the income-statement lines.\n"
            "- **Free cash flow** = operating cash flow − capex (capitalized software excluded).\n"
            "- **AI cost disclosure** is extracted by Gemini from each latest 10-K and scored against hand labels "
            "(see *AI cost & model choice*).\n"
            "- Margins move for many reasons (mix, scale, pricing, acquisitions), so this shows association and "
            "what companies say, not proof that AI caused the change."
        )


def drilldown() -> None:
    df = companies()
    names = dict(zip(df.ticker, df.company_name))
    ticker = st.selectbox("Company", sorted(names, key=names.get), format_func=lambda t: f"{names[t]} ({t})")
    row = df[df.ticker == ticker].iloc[0]
    st.title(f"{row.company_name} ({ticker})")
    st.caption(f"{row.segment} · fiscal year ends in month {row.fiscal_year_end_month} · TTM through {row.ttm_through}")

    c = st.columns(5)
    c[0].metric("FY2022 gross margin", pct(row.fy2022_gross_margin_pct))
    c[1].metric("TTM gross margin", pct(row.ttm_gross_margin_pct), f"{row.margin_change_bps:+.0f} bps")
    c[2].metric("Revenue growth", pct(row.ttm_revenue_growth_pct))
    c[3].metric("Cost growth gap", "–" if pd.isna(row.cost_growth_gap_pts) else f"{row.cost_growth_gap_pts:+.1f} pts",
                delta_color="off")
    c[4].metric("Rule of 40", "–" if pd.isna(row.rule_of_40) else f"{row.rule_of_40:.1f}")

    q = query(f"""
        select fiscal_year, fiscal_quarter, period_end, 'FY' || fiscal_year || ' Q' || fiscal_quarter as quarter,
               revenue / 1e6 as revenue_musd, cost_of_revenue / 1e6 as cost_musd, gross_margin_pct,
               sales_marketing_pct, rnd_pct, fcf_margin_pct
        from marts.fct_company_quarter where ticker = '{ticker}' order by quarter_index
    """)
    left, right = st.columns(2)
    with left:
        st.subheader("Gross margin by quarter")
        base = alt.Chart(q).encode(x=alt.X("period_end:T", title=None))
        line = base.mark_line(point=True).encode(
            y=alt.Y("gross_margin_pct:Q", title="Gross margin %", scale=alt.Scale(zero=False)),
            tooltip=["quarter", alt.Tooltip("gross_margin_pct:Q", format=".1f")],
        )
        baseline = alt.Chart(pd.DataFrame({"y": [row.fy2022_gross_margin_pct]})).mark_rule(
            strokeDash=[4, 4], color="#999").encode(y="y:Q")
        st.altair_chart((line + baseline).properties(height=320), width="stretch")
        st.caption("Dashed line = FY2022 baseline.")
    with right:
        st.subheader("Revenue and cost of revenue ($M)")
        long = q.melt(id_vars=["period_end", "quarter"], value_vars=["revenue_musd", "cost_musd"],
                      var_name="series", value_name="musd")
        long["series"] = long.series.map({"revenue_musd": "Revenue", "cost_musd": "Cost of revenue"})
        st.altair_chart(alt.Chart(long).mark_bar().encode(
            x=alt.X("period_end:T", title=None), y=alt.Y("musd:Q", title="$M", stack=None),
            color=alt.Color("series:N", title=None), opacity=alt.value(0.8),
            tooltip=["quarter", "series", alt.Tooltip("musd:Q", format=",.1f")],
        ).properties(height=320), width="stretch")

    st.subheader("What the latest 10-K says about AI costs")
    st.markdown(f"**{row.ai_disclosure}** · main cost driver: **{str(row.main_cost_driver).replace('_', ' ')}** · "
                f"earns AI revenue: **{'yes' if row.earns_ai_revenue else 'no'}**")
    if isinstance(row.evidence_quote, str) and row.evidence_quote:
        st.info(f"“{row.evidence_quote}”")
        st.caption("Quote verified word-for-word in the filing." if row.evidence_quote_verified
                   else "Quote could not be matched exactly in the filing text.")

    with st.expander("Quarterly data"):
        st.dataframe(q.drop(columns=["fiscal_year", "fiscal_quarter"]), hide_index=True, width="stretch")


def disclosures() -> None:
    df = companies()
    st.title("What companies say about AI costs")
    st.caption("Gemini read the margin and AI sections of each company's latest 10-K and filled a fixed form. "
               "Accuracy was measured against hand labels on 10 filings (see *AI cost & model choice*).")
    counts = df.ai_disclosure.value_counts().reindex(PRESSURE_LABELS.values(), fill_value=0)
    c = st.columns(3)
    for col, (label, n) in zip(c, counts.items()):
        col.metric(label, f"{n} companies")

    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X("count():Q", title="Companies"),
        y=alt.Y("main_cost_driver:N", sort="-x", title="Main driver of cost of revenue change"),
        color=alt.Color("ai_disclosure:N", title="AI cost disclosure", scale=PRESSURE_COLORS),
    ).properties(height=260)
    st.altair_chart(chart, width="stretch")

    pick = st.multiselect("Show", list(PRESSURE_LABELS.values()), default=list(PRESSURE_LABELS.values())[:2])
    for _, r in df[df.ai_disclosure.isin(pick)].sort_values(["ai_cost_pressure", "margin_change_bps"]).iterrows():
        with st.container(border=True):
            st.markdown(f"**{r.company_name} ({r.ticker})** · {r.ai_disclosure} · margin change "
                        f"{r.margin_change_bps:+.0f} bps · 10-K period ending {r.filing_period_end:%b %Y}")
            st.markdown(f"> {r.evidence_quote}")


def ask() -> None:
    st.title("Ask the data")
    st.caption("A Gemini agent turns your question into SQL on a defined semantic layer (so it can't invent its "
               "own math), runs it on the warehouse and answers. It scored 15/15 on a held-out test set.")

    key = os.getenv("GEMINI_API_KEY")
    try:
        key = key or st.secrets.get("GEMINI_API_KEY")
    except Exception:
        pass
    if not key:
        st.warning("The agent needs a GEMINI_API_KEY (in .env locally, or in the app's secrets when deployed).")
        return
    os.environ["GEMINI_API_KEY"] = key

    @st.cache_resource
    def get_agent():
        sys.path.insert(0, str(ROOT / "agent"))
        from agent import Agent
        return Agent()

    examples = [
        "Which companies say AI costs are already hurting their margins?",
        "Which 5 companies had the biggest gross margin drop since FY2022?",
        "What is the median TTM gross margin by segment?",
        "Which companies pass the Rule of 40?",
    ]
    st.session_state.setdefault("history", [])
    cols = st.columns(len(examples))
    clicked = next((e for c, e in zip(cols, examples) if c.button(e, width="stretch")), None)
    question = st.chat_input("Ask about margins, growth, R&D, S&M, free cash flow or AI disclosures") or clicked

    for h in st.session_state.history:
        st.chat_message("user").write(h["q"])
        render_answer(h["r"])

    if question:
        if len(st.session_state.history) >= MAX_QUESTIONS_PER_SESSION:
            st.error(f"Limit of {MAX_QUESTIONS_PER_SESSION} questions per session (it runs on a free API key).")
            return
        st.chat_message("user").write(question)
        with st.spinner("Writing SQL and querying the warehouse..."):
            try:
                r = get_agent().ask(question)
            except Exception as e:
                st.error(f"The agent failed: {e}")
                return
        st.session_state.history.append({"q": question, "r": r})
        render_answer(r)


def render_answer(r: dict) -> None:
    with st.chat_message("assistant"):
        st.write(r["answer"])
        with st.expander(f"SQL and results · ${r['cost_usd']:.5f} · {r['seconds']}s"):
            st.code(r["sql"], language="sql")
            if r["rows"]:
                st.dataframe(pd.DataFrame(r["rows"], columns=r["columns"]), hide_index=True)


def ai_cost() -> None:
    st.title("AI cost & model choice")
    st.caption("Every Gemini call is logged with tokens, cost and latency. The same extraction ran on three models "
               "and was scored against hand labels, then the cheapest model that was accurate enough was picked.")

    ev = read_ai_csv("eval_report.csv")
    if not ev.empty:
        best = ev.sort_values(["accuracy_pct", "cost_per_filing_usd"], ascending=[False, True]).iloc[0]
        c = st.columns(4)
        c[0].metric("Chosen model", best.model)
        c[1].metric("Accuracy on 30 labeled answers", f"{best.accuracy_pct:.1f}%")
        top = ev.sort_values("cost_per_filing_usd").iloc[-1]
        c[2].metric("Cheaper than the top model", f"{top.cost_per_filing_usd / best.cost_per_filing_usd:.1f}×")
        c[3].metric("Cost per filing", f"${best.cost_per_filing_usd:.4f}")

        st.subheader("Accuracy vs cost")
        pts = alt.Chart(ev).mark_circle(size=300).encode(
            x=alt.X("cost_per_filing_usd:Q", title="Cost per filing (USD, log scale)", scale=alt.Scale(type="log")),
            y=alt.Y("accuracy_pct:Q", title="Accuracy %", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("model:N", title="Model"),
            tooltip=["model", "accuracy_pct", "cost_per_filing_usd", "avg_latency_s"],
        )
        txt = pts.mark_text(dy=-18, fontSize=12).encode(text="model:N", color=alt.value("#333"))
        st.altair_chart((pts + txt).properties(height=340), width="stretch")

        st.dataframe(
            ev[["model", "accuracy_pct", "ai_cost_pressure_pct", "main_cost_driver_pct", "ai_revenue_pct",
                "quote_found_pct", "cost_per_filing_usd", "cost_vs_cheapest_x", "avg_latency_s"]],
            hide_index=True, width="stretch",
            column_config={
                "model": "Model", "accuracy_pct": "Accuracy %", "ai_cost_pressure_pct": "AI cost pressure %",
                "main_cost_driver_pct": "Cost driver %", "ai_revenue_pct": "AI revenue %",
                "quote_found_pct": "Quotes verified %",
                "cost_per_filing_usd": st.column_config.NumberColumn("$ / filing", format="%.5f"),
                "cost_vs_cheapest_x": st.column_config.NumberColumn("× cheapest", format="%.1f"),
                "avg_latency_s": st.column_config.NumberColumn("Seconds", format="%.1f"),
            },
        )
        st.caption("Costs are list prices for the paid tier; the project ran on Gemini's free tier. Labels were "
                   "reviewed against the filing text, and 5 were corrected before the final score.")

    log = read_ai_csv("cost_log.csv")
    if not log.empty:
        st.subheader("AI cost log")
        summary = log.groupby("model").agg(calls=("ticker", "size"), input_tokens=("input_tokens", "sum"),
                                           output_tokens=("output_tokens", "sum"), cost_usd=("cost_usd", "sum"),
                                           avg_latency_s=("latency_s", "mean")).reset_index()
        st.dataframe(summary, hide_index=True, width="stretch",
                     column_config={"cost_usd": st.column_config.NumberColumn("Cost (USD)", format="%.4f"),
                                    "avg_latency_s": st.column_config.NumberColumn("Avg seconds", format="%.1f")})
        st.caption(f"{len(log)} calls in total, ${log.cost_usd.sum():.3f} at paid-tier prices.")

    ag = read_ai_csv("agent_eval.csv")
    if not ag.empty:
        st.subheader(f"Ask-the-data agent: {int(ag.passed.sum())}/{len(ag)} test questions passed")
        st.dataframe(ag[["id", "question", "passed", "agent_answer"]], hide_index=True, width="stretch")


pg = st.navigation([
    st.Page(overview, title="Overview", icon="📉", url_path="overview", default=True),
    st.Page(drilldown, title="Company drilldown", icon="🔎", url_path="company"),
    st.Page(disclosures, title="AI disclosures", icon="🤖", url_path="ai-disclosures"),
    st.Page(ask, title="Ask the data", icon="💬", url_path="ask"),
    st.Page(ai_cost, title="AI cost & model choice", icon="💲", url_path="ai-cost"),
])
pg.run()
