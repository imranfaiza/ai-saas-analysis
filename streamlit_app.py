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

PRESSURE_LABELS = {"reported": "Says AI is raising costs now", "risk_only": "Lists AI as a risk only",
                   "none": "Not mentioned"}
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


TREND_LABELS = {"rising": "Rising", "falling": "Falling", "not_stated": "Not stated"}
COST_LINES = {
    "cost_of_revenue": "Cost of revenue", "sales_marketing": "Sales & marketing", "rnd": "R&D",
    "general_admin": "G&A", "stock_comp": "Stock comp",
}


def companies() -> pd.DataFrame:
    df = query("""
        select s.*, d.ai_cost_pressure, d.ai_cost_pressure_10k, d.ai_cost_pressure_10q, d.ai_cost_trend,
               d.main_cost_driver, d.earns_ai_revenue, d.evidence_quote, d.evidence_quote_verified, d.evidence_form,
               d.filing_period_end, d.newest_form, d.newest_filing_period_end, d.newest_evidence_quote,
               d.analyst_reviewed, d.review_reason
        from marts.mart_margin_squeeze s
        left join marts.mart_ai_disclosures d using (ticker)
    """)
    df["ai_disclosure"] = df["ai_cost_pressure"].map(PRESSURE_LABELS)
    df["ai_trend"] = df["ai_cost_trend"].map(TREND_LABELS)
    return df


def spend() -> pd.DataFrame:
    df = query("""
        select a.*, m.margin_change_bps, d.ai_cost_pressure, d.ai_cost_trend
        from marts.mart_ai_spend a
        join marts.mart_margin_squeeze m using (ticker)
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
    c4.metric("Say AI is raising their costs now", f"{(df.ai_cost_pressure == 'reported').sum()} of {len(df)}",
              help="The filing says AI already increased costs in the period (latest 10-K or 10-Q, whichever says "
                   "more). It doesn't mean the margin fell: four of the five still grew gross margin.")
    st.info("**Short answer:** not yet, at least not where you'd look first. Gross margins rose at most companies, "
            "even at the five that say AI is already raising their costs. The AI bill is showing up elsewhere: offset by "
            "cheaper hosting, paid for by cutting sales and R&D headcount, and locked in through multi-year cloud "
            "contracts. See *Where the money went* and *Findings & playbook*.")

    st.subheader("Gross margin change since FY2022")
    show_ai = st.toggle("Exclude C3.ai (revenue collapse, −4,570 bps, squashes the chart)", value=True)
    chart_df = df[df.ticker != "AI"] if show_ai else df
    bars = alt.Chart(chart_df).mark_bar().encode(
        x=alt.X("margin_change_bps:Q", title="Change in gross margin (basis points; 100 bps = 1 point)"),
        y=alt.Y("company_name:N", sort="x", title=None),
        color=alt.Color("ai_disclosure:N", title="What filings say about AI costs", scale=PRESSURE_COLORS),
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
                "ttm_rnd_pct", "ttm_fcf_margin_pct", "rule_of_40", "ai_disclosure", "ttm_period_end"]]
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
            "ai_disclosure": "AI cost disclosure",
            "ttm_period_end": st.column_config.DateColumn("TTM ends", format="MMM YYYY"),
        },
    )
    with st.expander("Method and limits"):
        st.markdown(
            "- **Gross margin** = (revenue − cost of revenue) ÷ revenue, from XBRL facts in 10-K and 10-Q filings. "
            "Restatements use the latest filed value; Q4 = annual − Q1–Q3.\n"
            "- These are **GAAP** margins, which include stock comp and amortization of acquired technology in cost "
            "of revenue. They run a few points below the \"non-GAAP\" margins in earnings releases (Snowflake's "
            "non-GAAP product margin is in the 70s; GAAP total is 67%).\n"
            "- **TTM** (trailing twelve months) = the latest four reported quarters, ending June–July 2026 for most "
            "companies. Fiscal labels differ (Salesforce calls Feb–Jul 2026 \"FY2027\"), so dates are shown as "
            "calendar months.\n"
            "- **FY2022** is each company's own fiscal year, so it ends between January and December 2022.\n"
            "- **Workday and Intuit** don't tag total cost of revenue; it is summed from the income-statement lines.\n"
            "- **Free cash flow** = operating cash flow − capex (capitalized software excluded).\n"
            "- **AI cost disclosure** is extracted by Gemini from each company's latest 10-K and 10-Q, keeping the "
            "stronger of the two, and scored against hand labels (see *AI cost & model choice*). Reading only the "
            "10-K found 3 companies; the newer 10-Qs added Salesforce and Zoom.\n"
            "- Margins move for many reasons (mix, scale, pricing, acquisitions), so this shows association and "
            "what companies say, not proof that AI caused the change."
        )


def drilldown() -> None:
    df = companies()
    names = dict(zip(df.ticker, df.company_name))
    ticker = st.selectbox("Company", sorted(names, key=names.get), format_func=lambda t: f"{names[t]} ({t})")
    row = df[df.ticker == ticker].iloc[0]
    st.title(f"{row.company_name} ({ticker})")
    st.caption(f"{row.segment} · fiscal year ends in month {row.fiscal_year_end_month} · TTM through "
               f"{row.ttm_period_end:%b %Y} ({row.ttm_through})")

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

    s = spend().set_index("ticker").loc[ticker]
    st.subheader("Where the money went (% of revenue, FY2022 vs TTM)")
    lines = pd.DataFrame([
        {"line": label, "period": period, "pct": s[f"{prefix}_{key}_pct"]}
        for key, label in COST_LINES.items() for prefix, period in [("fy2022", "FY2022"), ("ttm", "TTM")]
    ])
    st.altair_chart(alt.Chart(lines).mark_bar().encode(
        y=alt.Y("line:N", title=None, sort=list(COST_LINES.values())),
        yOffset=alt.YOffset("period:N", sort=["FY2022", "TTM"]),
        x=alt.X("pct:Q", title="% of revenue"),
        color=alt.Color("period:N", title=None, scale=alt.Scale(range=["#b0b0b0", "#1f77b4"])),
        tooltip=["line", "period", alt.Tooltip("pct:Q", format=".1f")],
    ).properties(height=260), width="stretch")
    m = st.columns(4)
    m[0].metric("Operating margin change", "–" if pd.isna(s.operating_margin_pct_change)
                else f"{s.operating_margin_pct_change:+.1f} pts")
    m[1].metric("Revenue growth vs a year earlier", "–" if pd.isna(s.revenue_growth_change_pts)
                else f"{s.revenue_growth_change_pts:+.1f} pts", help="TTM growth minus the prior TTM's growth.")
    m[2].metric("Contracted backlog (RPO) growth", pct(s.rpo_growth_pct),
                help="Remaining performance obligations vs four quarters earlier.")
    m[3].metric("Purchase commitments", "–" if pd.isna(s.purchase_obligations_musd)
                else f"${s.purchase_obligations_musd:,.0f}M", help="Mostly multi-year cloud contracts. "
                f"{pct(s.purchase_obligations_pct_of_ttm_revenue)} of a year's revenue.")

    st.subheader("What the filings say about AI costs")
    st.markdown(f"**{row.ai_disclosure}** · AI cost trend: **{row.ai_trend}** · main cost driver: "
                f"**{str(row.main_cost_driver).replace('_', ' ')}** · earns AI revenue: "
                f"**{'yes' if row.earns_ai_revenue else 'no'}**")
    st.caption(f"10-K says: {PRESSURE_LABELS.get(row.ai_cost_pressure_10k, '–')} · latest 10-Q says: "
               f"{PRESSURE_LABELS.get(row.ai_cost_pressure_10q, '–')}")
    if isinstance(row.evidence_quote, str) and row.evidence_quote:
        st.info(f"“{row.evidence_quote}” ({row.evidence_form}, period ending {row.filing_period_end:%b %Y})")
        st.caption("Quote verified word-for-word in the filing." if row.evidence_quote_verified
                   else "Quote could not be matched exactly in the filing text.")
    if isinstance(row.newest_evidence_quote, str) and row.newest_evidence_quote != row.evidence_quote:
        st.info(f"Latest filing: “{row.newest_evidence_quote}” ({row.newest_form}, period ending "
                f"{row.newest_filing_period_end:%b %Y})")
    if row.analyst_reviewed:
        st.warning(f"Analyst override: {row.review_reason}")

    with st.expander("Quarterly data"):
        st.dataframe(q.drop(columns=["fiscal_year", "fiscal_quarter"]), hide_index=True, width="stretch")


def disclosures() -> None:
    df = companies()
    st.title("What companies say about AI costs")
    st.caption("Gemini read the margin and AI sections of each company's latest 10-K (annual) and 10-Q (quarterly) "
               "and filled a fixed form; each company gets the stronger of the two answers. Accuracy was measured "
               "against hand labels on 10 filings (see *AI cost & model choice*).")
    st.markdown(
        "**Why both filings:** a 10-K can be up to a year old. Salesforce and Zoom only started naming AI as a cost "
        "driver in their latest 10-Qs, so a 10-K-only read found 3 companies instead of 5. The *trend* column "
        "matters as much as the label: Duolingo was the poster child for AI eating margins, and its latest 10-Q "
        "says per-unit AI costs are now falling and margins recovering."
    )
    st.markdown(
        "**Reading the labels:** *Says AI is raising costs now* means the filing ties a real cost increase in the "
        "period to AI. It doesn't mean the margin fell. *Lists AI as a risk only* is mostly standard risk-factor "
        "language that almost every company now includes, so it says little on its own."
    )
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

    st.dataframe(
        df.sort_values(["ai_cost_pressure", "margin_change_bps"])[
            ["ticker", "company_name", "ai_disclosure", "ai_cost_pressure_10k", "ai_cost_pressure_10q", "ai_trend",
             "margin_change_bps", "analyst_reviewed"]],
        hide_index=True, width="stretch",
        column_config={
            "ticker": "Ticker", "company_name": "Company", "ai_disclosure": "Overall",
            "ai_cost_pressure_10k": "10-K says", "ai_cost_pressure_10q": "10-Q says", "ai_trend": "AI cost trend",
            "margin_change_bps": st.column_config.NumberColumn("GM change (bps)", format="%+d"),
            "analyst_reviewed": "Analyst override",
        },
    )

    pick = st.multiselect("Show quotes for", list(PRESSURE_LABELS.values()),
                          default=list(PRESSURE_LABELS.values())[:1])
    for _, r in df[df.ai_disclosure.isin(pick)].sort_values(["ai_cost_pressure", "margin_change_bps"]).iterrows():
        with st.container(border=True):
            st.markdown(f"**{r.company_name} ({r.ticker})** · {r.ai_disclosure} · trend {r.ai_trend} · margin "
                        f"change {r.margin_change_bps:+.0f} bps · {r.evidence_form} period ending "
                        f"{r.filing_period_end:%b %Y}")
            st.markdown(f"> {r.evidence_quote}")
            if isinstance(r.newest_evidence_quote, str) and r.newest_evidence_quote != r.evidence_quote:
                st.markdown(f"Latest {r.newest_form} ({r.newest_filing_period_end:%b %Y}):")
                st.markdown(f"> {r.newest_evidence_quote}")
            if r.analyst_reviewed:
                st.caption(f"Analyst override: {r.review_reason}")


def money() -> None:
    df = spend()
    st.title("Where the money went")
    st.caption("Gross margin only covers the cost of delivering the product. AI spend also lands in R&D (model "
               "training, AI engineers), gets paid for by cuts elsewhere, and is locked in through cloud contracts "
               "that don't hit the income statement until they're used. This page follows each of those.")

    both = df.dropna(subset=["purchase_obligations_musd", "purchase_obligations_fy2022_musd"])
    rpo = df.dropna(subset=["rpo_growth_pct"])
    c = st.columns(4)
    c[0].metric("Median total opex change", f"{df.opex_pct_change.median():+.1f} pts of revenue",
                help="Sales & marketing + R&D + G&A, as % of revenue, FY2022 vs TTM.")
    c[1].metric("Operating margin improved", f"{(df.operating_margin_pct_change > 0).sum()} of {len(df)}")
    c[2].metric("Purchase commitments since FY2022",
                f"${both.purchase_obligations_fy2022_musd.sum() / 1e3:.1f}B → "
                f"${both.purchase_obligations_musd.sum() / 1e3:.1f}B",
                help=f"The {len(both)} companies that tag commitments in both periods.")
    c[3].metric("Backlog growing faster than revenue",
                f"{(rpo.rpo_growth_pct > rpo.ttm_revenue_growth_pct).sum()} of {len(rpo)}")

    st.subheader("1. Cost structure: AI was paid for with people")
    st.markdown("Every cost line shrank as a share of revenue at the median company, and the biggest cut was "
                "sales & marketing, not delivery costs. Companies funded AI investment by hiring fewer sellers "
                "and engineers per dollar of revenue (the 2023 \"efficiency era\"), which is why operating margins "
                "rose even where AI costs are climbing.")
    excl = st.toggle("Exclude C3.ai (revenue fell 37%, so every ratio jumps)", value=True, key="money_excl")
    d = df[df.ticker != "AI"] if excl else df
    medians = pd.DataFrame([{"line": label, "change": d[f"{key}_pct_change"].median()}
                            for key, label in COST_LINES.items()])
    st.altair_chart(alt.Chart(medians).mark_bar().encode(
        x=alt.X("change:Q", title="Median change, % of revenue (pts), FY2022 → TTM"),
        y=alt.Y("line:N", title=None, sort=list(COST_LINES.values())),
        color=alt.condition(alt.datum.change < 0, alt.value("#2ca02c"), alt.value("#d62728")),
        tooltip=["line", alt.Tooltip("change:Q", format="+.1f")],
    ).properties(height=200), width="stretch")

    heat = d.melt(id_vars=["ticker", "company_name"], var_name="metric", value_name="change",
                  value_vars=[f"{k}_pct_change" for k in COST_LINES] + ["operating_margin_pct_change"])
    names = {f"{k}_pct_change": v for k, v in COST_LINES.items()} | {"operating_margin_pct_change": "Operating margin"}
    heat["metric"] = heat.metric.map(names)
    st.altair_chart(alt.Chart(heat).mark_rect().encode(
        x=alt.X("metric:N", title=None, sort=list(names.values()), axis=alt.Axis(labelAngle=0, orient="top")),
        y=alt.Y("company_name:N", title=None, sort=alt.EncodingSortField("change", op="min")),
        color=alt.Color("change:Q", title="Change (pts)", scale=alt.Scale(scheme="redblue", domainMid=0,
                                                                         domain=[-30, 30], clamp=True)),
        tooltip=["company_name", "metric", alt.Tooltip("change:Q", format="+.1f")],
    ).properties(height=620), width="stretch")
    st.caption("Blue = cost fell (or operating margin rose) as a share of revenue. For costs, red is the warning "
               "sign; for operating margin, blue is good. Rows are sorted by their biggest cut. Stock comp isn't "
               "a separate cost: it's already spread across the other lines, shown on its own because it's the "
               "part paid in shares rather than cash.")

    st.subheader("2. Commitments: the bill that hasn't arrived yet")
    st.markdown("Purchase obligations are contracts a company must pay whether or not it uses the capacity, mostly "
                "multi-year cloud deals with AWS, Azure and Google. They don't show up in margins until they're "
                "consumed, so they're an early read on how much compute a company has promised to buy. Not all of "
                "it is AI, but the growth since FY2022 lines up with the AI build-out.")
    po = df.dropna(subset=["purchase_obligations_musd"]).sort_values("purchase_obligations_pct_of_ttm_revenue")
    st.altair_chart(alt.Chart(po).mark_bar().encode(
        x=alt.X("purchase_obligations_pct_of_ttm_revenue:Q", title="Purchase commitments, % of a year's revenue"),
        y=alt.Y("company_name:N", sort="-x", title=None),
        color=alt.Color("ai_disclosure:N", title="AI cost disclosure", scale=PRESSURE_COLORS),
        tooltip=["company_name", alt.Tooltip("purchase_obligations_musd:Q", title="$M", format=",.0f"),
                 alt.Tooltip("purchase_obligations_growth_since_fy2022_pct:Q", title="Growth since FY2022 %",
                             format="+.0f"), "purchase_obligations_as_of"],
    ).properties(height=440), width="stretch")
    st.dataframe(
        po.sort_values("purchase_obligations_musd", ascending=False)[
            ["ticker", "company_name", "purchase_obligations_musd", "purchase_obligations_fy2022_musd",
             "purchase_obligations_growth_since_fy2022_pct", "purchase_obligations_pct_of_ttm_revenue",
             "purchase_obligations_years_of_cost", "rpo_musd", "purchase_obligations_as_of"]],
        hide_index=True, width="stretch",
        column_config={
            "ticker": "Ticker", "company_name": "Company",
            "purchase_obligations_musd": st.column_config.NumberColumn("Commitments $M", format="%,.0f"),
            "purchase_obligations_fy2022_musd": st.column_config.NumberColumn("FY2022 $M", format="%,.0f"),
            "purchase_obligations_growth_since_fy2022_pct": st.column_config.NumberColumn("Growth %", format="%+.0f"),
            "purchase_obligations_pct_of_ttm_revenue": st.column_config.NumberColumn("% of revenue", format="%.1f"),
            "purchase_obligations_years_of_cost": st.column_config.NumberColumn(
                "Years of delivery cost", format="%.2f", help="Commitments ÷ TTM cost of revenue."),
            "rpo_musd": st.column_config.NumberColumn("Contracted revenue (RPO) $M", format="%,.0f"),
            "purchase_obligations_as_of": "As of",
        },
    )
    st.caption("Uses each company's latest fiscal year-end figure (10-K), falling back to a 10-Q only when no "
               "recent year-end figure exists. Figures more than 15 months old are dropped. Companies that don't "
               "tag commitments (Asana, HubSpot, Palantir, Okta, Duolingo, Zoom, C3.ai) are left out, and very "
               "small values (Workday, Elastic) likely cover only part of their contracts.")

    st.subheader("3. Payoff: is the spending bringing in revenue?")
    st.markdown("Two early signals: whether revenue growth sped up compared with a year earlier, and whether "
                "contracted-but-not-yet-billed revenue (RPO) is growing faster than revenue, which points to "
                "faster growth ahead. Neither proves AI did it, but a company spending on AI with both signals "
                "falling is the one to worry about.")
    pay = (df[df.ticker != "AI"] if excl else df).dropna(subset=["rpo_growth_pct", "revenue_growth_change_pts"])
    pts = alt.Chart(pay).mark_circle(size=140).encode(
        x=alt.X("revenue_growth_change_pts:Q", title="Revenue growth vs a year earlier (pts)"),
        y=alt.Y("rpo_growth_pct:Q", title="Backlog (RPO) growth %"),
        color=alt.Color("ai_disclosure:N", title="AI cost disclosure", scale=PRESSURE_COLORS),
        tooltip=["company_name", "ttm_revenue_growth_pct", "revenue_growth_change_pts", "rpo_growth_pct"],
    )
    txt = pts.mark_text(dx=9, align="left", fontSize=11).encode(text="ticker:N", color=alt.value("#444"))
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(strokeDash=[4, 4], color="#999").encode(x="x:Q")
    st.altair_chart((pts + txt + zero).properties(height=420), width="stretch")
    st.caption("Right of the dashed line = growth sped up. Intuit, Workday and Duolingo don't tag RPO and aren't "
               "shown. Palantir (RPO +104%) is the outlier at the top right.")


def findings() -> None:
    df = spend()
    co = companies().set_index("ticker")
    rep = df[df.ai_cost_pressure == "reported"]
    risk = df[df.ai_cost_pressure == "risk_only"]
    both = df.dropna(subset=["purchase_obligations_musd", "purchase_obligations_fy2022_musd"])
    po_then, po_now = both.purchase_obligations_fy2022_musd.sum(), both.purchase_obligations_musd.sum()
    worst = co.sort_values("margin_change_bps").drop(index="AI").head(3)
    now = df.set_index("ticker").loc["NOW"]
    rpo = df.dropna(subset=["rpo_growth_pct"])

    st.title("Findings & playbook")
    st.caption("What the numbers say, why AI changes the economics of software, and what to do about it.")

    st.header("Why AI is a margin problem for software at all")
    st.markdown(
        "Classic SaaS runs on near-zero marginal cost: once the software is built, serving one more user costs "
        "almost nothing, which is why gross margins sit near 75–80%. AI breaks that. Every AI answer runs a model "
        "on rented GPUs, so **cost grows with usage again**, like a utility. Most SaaS is still sold per seat at a "
        "flat price, so the heaviest AI users can cost more than they pay. Then there's a second-order risk: if AI "
        "agents do work people used to do, customers may need fewer seats, which hits revenue as well as cost."
    )

    st.header("What the filings show")
    st.markdown(f"""
**1. AI costs are real, but so far they're being absorbed.** {len(rep)} of {len(df)} companies say AI is already
raising their delivery costs ({", ".join(co.loc[rep.ticker, "company_name"])}). Yet their gross margins rose a median
**{rep.margin_change_bps.median():+.0f} bps** since FY2022, more than the companies that only list AI as a risk
({risk.margin_change_bps.median():+.0f} bps). Snowflake is the clearest case: cloud costs "including those related to
AI inference and GPUs" rose $113.6M in a single quarter, and its margin still improved, because scale and cheaper
hosting grew faster than the AI bill. **AI is a headwind against efficiency gains, not yet a net drag.**

**2. Margin is a lagging, noisy signal, and the biggest drops aren't blamed on AI.** The largest compressions outside
C3.ai were {", ".join(f"{r.company_name} ({r.margin_change_bps:+.0f} bps)" for _, r in worst.iterrows())}. None of them
names AI as the cause in its filings; mix shifts (moving customers to cloud, acquisitions, running their own data
centers) are bigger forces. Margin alone would point you at the wrong companies.

**3. The bill was paid with people.** At the median company, sales & marketing, R&D and G&A fell
**{-df.opex_pct_change.median():.1f} points** of revenue combined, and operating margin rose at
{(df.operating_margin_pct_change > 0).sum()} of {len(df)}. Some AI spend sits in R&D (Adobe books model training
there), so the cuts elsewhere are what made room for it. That's a one-time lever: you can't cut sales & marketing
by another 7 points next year.

**4. The real exposure is in commitments.** Purchase obligations, mostly multi-year cloud contracts, rose from
**${po_then / 1e3:.1f}B to ${po_now / 1e3:.1f}B** (+{po_now / po_then * 100 - 100:.0f}%) at the {len(both)} companies
with data for both years. That total leans on one company: without ServiceNow it's
${(po_then - now.purchase_obligations_fy2022_musd) / 1e3:.1f}B to ${(po_now - now.purchase_obligations_musd) / 1e3:.1f}B
(+{(po_now - now.purchase_obligations_musd) / (po_then - now.purchase_obligations_fy2022_musd) * 100 - 100:.0f}%), and
{(both.purchase_obligations_growth_since_fy2022_pct > 0).sum()} of the {len(both)} grew (median
+{both.purchase_obligations_growth_since_fy2022_pct.median():.0f}%). ServiceNow alone has **${now.purchase_obligations_musd / 1e3:.1f}B** committed
({now.purchase_obligations_pct_of_ttm_revenue:.0f}% of a year's revenue, up {now.purchase_obligations_growth_since_fy2022_pct:.0f}%
since FY2022), while its gross margin fell {-co.loc['NOW'].margin_change_bps:.0f} bps. These costs are fixed whatever
demand turns out to be, which is the downside if AI features don't sell.

**5. The early payoff looks positive.** Revenue growth sped up at {(df.revenue_growth_change_pts > 0).sum()} of
{len(df)} companies, and contracted backlog is growing faster than revenue at
{(rpo.rpo_growth_pct > rpo.ttm_revenue_growth_pct).sum()} of {len(rpo)}. That can't be credited to AI alone, but it
means the spending isn't happening into a slowdown.

**6. Unit costs are falling fast, so the risk is volume, not price.** Duolingo was the original example of AI eating
margins (its 10-K blamed AI costs for Video Call). Its latest 10-Q reports "continued reductions in per-unit
third-party AI costs" and a recovering margin. Model prices keep dropping; what can still hurt is usage growing
faster than prices fall, which Zoom (AI included at no extra charge) and Atlassian (expects margin to "decline
slightly" from customers' AI usage) are flagging now.
""")

    st.header("Playbook: how to manage AI costs")
    st.markdown("""
**For finance and operating teams**
- **Price AI on usage, not seats.** If cost scales with queries, price should too: credits, per-task fees or AI
  add-ons. Zoom includes its AI assistant at no extra charge and now reports hosting costs rising from AI usage,
  with revenue growing about 5% a year to pay for it.
- **Right-size the model.** This project's own test: the cheapest Gemini model scored 86.7% on the extraction task
  versus 70% for the top model, at about 1/11th of the cost. Route routine work to small models and save large ones
  for hard cases.
- **Measure AI cost per customer and per feature.** Company-wide gross margin hides heavy users. Track cost-to-serve
  by account so pricing and usage limits rest on data.
- **Keep cloud commitments flexible.** Multi-year deals buy discounts but turn a variable cost into a fixed one.
  Compare committed spend with contracted revenue (RPO) so commitments don't outrun demand.

**For analysts and investors: what to watch each quarter**
- **The latest 10-Q, not the 10-K.** Two of the five companies only started citing AI costs in their quarterly reports.
- **Cost growth gap** (delivery-cost growth minus revenue growth): the first place AI cost shows up in the numbers.
- **Purchase obligations as % of revenue,** with RPO next to it: the bill that's coming, and the revenue meant to pay it.
- **Opex ratios:** the sales and R&D cuts that funded AI so far can't repeat, so margins depend on AI earning its keep.
- **AI cost trend language** ("per-unit costs declining" vs "increased AI consumption"): a turning point shows up in
  the text before it shows up in the margin.
""")

    with st.expander("What about debt?"):
        st.markdown("Debt isn't where the AI bill sits for these companies. They rent compute from cloud providers "
                    "instead of building data centers, so capital spending stays under about 3% of revenue for most, "
                    "and only about a third carry long-term debt, mostly convertible notes. The borrowing "
                    "for the AI build-out is happening at the hyperscalers and GPU cloud providers; for SaaS "
                    "companies the equivalent risk is the purchase commitments above.")

    with st.expander("Limits"):
        st.markdown("- Filings show what companies choose to disclose. Most group AI with general hosting costs, so "
                    "the true AI share is hidden.\n"
                    "- FY2022 to now also covers the post-2022 cost-cutting cycle, which moved opex for reasons "
                    "beyond AI.\n"
                    "- Purchase obligations include non-AI contracts and are tagged inconsistently; seven companies "
                    "don't tag them at all.\n"
                    "- 25 companies is a sample of large public SaaS, not the whole industry.")


def faq() -> None:
    st.title("Questions readers ask")
    qa = {
        "Why these 25 companies?":
            "A hand-picked mix of large and mid-size US-listed software companies in three groups: business "
            "applications (Salesforce, Adobe, Workday…), data & infrastructure (Snowflake, Datadog, MongoDB…) and "
            "security (CrowdStrike, Zscaler, Okta…). It deliberately includes AI-first companies (Palantir, C3.ai) "
            "and ones where AI is a side feature. It's a sample, not the whole industry, and not chosen at random.",
        "Why compare against fiscal 2022?":
            "ChatGPT launched in November 2022, so each company's fiscal 2022 is the last full year before the "
            "generative-AI rush. It's compared with the latest twelve months so seasonality cancels out.",
        "What's a basis point?": "One hundredth of a percentage point. A margin going from 75.0% to 73.5% is "
            "−150 bps (−1.5 points).",
        "How do you know AI caused any of this?":
            "We don't, and the dashboard doesn't claim it. The numbers show what changed; the AI link comes from "
            "what companies say in their own filings. Margins also move with pricing, product mix, acquisitions "
            "and scale, and FY2022 to now overlaps with the post-2022 cost-cutting wave.",
        "Why not just use the AI cost number companies report?":
            "Almost none report one. AI compute is usually buried inside \"hosting\" or \"third-party cloud\" costs, "
            "and model training often sits in R&D. That's why this looks at several places at once: gross margin, "
            "opex, cloud commitments and the filings' own words.",
        "Why are these margins lower than the ones in earnings releases?":
            "Earnings releases usually quote non-GAAP margins, which strip out stock comp and amortization. These "
            "are GAAP numbers straight from the SEC filings so every company is measured the same way.",
        "How did the AI read 50 filings, and can I trust it?":
            "Gemini read the cost and AI sections of each company's latest 10-K and 10-Q and filled a fixed form "
            "with three answers plus a supporting quote. On 10 hand-labeled filings it was right on 86.7% of "
            "answers, every quote is checked word-for-word against the filing, and one wrong call (Atlassian) "
            "was corrected by hand and flagged. See *AI cost & model choice*.",
        "Why did the cheapest model beat the expensive one?":
            "For a narrow, well-defined form-filling task, a small model following a clear prompt is enough; the "
            "larger model over-interpreted some questions (it scored 40% on \"does the company earn AI revenue\"). "
            "That's the right-sizing point in the playbook: test before paying for the biggest model.",
        "How current is the data?":
            "It's a snapshot of SEC filings up to the date in the sidebar, not a live feed. Rerunning the pipeline "
            "(fetch → dbt build → extraction) refreshes it.",
        "Can I check the numbers myself?":
            "Yes. Every figure traces back to an SEC filing, and the code is on "
            "[GitHub](https://github.com/imranfaiza/ai-saas-analysis). Duolingo, Intuit and Salesforce were "
            "checked by hand against their filed income statements, and the warehouse runs 76 automated tests.",
    }
    for q, a in qa.items():
        with st.expander(q):
            st.markdown(a)


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
        "Which companies say AI is already raising their costs?",
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
                   "reviewed against the filing text, and 5 were corrected before the final score. The top model "
                   "hit its free-tier daily limit during the final rerun, so 7 of its 10 scored answers come from "
                   "the earlier prompt version.")

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
    st.Page(money, title="Where the money went", icon="💸", url_path="spend"),
    st.Page(findings, title="Findings & playbook", icon="🧭", url_path="findings"),
    st.Page(drilldown, title="Company drilldown", icon="🔎", url_path="company"),
    st.Page(disclosures, title="AI disclosures", icon="🤖", url_path="ai-disclosures"),
    st.Page(ask, title="Ask the data", icon="💬", url_path="ask"),
    st.Page(ai_cost, title="AI cost & model choice", icon="💲", url_path="ai-cost"),
    st.Page(faq, title="FAQ", icon="❓", url_path="faq"),
])
st.sidebar.caption(f"SEC filings through {query('select max(filed) as d from raw.raw_sec__xbrl_facts').d[0]:%b %d, %Y} · "
                   "[Code on GitHub](https://github.com/imranfaiza/ai-saas-analysis)")
pg.run()
